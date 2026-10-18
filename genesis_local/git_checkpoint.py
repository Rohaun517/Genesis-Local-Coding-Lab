"""Plumbing checkpoints use a private index; never stage into the owner's index."""
import os
from pathlib import Path
import subprocess
import tempfile
from .workspace import SafetyError


def git(root, *args, env=None, binary=False):
    clean = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1',
             'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
    if env:
        clean.update(env)
    p = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                        '-c', 'core.untrackedCache=false', '-C', str(root), *args],
                       env=clean, capture_output=True, timeout=15)
    if p.returncode:
        raise SafetyError('Git operation refused: ' + args[0])
    return p.stdout if binary else p.stdout.decode().strip()


def inspect(root, approved):
    root = Path(root)
    if (root / '.git').is_symlink() or not (root / '.git').is_dir():
        raise SafetyError('standalone Git repository required')
    if Path(git(root, 'rev-parse', '--show-toplevel')) != root:
        raise SafetyError('ambiguous Git root')
    for n in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'index.lock'):
        if (root / '.git' / n).exists():
            raise SafetyError('ambiguous Git operation in progress')
    head = git(root, 'rev-parse', 'HEAD')
    git(root, 'symbolic-ref', '-q', 'HEAD')
    if git(root, 'diff', '--cached', '--name-only'):
        raise SafetyError('preexisting staged changes refused')
    if git(root, 'ls-files', '-u'):
        raise SafetyError('unmerged index refused')
    for n in approved:
        if git(root, 'status', '--porcelain', '--untracked-files=all', '--', n):
            raise SafetyError('approved file already has owner changes')
        # Exclude ignored paths, filters, symlink entries, and submodules.
        attrs = git(root, 'check-attr', 'filter', '--', n)
        if not attrs.endswith(': unspecified'):
            raise SafetyError('Git filters not supported')
        entry = git(root, 'ls-files', '-s', '--', n)
        if entry and not entry.startswith(('100644 ', '100755 ')):
            raise SafetyError('nonregular Git entry refused')
        q = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--', n],
                           capture_output=True, timeout=10)
        if q.returncode != 1:
            raise SafetyError('ignored or ambiguous approved path')
    return head


def checkpoint(root, plan, files, expected_hashes):
    from .workspace import snapshot
    if not plan.checkpoint or not files or not set(files) <= set(plan.expected_source_changes):
        raise SafetyError('checkpoint lacks explicit approved validated changes')
    # Approved changes now exist, so inspect everything except their dirty status.
    inspect(root, [])
    if git(root, 'rev-parse', 'HEAD') != plan.git_head:
        raise SafetyError('HEAD changed')
    if snapshot(root, plan.expected_source_changes, plan.limits['written_bytes']) != expected_hashes:
        raise SafetyError('validated bytes changed')
    ref = git(root, 'symbolic-ref', '-q', 'HEAD')
    with tempfile.TemporaryDirectory(prefix='genesis-index-') as d:
        env = {'GIT_INDEX_FILE': str(Path(d) / 'index')}
        git(root, 'read-tree', plan.git_head, env=env)
        for name in files:
            # hash-object --no-filters avoids repo-configured command execution.
            blob = git(root, 'hash-object', '-w', '--no-filters', '--', name)
            mode = '100755' if os.stat(Path(root) / name).st_mode & 0o111 else '100644'
            git(root, 'update-index', '--add', '--cacheinfo', mode, blob, name, env=env)
        tree = git(root, 'write-tree', env=env)
        env.update(GIT_AUTHOR_NAME='Genesis Local Development', GIT_AUTHOR_EMAIL='genesis@localhost',
                   GIT_COMMITTER_NAME='Genesis Local Development', GIT_COMMITTER_EMAIL='genesis@localhost')
        commit = git(root, 'commit-tree', tree, '-p', plan.git_head,
                     '-m', f'genesis-local: {plan.objective_id}', env=env)
        git(root, 'update-ref', ref, commit, plan.git_head)
        # Owner index must reflect the committed approved entries, without touching others.
        for name in files:
            entry = git(root, 'ls-tree', commit, '--', name).split()
            git(root, 'update-index', '--add', '--cacheinfo', entry[0], entry[2], name)
        return commit


def find_checkpoint(root, plan):
    head = git(root, 'rev-parse', 'HEAD')
    if (git(root, 'show', '-s', '--format=%B', head) == f'genesis-local: {plan.objective_id}'
            and git(root, 'rev-parse', head + '^') == plan.git_head):
        return head
    return None
