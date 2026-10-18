"""Installed parser compatibility without importing/running an Aider agent."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from genesis_local.config import Config
from genesis_local.containment import Bubblewrap
from genesis_local.evidence import result
from genesis_local.models import Plan
from genesis_local.provider import AiderProvider

ROOT = Path(__file__).resolve().parents[1]


def parser_probe(argv, directory):
    path = Path(directory) / 'argv.json'
    path.write_text(json.dumps(argv))
    p = subprocess.run([Config().aider_python, '-I', '-B', str(ROOT / 'tools/aider_parser_probe.py'),
                        '--argv-file', str(path)], capture_output=True, timeout=5,
                       env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'})
    if p.returncode:
        raise AssertionError('parser-only probe failed; no agent was launched')
    return json.loads(p.stdout)


@unittest.skipUnless(Path(Config().aider_python).exists(), 'installed pinned Aider parser unavailable')
class ProviderStartupTests(unittest.TestCase):
    def test_legacy_empty_yaml_matches_confirmed_host_failure(self):
        with tempfile.TemporaryDirectory() as d:
            evidence = parser_probe(['--config', '/dev/null'], d)
        self.assertEqual(evidence['exit_code'], 2)
        self.assertEqual(evidence['diagnostic'], 'empty_yaml_configuration')
        self.assertEqual(evidence['output_bytes'], 5297)
        self.assertEqual(evidence['output_sha256'],
                         'c3ebf60dec739078079c38acc1028aa2cd1b9c1f92ec8b5395baf1813dca39f4')

    def test_actual_provider_control_configuration_is_accepted(self):
        """Exercises actual provider argv AND control-file creation, no namespace bypass."""
        config = Config()
        sandbox = Bubblewrap(config)
        provider = AiderProvider(config, sandbox)
        # This is a parser-only adapter test: no executable agent or broker is run.
        provider._verified = True
        plan = Plan('0' * 32, 'Fix the fixture.', '/fixture', ['utility.py'], {}, {}, {}, 'a' * 40)
        captured = {}

        @contextmanager
        def broker(*args):
            yield {'provider_calls': 0, 'denials': 0, 'requests': 0}

        def parse_only(cmd, timeout, output_limit, evidence_argv=None):
            control = Path(cmd[cmd.index('/control') - 1])
            argv = list(evidence_argv)
            index = argv.index('--config') + 1
            if argv[index].startswith('/control/'):
                config_file = control / Path(argv[index]).name
                self.assertEqual(config_file.read_text(), '{}\n')
                argv[index] = str(config_file)
                captured['config_is_control_mount'] = True
            captured['parser'] = parser_probe(argv, control)
            return result([], captured['parser']['exit_code'], .01), b''

        with tempfile.TemporaryDirectory() as d:
            Path(d, 'utility.py').write_text('def add(a, b): return a - b\n')
            with patch('genesis_local.provider.ollama_broker', broker), \
                    patch('genesis_local.containment.supervise', side_effect=parse_only):
                evidence, _, _ = provider.generate(plan, d, 'Fix the fixture.', 1, 3)
        self.assertEqual(captured['parser']['exit_code'], 0, captured['parser'])
        self.assertTrue(captured['config_is_control_mount'])
        self.assertEqual(evidence['exit_code'], 0)


class DiagnosticSafetyTests(unittest.TestCase):
    def test_diagnostic_never_persists_raw_secret_text(self):
        from tools.aider_provider_diagnostic import startup_summary
        secret = b'private-value-that-must-not-be-recorded'
        summary = startup_summary(b'PermissionError: ' + secret)
        self.assertEqual(summary, ['runtime_permission_denied'])
        self.assertNotIn(secret.decode(), json.dumps(summary))
        self.assertEqual(startup_summary(secret), ['unclassified_output'])

    def test_focused_runner_stops_before_agent_when_preflight_fails(self):
        from tools.aider_provider_diagnostic import main
        from genesis_local.workspace import SafetyError
        with tempfile.TemporaryDirectory() as d:
            evidence = Path(d) / 'evidence.json'
            with patch('tools.aider_provider_diagnostic.AiderProvider.preflight',
                       side_effect=SafetyError('blocked secret-value')), \
                    patch('tools.aider_provider_diagnostic.AiderProvider.generate') as generate:
                code = main(['--approve-disposable-fixture', '--evidence', str(evidence)])
            self.assertEqual(code, 2)
            generate.assert_not_called()
            self.assertNotIn('secret-value', evidence.read_text())
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)

    def test_focused_runner_never_overwrites_prior_evidence(self):
        from tools.aider_provider_diagnostic import main
        with tempfile.TemporaryDirectory() as d:
            evidence = Path(d) / 'evidence.json'
            evidence.write_text('existing evidence')
            with self.assertRaises(SystemExit):
                main(['--approve-disposable-fixture', '--evidence', str(evidence)])
            self.assertEqual(evidence.read_text(), 'existing evidence')


if __name__ == '__main__':
    unittest.main()
