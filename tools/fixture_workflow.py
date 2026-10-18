#!/usr/bin/env python3
"""Known-code disposable fixture demo; mocked generation, real unittest and Git."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_orchestrator import FakeProvider, RealFixtureValidator, fixture
from genesis_local.config import Config
from genesis_local.coordinator import Coordinator
from genesis_local.git_checkpoint import git
from genesis_local.planner import plan_objective
from genesis_local.state import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='genesis-mocked-fixture-') as directory:
        root = fixture(directory)
        store = Store(Path(directory) / 'state')
        config = Config()
        provider = FakeProvider()
        plan = plan_objective('Fix addition, retaining the unit test.', root,
                              ['utility.py', 'tests/test_utility.py'], ['unittest'], config, True)
        runner = Coordinator(config, store, provider, RealFixtureValidator())
        runner.create(plan)
        (root / 'unrelated.txt').write_text('owner changes must survive\n')
        state = runner.execute(plan.objective_id, 'approve', plan.digest())
        assert state['status'] == 'SUCCEEDED', state
        before = state['checkpoint_hash']
        assert runner.execute(plan.objective_id)['checkpoint_hash'] == before
        assert provider.calls == 1
        assert (root / 'unrelated.txt').read_text() == 'owner changes must survive\n'
        evidence = {
            'scope': 'MOCKED_PROVIDER_REAL_VALIDATION_REAL_DISPOSABLE_GIT',
            'not_host_containment_acceptance': True,
            'state': state,
            'checkpoint_changed_files': git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'),
            'owner_changes_preserved': True,
            'safe_restart_no_repeated_provider_call': True,
            'github_push_attempted': False,
            'fixture_removed_on_exit': True,
        }
        Path(args.evidence).write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
        print(json.dumps({k: v for k, v in evidence.items() if k != 'state'}, indent=2))


if __name__ == '__main__':
    main()
