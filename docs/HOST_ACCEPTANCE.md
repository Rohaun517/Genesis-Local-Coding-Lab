# Host acceptance — PENDING

Run from a regular owner terminal outside Codex's nested sandbox. Do not change kernel settings, escalate privileges, disable Codex restrictions, restart Ollama, or run Aider directly to bypass a failed check.

From this review checkout, with the required host runtimes already installed:

```bash
python3.12 -B -m unittest discover -s tests -v
python3.12 -B tools/host_acceptance.py \
  --approve-disposable-fixture \
  --evidence /tmp/genesis-host-acceptance-001.json
```

The evidence filename must not exist. The explicit flag approves only the runner's freshly created disposable fixture, its source mutations, and its validated fixture-only Git checkpoint. The runner takes no repository/workspace argument and never operates on an existing Genesis repository. Its temporary fixture and private state are deleted on exit; the JSON evidence survives at the requested path. No root repository commit or push is authorized.

The runner uses the exact mount/namespace builder in `genesis_local/containment.py`, without a weaker fallback. Its namespace base is the earlier successful host configuration (`--unshare-all --die-with-parent`); the narrower runtime mounts, capability dropping, fresh temporary filesystem, syscall policy, and socket capability are additional requirements whose combined host behavior has not yet been demonstrated. The owner evidence established namespace feasibility, not acceptance of this complete configuration.

The active probe tests shell/exec denial, process denial, thread limits, host-home and repository inaccessibility, external and host-loopback network denial, source write limits, forbidden writes, and symlink creation refusal. The runner additionally checks read-only validation, namespace timeout, input symlink traversal refusal, actual Aider/Qwen/Ollama generation, real contained unit tests, exact checkpoint contents, unrelated and `.env` file preservation, and restart without another inference call. Broker policy and adversarial request parsing are unit-tested in memory inside Codex; the host workflow exercises the real Unix socket and relay.

On success the JSON status is `HOST_ACCEPTANCE_PASSED`; any failed assertion, preflight, library/runtime incompatibility, timeout, missing Ollama/model, or unsupported namespace returns `BLOCKED` and exit 2. A failure must be investigated, never bypassed. Retain the JSON for independent review. The delivery status remains `CANDIDATE_READY_FOR_HOST_ACCEPTANCE` until this command is independently executed and its report reviewed.

Other reproducible evidence commands:

```bash
python3.12 -B tools/fixture_workflow.py --evidence /tmp/genesis-mocked-fixture.json
python3.12 -B tools/package_review.py
```

The mocked fixture command runs known test-owned code with real unit tests and real Git; it does not exercise Aider or prove containment. The package command uses an explicit file inventory and excludes Git data, preexisting Aider artifacts, caches, installed runtimes, secrets, and nested archives.
