"""Bounded broker diagnostics. No bodies, raw paths, headers or digests escape."""
import hashlib
import hmac
import json
import secrets
import time

ALLOWED_ROUTES = {('POST', '/api/chat'), ('POST', '/api/show'), ('GET', '/api/tags')}
MAX_REQUESTS = 12  # Existing broker total-request budget, not an inference budget.
MAX_EVENTS = 24


class BrokerAudit:
    def __init__(self, metrics, model):
        self.metrics, self.model = metrics, model
        # An ephemeral private key prevents request payloads from becoming public
        # dictionary-attackable hashes. Only ordinal equality groups are retained.
        self._key, self._seen = secrets.token_bytes(32), {}
        self._started = time.monotonic()
        metrics.update(events=[], events_omitted=0, denial_reasons={},
                       metadata_requests=0, inference_requests=0, unsupported_requests=0,
                       unique_payloads=0, repeated_payloads=0, upstream_attempts=0)

    def begin(self, method, path, version, headers):
        now = time.monotonic()
        m = self.metrics
        m['requests'] += 1
        allowed = (method, path) in ALLOWED_ROUTES
        kind = ('inference' if path == '/api/chat' else 'metadata') if allowed else 'unsupported'
        m[kind + '_requests'] += 1
        content_type = headers.get('Content-Type')
        event = dict(sequence=m['requests'], offset_seconds=round(now - self._started, 4), method=method if method in {'GET', 'POST'} else '<other>',
                     route=path if path in {p for _, p in ALLOWED_ROUTES} else '<unsupported>',
                     kind=kind, http_version=version if version in {'HTTP/1.0', 'HTTP/1.1'} else '<other>',
                     content_type='application/json' if content_type == 'application/json'
                                  else 'missing' if content_type is None else '<other>',
                     transfer_encoding_present=headers.get('Transfer-Encoding') is not None,
                     authorization_present=headers.get('Authorization') is not None,
                     model_field='unexamined', model_match='unexamined', payload_group=None,
                     repeated_payload=None, charged_provider_call=None, upstream_started=False,
                     upstream_status=None, upstream_completed=False, outcome='received',
                     denial_reason=None)
        if len(m['events']) < MAX_EVENTS:
            m['events'].append(event)
        else:
            m['events_omitted'] += 1
        return event, now

    def payload(self, event, data):
        # Called only after the total request budget and body size/type checks.
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        prefix = (event['method'] + ' ' + event['route']).encode()
        fingerprint = hmac.new(self._key, prefix + b'\0' + canonical, hashlib.sha256).digest()
        group = self._seen.get(fingerprint)
        repeated = group is not None
        if not repeated:
            group = event['sequence']
            self._seen[fingerprint] = group
        event.update(payload_group=group, repeated_payload=repeated)
        self.metrics['repeated_payloads' if repeated else 'unique_payloads'] += 1
        keys = [k for k in ('model', 'name') if k in data]
        event['model_field'] = 'both' if len(keys) == 2 else keys[0] if keys else 'missing'
        values = [data[k] for k in keys]
        event['model_match'] = ('missing' if not values else 'pinned' if all(v == self.model for v in values)
                                else 'conflict' if len(values) == 2 and values[0] != values[1] else 'other')

    def deny(self, event, reason):
        if event['outcome'] != 'denied':
            self.metrics['denials'] += 1
            counts = self.metrics['denial_reasons']
            counts[reason] = counts.get(reason, 0) + 1
        event.update(outcome='denied', denial_reason=reason)

    def finish(self, event, started):
        event['elapsed_seconds'] = round(time.monotonic() - started, 4)
