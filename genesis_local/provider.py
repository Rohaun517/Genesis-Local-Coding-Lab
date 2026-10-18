"""Pinned Aider adapter. All inference is metered by a host-side capability broker."""
import tempfile
import http.client
import json
import time
from pathlib import Path
from .broker import ollama_broker
from .containment import Bubblewrap
from .workspace import SafetyError


class AiderProvider:
    def __init__(self, config, sandbox=None):
        self.config = config
        self._verified = False
        self.sandbox = sandbox or Bubblewrap(config)

    def preflight(self):
        self.sandbox.preflight()
        conn = http.client.HTTPConnection('127.0.0.1', 11434, timeout=3)
        try:
            conn.request('GET', '/api/version')
            response = conn.getresponse()
            data = response.read(1025)
            if response.status != 200 or len(data) > 1024 or json.loads(data).get('version') != '0.23.2':
                raise SafetyError('Ollama 0.23.2 is required')
        finally:
            conn.close()
        self._verified = True
        return {'status': 'VERIFIED_FOR_THIS_RUN',
                'probe': getattr(self.sandbox, 'last_probe', None),
                'ollama_version': '0.23.2', 'aider_version_required': '0.86.2',
                'python_version_required': '3.12'}

    def generate(self, plan, candidate, message, remaining_calls, timeout):
        if not self._verified:
            raise SafetyError('active containment verification required before Aider')
        if remaining_calls <= 0:
            raise SafetyError('provider invocation budget exhausted')
        argv = ['--model', 'ollama_chat/qwen2.5-coder:32b', '--no-git',
                '--no-auto-commits', '--no-dirty-commits', '--no-gitignore',
                '--no-add-gitignore-files', '--no-restore-chat-history', '--no-auto-lint', '--no-auto-test',
                '--no-suggest-shell-commands', '--no-detect-urls', '--disable-playwright',
                '--no-check-update', '--no-show-release-notes', '--no-analytics',
                '--no-stream', '--no-pretty', '--no-fancy-input', '--yes-always',
                '--map-tokens', '0', '--config', '/control/aider.yml', '--env-file', '/dev/null',
                '--input-history-file', '/tmp/input', '--chat-history-file', '/tmp/chat',
                '--weak-model', 'ollama_chat/qwen2.5-coder:32b',
                '--model-settings-file', '/control/settings.yml',
                '--model-metadata-file', '/control/metadata.json', '--timeout', str(timeout),
                '--message', message]
        for name in plan.expected_source_changes:
            argv += ['--file', '/work/' + name]
        with tempfile.TemporaryDirectory(prefix='genesis-broker-') as tmp:
            sock = Path(tmp) / 'ollama.sock'
            with ollama_broker(sock, self.config, remaining_calls, time.time() + timeout) as metrics:
                evidence, output = self.sandbox.run(candidate, plan.expected_source_changes,
                    'provider', argv, timeout, broker=sock)
                # Never persist objective/repair text a second time in process argv evidence.
                evidence['argv'] = ['aider', '--model', 'ollama_chat/qwen2.5-coder:32b',
                                    '--message', '<approved-objective-or-bounded-repair>']
            # Snapshot after broker teardown; keep the actual process exit
            # separate from the policy override so exit 77 is attributable.
            evidence['process_exit_code'] = evidence['exit_code']
            evidence['broker'] = json.loads(json.dumps(metrics))
            if metrics['denials']:
                evidence['exit_code'] = evidence['exit_code'] or 77
            return evidence, output, metrics['provider_calls']
