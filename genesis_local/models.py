"""Versioned, reviewable objective plans."""
from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class Plan:
    objective_id: str
    objective: str
    workspace: str
    expected_source_changes: list[str]
    validation_commands: dict[str, list[str]]
    limits: dict
    baseline: dict
    git_head: str
    checkpoint: bool = False
    git_policy: str = 'explicit-files; validated-only; owner-approved; push-disabled'
    version: int = 1

    def to_dict(self):
        return asdict(self)

    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()
