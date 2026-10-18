"""Deterministic planner: objectives never select files or executable commands."""
import uuid
from .config import Config
from .git_checkpoint import inspect
from .models import Plan
from .workspace import SafetyError, root_path, relative, safe_text, snapshot


def plan_objective(objective, workspace, files, validations, config: Config, checkpoint=False):
    config.check()
    safe_text(objective)
    if not objective.strip() or len(objective) > 12000:
        raise SafetyError('objective must contain 1..12000 characters')
    root = root_path(workspace)
    names = sorted(set(relative(x) for x in files))
    if not names or len(names) > config.limits.changed_files:
        raise SafetyError('approved file count exceeds limit or is empty')
    if not validations or any(x not in config.validations for x in validations):
        raise SafetyError('validation not explicitly allowlisted')
    baseline = snapshot(root, names, config.limits.written_bytes)
    per_file = config.limits.written_bytes // len(names)
    for name in names:
        p = root / name
        if p.exists() and p.stat().st_size > per_file:
            raise SafetyError('source exceeds conservative per-file write allowance')
    return Plan(uuid.uuid4().hex, objective, str(root), names,
                {x: config.validations[x] for x in validations}, vars(config.limits),
                baseline, inspect(root, names), checkpoint)
