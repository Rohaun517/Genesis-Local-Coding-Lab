import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from genesis_local.cli import main
from genesis_local.config import Config, Limits
from genesis_local.containment import Bubblewrap, supervise
from genesis_local.coordinator import Coordinator
from genesis_local.evidence import result
from genesis_local.git_checkpoint import checkpoint, git
from genesis_local.planner import plan_objective
from genesis_local.recovery import recover
from genesis_local.state import Store, lock
from genesis_local.workspace import SafetyError, read_source, relative, snapshot


def fixture(parent):
    root = Path(parent) / 'fixture'
    root.mkdir()
    (root / '.genesis-disposable').write_text('development-only\n')
    (root / 'utility.py').write_text('def add(a, b):\n    return a - b\n')
    (root / 'tests').mkdir()
    (root / 'tests/test_utility.py').write_text(
        'import unittest\nfrom utility import add\nclass TestAdd(unittest.TestCase):\n'
        '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n')
    (root / 'unrelated.txt').write_text('owner baseline\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', 'utility.py', 'tests', 'unrelated.txt'], check=True)
    env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@localhost',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@localhost')
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), 'commit', '-qm', 'fixture baseline'],
                   check=True, env=env)
    return root


class FakeProvider:
    def __init__(self, failure=False, interrupt=False, mutate=None):
        self.calls = 0
        self.failure, self.interrupt, self.mutate = failure, interrupt, mutate

    def preflight(self):
        pass

    def generate(self, plan, candidate, message, remaining_calls, timeout):
        self.calls += 1
        if self.interrupt:
            raise KeyboardInterrupt()
        (Path(candidate) / 'utility.py').write_text('def add(a, b):\n    return a + b\n')
        if self.mutate:
            self.mutate(plan, candidate)
        return result(['fake-provider'], 1 if self.failure else 0, 0.01), b'', 1


class FakeValidator:
    def __init__(self, failures=0, timed_out=False, interrupt=False, mutate=False):
        self.calls, self.failures = 0, failures
        self.timed_out, self.interrupt, self.mutate = timed_out, interrupt, mutate

    def run(self, plan, candidate, remaining):
        self.calls += 1
        if self.interrupt:
            raise KeyboardInterrupt()
        if self.mutate:
            (Path(candidate) / 'utility.py').write_text('changed after validation\n')
        return [result(['python', '-m', 'unittest'], int(self.calls <= self.failures),
                       .01, timed_out=self.timed_out)], b'test failed' if self.calls <= self.failures else b'OK'


