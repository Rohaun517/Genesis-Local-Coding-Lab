"""Operator configuration. Commands are argv arrays, never shell text."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    elapsed_seconds: int = 900
    invocation_seconds: int = 240
    provider_invocations: int = 3
    repair_attempts: int = 2
    changed_files: int = 8
    written_bytes: int = 262144
    memory_bytes: int = 4 * 1024**3
    cpu_seconds: int = 180
    process_threads: int = 32
    temporary_bytes: int = 16 * 1024**2
    output_bytes: int = 1024**2

    def check(self):
        if any(type(v) is not int or v <= 0 for k, v in vars(self).items()
               if k != 'repair_attempts'):
            raise ValueError('limits must be positive integers')
        if type(self.repair_attempts) is not int or not 0 <= self.repair_attempts <= 2:
            raise ValueError('at most two repairs')
        if self.provider_invocations > 3:
            raise ValueError('at most three provider invocations')


@dataclass(frozen=True)
class Config:
    aider_python: str = '/home/rohaun/.venvs/genesis-aider/bin/python'
    bwrap: str = '/usr/bin/bwrap'
    model: str = 'qwen2.5-coder:32b'
    endpoint: str = 'http://127.0.0.1:11434'
    limits: Limits = field(default_factory=Limits)
    validations: dict = field(default_factory=lambda: {
        'unittest': ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-v']})

    def check(self):
        self.limits.check()
        if self.model != 'qwen2.5-coder:32b' or self.endpoint != 'http://127.0.0.1:11434':
            raise ValueError('V1 only supports the local pinned model endpoint')
        for name, argv in self.validations.items():
            if (not name or not isinstance(argv, list) or len(argv) < 3
                    or argv[:2] != ['python', '-m']
                    or not all(isinstance(x, str) and '\x00' not in x for x in argv)
                    or not all(c.isalnum() or c in '._' for c in argv[2])):
                raise ValueError('validation allowlist requires Python module argv')
        if not Path(self.aider_python).is_absolute():
            raise ValueError('absolute provider interpreter required')
