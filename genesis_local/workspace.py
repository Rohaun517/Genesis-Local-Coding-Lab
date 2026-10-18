"""Fail-closed path, file-type, secret and snapshot checks."""
import os
from pathlib import Path, PurePosixPath
import re
import stat
from .evidence import digest


class SafetyError(RuntimeError):
    pass


SECRET = re.compile(rb'(-----BEGIN [A-Z ]*PRIVATE KEY-----|'
                    rb'(?i:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*[\"\x27]?[^\s\"\x27]{8,}|'
                    rb'AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,})')


def safe_text(value):
    if not isinstance(value, str) or '\x00' in value or SECRET.search(value.encode()):
        raise SafetyError('secret-like or invalid text refused')
    return value


def relative(name):
    if not isinstance(name, str):
        raise SafetyError('file path must be text')
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or str(p) != name or '..' in p.parts
            or any(x.startswith('.') for x in p.parts)
            or any(x.lower() in {'credentials', 'id_rsa', 'id_ed25519', 'secrets', 'node_modules'}
                   for x in p.parts)
            or p.suffix.lower() not in {'.py', '.md', '.txt', '.toml', '.json', '.yaml', '.yml'}
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-' for c in name)
            or any(s in p.name.lower() for s in ('secret', 'credential', '.env', 'private_key'))):
        raise SafetyError('unapproved source path')
    return name


def root_path(root):
    p = Path(root).absolute()
    if p != p.resolve() or not p.is_dir():
        raise SafetyError('workspace must be a real directory without symlink components')
    # Deliberate opt-in marker is required; this is never inferred from a Git repo.
    marker = p / '.genesis-disposable'
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != 'development-only\n':
        raise SafetyError('explicit disposable workspace marker required')
    return p


def read_source(root, name, cap):
    relative(name)
    root = Path(root)
    p = root
    for component in PurePosixPath(name).parts:
        p = p / component
        if p.is_symlink():
            raise SafetyError('symlink traversal refused')
    if not p.exists():
        return None
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > cap:
            raise SafetyError('nonregular, hardlinked or oversized source refused')
        data = os.read(fd, cap + 1)
    finally:
        os.close(fd)
    if len(data) > cap or SECRET.search(data):
        raise SafetyError('oversized or secret-like source refused')
    return data


def snapshot(root, names, cap):
    return {n: None if (b := read_source(root, n, cap)) is None else digest(b) for n in names}


def materialize(root, target, names, cap):
    target = Path(target)
    for name in names:
        data = read_source(root, name, cap)
        p = target / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if data is not None else b'')
