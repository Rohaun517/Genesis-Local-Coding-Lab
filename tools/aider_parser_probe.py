"""Parser definitions only: does not import/run Aider, a coder, or a provider."""
import argparse
import ast
import configargparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shtab
import sys
import types

probe_args = argparse.ArgumentParser(description=__doc__)
probe_args.add_argument('--argv-file', help='JSON argv from an operator-owned test fixture')
options = probe_args.parse_args()
argv = json.loads(Path(options.argv_file).read_text()) if options.argv_file else ['--config', '/dev/null']

runtime = Path(sys.prefix) / 'lib/python3.12/site-packages/aider'
class NoCoders(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module == 'aider':
            return ast.copy_location(ast.Pass(), node)
        return node
functions = []
for name, wanted in [('args.py', {'resolve_aiderignore_path', 'default_env_file', 'get_parser'}),
                     ('deprecated.py', {'add_deprecated_model_args'})]:
    tree = ast.parse((runtime / name).read_text())
    functions += [NoCoders().visit(n) for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name in wanted]
namespace = dict(argparse=argparse, configargparse=configargparse, os=os, sys=sys,
                 Path=Path, shtab=shtab, __version__=importlib.metadata.version('aider-chat'),
                 _aider_coders=types.SimpleNamespace(__all__=[]))
exec(compile(ast.Module(body=functions, type_ignores=[]), '<installed-parser-definitions>', 'exec'), namespace)
assert not any(n == 'aider' or n.startswith('aider.') for n in sys.modules)
parser = namespace['get_parser']([], None)
parser.prog = 'aider'
error = io.StringIO()
code = 0
with contextlib.redirect_stderr(error):
    try:
        parser.parse_args(argv)
    except SystemExit as e:
        code = e.code
assert not any(n == 'aider' or n.startswith('aider.') for n in sys.modules)
output = error.getvalue().encode()
print(json.dumps({'scope': 'PARSER_DEFINITIONS_ONLY_NO_AIDER_EXECUTION', 'exit_code': code,
                  'output_bytes': len(output), 'output_sha256': hashlib.sha256(output).hexdigest(),
                  'diagnostic': ('empty_yaml_configuration' if "returned type 'NoneType' instead of 'dict'"
                                 in error.getvalue() else 'cli_argument_error' if code else 'parser_accepted')}))
