"""Recover durable mutation journals without repeating provider invocations."""
from pathlib import Path
from .evidence import digest
from .git_checkpoint import find_checkpoint, git
from .workspace import SafetyError, read_source, snapshot


TERMINAL = {'SUCCEEDED', 'DENIED', 'FAILED', 'BLOCKED', 'INTERRUPTED'}


def recover(state, plan, store):
    phase = state['status']
    if phase in {'GENERATING', 'VALIDATING'}:
        state['status'] = 'INTERRUPTED'
        state['reason'] = 'in-flight untrusted execution; no automatic replay; create a new approved objective'
        store.save(state)
    elif phase == 'PUBLISHING':
        publish(state, plan, store)
    elif phase == 'CHECKPOINTING':
        found = find_checkpoint(plan.workspace, plan)
        if found:
            if snapshot(plan.workspace, plan.expected_source_changes,
                        plan.limits['written_bytes']) != state['validated_hashes']:
                raise SafetyError('checkpoint recovery bytes differ')
            committed = git(plan.workspace, 'diff-tree', '--no-commit-id', '--name-only', '-r', found).splitlines()
            if sorted(committed) != sorted(state['changed_files']):
                raise SafetyError('checkpoint recovery file set differs')
            staged = git(plan.workspace, 'diff', '--cached', '--name-only').splitlines()
            if not set(staged) <= set(state['changed_files']):
                raise SafetyError('unrelated staging blocks checkpoint recovery')
            for name in state['changed_files']:
                actual = git(plan.workspace, 'ls-files', '-s', '--', name).split()
                before = git(plan.workspace, 'ls-tree', plan.git_head, '--', name).split()
                after = git(plan.workspace, 'ls-tree', found, '--', name).split()
                allowed = {before[2] if before else None, after[2]}
                if (actual[1] if actual else None) not in allowed:
                    raise SafetyError('owner staging conflicts with checkpoint recovery')
            # Repair index entries if interrupted between ref update and index update.
            for name in state['changed_files']:
                entry = git(plan.workspace, 'ls-tree', found, '--', name).split()
                git(plan.workspace, 'update-index', '--add', '--cacheinfo', entry[0], entry[2], name)
            state['checkpoint_hash'] = found
            state['status'] = 'SUCCEEDED'
            state.pop('reason', None)
            store.save(state)
        elif git(plan.workspace, 'rev-parse', 'HEAD') != plan.git_head:
            raise SafetyError('ambiguous checkpoint recovery')
    return state


def publish(state, plan, store):
    """Compare both old and intended bytes around each atomic source replacement."""
    import os
    import tempfile
    root = Path(plan.workspace)
    candidate = Path(state['candidate'])
    for name in state['changed_files']:
        current = read_source(root, name, plan.limits['written_bytes'])
        current_hash = digest(current) if current is not None else None
        wanted = state['validated_hashes'][name]
        if current_hash == wanted:
            continue
        if current_hash != plan.baseline[name]:
            raise SafetyError('owner edit conflicts with publication recovery')
        data = read_source(candidate, name, plan.limits['written_bytes'])
        if data is None or digest(data) != wanted:
            raise SafetyError('candidate no longer matches validated bytes')
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Recheck parents after mkdir; reject all symlink components.
        read_source(root, name, plan.limits['written_bytes'])
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix='.genesis-publish-')
        try:
            mode = dest.stat().st_mode & 0o777 if dest.exists() else 0o644
            with os.fdopen(fd, 'wb') as f:
                os.fchmod(f.fileno(), mode)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
            dfd = os.open(dest.parent, os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        state.setdefault('published', []).append(name)
        store.save(state)
    state['status'] = 'CHECKPOINTING' if plan.checkpoint else 'SUCCEEDED'
    state.pop('reason', None)
    store.save(state)
