"""Runs inside Bubblewrap. This file is mounted read-only, never imported from /work."""
import ctypes
import errno
import json
import os
import resource
import runpy
import socket
import socketserver
import sys
import threading


def restrict(limits, per_file):
    for kind, value in ((resource.RLIMIT_FSIZE, per_file),
                        (resource.RLIMIT_AS, limits['memory_bytes']),
                        (resource.RLIMIT_CPU, limits['cpu_seconds']),
                        (resource.RLIMIT_NPROC, limits['process_threads']),
                        (resource.RLIMIT_NOFILE, 96), (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(kind, (value, value))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError('no_new_privs failed')
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError('seccomp unavailable')
    deny = 0x00050000 | errno.EPERM

    def rule(name, action=deny, comparison=None):
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number < 0:
            return
        if lib.seccomp_rule_add_array(ctx, action, number, int(comparison is not None),
                                     ctypes.byref(comparison) if comparison is not None else None):
            raise RuntimeError('seccomp rule failed: ' + name)

    # No executable can be launched after this interpreter starts. No subprocesses,
    # namespace changes, process-group escapes, ptrace or kernel interfaces.
    for name in ('execve', 'execveat', 'fork', 'vfork', 'setsid', 'setpgid', 'unshare',
                 'setns', 'mount', 'umount2', 'pivot_root', 'chroot', 'ptrace',
                 'process_vm_readv', 'process_vm_writev', 'bpf', 'perf_event_open',
                 'keyctl', 'add_key', 'request_key', 'io_uring_setup', 'open_by_handle_at'):
        rule(name)
    rule('clone3', 0x00050000 | errno.ENOSYS)  # libc falls back to clone for threads

    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                    ('a', ctypes.c_uint64), ('b', ctypes.c_uint64)]

    # SCMP_CMP_MASKED_EQ: only thread creation may use clone.
    rule('clone', comparison=Compare(0, 7, 0x10000, 0))
    try:
        if lib.seccomp_load(ctx):
            raise RuntimeError('seccomp load failed')
    finally:
        lib.seccomp_release(ctx)


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        import select
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.settimeout(5)
            upstream.connect('/broker/ollama.sock')
            peers = [self.request, upstream]
            while True:
                ready, _, _ = select.select(peers, [], [], 5)
                if not ready:
                    # Generation can legitimately take longer than five seconds.
                    continue
                for src in ready:
                    data = src.recv(65536)
                    if not data:
                        return
                    (upstream if src is self.request else self.request).sendall(data)


def main():
    job = json.loads(open('/control/job.json').read())
    # Load syscall filter before any untrusted code or Aider imports.
    restrict(job['limits'], job['per_file'])
    if job['mode'] == 'provider':
        import importlib.metadata
        if sys.version_info[:2] != (3, 12) or importlib.metadata.version('aider-chat') != '0.86.2':
            raise RuntimeError('provider requires Python 3.12 and Aider 0.86.2')
        server = socketserver.TCPServer(('127.0.0.1', 11434), Relay)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        sys.argv = ['aider', *job['argv']]
        runpy.run_module('aider', run_name='__main__')
    elif job['mode'] == 'validation':
        sys.path.insert(0, '/work')
        sys.argv = [job['argv'][2], *job['argv'][3:]]
        runpy.run_module(job['argv'][2], run_name='__main__', alter_sys=True)
    elif job['mode'] == 'probe':
        # Operator-owned acceptance code; seccomp still applies.
        sys.path.insert(0, '/work')
        runpy.run_path('/work/probe.py', run_name='__main__')
    else:
        raise RuntimeError('unsupported sandbox mode')


if __name__ == '__main__':
    main()
