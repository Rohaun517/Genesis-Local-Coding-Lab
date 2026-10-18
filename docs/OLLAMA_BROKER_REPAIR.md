# Ollama broker compatibility and denial attribution — 2026-10-18

**BLOCKED pending a real host trace and successful contained generation.** A reproducible LiteLLM/broker incompatibility is fixed. Report 002 cannot establish the reasons for all 12 historical denials, because it retained only aggregate counters. No live Ollama or Aider request, full host acceptance, service change, implementation-repository commit, push or privilege escalation was performed for this diagnosis in Codex.

## Confirmed findings

The installed LiteLLM 1.81.10 `OllamaConfig.get_model_info()` strips `ollama_chat/` from the provider model and constructs:

```text
POST /api/show
{"name": "qwen2.5-coder:32b"}
```

The old broker checked only `data.get('model')` for every POST, so this legitimate metadata request was refused. A regression extracts just this installed request-builder function and executes it with a fake client, without importing LiteLLM/Aider or making network calls. Its exact captured request received HTTP 403 from the original broker. The regression failed before the production change and passes after it.

LiteLLM chat generation uses POST `/api/chat` with `model`, `messages`, `options` and `stream`. Aider can request model information repeatedly during initialization, model setup and token/cost bookkeeping. Its inference retry loops use exponential delays for retryable exceptions. Repeated identical metadata queries are not necessarily inference retries; matching payloads alone cannot prove why a call was repeated.

Report `/home/rohaun/genesis-local-host-acceptance-002.json` records **13 handled GET/POST requests, 12 denials, and 1 charged inference attempt**. Thus the 13 requests are not evidence of 13 model invocations. `provider_calls` increments only after a POST `/api/chat` passes model/body/budget checks, immediately before the upstream attempt. It is not proof that inference completed. The old denial counter also included parsing and upstream/downstream errors, not just API policy refusals.

The unchanged total-request check denies request 13; the recorded 159.6883-second run is within the normal 240-second provider deadline. There is no saved route/body/reason information to classify requests 1–12 or determine how many were probes, unique payloads, repeated lookups, or retries. The `name` mismatch is confirmed in installed code and a wire-level regression, but attributing every historical denial to it would be unsupported. The 333-byte provider output was retained only as a digest, not raw text. The old adapter could also override a successful process exit to 77 whenever any broker denial occurred, so code 77 alone does not establish Aider's original exit status.

## Exact compatibility repair and preserved policy

Only POST `/api/show`, an already allowed route, additionally accepts the legacy `name` spelling. Every supplied identifier must equal exactly `qwen2.5-coder:32b`. If both `name` and `model` are supplied, both must be the pinned model. Missing, null, different, prefixed, or conflicting model identifiers are denied. The upstream request is normalized to exactly `{"model":"qwen2.5-coder:32b"}`; unrelated metadata-body fields are not forwarded. POST `/api/chat` still requires `model`; no general alias or model fallback was introduced.

The network/API policy remains:

| Control | Result |
| --- | --- |
| Routes | Only POST `/api/chat`, POST `/api/show`, GET `/api/tags`; no new route |
| Destination/transport | Only host `127.0.0.1:11434`; worker plain HTTP over isolated-loopback relay to the mounted Unix-socket capability |
| Model | Exact pinned model; tag responses filtered to it |
| Request framing | Bounded Content-Length JSON; chunked Transfer-Encoding refused |
| Headers | Only fixed Content-Type forwarded upstream; no incoming credential/header values logged or forwarded |
| Context/output | Server-bound chat forces `num_ctx=16384`, `num_predict=4096`, `stream=false` |
| Budgets | Same 12 total requests and approved remaining inference calls, at most 3; repeated inference attempts are charged separately |
| Failures | Denials still fail the provider; no ignored denials, cache loophole, refunded retry, or unrestricted fallback |
| Containment | Bubblewrap, bootstrap/seccomp, writable mounts, environment, CPU/memory/process/time limits unchanged |

## Minimal diagnostic for unresolved historical attribution

