"""A Unix-socket capability exposes only bounded, fixed-model Ollama HTTP routes."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
import http.client
import json
from pathlib import Path
import socketserver
import threading
import time
from .broker_audit import ALLOWED_ROUTES, MAX_REQUESTS, BrokerAudit


class UnixHTTP(socketserver.UnixStreamServer):
    allow_reuse_address = False


@contextmanager
def ollama_broker(path, config, remaining_calls, deadline):
    metrics = {'provider_calls': 0, 'requests': 0, 'denials': 0}
    active = []
    audit = BrokerAudit(metrics, config.model)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(min(5, config.limits.invocation_seconds))

        def do_GET(self):
            self.route()

        def do_POST(self):
            self.route()

        def route(self):
            event, started = audit.begin(self.command, self.path, self.request_version, self.headers)
            try:
                self.forward(event)
            finally:
                audit.finish(event, started)

        def forward(self, event):
            if time.time() >= deadline:
                return self.deny(event, 'deadline_expired')
            if metrics['requests'] > MAX_REQUESTS:
                return self.deny(event, 'request_budget_exceeded')
            if (self.command, self.path) not in ALLOWED_ROUTES:
                return self.deny(event, 'route_not_allowed')
            try:
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    return self.deny(event, 'invalid_content_length')
                if size < 0:
                    return self.deny(event, 'invalid_content_length')
                if size > config.limits.output_bytes:
                    return self.deny(event, 'body_limit_exceeded')
                if self.headers.get('Transfer-Encoding'):
                    return self.deny(event, 'transfer_encoding_not_allowed')
                body = self.rfile.read(size)
                if len(body) != size:
                    return self.deny(event, 'incomplete_body')
                try:
                    data = json.loads(body) if body else {}
                except (ValueError, RecursionError):
                    return self.deny(event, 'invalid_json')
                if not isinstance(data, dict):
                    return self.deny(event, 'invalid_body_type')
                try:
                    audit.payload(event, data)
                except (ValueError, RecursionError):
                    return self.deny(event, 'invalid_json')
                # LiteLLM 1.81.10 uses Ollama's legacy `name` field for metadata.
                # Only this route accepts that spelling; every identifier must
                # still equal the exact pinned model, including when both occur.
                if self.path == '/api/show':
                    identifiers = [data[k] for k in ('model', 'name') if k in data]
                    if not identifiers or any(v != config.model for v in identifiers):
                        return self.deny(event, 'model_not_allowed')
                    data = {'model': config.model}
                    body = json.dumps(data).encode()
                if self.command == 'POST' and data.get('model') != config.model:
                    return self.deny(event, 'model_not_allowed')
                if self.path == '/api/chat':
                    if metrics['provider_calls'] >= remaining_calls:
                        return self.deny(event, 'provider_budget_exhausted')
                    # Every forwarded inference attempt is charged, even a retry
                    # with an identical payload or an unsuccessful upstream call.
                    metrics['provider_calls'] += 1
                    event['charged_provider_call'] = metrics['provider_calls']
                    data = {k: v for k, v in data.items() if k in {'model', 'messages', 'format'}}
                    data.update(stream=False, options={'num_ctx': 16384, 'num_predict': 4096})
                    body = json.dumps(data).encode()
                upstream = http.client.HTTPConnection('127.0.0.1', 11434,
                    timeout=max(0.1, min(config.limits.invocation_seconds, deadline - time.time())))
                active.append(upstream)
                try:
                    event['upstream_started'] = True
                    metrics['upstream_attempts'] += 1
                    upstream.request(self.command, self.path, body=body,
                                     headers={'Content-Type': 'application/json'})
                    response = upstream.getresponse()
                    event['upstream_status'] = response.status
                    payload = response.read(config.limits.output_bytes + 1)
                    if len(payload) > config.limits.output_bytes:
                        return self.deny(event, 'response_limit_exceeded')
                    event['upstream_completed'] = True
                    if self.path == '/api/tags' and response.status == 200:
                        try:
                            value = json.loads(payload)
                            if not isinstance(value, dict) or not isinstance(value.get('models', []), list):
                                raise ValueError()
                            payload = json.dumps({'models': [m for m in value.get('models', [])
                                if isinstance(m, dict) and m.get('name') == config.model]}).encode()
                        except (ValueError, RecursionError):
                            return self.deny(event, 'invalid_upstream_json')
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    event['outcome'] = 'forwarded'
                finally:
                    upstream.close()
                    if upstream in active:
                        active.remove(upstream)
            except TimeoutError:
                return self.deny(event, 'upstream_timeout' if event['upstream_started'] else 'request_read_timeout')
            except OSError:
                return self.deny(event, 'downstream_io_error' if event['upstream_completed']
                                 else 'upstream_io_error' if event['upstream_started'] else 'request_read_error')
            except http.client.HTTPException:
                return self.deny(event, 'upstream_protocol_error')

        def deny(self, event, reason):
            audit.deny(event, reason)
            try:
                self.send_error(403, 'local capability denied')
            except OSError:
                pass

    server = UnixHTTP(str(path), Handler)
    server.timeout = 0.1
    stop = threading.Event()

    def serve():
        while not stop.is_set() and time.time() < deadline:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield metrics
    finally:
        stop.set()
        # Close active upstream sockets on interruption; do not leave an inference
        # connection running after the disposable provider process was killed.
        for connection in list(active):
            try:
                if getattr(connection, 'sock', None):
                    connection.sock.shutdown(2)
                connection.close()
            except OSError:
                pass
        thread.join(timeout=0.3)
        metrics['broker_thread_stopped'] = not thread.is_alive()
        server.server_close()
        Path(path).unlink(missing_ok=True)
