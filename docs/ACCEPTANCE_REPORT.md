# Acceptance report — 2026-10-18

**CANDIDATE_READY_FOR_HOST_ACCEPTANCE**

The implementation and available tests pass. Host-only containment and real Aider/Ollama execution remain **PENDING**. This report does not claim full acceptance or production readiness.

## Executed in Codex

- `python3 -B -m unittest discover -s tests -v`: **49 passed**, 21.351 seconds, no skipped tests. Complete transcript: `artifacts/available-tests.txt`.
- `python3 -B tools/fixture_workflow.py --evidence artifacts/fixture-workflow.json`: **PASS**. Mocked generation corrected addition; real Python unittest validation passed in a disposable Git repository. The fixture-only checkpoint changed exactly `utility.py`, unrelated owner edits survived, and restart performed no second provider call or checkpoint. The fixture was removed. Full plan, approval, validation metrics/output digest, checkpoint hash, and outcome are in the JSON evidence. This is not a real-model or containment demonstration.
- Actual libseccomp test in a separate Python child: **PASS**, executable launch and process creation both denied. The test does not change the test runner's filter or any system configuration.
- All Python source parsed successfully. Offline installation from a temporary source copy into a disposable virtualenv with `--no-index --no-deps --no-build-isolation`, followed by the installed `genesis-local --help`, passed. No installed owner runtime was modified.
- Source archive membership, content hashes, CRC and forbidden-file exclusions are checked after packaging. Archive SHA-256 is delivered separately.

## Required functional/adversarial coverage

| Requirement | Available evidence | Host status |
| --- | --- | --- |
| Natural-language objective, structured plan and explicit approval | CLI planning/denial, digest binding and no implicit approval tests pass | Real generation pending |
| Successful objective execution | Mocked generation + real validation + real fixture checkpoint passes | Real Aider/Qwen workflow pending |
| Explicit denial | Denied objective makes zero provider calls | Covered locally |
| Provider failure | Failed provider does not validate/publish/commit | Real runtime compatibility pending |
| Validation failure | Failure exhausts bounded repairs without checkpoint | Contained real validation pending |
| Bounded repairs and inference count | Two repairs / three calls maximum; smaller budget test passes; broker meters HTTP requests | Actual broker transport pending |
| Timeout | Supervisor timeout, output cap, persisted elapsed limit and hard preflight deadline pass | Namespace timeout and CPU limit pending |
| Interrupted execution and safe restart | Generation/validation interruption never replays; completed objective is idempotent | Real process lifecycle pending |
| Workspace escape | Absolute/parent/hidden paths and missing disposable marker refused | Actual mount isolation pending |
| Symlink traversal | Input symlinks, parent symlinks and hardlinks refused | In-namespace symlink/write restrictions pending |
| Secret-file exclusion | Hidden/environment/credential paths and known credential patterns refused; generated known secret withheld | Real filesystem isolation pending; semantic detector limitation applies |
| Unauthorized Git staging | Preexisting and newly introduced staging refused and preserved | Covered with real disposable Git |
| Checkpoint correctness | Only approved changed source committed, parent correct, index clean, unrelated edits preserved | Real generated-source checkpoint pending |
| GitHub push disabled | No API/CLI configuration path for push; push command rejected | No push attempted |
| Concurrent execution attempts | State lock and per-workspace lock refuse a second owner execution | Covered locally |
| Failure recovery | Publication intent, already-replaced bytes, post-ref-update checkpoint, and intervening owner edit cases pass | Real abrupt namespace interruption pending |
| Changed-file / written-source-byte budgets | Explicit mount list, over-count/oversize refusal, conservative per-file budget tests pass | Actual RLIMIT_FSIZE/mount enforcement pending |
| Shell/process/network boundaries | Real exec/fork syscall-filter denial; mount argv policy; broker route/model/context/budget policy tests pass | Combined namespace, thread, network and socket behavior pending |

## Pending host acceptance

Codex's nested sandbox rejected the earlier namespace probe and this session's Unix-socket bind. Broker HTTP policy tests therefore exercise the actual request handler using an in-memory transport; they do not claim that the real socket/relay has passed. No real Aider/model invocation was attempted in Codex. The owner's independent successful Bubblewrap test establishes host feasibility only.

Run the exact command in `docs/HOST_ACCEPTANCE.md`. `tools/host_acceptance.py` accepts no existing repository path and requires explicit disposable-fixture approval. It must pass the active isolation probe before any real Aider invocation. It then checks read-only validation, timeout/CPU enforcement, real model generation, validation, checkpoint contents, source/secret-file preservation, symlink rejection and safe restart. Any failed check returns BLOCKED; no weaker fallback exists. Current machine-readable status: `artifacts/host-acceptance-pending.json`.

## Remaining limitations

1. The combined host configuration, runtime compatibility, actual socket relay, GPU/model operation, and in-namespace resource enforcement have not yet been independently executed. Offline tokenizer/runtime dependencies may need review if host acceptance fails; unrestricted network or shell fallback is not permitted.
2. V1 supports explicit regular source files and Python-module validation only. It precreates missing approved files; it does not support deletion, renaming, symlinks, executable validators, arbitrary shell commands, or production workspaces.
3. The written-byte budget caps resulting approved source contents, conservatively divided per file. It is not a cumulative disk-I/O accounting quota. Temporary storage and process output have separate hard caps. RLIMIT_NPROC is per real UID; the active probe must demonstrate effective thread limits on the host or refuse execution.
4. Secret checks are conservative filename/pattern checks, not a universal credential detector. Real credentials must never enter objectives, fixtures, state or the trusted runtime. Process output is retained as hashes/lengths rather than raw logs. Abrupt SIGKILL can leave private candidate files until recovery.
5. The trusted operator/runtime/kernel/state boundary excludes malicious same-UID races. Locks coordinate orchestrator instances; operators must not concurrently edit approved paths, stage changes, or manipulate Git/state during execution. Already-published multi-file work has forward recovery rather than transactional rollback. An expired deadline or owner conflict can require manual review before a new objective is approved.
6. Passing generated tests establishes only the configured validation result. It does not prove source behavior or test completeness. Independent tests and review remain necessary. Ollama-side inference cancellation latency depends on the server even after the broker closes its connection.

## Repository preservation

The implementation repository remains on `test/aider-qwen-integration` at `cc8eaa40da86bfccbb776313a98bb7c0c80e663f`. No implementation commit, reset, clean, stash, push, remote change, service restart, deployment, privilege escalation, account/credential change, or protected-project modification was performed. Existing tracked source and preexisting untracked Aider histories/cache/bytecode were left intact. All Git mutation demonstrations used freshly created disposable fixture repositories.
