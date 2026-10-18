from dataclasses import replace
import http.client
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from genesis_local.broker import ollama_broker
from genesis_local.config import Config
from genesis_local.containment import Bubblewrap
from genesis_local.provider import AiderProvider
from genesis_local.workspace import SafetyError


class MemoryTransport:
    """Exercises the actual HTTP handler without binding sockets in Codex."""
    current = None
    def __init__(self, path, handler):
        self.handler = handler
        MemoryTransport.current = self
    def handle_request(self):
        time.sleep(.01)
    def server_close(self):
        pass


class RequestSocket:
    def __init__(self, data):
        self.input = io.BytesIO(data)
        self.output = bytearray()
    def makefile(self, *args, **kwargs):
        return self.input
    def settimeout(self, timeout):
        pass
    def sendall(self, data):
        self.output.extend(data)


class Response:
    status = 200
    def read(self, limit):
        return b'{"message":{"content":"test"},"done":true}'


class Upstream:
    requests = []
    def __init__(self, *args, **kwargs):
        pass
    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
    def getresponse(self):
        return Response()
    def close(self):
        pass


class SecurityTests(unittest.TestCase):
    def test_actual_seccomp_blocks_exec_and_fork(self):
        # Runs in a child interpreter; does not alter the test runner's syscall policy.
        code = '''
from genesis_local._sandbox_bootstrap import restrict
from genesis_local.config import Limits
import os, subprocess
restrict(vars(Limits()), 1024)
try:
    subprocess.run(['/usr/bin/true'])
except PermissionError:
    pass
else:
    raise AssertionError('exec escaped')
try:
    pid = os.fork()
except PermissionError:
    pass
else:
    if pid == 0: os._exit(0)
    os.waitpid(pid, 0)
    raise AssertionError('fork escaped')
print('FILTER_OK')
'''
        p = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, timeout=5)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertIn(b'FILTER_OK', p.stdout)

    def request(self, path, route, data=None, method='POST'):
        body = json.dumps(data or {}).encode()
        raw = (f'{method} {route} HTTP/1.0\r\nHost: localhost\r\n'
               f'Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n').encode() + body
        connection = RequestSocket(raw)
        server = MemoryTransport.current
        server.handler(connection, ('local', 0), server)
        status = int(bytes(connection.output).split(b' ', 2)[1])
        return status, bytes(connection.output)

    def test_broker_allowlist_model_context_and_budget(self):
        Upstream.requests = []
        with tempfile.TemporaryDirectory() as d, patch('genesis_local.broker.UnixHTTP', MemoryTransport):
            path = Path(d) / 'broker.sock'
            with ollama_broker(path, Config(), 1, time.time() + 10) as metrics:
                with patch('genesis_local.broker.http.client.HTTPConnection', Upstream):
                    self.assertEqual(self.request(path, '/api/pull', {'model': 'other'})[0], 403)
                    self.assertEqual(self.request(path, '/api/chat', {'model': 'other'})[0], 403)
                    self.assertEqual(self.request(path, 'http://evil/api/chat')[0], 403)
                    self.assertEqual(self.request(path, '/api/chat', {
                        'model': 'qwen2.5-coder:32b', 'messages': [], 'stream': True,
                        'options': {'num_ctx': 99999}, 'keep_alive': -1})[0], 200)
                    self.assertEqual(self.request(path, '/api/chat', {'model': 'qwen2.5-coder:32b'})[0], 403)
                self.assertEqual(metrics['provider_calls'], 1)
                self.assertEqual(len(Upstream.requests), 1)
                data = json.loads(Upstream.requests[0][1]['body'])
                self.assertEqual(data['options']['num_ctx'], 16384)
                self.assertFalse(data['stream'])
                self.assertNotIn('keep_alive', data)

    def test_broker_deadline(self):
        with tempfile.TemporaryDirectory() as d, patch('genesis_local.broker.UnixHTTP', MemoryTransport):
            path = Path(d) / 'broker.sock'
            with ollama_broker(path, Config(), 0, time.time() + 5):
                self.assertEqual(self.request(path, '/api/chat', {'model': 'qwen2.5-coder:32b'})[0], 403)

    def test_unavailable_containment_no_aider(self):
        sandbox = Bubblewrap(Config())
        class Failed:
            returncode = 1
        with patch('genesis_local.containment.subprocess.run', return_value=Failed()):
            with self.assertRaises(SafetyError):
                AiderProvider(Config(), sandbox).preflight()

    def test_no_uncontained_provider_fallback(self):
        class Sandbox:
            def preflight(self):
                raise SafetyError('no namespaces')
        with self.assertRaises(SafetyError):
            AiderProvider(Config(), Sandbox()).preflight()

class AdditionalSecurityTests(unittest.TestCase):
    def test_provider_requires_active_probe(self):
        from genesis_local.provider import AiderProvider
        with self.assertRaises(SafetyError):
            AiderProvider(Config()).generate(None, None, 'objective', 1, 1)

    def test_provider_flags(self):
        from contextlib import contextmanager
        from genesis_local.models import Plan
        from genesis_local.evidence import result
        class Sandbox:
            def run(self, work, names, mode, argv, timeout, broker=None):
                self.argv = argv
                return result(argv, 0, .1), b''
        @contextmanager
        def broker(*args):
            yield {'provider_calls': 1, 'denials': 0, 'requests': 1}
        sandbox = Sandbox()
        provider = AiderProvider(Config(), sandbox)
        provider._verified = True  # Only this adapter-unit test bypasses a real host probe.
        plan = Plan('0'*32, 'objective', '/fixture', ['utility.py'], {}, {}, {}, 'a'*40)
        with patch('genesis_local.provider.ollama_broker', broker):
            evidence, _, calls = provider.generate(plan, '/candidate', 'objective', 1, 3)
        for flag in ('--no-git', '--no-auto-commits', '--no-dirty-commits', '--no-auto-test',
                     '--no-auto-lint', '--no-suggest-shell-commands', '--no-detect-urls'):
            self.assertIn(flag, sandbox.argv)
        self.assertEqual(calls, 1)
        self.assertEqual(evidence['argv'][-1], '<approved-objective-or-bounded-repair>')


class NamespaceJobTests(unittest.TestCase):
    def test_probe_receives_real_host_namespace_ids(self):
        from genesis_local.evidence import result
        sandbox = Bubblewrap(Config())
        def inspect_job(cmd, *args, **kwargs):
            control = Path(cmd[cmd.index('/control') - 1])
            job = json.loads((control / 'job.json').read_text())
            import os
            for name in ('net', 'pid', 'mnt', 'user'):
                self.assertEqual(job['host_namespaces'][name], os.readlink('/proc/self/ns/' + name))
            return result([], 0, .01), b''
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'probe.py').write_text('pass')
            with patch('genesis_local.containment.supervise', side_effect=inspect_job):
                sandbox.run(d, ['probe.py'], 'probe', [], 1)


if __name__ == '__main__':
    unittest.main()
