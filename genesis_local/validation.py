"""Only exact operator-allowlisted argv is run, inside a read-only sandbox."""
from .workspace import SafetyError


class Validator:
    def __init__(self, config, sandbox):
        self.config = config
        self.sandbox = sandbox

    def run(self, plan, candidate, remaining):
        results, outputs = [], []
        import time
        start = time.monotonic()
        for name, argv in plan.validation_commands.items():
            if self.config.validations.get(name) != argv:
                raise SafetyError('validation allowlist changed')
            budget = min(self.config.limits.invocation_seconds, remaining - (time.monotonic() - start))
            item, output = self.sandbox.run(candidate, plan.expected_source_changes,
                                            'validation', argv, budget)
            item['name'] = name
            results.append(item)
            outputs.append(output)
            if item['exit_code'] or item['timed_out']:
                break
        return results, b'\n'.join(outputs)
