"""Explicit plan review and local development approval CLI."""
import argparse
import json
from pathlib import Path
import sys
from .config import Config, Limits
from .coordinator import Coordinator
from .planner import plan_objective
from .state import Store
from .workspace import SafetyError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Development only; no Trusted Authority privileges')
    parser.add_argument('--state-dir', required=True, help='private 0700 directory outside fixture repo')
    parser.add_argument('--config', help='operator-owned JSON config (never model-produced)')
    subs = parser.add_subparsers(dest='command', required=True)
    engineer = subs.add_parser('engineer')
    engineer.add_argument('objective')
    engineer.add_argument('--workspace', required=True)
    engineer.add_argument('--file', action='append', required=True)
    engineer.add_argument('--validation', action='append', default=None)
    engineer.add_argument('--checkpoint', action='store_true', help='include an owner-approved commit in the plan')
    for command in ('show', 'approve', 'deny', 'resume'):
        sub = subs.add_parser(command)
        sub.add_argument('objective_id')
        if command in ('approve', 'deny'):
            sub.add_argument('--plan-digest', required=True)
    args = parser.parse_args(argv)
    try:
        data = json.loads(Path(args.config).read_text()) if args.config else {}
        if 'limits' in data:
            data['limits'] = Limits(**data['limits'])
        config = Config(**data)
        store = Store(args.state_dir)
        runner = Coordinator(config, store)
        if args.command == 'engineer':
            plan = plan_objective(args.objective, args.workspace, args.file,
                                  args.validation or ['unittest'], config, args.checkpoint)
            state = runner.create(plan)
        elif args.command == 'show':
            state = store.load(args.objective_id)
        else:
            decision = {'approve': 'approve', 'deny': 'deny'}.get(args.command)
            state = runner.execute(args.objective_id, decision, getattr(args, 'plan_digest', None))
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0 if state['status'] in {'PLANNED', 'DENIED', 'SUCCEEDED'} else 2
    except (SafetyError, OSError, ValueError, TypeError) as e:
        print('BLOCKED: ' + str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
