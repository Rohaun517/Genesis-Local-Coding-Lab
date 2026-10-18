# Aider provider startup repair — 2026-10-18

**BLOCKED pending successful real provider generation through the restricted broker.**

The precise pre-request startup failure is verified and repaired locally. The original host report established passing active containment, CPU limit, namespace timeout, read-only validation and provider containment. A repaired real provider invocation cannot be demonstrated inside Codex because nested namespace creation is denied. Full host acceptance was not rerun automatically.

## Verified cause

The adapter passed `--config /dev/null`. Aider 0.86.2 uses ConfigArgParse 1.7.1's `YAMLConfigFileParser`, backed here by PyYAML 6.0.3. An empty stream loads as Python `None`; the parser requires a dictionary/YAML mapping and exits 2 before any Ollama request:

```text
aider: error: The config file doesn't appear to contain 'key: value' pairs (aka. a YAML mapping). yaml.load('/dev/null') returned type 'NoneType' instead of 'dict'.
```

The original `/home/rohaun/genesis-local-host-acceptance-001.json` retained only process-output length and hash, not raw text. A safe parser-only reconstruction using the installed parser definitions produced **exactly the same 5,297 bytes and SHA-256**:

```text
c3ebf60dec739078079c38acc1028aa2cd1b9c1f92ec8b5395baf1813dca39f4
```

That reconstruction does not import Aider, coders, model libraries, or a provider. It executes only the installed argument-parser definitions with the installed ConfigArgParse/PyYAML dependencies; coder enumeration is stubbed out. Assertions verify no `aider` module was imported. It makes no network requests and is not an uncontained Aider invocation. The identical full output digest ties the error directly to the observed host failure rather than merely suggesting a likely cause.

The inspection found the Python virtualenv mounted read-only at `/opt/aider`, with its Python symlinks resolving through the read-only `/usr` runtime. The host provider had already passed Python 3.12/Aider 0.86.2 metadata checks and the active containment probe. Its exact argparse output proves the interpreter and parser startup were reached. Installed metadata reports Python 3.12.3, Aider 0.86.2, ConfigArgParse 1.7.1, PyYAML 6.0.3, LiteLLM 1.81.10, GitPython 3.1.46, HTTPX 0.28.1 and tiktoken 0.12.0. Dependency presence is not a claim that all post-parser initialization succeeds inside the sandbox.

## Minimal production repair

Only two existing production files changed:

- `genesis_local/provider.py`: change `--config /dev/null` to `--config /control/aider.yml`.
- `genesis_local/containment.py`: write `aider.yml` containing exactly `{}\n` into the existing generated control directory.

The YAML mapping is empty, so no configuration options or credentials are introduced. It is inside the existing read-only `/control` mount. All original Aider safety arguments and the empty dotenv file (`--env-file /dev/null`) remain. Dotenv does not require a YAML mapping.

All other production modules, including syscall filtering, bootstrap, broker, limits and execution coordination, were compared byte-for-byte with the preserved V1 source archive and are unchanged. No mount flags, writable paths, namespaces, executable paths, environment variables, process permissions, network permissions or broker routing changed. The production repair adds no dependency.

## Regression evidence

The regression was added and run **before** changing production code. It captured the real adapter argv and generated control files, then used the installed parser definitions without running an agent:

- Before repair: 2 tests run, **1 expected regression failure**. The legacy configuration reproduced exit 2 and the exact host output digest. The actual adapter compatibility test failed with that same error.
- After repair: both parser regressions passed. The full provider argv was accepted with the new mapping file.
- Final full suite: **54 tests passed, no skips**, 23.214 seconds. This includes the original 49 tests, two parser regressions and three diagnostic safety tests.
- A focused contained diagnostic attempted inside Codex stopped at the namespace preflight, before launching Aider or contacting Ollama. It returned BLOCKED. No privileged or weaker fallback was attempted.

Evidence files added without overwriting the original acceptance artifacts:

| File | Purpose |
| --- | --- |
| `artifacts/aider-startup-regression-before.txt` | Regression failure recorded before the repair |
| `artifacts/aider-startup-regression-after.txt` | Both parser regressions passing after repair |
| `artifacts/aider-startup-full-tests.txt` | Final 54-test transcript |
| `artifacts/aider-startup-parser-reproduction.json` | Exact legacy output length/hash and fixed diagnostic label |
| `artifacts/aider-startup-codex-diagnostic.json` | Nested-sandbox refusal evidence |
| `artifacts/aider-startup-repair-evidence.json` | Host evidence hash, local results and source-change hashes |

Other new files are `tests/test_provider_startup.py`, `tools/aider_parser_probe.py`, `tools/aider_provider_diagnostic.py` and this report. Existing acceptance reports, inventories, review ZIP/checksum, Aider histories/caches and original host evidence are preserved. The old V1 ZIP represents the pre-repair source; use the repaired workspace for the commands below. No implementation-repository commit or push was made. Existing automated Git tests used disposable repositories; the new focused diagnostic performs **no Git operations**.

## Focused owner-host regression (recommended first)

From a regular owner terminal, outside Codex's nested sandbox:

```bash
cd /home/rohaun/Projects/Genesis-Aider-Test
python3.12 -B tools/aider_provider_diagnostic.py \
  --approve-disposable-fixture \
  --evidence /home/rohaun/genesis-local-aider-provider-startup-002.json
```

The evidence path must be new. The runner reserves it exclusively with mode 0600. It takes no existing repository path, does not initialize or commit Git, and creates only disposable fixture files. It performs the same production containment preflight, calls the actual provider through the real restricted broker, requires at least one authorized inference request with zero broker denials, checks that source changed while the independent tests remained unchanged, and runs contained validation. It records only hashes, metrics and fixed diagnostic labels; arbitrary process text and exception messages are not persisted. It fails closed on any error and never relaxes policy.

Success is `PROVIDER_GENERATION_AND_VALIDATION_PASSED`; a zero-exit parser result alone is insufficient. Supply that JSON evidence for review. Further startup failures are possible after this now-correct parser stage and must be diagnosed without weakening containment.

The existing broker authorizes access via its narrowly exposed Unix-socket capability and route/model restrictions; it is not configured for HTTP bearer/token authentication. No authentication credentials or installed authorization were added or changed. This repair does not claim an authenticated HTTP request or completed generation has occurred.

## Exact full host acceptance repeat command

Run only when the owner elects to repeat the complete acceptance after reviewing the focused result:

```bash
cd /home/rohaun/Projects/Genesis-Aider-Test
python3.12 -B tools/host_acceptance.py \
  --approve-disposable-fixture \
  --evidence /home/rohaun/genesis-local-host-acceptance-002.json
```

The existing full runner creates a fresh disposable Git fixture and its fixture-only validated checkpoint; the flag explicitly approves those fixture mutations. It does not use an existing Genesis repository or push. The filename must not exist, preserving report 001. This command has **not** been run automatically. Successful real broker-authorized generation and validation are still needed before this repair can be called complete; full acceptance additionally needs this runner's final success report.
