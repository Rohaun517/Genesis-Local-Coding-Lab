#!/usr/bin/env python3
"""Focused host-only real-provider regression. Disposable files, no Git operations."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genesis_local.config import Config
from genesis_local.containment import Bubblewrap
from genesis_local.models import Plan
from genesis_local.provider import AiderProvider
from genesis_local.validation import Validator
from genesis_local.workspace import SafetyError, snapshot


def startup_summary(output):
    """Return fixed diagnostic labels only; never persist arbitrary process text."""
    signatures = [
        (b"returned type 'NoneType' instead of 'dict'", 'empty_yaml_configuration'),
        (b'ModuleNotFoundError:', 'missing_python_dependency'),
        (b'ImportError:', 'python_import_failure'),
        (b'Bad git executable', 'git_subprocess_dependency'),
        (b'PermissionError:', 'runtime_permission_denied'),
        (b'unrecognized arguments:', 'unrecognized_cli_arguments'),
        (b'ConnectionError:', 'connection_failure'),
        (b'APIConnectionError:', 'provider_connection_failure'),
        (b'TimeoutError:', 'runtime_timeout'),
    ]
    return [label for signature, label in signatures if signature in output] or ['unclassified_output']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-disposable-fixture', action='store_true', required=True)
    parser.add_argument('--evidence', required=True, help='new private evidence JSON; never overwrites')
    parser.add_argument('--aider-python', default=Config().aider_python)
    args = parser.parse_args(argv)
    output_path = Path(args.evidence).absolute()
    # Reserve evidence exclusively before mutations. Preexisting files/symlinks survive.
    try:
        fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        parser.error('evidence must be a new file in an existing writable directory')
    report = {'status': 'BLOCKED', 'scope': 'FOCUSED_HOST_PROVIDER_REGRESSION',
              'started_at': time.time(), 'phase': 'containment_preflight', 'git_operations': False, 'full_host_acceptance_run': False,
              'raw_process_output_persisted': False,
              'broker_authorization': 'mounted Unix-socket capability; no HTTP bearer authentication configured'}
    try:
        config = replace(Config(), aider_python=args.aider_python)
        sandbox = Bubblewrap(config)
        provider = AiderProvider(config, sandbox)
        # Same full active policy verification as production. No skip or fallback.
        report['containment'] = provider.preflight()
        with tempfile.TemporaryDirectory(prefix='genesis-provider-startup-') as d:
            root = Path(d)
            (root / '.genesis-disposable').write_text('development-only\n')
            (root / 'tests').mkdir()
            (root / 'utility.py').write_text('def add(a, b):\n    return a - b\n')
            (root / 'tests/test_utility.py').write_text(
                'import unittest\nfrom utility import add\nclass AddTests(unittest.TestCase):\n'
                '    def test_add(self):\n'
                '        self.assertEqual(add(2, 3), 5)\n'
                '        self.assertEqual(add(-2, 3), 1)\n'
                '        self.assertEqual(add(0, 0), 0)\n')
            names = ['utility.py', 'tests/test_utility.py']
            baseline = snapshot(root, names, config.limits.written_bytes // len(names))
            plan = Plan(uuid.uuid4().hex,
                'Fix utility.py so add(a, b) returns a + b. Only change utility.py; '
                'leave tests/test_utility.py unchanged. Make the minimal source correction.',
                str(root), names, config.validations, vars(config.limits), baseline,
                'not-applicable-no-git', False)
            report['plan'] = plan.to_dict()
            report['approval'] = {'decision': 'approve', 'plan_digest': plan.digest(),
                                  'scope': 'disposable fixture generation and validation only; no checkpoint'}
            report['fixture_removed_on_exit'] = True
            report['phase'] = 'provider_generation'
            evidence, output, calls = provider.generate(plan, root, plan.objective,
                config.limits.provider_invocations, config.limits.invocation_seconds)
            report['provider'] = evidence
            report['startup_diagnostics'] = startup_summary(output) if evidence['exit_code'] else []
            if evidence['exit_code'] or evidence['timed_out']:
                raise SafetyError('contained provider failed; inspect fixed diagnostic labels and output digest')
            if calls < 1 or evidence['broker']['denials'] or evidence['broker']['requests'] < 1:
                raise SafetyError('no proven broker-authorized inference request')
            after = snapshot(root, names, config.limits.written_bytes // len(names))
            if (after['utility.py'] == baseline['utility.py']
                    or after['tests/test_utility.py'] != baseline['tests/test_utility.py']):
                raise SafetyError('expected generated source change or independent test preservation failed')
            report['phase'] = 'contained_validation'
            checks, _ = Validator(config, sandbox).run(plan, root, config.limits.invocation_seconds)
            report['validation'] = checks
            if (len(checks) != len(plan.validation_commands)
                    or any(item['exit_code'] or item['timed_out'] for item in checks)):
                raise SafetyError('contained validation failed')
            if snapshot(root, names, config.limits.written_bytes // len(names)) != after:
                raise SafetyError('validation changed source')
            report['validated_hashes'] = after
            report['phase'] = 'complete'
            report['status'] = 'PROVIDER_GENERATION_AND_VALIDATION_PASSED'
    except (Exception, KeyboardInterrupt) as e:
        # Exception text may include secrets; only retain a fixed category and type.
        report['failure_type'] = type(e).__name__
        report['failure_category'] = 'focused_provider_regression_not_completed'
    finally:
        report['finished_at'] = time.time()
        with os.fdopen(fd, 'w') as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'PROVIDER_GENERATION_AND_VALIDATION_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