`genesis_local/broker_audit.py` records fixed denial reasons and sanitized per-request events for handled GET/POST traffic. Other HTTP methods retain the existing default rejection behavior. Events include ordinal sequence, fixed route/method labels, metadata/inference/unsupported classification, protocol/header categories, model-field spelling and pinned/mismatched classification, upstream status/completion, charged inference ordinal, and relative timing. Unsupported paths are replaced by `<unsupported>`; model values and header contents are never retained.

Canonical JSON equality is tracked using a fresh private HMAC key in memory. Only ordinal payload-group numbers and repeated/not-repeated flags are persisted: no body, prompt hash, HMAC, key, credential, raw URL/query, model response or exception text. Payload equality distinguishes unique wire requests from repeats within one invocation; it does not claim that a repeated request is semantically a retry. Payload attribution is unavailable when a request is rejected before reading its body, such as after exhausting the total budget.

The sample is capped at 24 events, with a count of omitted events. Aggregate category/reason counts continue. The body-equality table has at most 12 entries because budget checks occur before body processing. The provider snapshots diagnostics after broker teardown and separately records `process_exit_code`, preserving the policy result in `exit_code`. A `broker_thread_stopped` flag identifies whether teardown fully quiesced the broker; if false, evidence must be treated as a snapshot with potentially incomplete in-flight outcomes.

The existing focused diagnostic `tools/aider_provider_diagnostic.py` automatically includes these new metrics. It accepts no repository path, creates disposable files, verifies the full existing containment policy, invokes real Aider through the broker, requires an authorized inference attempt and changed source, and validates it against unchanged fixture tests. It performs **no Git operations** and preserves existing evidence with exclusive file creation.

## Test evidence

- Before the compatibility repair: **1 regression, expected failure**, installed metadata request returned 403.
- After the narrow repair: **1 regression passed**.
- Final focused suite: **10 passed**. Coverage includes installed request-builder compatibility, both model identifiers/conflicts, metadata-only alias scope, repeat-versus-unique attribution, unchanged inference and total budgets, context/output forcing, framing/JSON errors, upstream timeout charging, privacy and bounded audit memory, and original-process/policy exit separation.
- Full automated suite: **64 passed, no skips**, 18.728 seconds. All earlier functional, Git, interruption, recovery and containment security tests remain passing; their Git mutations use disposable test fixtures only.
- Codex containment-only preflight: **BLOCKED_NAMESPACE_PREFLIGHT**, with no Aider or Ollama invocation. Full host acceptance was not rerun.

New evidence: `artifacts/ollama-broker-regression-before.txt`, `artifacts/ollama-broker-regression-after.txt`, `artifacts/ollama-broker-focused-tests.txt`, `artifacts/ollama-broker-full-tests.txt`, `artifacts/ollama-broker-codex-preflight.json`, and `artifacts/ollama-broker-repair-evidence.json`.

Existing production changes are limited to `genesis_local/broker.py` (metadata compatibility plus reason attribution) and `genesis_local/provider.py` (final diagnostic snapshot and separate process exit). New source files are `genesis_local/broker_audit.py` and `tests/test_broker_compatibility.py`; this report and the evidence files complete the additive repair inventory. Original host reports, earlier repair evidence, review ZIP/checksum, histories/caches and all other production modules are preserved. The original ZIP remains a historical pre-repair artifact; use this repaired workspace.

## Single next host command

Run from a regular owner terminal outside Codex. This focused acceptance attempt does not rerun the full Git/checkpoint acceptance or alter any service. The output filename must be new:

```bash
cd /home/rohaun/Projects/Genesis-Aider-Test && python3.12 -B tools/aider_provider_diagnostic.py --approve-disposable-fixture --evidence /home/rohaun/genesis-local-broker-diagnostic-003.json
```

Return that JSON evidence. A successful result is `PROVIDER_GENERATION_AND_VALIDATION_PASSED`, with zero broker denials and a completed broker trace. If requests still fail, the route classes, fixed denial reasons, repeated-payload groups and budget charges identify the next boundary without recording sensitive data. The 12-request cap has deliberately not been raised; if legitimate metadata traffic still exhausts it, that remains BLOCKED pending evidence and a separate narrowly reviewed solution. No complete broker compatibility or production-readiness claim is made yet.
