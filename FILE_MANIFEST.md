# Exact generated-file manifest

No preexisting project file is part of this delivery. The 36 generated delivery files are listed below. The ZIP contains the 34 source/documentation/evidence members enumerated by `artifacts/source-inventory.json`; the ZIP and its external checksum are excluded from the archive. The inventory hashes every archive member except itself to avoid self-reference.

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Package metadata and `genesis-local` entry point |
| `README.md` | Development installation and local approval usage |
| `FILE_MANIFEST.md` | This complete generated-file inventory |
| `genesis_local/__init__.py` | Package version and development scope |
| `genesis_local/__main__.py` | Python module entry point |
| `genesis_local/cli.py` | Engineer/show/approve/deny/resume commands |
| `genesis_local/config.py` | Pinned provider configuration and resource limits |
| `genesis_local/models.py` | Structured immutable plan and approval digest |
| `genesis_local/planner.py` | Deterministic objective planning |
| `genesis_local/provider.py` | Ollama/Qwen/Aider adapter |
| `genesis_local/containment.py` | Bubblewrap builder, probes, timeout/output supervision |
| `genesis_local/_sandbox_bootstrap.py` | Inside-sandbox limits, seccomp and Python execution |
| `genesis_local/probes.py` | Operator-owned adversarial containment probe |
| `genesis_local/broker.py` | Restricted Unix-socket Ollama capability |
| `genesis_local/coordinator.py` | Approval, generation, validation, repairs and publication |
| `genesis_local/validation.py` | Exact argv allowlist validation runner |
| `genesis_local/git_checkpoint.py` | Validated explicit-file private-index Git checkpoints |
| `genesis_local/state.py` | Atomic disk state and nonblocking locks |
| `genesis_local/recovery.py` | Hash-based publication and checkpoint recovery |
| `genesis_local/workspace.py` | Disposable marker, path, symlink, hardlink and secret checks |
| `genesis_local/evidence.py` | Output-free evidence metrics and digests |
| `genesis_local/deadline.py` | Hard wall clock execution deadline |
| `tests/test_orchestrator.py` | Functional, failure, recovery and Git tests |
| `tests/test_security.py` | Syscall, broker policy and adapter tests |
| `tools/fixture_workflow.py` | Mocked-provider, real-validation disposable Git demonstration |
| `tools/host_acceptance.py` | Real Bubblewrap/Aider/Ollama disposable-fixture acceptance |
| `tools/package_review.py` | Explicit-allowlist review ZIP builder |
| `docs/ARCHITECTURE.md` | Architecture, security boundaries, recovery and limitations |
| `docs/HOST_ACCEPTANCE.md` | Exact host-only acceptance command and interpretation |
| `docs/ACCEPTANCE_REPORT.md` | Available test results and pending acceptance mapping |
| `artifacts/available-tests.txt` | Complete available test-run transcript |
| `artifacts/fixture-workflow.json` | Successful known-code fixture evidence |
| `artifacts/host-acceptance-pending.json` | Explicit unexecuted host acceptance status |
| `artifacts/source-inventory.json` | Exact archive membership and per-file SHA-256/size |
| `artifacts/genesis-local-source.zip` | Source-only independent review archive |
| `artifacts/genesis-local-source.zip.sha256` | External archive checksum |

The review package excludes the existing `calculator.py`, `test_calculator.py`, `.aider.chat.history.md`, `.aider.input.history`, `.aider.tags.cache.v4/`, `__pycache__/`, `.git/`, and environment-owned `.agents/`, `.codex/`, `.aws/`. Their exclusion does not delete or modify them. Temporary fixture repositories, private state, provider candidates, and test/install scratch are outside this implementation repository and are removed by their owning runners.
