"""Minimal mounts, isolated network/PID namespaces, bounded process supervision."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from .evidence import result
from .workspace import SafetyError, read_source


class Bubblewrap:
    def __init__(self, config):
        config.check()
        self.config = config

    def command(self, work, names, control, mode, broker=None):
        cfg = self.config
        venv = Path(cfg.aider_python).parent.parent
        if not (venv / 'pyvenv.cfg').is_file():
            raise SafetyError('provider virtualenv required')
        cmd = [cfg.bwrap, '--unshare-all', '--die-with-parent', '--new-session',
               '--cap-drop', 'ALL', '--clearenv', '--ro-bind', '/usr', '/usr']
        for name in ('/lib', '/lib64'):
            if Path(name).exists():
                cmd += ['--ro-bind', name, name]
        cmd += ['--ro-bind', str(venv), '/opt/aider',
                '--ro-bind', str(control), '/control',
                '--ro-bind', str(Path(__file__).with_name('_sandbox_bootstrap.py')), '/bootstrap.py',
                '--ro-bind', str(work), '/work', '--proc', '/proc', '--dir', '/dev',
                '--dev-bind', '/dev/null', '/dev/null',
                '--dev-bind', '/dev/zero', '/dev/zero',
                '--dev-bind', '/dev/urandom', '/dev/urandom',
                '--size', str(cfg.limits.temporary_bytes), '--tmpfs', '/tmp',
                '--dir', '/home', '--dir', '/broker']
        if mode in {'provider', 'probe'}:
            if mode == 'provider' and broker is None:
                raise SafetyError('provider broker required')
            if broker is not None:
                cmd += ['--ro-bind', str(broker), '/broker/ollama.sock']
            for name in names:
                cmd += ['--bind', str(Path(work) / name), '/work/' + name]
        cmd += ['--remount-ro', '/', '--chdir', '/work',
                '--setenv', 'HOME', '/tmp', '--setenv', 'PATH', '/opt/aider/bin:/usr/bin',
                '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                '--setenv', 'OLLAMA_API_BASE', cfg.endpoint,
                '--setenv', 'OMP_NUM_THREADS', '1', '--setenv', 'OPENBLAS_NUM_THREADS', '1',
                '--setenv', 'TOKENIZERS_PARALLELISM', 'false',
                '--setenv', 'LITELLM_LOCAL_MODEL_COST_MAP', 'True',
                '--setenv', 'GIT_PYTHON_REFRESH', 'quiet',
                '/opt/aider/bin/python', '-I', '/bootstrap.py']
        return cmd

    def run(self, work, names, mode, argv, timeout, broker=None):
        cfg = self.config
        if timeout <= 0:
            return result(argv, -9, 0, timed_out=True), b''
        for name in names:
            read_source(work, name, cfg.limits.written_bytes)
        with tempfile.TemporaryDirectory(prefix='genesis-control-') as control:
            job = {'mode': mode, 'argv': argv, 'limits': vars(cfg.limits),
                   'per_file': cfg.limits.written_bytes // len(names),
                   'host_namespaces': {n: os.readlink('/proc/self/ns/' + n)
                                       for n in ('net', 'pid', 'mnt', 'user')}}
            Path(control, 'job.json').write_text(json.dumps(job))
            # ConfigArgParse requires a YAML mapping; an empty /dev/null is invalid.
            Path(control, 'aider.yml').write_text('{}\n')
            Path(control, 'settings.yml').write_text(
                '- name: ollama_chat/qwen2.5-coder:32b\n'
                '  extra_params:\n    num_ctx: 16384\n')
            Path(control, 'metadata.json').write_text(json.dumps({
                'ollama_chat/qwen2.5-coder:32b': {
                    'max_input_tokens': 16384, 'max_output_tokens': 4096,
                    'input_cost_per_token': 0, 'output_cost_per_token': 0,
                    'litellm_provider': 'ollama_chat', 'mode': 'chat'}}))
            cmd = self.command(work, names, control, mode, broker)
            return supervise(cmd, timeout, cfg.limits.output_bytes, evidence_argv=argv)

    def preflight(self):
        """Never fall back to uncontained execution if namespace creation fails."""
        p = subprocess.run([self.config.bwrap, '--unshare-all', '--die-with-parent',
                            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
                            '--ro-bind-try', '/lib64', '/lib64', '/usr/bin/true'],
                           capture_output=True, timeout=10, env={'PATH': '/usr/bin:/bin'})
        if p.returncode:
            raise SafetyError('Bubblewrap namespace preflight failed; host acceptance required')
        from .probes import PROBE
        with tempfile.TemporaryDirectory(prefix='genesis-probe-') as d:
            Path(d, 'probe.py').write_text(PROBE)
            Path(d, 'scratch.py').write_text('')
            evidence, output = self.run(d, ['probe.py', 'scratch.py'], 'probe', [],
                                       min(15, self.config.limits.invocation_seconds))
            if (evidence['exit_code'] or evidence['timed_out']
                    or b'GENESIS_CONTAINMENT_PROBE=' not in output):
                raise SafetyError('active containment probe failed; Aider was not launched')
            self.last_probe = evidence


def supervise(cmd, timeout, output_limit, evidence_argv=None):
    start = time.monotonic()
    output = bytearray()
    timed_out = False
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True,
                         env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, close_fds=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(0.1, remaining)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(data[:max(0, output_limit + 1 - len(output))])
                if len(output) > output_limit:
                    break
        if timed_out or len(output) > output_limit:
            os.killpg(p.pid, signal.SIGKILL)
        remaining = max(0.01, timeout - (time.monotonic() - start))
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    except BaseException:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        raise
    finally:
        p.stdout.close()
    return result(evidence_argv or cmd, p.returncode, time.monotonic() - start,
                  bytes(output), timed_out), bytes(output)
