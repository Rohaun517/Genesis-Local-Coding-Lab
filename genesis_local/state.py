"""Atomic durable state, private permissions, and advisory execution locks."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
from .workspace import SafetyError


@contextmanager
def lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise SafetyError('concurrent execution refused') from e
        yield
    finally:
        os.close(fd)


class Store:
    def __init__(self, directory):
        self.path = Path(directory).absolute()
        if self.path != self.path.resolve():
            raise SafetyError('state directory symlink refused')
        self.path.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.path.stat().st_uid != os.getuid() or self.path.stat().st_mode & 0o077:
            raise SafetyError('state directory must be owner-only (0700)')

    def file(self, objective_id):
        import re
        if not re.fullmatch('[0-9a-f]{32}', objective_id):
            raise SafetyError('invalid objective ID')
        return self.path / (objective_id + '.json')

    def load(self, objective_id):
        p = self.file(objective_id)
        if p.is_symlink():
            raise SafetyError('state symlink refused')
        return json.loads(p.read_text())

    def save(self, state):
        dest = self.file(state['plan']['objective_id'])
        fd, tmp = tempfile.mkstemp(dir=self.path, prefix='.state-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(state, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
            dfd = os.open(self.path, os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