class RealFixtureValidator:
    """Only test-owned known code is run this way. Production always uses Bubblewrap."""
    def run(self, plan, candidate, remaining):
        started = time.monotonic()
        p = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                           cwd=candidate, capture_output=True, timeout=10,
                           env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
        output = p.stdout + p.stderr
        return [result(['python', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                       p.returncode, time.monotonic() - started, output)], output


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = fixture(self.tmp.name)
        self.config = Config()
        self.store = Store(Path(self.tmp.name) / 'state')
        self.provider = FakeProvider()
        self.validator = FakeValidator()

    def make(self, checkpoint_enabled=False, provider=None, validator=None):
        p = plan_objective('Fix addition and preserve tests.', self.root,
                           ['utility.py', 'tests/test_utility.py'], ['unittest'],
                           self.config, checkpoint_enabled)
        runner = Coordinator(self.config, self.store, provider or self.provider, validator or self.validator)
        runner.create(p)
        return p, runner

    def run_plan(self, p, runner):
        return runner.execute(p.objective_id, 'approve', p.digest())

    def test_successful_objective_and_real_fixture_validation(self):
        p, runner = self.make(True, validator=RealFixtureValidator())
        (self.root / 'unrelated.txt').write_text('owner changes preserved\n')
        (self.root / 'owner-untracked.txt').write_text('owner data')
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'SUCCEEDED')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), state['checkpoint_hash'])
        self.assertEqual(git(self.root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'), 'utility.py')
        self.assertEqual(git(self.root, 'diff', '--cached', '--name-only'), '')
        self.assertEqual((self.root / 'unrelated.txt').read_text(), 'owner changes preserved\n')
        self.assertEqual((self.root / 'owner-untracked.txt').read_text(), 'owner data')
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(runner.execute(p.objective_id)['checkpoint_hash'], state['checkpoint_hash'])
        self.assertEqual(self.provider.calls, 1)

    def test_explicit_denial(self):
        p, runner = self.make()
        self.assertEqual(runner.execute(p.objective_id, 'deny', p.digest())['status'], 'DENIED')
        self.assertEqual(self.provider.calls, 0)

    def test_no_implicit_approval(self):
        p, runner = self.make()
        self.assertEqual(runner.execute(p.objective_id)['status'], 'PLANNED')
        self.assertEqual(self.provider.calls, 0)

    def test_approval_digest_required(self):
        p, runner = self.make()
        self.assertEqual(runner.execute(p.objective_id, 'approve', 'bad')['status'], 'BLOCKED')
        self.assertEqual(self.provider.calls, 0)

    def test_provider_failure(self):
        p, runner = self.make(provider=FakeProvider(failure=True))
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'FAILED')
        self.assertEqual(self.validator.calls, 0)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), p.git_head)

    def test_bounded_repairs_validation_failure(self):
        p, runner = self.make(validator=FakeValidator(failures=99))
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'FAILED')
        self.assertEqual(state['repairs'], 2)
        self.assertEqual(state['provider_invocations'], 3)
        self.assertEqual(self.provider.calls, 3)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), p.git_head)

    def test_repair_success(self):
        p, runner = self.make(validator=FakeValidator(failures=1))
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'SUCCEEDED')
        self.assertEqual(state['repairs'], 1)

    def test_provider_budget(self):
        self.config = replace(self.config, limits=replace(self.config.limits, provider_invocations=1))
        p, runner = self.make(validator=FakeValidator(failures=99))
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'BLOCKED')
        self.assertEqual(self.provider.calls, 1)

    def test_timeout_supervisor(self):
        item, _ = supervise([sys.executable, '-c', 'import time; time.sleep(5)'], .15, 1024)
        self.assertTrue(item['timed_out'])
        self.assertLess(item['elapsed_seconds'], 2)
        self.assertNotEqual(item['exit_code'], 0)

    def test_output_limit(self):
        item, output = supervise([sys.executable, '-c', 'while True: print("x"*1000, flush=True)'], 3, 1024)
        self.assertLessEqual(len(output), 1025)
        self.assertNotEqual(item['exit_code'], 0)

    def test_elapsed_timeout(self):
        p, runner = self.make()
        state = self.store.load(p.objective_id)
        state['deadline'] = time.time() - 1
        state['status'] = 'APPROVED'
        self.store.save(state)
        self.assertEqual(runner.execute(p.objective_id)['status'], 'BLOCKED')
        self.assertEqual(self.provider.calls, 0)

    def test_interrupted_generation_safe_restart(self):
        provider = FakeProvider(interrupt=True)
        p, runner = self.make(provider=provider)
        with self.assertRaises(KeyboardInterrupt):
            self.run_plan(p, runner)
        state = runner.execute(p.objective_id)
        self.assertEqual(state['status'], 'INTERRUPTED')
        self.assertEqual(provider.calls, 1)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), p.git_head)

    def test_interrupted_validation_safe_restart(self):
        p, runner = self.make(validator=FakeValidator(interrupt=True))
        with self.assertRaises(KeyboardInterrupt):
            self.run_plan(p, runner)
        self.assertEqual(runner.execute(p.objective_id)['status'], 'INTERRUPTED')
        self.assertEqual(self.provider.calls, 1)

    def test_workspace_escape(self):
        for name in ('../evil.py', '/tmp/evil.py', 'a/../../evil.py', '.git/config', 'a//b.py'):
            with self.subTest(name=name), self.assertRaises(SafetyError):
                relative(name)

    def test_workspace_marker_required(self):
        (self.root / '.genesis-disposable').unlink()
        with self.assertRaises(SafetyError):
            self.make()

    def test_symlink_traversal(self):
        (self.root / 'linked').symlink_to(self.root / 'tests', target_is_directory=True)
        with self.assertRaises(SafetyError):
            read_source(self.root, 'linked/test_utility.py', 1024)
        (self.root / 'linked.py').symlink_to(self.root / 'utility.py')
        with self.assertRaises(SafetyError):
            read_source(self.root, 'linked.py', 1024)

    def test_hardlink_refused(self):
        os.link(self.root / 'utility.py', self.root / 'hard.py')
        with self.assertRaises(SafetyError):
            read_source(self.root, 'hard.py', 1024)

    def test_secret_file_and_content_exclusion(self):
        for name in ('.env', 'credentials.json', 'secrets.py', '.ssh/id_rsa'):
            with self.assertRaises(SafetyError):
                relative(name)
        (self.root / 'new.py').write_text('api_key = "' + 'a' * 32 + '"')
        with self.assertRaises(SafetyError):
            read_source(self.root, 'new.py', 1024)
        with self.assertRaises(SafetyError):
            plan_objective('password=' + 'a' * 20, self.root, ['utility.py'], ['unittest'], self.config)

    def test_generated_secret_not_published(self):
        def mutate(plan, candidate):
            (Path(candidate) / 'utility.py').write_text('api_key="' + 'z' * 32 + '"')
        p, runner = self.make(provider=FakeProvider(mutate=mutate))
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')
        self.assertNotIn('z' * 32, self.store.file(p.objective_id).read_text())

    def test_unauthorized_git_staging(self):
        (self.root / 'unrelated.txt').write_text('staged owner change')
        subprocess.run(['git', '-C', str(self.root), 'add', 'unrelated.txt'], check=True)
        with self.assertRaises(SafetyError):
            self.make(True)
        self.assertEqual(git(self.root, 'diff', '--cached', '--name-only'), 'unrelated.txt')

    def test_staging_appears_during_generation(self):
        def stage(plan, candidate):
            (self.root / 'unrelated.txt').write_text('owner staging')
            subprocess.run(['git', '-C', str(self.root), 'add', 'unrelated.txt'], check=True)
        p, runner = self.make(True, provider=FakeProvider(mutate=stage))
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')
        self.assertEqual(git(self.root, 'diff', '--cached', '--name-only'), 'unrelated.txt')

    def test_checkpoint_rejects_unapproved_files(self):
        p, runner = self.make(True)
        with self.assertRaises(SafetyError):
            checkpoint(self.root, p, ['unrelated.txt'], p.baseline)

    def test_push_disabled(self):
        self.assertFalse(hasattr(self.config, 'push'))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['--state-dir', str(self.store.path), 'push'])
        for file in ('git_checkpoint.py', 'provider.py', 'coordinator.py'):
            text = (Path(__file__).parents[1] / 'genesis_local' / file).read_text()
            self.assertNotIn("'push'", text)

    def test_concurrent_execution_attempts(self):
        p, runner = self.make()
        with lock(self.root / '.genesis-execution.lock'):
            with self.assertRaises(SafetyError):
                self.run_plan(p, runner)
        with lock(self.store.path / '.lock'):
            with self.assertRaises(SafetyError):
                runner.execute(p.objective_id)

    def test_failure_recovery_during_publication(self):
        p, runner = self.make(True)
        from genesis_local.recovery import publish
        with patch('genesis_local.coordinator.publish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan(p, runner)
        self.assertEqual(self.store.load(p.objective_id)['status'], 'PUBLISHING')
        state = runner.execute(p.objective_id)
        self.assertEqual(state['status'], 'SUCCEEDED')
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(state['checkpoint_hash'], git(self.root, 'rev-parse', 'HEAD'))

    def test_failure_recovery_after_ref_update(self):
        p, runner = self.make(True)
        from genesis_local.git_checkpoint import checkpoint as actual
        def crash(*args):
            actual(*args)
            raise KeyboardInterrupt()
        with patch('genesis_local.coordinator.checkpoint', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan(p, runner)
        before = git(self.root, 'rev-parse', 'HEAD')
        self.assertEqual(runner.execute(p.objective_id)['checkpoint_hash'], before)
        self.assertEqual(self.provider.calls, 1)

    def test_owner_edit_blocks_recovery(self):
        p, runner = self.make()
        with patch('genesis_local.coordinator.publish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan(p, runner)
        (self.root / 'utility.py').write_text('owner intervening edit\n')
        state = runner.execute(p.objective_id)
        self.assertEqual(state['status'], 'PUBLISHING')
        self.assertIn('conflicts', state['reason'])
        self.assertEqual(self.provider.calls, 1)

    def test_validation_mutation_refused(self):
        p, runner = self.make(validator=FakeValidator(mutate=True))
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')

    def test_unknown_command_refused(self):
        with self.assertRaises(SafetyError):
            plan_objective('do work', self.root, ['utility.py'], ['sh'], self.config)
        with self.assertRaises(ValueError):
            replace(self.config, validations={'shell': ['sh', '-c', 'true']}).check()

    def test_changed_file_limit(self):
        self.config = replace(self.config, limits=replace(self.config.limits, changed_files=1))
        with self.assertRaises(SafetyError):
            self.make()

    def test_written_byte_limit(self):
        def large(plan, candidate):
            (Path(candidate) / 'utility.py').write_bytes(b'x' * self.config.limits.written_bytes)
        p, runner = self.make(provider=FakeProvider(mutate=large))
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')

    def test_no_source_change_no_checkpoint(self):
        class NoChange(FakeProvider):
            def generate(self, plan, candidate, message, remaining_calls, timeout):
                return result(['fake'], 0, .01), b'', 1
        p, runner = self.make(True, provider=NoChange())
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')

    def test_no_checkpoint_without_owner_opt_in(self):
        p, runner = self.make()
        state = self.run_plan(p, runner)
        self.assertEqual(state['status'], 'SUCCEEDED')
        self.assertIsNone(state['checkpoint_hash'])
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), p.git_head)

    def test_ambiguous_repo_refused(self):
        (self.root / '.git/MERGE_HEAD').write_text('x')
        with self.assertRaises(SafetyError):
            self.make()

    def test_state_symlink_and_permissions(self):
        (Path(self.tmp.name) / 'link').symlink_to(self.store.path)
        with self.assertRaises(SafetyError):
            Store(Path(self.tmp.name) / 'link')
        os.chmod(self.store.path, 0o755)
        with self.assertRaises(SafetyError):
            Store(self.store.path)

    def test_mount_policy(self):
        sandbox = Bubblewrap(self.config)
        cmd = sandbox.command('/fixture-copy', ['utility.py'], '/control-dir', 'provider', '/cap.sock')
        self.assertIn('--unshare-all', cmd)
        self.assertNotIn('--share-net', cmd)
        self.assertNotIn('--ro-bind / /', ' '.join(cmd))
        self.assertNotIn(str(self.root), cmd)
        self.assertEqual(cmd.count('--bind'), 1)
        self.assertIn('/fixture-copy/utility.py', cmd)
        self.assertIn('--clearenv', cmd)

class AdditionalOrchestratorTests(unittest.TestCase):
    setUp = OrchestratorTests.setUp
    make = OrchestratorTests.make
    run_plan = OrchestratorTests.run_plan
    def test_hard_wall_clock_includes_preflight(self):
        self.config = replace(self.config, limits=replace(self.config.limits, elapsed_seconds=1))
        class Slow(FakeProvider):
            def preflight(self):
                time.sleep(3)
        provider = Slow()
        p, runner = self.make(provider=provider)
        start = time.monotonic()
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(provider.calls, 0)

    def test_candidate_removed_after_failure(self):
        p, runner = self.make(provider=FakeProvider(failure=True))
        state = self.run_plan(p, runner)
        self.assertFalse(Path(state['candidate']).exists())

    def test_partial_publication_is_idempotent(self):
        p, runner = self.make(True)
        with patch('genesis_local.coordinator.publish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan(p, runner)
        state = self.store.load(p.objective_id)
        # Simulates a durable atomic replacement followed by death before journal update.
        (self.root / 'utility.py').write_bytes((Path(state['candidate']) / 'utility.py').read_bytes())
        self.assertEqual(runner.execute(p.objective_id)['status'], 'SUCCEEDED')
        self.assertEqual(self.provider.calls, 1)

    def test_approval_does_not_allow_later_owner_edit(self):
        p, runner = self.make()
        (self.root / 'utility.py').write_text('owner edited after planning\n')
        self.assertEqual(self.run_plan(p, runner)['status'], 'BLOCKED')
        self.assertEqual(self.provider.calls, 0)

    def test_cli_plan_and_denial(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['--state-dir', str(self.store.path), 'engineer', 'Fix addition.',
                         '--workspace', str(self.root), '--file', 'utility.py',
                         '--file', 'tests/test_utility.py'])
        self.assertEqual(code, 0)
        state = json.loads(output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['--state-dir', str(self.store.path), 'deny', state['plan']['objective_id'],
                         '--plan-digest', state['plan_digest']])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'DENIED')


if __name__ == '__main__':
    unittest.main()
