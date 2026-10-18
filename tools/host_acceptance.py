#!/usr/bin/env python3
"""Host-only, fail-closed acceptance. Creates its own fixture; never accepts a repo path."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_orchestrator import fixture
from genesis_local.config import Config
from genesis_local.containment import Bubblewrap
from genesis_local.coordinator import Coordinator
from genesis_local.git_checkpoint import git
from genesis_local.planner import plan_objective
from genesis_local.probes import PROBE
from genesis_local.state import Store
from genesis_local.workspace import SafetyError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-disposable-fixture', action='store_true', required=True,
                        help='explicit owner approval of fixture mutations and fixture-only checkpoint')
    parser.add_argument('--evidence', required=True, help='new output JSON path outside fixture')
    parser.add_argument('--aider-python', default=Config().aider_python)
    args = parser.parse_args()
    output = Path(args.evidence).absolute()
    if output.exists() or output.is_symlink():
        parser.error('evidence must be a new file')
    report = {'status': 'PENDING', 'host_only': True, 'started_at': time.time(),
              'tests': {}, 'github_push_attempted': False}
    try:
        config = replace(Config(), aider_python=args.aider_python)
        sandbox = Bubblewrap(config)
        sandbox.preflight()
        report['tests']['active_containment_probe'] = {'status': 'PASS', 'evidence': sandbox.last_probe}
        # Test write restrictions for validation separately, not merely the provider view.
        with tempfile.TemporaryDirectory(prefix='genesis-host-acceptance-') as directory:
            root = fixture(directory)
            report['fixture'] = str(root)
            report['fixture_removed_on_exit'] = True
            probe = Path(directory) / 'readonly'
            probe.mkdir()
            (probe / 'probe.py').write_text(
                "from pathlib import Path\n"
                "try: Path('/work/probe.py').write_text('bad')\n"
                "except OSError: print('READONLY_OK')\n"
                "else: raise AssertionError('validation source writable')\n")
            item, data = sandbox.run(probe, ['probe.py'], 'validation', ['python', '-m', 'probe'], 10)
            assert item['exit_code'] == 0 and b'READONLY_OK' in data
            report['tests']['validation_readonly'] = {'status': 'PASS', 'evidence': item}
            (probe / 'probe.py').write_text('import time\ntime.sleep(60)\n')
            item, _ = sandbox.run(probe, ['probe.py'], 'probe', [], .5)
            assert item['timed_out'] and item['elapsed_seconds'] < 5
            report['tests']['namespace_timeout'] = {'status': 'PASS', 'evidence': item}
            cpu_config = replace(config, limits=replace(config.limits, cpu_seconds=1))
            (probe / 'probe.py').write_text('while True: pass\n')
            item, _ = Bubblewrap(cpu_config).run(probe, ['probe.py'], 'probe', [], 5)
            assert item['exit_code'] != 0 and not item['timed_out']
            report['tests']['cpu_limit'] = {'status': 'PASS', 'evidence': item}
            store = Store(Path(directory) / 'state')
            plan = plan_objective(
                'Fix utility.py so add(a, b) returns a + b. Keep tests/test_utility.py unchanged. '
                'Only make the minimal Python source correction.', root,
                ['utility.py', 'tests/test_utility.py'], ['unittest'], config, True)
            runner = Coordinator(config, store)
            runner.create(plan)
            (root / 'unrelated.txt').write_text('owner changes must survive\n')
            (root / '.env').write_text('fixture-only do not expose\n')
            state = runner.execute(plan.objective_id, 'approve', plan.digest())
            report['workflow'] = state
            assert state['status'] == 'SUCCEEDED', state.get('reason', state['status'])
            assert state['checkpoint_hash'] == git(root, 'rev-parse', 'HEAD')
            assert git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD') == 'utility.py'
            assert (root / 'unrelated.txt').read_text() == 'owner changes must survive\n'
            assert (root / '.env').read_text() == 'fixture-only do not expose\n'
            assert git(root, 'diff', '--cached', '--name-only') == ''
            assert runner.execute(plan.objective_id)['checkpoint_hash'] == state['checkpoint_hash']
            report['tests']['real_aider_ollama_fixture'] = {'status': 'PASS'}
            report['tests']['checkpoint_and_safe_restart'] = {'status': 'PASS'}
            # Symlink candidate must be rejected before a contained invocation.
            (probe / 'linked.py').symlink_to(root / 'utility.py')
            try:
                sandbox.run(probe, ['linked.py'], 'probe', [], 1)
            except SafetyError:
                report['tests']['symlink_traversal'] = {'status': 'PASS'}
            else:
                raise AssertionError('symlink accepted')
        report['status'] = 'HOST_ACCEPTANCE_PASSED'
    except (Exception, KeyboardInterrupt) as e:
        report['status'] = 'BLOCKED'
        report['failure'] = type(e).__name__ + ': ' + str(e)[:300]
    finally:
        report['finished_at'] = time.time()
        # Output contains hashes/metrics, not raw model output or environment values.
        with output.open('x') as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'HOST_ACCEPTANCE_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
