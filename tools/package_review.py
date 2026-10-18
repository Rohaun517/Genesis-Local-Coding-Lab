#!/usr/bin/env python3
"""Build a deterministic source-only ZIP from this explicit delivery allowlist."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'artifacts/genesis-local-source.zip'
# No filesystem glob over the repository root: legacy artifacts never enter review.
FILES = [
    'pyproject.toml', 'README.md', 'FILE_MANIFEST.md',
    'genesis_local/__init__.py', 'genesis_local/__main__.py',
    'genesis_local/cli.py', 'genesis_local/config.py', 'genesis_local/models.py',
    'genesis_local/planner.py', 'genesis_local/provider.py', 'genesis_local/containment.py',
    'genesis_local/_sandbox_bootstrap.py', 'genesis_local/probes.py', 'genesis_local/broker.py',
    'genesis_local/coordinator.py', 'genesis_local/validation.py',
    'genesis_local/git_checkpoint.py', 'genesis_local/state.py', 'genesis_local/recovery.py',
    'genesis_local/workspace.py', 'genesis_local/evidence.py', 'genesis_local/deadline.py',
    'tests/test_orchestrator.py', 'tests/test_security.py',
    'tools/fixture_workflow.py', 'tools/host_acceptance.py', 'tools/package_review.py',
    'docs/ARCHITECTURE.md', 'docs/HOST_ACCEPTANCE.md', 'docs/ACCEPTANCE_REPORT.md',
    'artifacts/available-tests.txt', 'artifacts/fixture-workflow.json',
    'artifacts/host-acceptance-pending.json',
]


def main():
    inventory = {}
    for name in sorted(FILES):
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('missing or symlink delivery file: ' + name)
        data = path.read_bytes()
        inventory[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    inventory_name = 'artifacts/source-inventory.json'
    (ROOT / inventory_name).write_text(json.dumps({
        'files': inventory,
        'archive_members': sorted([*FILES, inventory_name]),
        'self_hash_excluded': inventory_name,
        'excluded': ['.git', 'preexisting source', 'Aider histories/caches', 'bytecode',
                     'virtualenvs', 'credentials', 'runtime state/candidates', 'nested archives'],
    }, indent=2, sort_keys=True) + '\n')
    with zipfile.ZipFile(ARCHIVE, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted([*FILES, inventory_name]):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 18, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, (ROOT / name).read_bytes())
    checksum = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    (ROOT / 'artifacts/genesis-local-source.zip.sha256').write_text(
        checksum + '  genesis-local-source.zip\n')
    print(f'{len(FILES) + 1} archive members; SHA256 {checksum}')


if __name__ == '__main__':
    main()
