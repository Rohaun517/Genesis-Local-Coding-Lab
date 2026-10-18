"""Wire compatibility and bounded, content-free broker request attribution."""
import ast
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from genesis_local.broker import ollama_broker
from genesis_local.config import Config
import test_security as transport

MODEL = 'qwen2.5-coder:32b'
RUNTIME = Path(Config().aider_python).parent.parent / 'lib/python3.12/site-packages'


def installed_metadata_payload():
    """Execute only the installed request builder with a fake client; no LLM/network."""
    source = RUNTIME / 'litellm/llms/ollama/completion/transformation.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'OllamaConfig')
    function = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'get_model_info')
    function.returns = None
    for arg in function.args.args:
        arg.annotation = None
    captured = {}
    def post(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(json=lambda: {})
    namespace = {'get_secret_str': lambda key: 'http://127.0.0.1:11434',
                 'litellm': types.SimpleNamespace(module_level_client=types.SimpleNamespace(post=post)),
                 'ModelInfoBase': lambda **kwargs: kwargs}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    instance = types.SimpleNamespace(get_api_key=lambda: None, _get_max_tokens=lambda value: None,
                                     _supports_function_calling=lambda value: False)
    namespace['get_model_info'](instance, 'ollama_chat/' + MODEL)
    return captured


class BrokerCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        d = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch('genesis_local.broker.UnixHTTP', transport.MemoryTransport))
        self.path = Path(d) / 'broker.sock'
        self.metrics = self.stack.enter_context(ollama_broker(self.path, Config(), 3, time.time() + 10))
        transport.Upstream.requests = []
        self.stack.enter_context(patch('genesis_local.broker.http.client.HTTPConnection', transport.Upstream))

    def request(self, route, data, method='POST', headers=None, raw_body=None):
        body = json.dumps(data).encode() if raw_body is None else raw_body
        values = {'Content-Length': str(len(body)), 'Content-Type': 'application/json'}
        values.update(headers or {})
        raw = f'{method} {route} HTTP/1.1\r\nHost: localhost\r\n'.encode()
        raw += ''.join(f'{k}: {v}\r\n' for k,v in values.items()).encode() + b'\r\n' + body
        sock = transport.RequestSocket(raw)
        server = transport.MemoryTransport.current
        server.handler(sock, ('local', 0), server)
        return int(bytes(sock.output).split(b' ', 2)[1])

    @unittest.skipUnless((RUNTIME / 'litellm/llms/ollama/completion/transformation.py').is_file(),
                         'installed pinned LiteLLM source unavailable')
    def test_installed_litellm_show_name_is_accepted(self):
        wire = installed_metadata_payload()
        self.assertEqual(wire['url'], 'http://127.0.0.1:11434/api/show')
        self.assertEqual(wire['json'], {'name': MODEL})
        self.assertEqual(self.request('/api/show', wire['json']), 200)
        self.assertEqual(self.metrics['provider_calls'], 0)
        upstream = json.loads(transport.Upstream.requests[0][1]['body'])
        self.assertEqual(upstream, {'model': MODEL})

    def test_model_alias_is_metadata_only_and_conflicts_fail_closed(self):
        for body in ({'name': 'other'}, {'model': MODEL, 'name': 'other'},
                     {'model': 'other', 'name': MODEL}, {}, {'name': None},
                     {'name': 'ollama_chat/' + MODEL}):
            self.assertEqual(self.request('/api/show', body), 403)
            self.assertEqual(self.metrics['events'][-1]['denial_reason'], 'model_not_allowed')
        self.assertEqual(self.request('/api/show', {'name': MODEL, 'model': MODEL}), 200)
        self.assertEqual(self.request('/api/chat', {'name': MODEL}), 403)
        self.assertEqual(self.metrics['provider_calls'], 0)
        self.assertEqual(len(transport.Upstream.requests), 1)

    def test_repeated_inference_is_not_free_or_mistaken_for_metadata(self):
        body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'test fixture'}]}
        for _ in range(3):
            self.assertEqual(self.request('/api/chat', body), 200)
        self.assertEqual(self.request('/api/chat', body), 403)
        events = self.metrics['events']
        self.assertEqual([e['payload_group'] for e in events], [1, 1, 1, 1])
        self.assertEqual([e['repeated_payload'] for e in events], [False, True, True, True])
        self.assertEqual([e['charged_provider_call'] for e in events], [1, 2, 3, None])
        self.assertEqual(events[-1]['denial_reason'], 'provider_budget_exhausted')
        self.assertEqual(self.metrics['provider_calls'], 3)
        self.assertEqual(self.metrics['inference_requests'], 4)
        self.assertEqual(len(transport.Upstream.requests), 3)
        for args, kwargs in transport.Upstream.requests:
            data = json.loads(kwargs['body'])
            self.assertEqual(data['options'], {'num_ctx': 16384, 'num_predict': 4096})
            self.assertFalse(data['stream'])

    def test_thirteenth_request_is_denied_without_expanding_total_budget(self):
        for _ in range(12):
            self.assertEqual(self.request('/api/show', {'name': MODEL}), 200)
        self.assertEqual(self.request('/api/chat', {'model': MODEL}), 403)
        self.assertEqual(self.metrics['events'][-1]['denial_reason'], 'request_budget_exceeded')
        self.assertIsNone(self.metrics['events'][-1]['payload_group'])
        self.assertEqual(self.metrics['provider_calls'], 0)
        self.assertEqual(self.metrics['requests'], 13)
        self.assertEqual(self.metrics['repeated_payloads'], 11)
        self.assertEqual(self.metrics['unique_payloads'], 1)

    def test_distinct_payloads_and_metadata_are_attributed_separately(self):
        self.assertEqual(self.request('/api/show', {'name': MODEL}), 200)
        self.assertEqual(self.request('/api/show', {'name': MODEL}), 200)
        self.assertEqual(self.request('/api/chat', {'model': MODEL, 'messages': []}), 200)
        self.assertEqual(self.request('/api/chat', {'messages': [{'role': 'user', 'content': 'new'}], 'model': MODEL}), 200)
        events = self.metrics['events']
        self.assertEqual([e['payload_group'] for e in events], [1, 1, 3, 4])
        self.assertEqual(self.metrics['metadata_requests'], 2)
        self.assertEqual(self.metrics['inference_requests'], 2)
        self.assertEqual(self.metrics['provider_calls'], 2)
        self.assertEqual(events[0]['model_field'], 'name')
        self.assertEqual(events[0]['model_match'], 'pinned')

    def test_diagnostics_do_not_record_bodies_credentials_responses_or_raw_paths(self):
        secret = 'sensitive-fixture-value-never-persist'
        self.assertEqual(self.request('/api/show', {'name': MODEL, 'extra': secret},
                                      headers={'Authorization': 'Bearer ' + secret}), 200)
        self.assertEqual(self.request('/api/chat', {'model': MODEL, 'messages': [{'content': secret}]}), 200)
        self.assertEqual(self.request('/api/show?token=' + secret, {'model': MODEL}), 403)
        self.assertEqual(self.request('/api/show', {'name': secret}), 403)
        stored = json.dumps(self.metrics)
        self.assertNotIn(secret, stored)
        self.assertNotIn('message', stored)
        self.assertNotIn('content"', stored)
        self.assertNotIn('Bearer', stored)
        self.assertTrue(self.metrics['events'][0]['authorization_present'])
        self.assertEqual(self.metrics['events'][2]['route'], '<unsupported>')
        self.assertEqual(self.metrics['events'][2]['denial_reason'], 'route_not_allowed')
        self.assertEqual(transport.Upstream.requests[0][1]['headers'], {'Content-Type': 'application/json'})
        self.assertNotIn(secret, transport.Upstream.requests[0][1]['body'].decode())

    def test_protocol_and_json_denials_have_precise_safe_categories(self):
        cases = [({'headers': {'Content-Length': 'invalid-secret'}}, 'invalid_content_length'),
                 ({'headers': {'Content-Length': '-1'}}, 'invalid_content_length'),
                 ({'headers': {'Content-Length': '999999999'}}, 'body_limit_exceeded'),
                 ({'headers': {'Transfer-Encoding': 'chunked'}}, 'transfer_encoding_not_allowed'),
                 ({'raw_body': b'not-json-secret'}, 'invalid_json'),
                 ({'raw_body': b'[]'}, 'invalid_body_type'),
                 ({'headers': {'Content-Length': '999'}}, 'incomplete_body')]
        for kwargs, reason in cases:
            self.assertEqual(self.request('/api/show', {'name': MODEL}, **kwargs), 403)
            self.assertEqual(self.metrics['events'][-1]['denial_reason'], reason)
        self.assertEqual(self.metrics['provider_calls'], 0)

    def test_upstream_failure_remains_charged_and_distinct_from_policy_denial(self):
        class Timeout(transport.Upstream):
            def request(self, *args, **kwargs):
                raise TimeoutError('secret upstream exception text')
        with patch('genesis_local.broker.http.client.HTTPConnection', Timeout):
            self.assertEqual(self.request('/api/chat', {'model': MODEL}), 403)
        event = self.metrics['events'][0]
        self.assertEqual(event['denial_reason'], 'upstream_timeout')
        self.assertTrue(event['upstream_started'])
        self.assertFalse(event['upstream_completed'])
        self.assertEqual(self.metrics['provider_calls'], 1)
        self.assertNotIn('secret upstream', json.dumps(self.metrics))

    def test_audit_memory_is_bounded_after_request_budget_exhaustion(self):
        for _ in range(40):
            self.request('/api/pull', {'model': MODEL})
        self.assertEqual(self.metrics['requests'], 40)
        self.assertEqual(self.metrics['denials'], 40)
        self.assertEqual(len(self.metrics['events']), 24)
        self.assertEqual(self.metrics['events_omitted'], 16)
        self.assertEqual(self.metrics['denial_reasons'], {'route_not_allowed': 12, 'request_budget_exceeded': 28})


class ProviderAttributionTests(unittest.TestCase):
    def test_policy_exit_77_does_not_hide_actual_process_exit(self):
        from contextlib import contextmanager
        from genesis_local.evidence import result
        from genesis_local.models import Plan
        from genesis_local.provider import AiderProvider
        class Sandbox:
            def run(self, *args, **kwargs):
                return result([], 0, .01), b''
        @contextmanager
        def broker(*args):
            yield {'provider_calls': 1, 'requests': 2, 'denials': 1,
                   'denial_reasons': {'model_not_allowed': 1}}
        provider = AiderProvider(Config(), Sandbox())
        provider._verified = True  # Mocked adapter only; never launches an agent.
        plan = Plan('0' * 32, 'fixture', '/fixture', ['utility.py'], {}, {}, {}, 'a' * 40)
        with patch('genesis_local.provider.ollama_broker', broker):
            evidence, _, calls = provider.generate(plan, '/fixture', 'fixture', 3, 3)
        self.assertEqual(evidence['exit_code'], 77)
        self.assertEqual(evidence['process_exit_code'], 0)
        self.assertEqual(calls, 1)
        self.assertEqual(evidence['broker']['denial_reasons'], {'model_not_allowed': 1})


if __name__ == '__main__':
    unittest.main()
