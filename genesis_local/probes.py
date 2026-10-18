"""Operator-owned adversarial acceptance payload; no model-generated probe code."""
PROBE = r'''
import errno, json, os, pathlib, resource, signal, socket, subprocess, threading
checks = {}
job = json.loads(pathlib.Path('/control/job.json').read_text())
for namespace, host_id in job['host_namespaces'].items():
    assert os.readlink('/proc/self/ns/' + namespace) != host_id, 'shared host namespace: ' + namespace
checks['separate_namespaces'] = True
def refused(name, action):
    try:
        action()
    except (OSError, RuntimeError):
        checks[name] = True
    else:
        raise AssertionError('boundary failed: ' + name)
refused('shell_exec', lambda: subprocess.run(['/usr/bin/true'], check=True))
def fork():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
refused('process_creation', fork)
refused('sensitive_home', lambda: open('/home/rohaun/.ssh/id_rsa', 'rb'))
refused('host_repository', lambda: open('/home/rohaun/Projects/Genesis-Aider-Test/calculator.py'))
refused('write_outside_workspace', lambda: pathlib.Path('/usr/escape.py').write_text('x'))
refused('write_device_directory', lambda: pathlib.Path('/dev/escape').write_text('x'))
refused('write_unapproved_file', lambda: pathlib.Path('/work/escape.py').write_text('x'))
refused('symlink_escape', lambda: os.symlink('/usr', '/work/link'))
for address, label in [(('1.1.1.1', 443), 'external_network'),
                        (('127.0.0.1', 22), 'host_loopback')]:
    def connect():
        with socket.socket() as s:
            s.settimeout(.2)
            s.connect(address)
    refused(label, connect)
assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
checks['resource_limits'] = True
try:
    bytearray(resource.getrlimit(resource.RLIMIT_AS)[0] + 1)
except (MemoryError, OverflowError):
    checks['memory_limit'] = True
else:
    raise AssertionError('address-space cap failed')
# In probe mode only explicitly listed regular files are writable.
p = pathlib.Path('/work/scratch.py')
p.write_text('approved = True\n')
checks['approved_write'] = p.read_text() == 'approved = True\n'
size = resource.getrlimit(resource.RLIMIT_FSIZE)[0]
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
def oversize():
    with p.open('wb') as f:
        f.seek(size)
        f.write(b'x')
refused('source_byte_limit', oversize)
assert p.stat().st_size <= size
# clone is permitted only for threads; RLIMIT_NPROC must bound them in practice.
event = threading.Event()
threads = []
blocked = False
try:
    for _ in range(resource.getrlimit(resource.RLIMIT_NPROC)[0] + 1):
        t = threading.Thread(target=lambda: event.wait(3))
        try:
            t.start()
        except RuntimeError:
            blocked = True
            break
        threads.append(t)
finally:
    event.set()
    for t in threads:
        t.join()
assert threads, 'thread budget cannot support even one worker thread'
assert blocked, 'thread limit did not stop creation'
checks['thread_limit'] = True
print('GENESIS_CONTAINMENT_PROBE=' + json.dumps(checks, sort_keys=True))
'''
