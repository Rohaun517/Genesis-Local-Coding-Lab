"""Durable orchestration; mutation intents precede execution and publication."""
from pathlib import Path
import tempfile
import shutil
import time
from .config import Config
from .deadline import wall_deadline
from .containment import Bubblewrap
from .git_checkpoint import checkpoint, inspect, git
from .models import Plan
from .provider import AiderProvider
from .recovery import TERMINAL, publish, recover
from .state import lock
from .validation import Validator
from .workspace import SafetyError, materialize, root_path, snapshot, safe_text


class Coordinator:
    def __init__(self, config: Config, store, provider=None, validator=None):
        config.check()
        self.config, self.store = config, store
        sandbox = Bubblewrap(config)
        self.provider = provider or AiderProvider(config, sandbox)
        self.validator = validator or Validator(config, sandbox)

    def create(self, plan):
        state = {'plan': plan.to_dict(), 'plan_digest': plan.digest(), 'status': 'PLANNED',
                 'approval': None, 'attempts': [], 'provider_invocations': 0,
                 'repairs': 0, 'checkpoint_hash': None, 'final_outcome': None, 'created_at': time.time()}
        with lock(self.store.path / '.lock'):
            if self.store.file(plan.objective_id).exists():
                raise SafetyError('objective already exists')
            self.store.save(state)
        return state

    def execute(self, objective_id, decision=None, approved_digest=None):
        with lock(self.store.path / '.lock'):
            state = self.store.load(objective_id)
            plan = Plan(**state['plan'])
            root = root_path(plan.workspace)
            if root == self.store.path or root in self.store.path.parents:
                raise SafetyError('state must be outside disposable repository')
            with lock(root / '.genesis-execution.lock'):
                try:
                    if plan.digest() != state['plan_digest']:
                        raise SafetyError('plan changed after creation')
                    if state['status'] not in {'PLANNED', 'DENIED'}:
                        approval = state.get('approval') or {}
                        if (approval.get('decision') != 'approve'
                                or approval.get('plan_digest') != plan.digest()):
                            raise SafetyError('durable explicit approval missing or mismatched')
                    if state['status'] in TERMINAL:
                        return state
                    if state['status'] in {'GENERATING', 'VALIDATING'}:
                        return recover(state, plan, self.store)
                    deadline = state.get('deadline', time.time() + self.config.limits.elapsed_seconds)
                    with wall_deadline(deadline):
                        return self._execute(state, plan, decision, approved_digest)
                except (SafetyError, OSError, ValueError) as e:
                    # PUBLISHING/CHECKPOINTING retain intent for recovery; never replay provider work.
                    if state['status'] not in {'PUBLISHING', 'CHECKPOINTING'}:
                        state['status'] = 'BLOCKED'
                    state['reason'] = type(e).__name__ + ': ' + str(e)[:240]
                    self.store.save(state)
                    return state
                except BaseException:
                    self.store.save(state)
                    if state['status'] not in {'PUBLISHING', 'CHECKPOINTING'}:
                        self._discard_candidate(state)
                    raise
                finally:
                    if state['status'] in TERMINAL:
                        state['final_outcome'] = state['status']
                        self._discard_candidate(state)
                    elif state.get('reason') and state['status'] in {'PUBLISHING', 'CHECKPOINTING'}:
                        state['final_outcome'] = 'BLOCKED_RECOVERY_REQUIRED'
                    elif state['status'] in {'GENERATING', 'VALIDATING'}:
                        state['final_outcome'] = 'INTERRUPTED_PENDING_RECOVERY'
                    self.store.save(state)

    def _discard_candidate(self, state):
        candidate = state.get('candidate')
        if candidate:
            p = Path(candidate)
            if p.parent == self.store.path and p.name.startswith('candidate-') and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)

    def _execute(self, state, plan, decision, approved_digest):
        if plan.digest() != state['plan_digest']:
            raise SafetyError('plan changed after creation')
        if plan.limits != vars(self.config.limits):
            raise SafetyError('resource configuration changed')
        if state['status'] in TERMINAL:
            return state
        if state['status'] == 'PLANNED':
            if decision is None:
                return state
            if decision not in {'approve', 'deny'}:
                raise SafetyError('explicit local approve/deny required')
            if approved_digest != plan.digest():
                raise SafetyError('approval must bind the exact displayed plan digest')
            state['approval'] = {'decision': decision, 'plan_digest': approved_digest,
                                 'at': time.time(), 'authority': 'local-development-operator-only'}
            state['status'] = 'APPROVED' if decision == 'approve' else 'DENIED'
            if decision == 'approve':
                state['deadline'] = time.time() + self.config.limits.elapsed_seconds
            self.store.save(state)
            if decision == 'deny':
                return state
        state = recover(state, plan, self.store)
        if state['status'] in TERMINAL:
            return state
        if state['status'] == 'CHECKPOINTING':
            return self._checkpoint(state, plan)
        if state['status'] != 'APPROVED':
            raise SafetyError('unsupported recovery phase')
        if inspect(plan.workspace, plan.expected_source_changes) != plan.git_head:
            raise SafetyError('HEAD changed since approval')
        if snapshot(plan.workspace, plan.expected_source_changes,
                    self.config.limits.written_bytes) != plan.baseline:
            raise SafetyError('approved baseline changed')
        state.setdefault('deadline', time.time() + self.config.limits.elapsed_seconds)
        self.store.save(state)
        state['containment'] = self.provider.preflight()
        self.store.save(state)
        candidate = Path(tempfile.mkdtemp(prefix='candidate-', dir=self.store.path))
        materialize(plan.workspace, candidate, plan.expected_source_changes,
                    self.config.limits.written_bytes)
        state['candidate'] = str(candidate)
        self.store.save(state)
        message = plan.objective
        for attempt in range(self.config.limits.repair_attempts + 1):
            remaining = state['deadline'] - time.time()
            if remaining <= 0:
                raise SafetyError('objective elapsed limit reached')
            available = self.config.limits.provider_invocations - state['provider_invocations']
            if available <= 0:
                raise SafetyError('provider invocation budget exhausted')
            if attempt:
                state['repairs'] += 1
            record = {'number': attempt + 1, 'repair': bool(attempt)}
            state['attempts'].append(record)
            # Reserve all remaining HTTP calls during an uncertain in-flight invocation.
            state['reserved_provider_invocations'] = available
            state['status'] = 'GENERATING'
            self.store.save(state)
            evidence, _, calls = self.provider.generate(plan, candidate, message, available,
                min(remaining, self.config.limits.invocation_seconds))
            if type(calls) is not int or calls < 0 or calls > available:
                raise SafetyError('invalid provider accounting')
            state['provider_invocations'] += calls
            state.pop('reserved_provider_invocations', None)
            record['provider'] = evidence
            self.store.save(state)
            if evidence['exit_code'] or evidence['timed_out']:
                state['status'] = 'FAILED'
                state['reason'] = 'provider failed or timed out'
                self.store.save(state)
                return state
            hashes = snapshot(candidate, plan.expected_source_changes,
                              self.config.limits.written_bytes // len(plan.expected_source_changes))
            # Provider cannot introduce directories/symlinks/files outside the approved mounts.
            found = sorted(str(p.relative_to(candidate)) for p in candidate.rglob('*') if not p.is_dir())
            if found != sorted(plan.expected_source_changes):
                raise SafetyError('unapproved candidate file detected')
            state['status'] = 'VALIDATING'
            self.store.save(state)
            results, feedback = self.validator.run(plan, candidate, state['deadline'] - time.time())
            record['validation'] = results
            self.store.save(state)
            if not results:
                raise SafetyError('validation produced no evidence')
            if (len(results) == len(plan.validation_commands)
                    and all(r['exit_code'] == 0 and not r['timed_out'] for r in results)):
                after = snapshot(candidate, plan.expected_source_changes,
                                 self.config.limits.written_bytes // len(plan.expected_source_changes))
                if after != hashes:
                    raise SafetyError('validation mutated source')
                changed = [n for n in hashes if hashes[n] != plan.baseline[n]]
                if not changed or not any(n.endswith('.py') for n in changed):
                    raise SafetyError('validated source changes required')
                if time.time() > state['deadline']:
                    raise SafetyError('elapsed budget exhausted before publication')
                if git(plan.workspace, 'rev-parse', 'HEAD') != plan.git_head:
                    raise SafetyError('HEAD changed during generation')
                if snapshot(plan.workspace, plan.expected_source_changes,
                            self.config.limits.written_bytes) != plan.baseline:
                    raise SafetyError('owner changed approved source during generation')
                inspect(plan.workspace, [])
                state.update(validated_hashes=hashes, changed_files=changed, status='PUBLISHING')
                self.store.save(state)
                publish(state, plan, self.store)
                return self._checkpoint(state, plan) if plan.checkpoint else state
            # Feedback remains in memory; raw provider/validation output is never persisted.
            # Treat output as data, not a command or an approval.
            message = plan.objective + '\nRepair the approved source to pass the approved validation.\n'
            try:
                safe_text(feedback.decode(errors='replace'))
                message += feedback[-8192:].decode(errors='replace')
            except SafetyError:
                message += '[feedback withheld: secret-like output]'
        state['status'] = 'FAILED'
        state['reason'] = 'validation failed; bounded repairs exhausted'
        self.store.save(state)
        return state

    def _checkpoint(self, state, plan):
        if time.time() > state['deadline']:
            raise SafetyError('elapsed budget exhausted before checkpoint; publication retained')
        state['checkpoint_hash'] = checkpoint(plan.workspace, plan, state['changed_files'],
                                               state['validated_hashes'])
        state['status'] = 'SUCCEEDED'
        state.pop('reason', None)
        self.store.save(state)
        return state
