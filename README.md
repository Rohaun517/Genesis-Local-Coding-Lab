# Genesis Local Engineering Orchestrator V1

Development-only local tooling. This CLI has no Genesis Trusted Authority role or credentials. It does not deploy or push. Host acceptance is pending; see [the acceptance report](docs/ACCEPTANCE_REPORT.md).

Requires Linux x86-64, Python 3.12, Git, Bubblewrap 0.9.0 with usable unprivileged namespaces, libseccomp.so.2, Ollama 0.23.2 at `http://127.0.0.1:11434`, and Aider 0.86.2 in `/home/rohaun/.venvs/genesis-aider`. The pinned model is `qwen2.5-coder:32b`. Do not restart Ollama or change host configuration for this package.

## Development installation

From a review checkout, using an owner-selected development virtualenv:

```bash
python3.12 -m venv /tmp/genesis-local-review-venv
/tmp/genesis-local-review-venv/bin/python -m pip install --no-deps .
/tmp/genesis-local-review-venv/bin/genesis-local --help
python3.12 -B -m unittest discover -s tests -v
```

The package has no runtime PyPI dependencies. Installation needs setuptools>=68 (build isolation may download it); an offline environment with setuptools already installed can use `--no-build-isolation --no-deps`. Installation does not install or reconfigure Ollama, Aider, or Bubblewrap. Python tests require no model, network, GPUs, or namespace privileges.

## Plan, review, approve

Only use a newly created disposable Git repository. The marker is an explicit operator declaration, not a security certificate. Never mark an existing Genesis or production repository disposable.

```bash
mkdir -m 700 /tmp/genesis-objectives
mkdir /tmp/genesis-example
cd /tmp/genesis-example
git init
printf 'development-only\n' > .genesis-disposable
printf '# disposable fixture\n' > README.md
git add README.md
# Run this fixture initialization commit only with owner approval:
git -c user.name='Fixture Owner' -c user.email='fixture@localhost' commit -m 'fixture baseline'

genesis-local --state-dir /tmp/genesis-objectives engineer \
  'Create a Python utility with unit tests.' \
  --workspace /tmp/genesis-example \
  --file utility.py --file tests/test_utility.py --validation unittest
```

`engineer` creates a structured plan and performs no generation. Review its objective ID, exact allowed paths, baseline hashes, validation argv, resource limits, checkpoint policy, and digest. Approval is an explicit local operator action bound to that digest:

```bash
genesis-local --state-dir /tmp/genesis-objectives show OBJECTIVE_ID
genesis-local --state-dir /tmp/genesis-objectives approve OBJECTIVE_ID --plan-digest PLAN_DIGEST
# Or refuse it:
genesis-local --state-dir /tmp/genesis-objectives deny OBJECTIVE_ID --plan-digest PLAN_DIGEST
# Inspect/recover the same objective; completed model calls are never replayed:
genesis-local --state-dir /tmp/genesis-objectives resume OBJECTIVE_ID
```

Plan with `--checkpoint` only when the owner explicitly approves a fixture checkpoint after successful validation. Approving that displayed plan authorizes its limited checkpoint policy. Without this option, validated source is published as uncommitted changes. This delivery does not commit into the implementation repository.

Exit 0 means planned, denied, or succeeded; exit 2 means blocked, failed, or interrupted. There is no push command or push option.

## Operator configuration

Pass an operator-owned JSON file using `--config /absolute/config.json` before the subcommand. Never accept a model-produced configuration. Example:

```json
{
  "aider_python": "/home/rohaun/.venvs/genesis-aider/bin/python",
  "validations": {
    "unittest": ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
  },
  "limits": {
    "elapsed_seconds": 900,
    "invocation_seconds": 240,
    "provider_invocations": 3,
    "repair_attempts": 2,
    "changed_files": 8,
    "written_bytes": 262144,
    "memory_bytes": 4294967296,
    "cpu_seconds": 180,
    "process_threads": 32,
    "temporary_bytes": 16777216,
    "output_bytes": 1048576
  }
}
```

Validation supports exact allowlisted Python module argv arrays in V1. Shell commands and executable commands are refused. Adding modules to the allowlist is an operator trust decision. Validation has no network broker, no writable source mounts, no shell execution, and no subprocess creation.

See [architecture and limits](docs/ARCHITECTURE.md), [host acceptance](docs/HOST_ACCEPTANCE.md), and [the exact file manifest](FILE_MANIFEST.md).
