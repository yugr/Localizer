#!/usr/bin/env python3

# Copyright 2021-2026 Yury Gribov
# 
# Use of this source code is governed by MIT license that can be
# found in the LICENSE.txt file.

"""
A simple script which locates functions in codebase which can
be changed to statics (or moved to anon. namespace).
"""

import argparse
import atexit
import json
import os
import os.path
import re
import subprocess
import shutil
import sys
import tempfile

me = os.path.basename(__file__)
VERBOSE = 0

def warn(msg):
  """
  Print nicely-formatted warning message.
  """
  sys.stderr.write(f'{me}: warning: {msg}\n')

def error(msg):
  """
  Print nicely-formatted error message and exit.
  """
  sys.stderr.write(f'{me}: error: {msg}\n')
  sys.exit(1)

def warn_if(cond, msg):
  if cond:
    warn(msg)

def error_if(cond, msg):
  if cond:
    error(msg)

def run(cmd, fatal=False, tee=False, stdin='', **kwargs):
  """
  Simple wrapper for subprocess.
  """
  if isinstance(cmd, str):
    cmd = cmd.split(' ')
#  print(cmd)
  with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, **kwargs) as p:
    out, err = p.communicate(input=stdin.encode('utf-8'))
  out = out.decode()
  err = err.decode()
  if fatal and p.returncode != 0:
    cmds = ' '.join(cmd)
    error(f"'{cmds}' failed:\n{out}{err}")
  if tee:
    sys.stdout.write(out)
    sys.stderr.write(err)
  return p.returncode, out, err

class Symbol:
  def __init__(self, name):
    self.name = name
    self.demangled_name = None
    self.defs = set()
    self.uses = set()

  def has_multiple_defs(self):
    return len(self.defs) > 1

  def is_imported(self):
    return len(self.uses) > 0

  def is_system_symbol(self):
    for origin in sorted(self.defs):
      if origin.startswith("/usr/") or origin.startswith("/lib/"):
        return True
    return False

  def first_origin(self):
    return next(iter(self.defs))

class Symtab:
  def __init__(self):
    self.syms = {}
    self.imports = {}
    self.exports = {}

  def empty(self):
    return not self.syms

  def get_or_create(self, name):
    sym = self.syms.get(name)
    if sym is None:
      sym = self.syms[name] = Symbol(name)
    return sym

  def add_import(self, origin, name):
    sym = self.get_or_create(name)
    sym.uses.add(origin)
    self.imports.setdefault(name, []).append(origin)

  def add_export(self, origin, name):
    sym = self.get_or_create(name)
    sym.defs.add(origin)
    self.exports.setdefault(name, []).append(origin)

def analyze_reports(reports, header_syms):
  # Collect global imports/exports
  symtab = Symtab()
  for report in reports:
    with open(report, errors='replace') as f:
      contents = json.load(f)
    for s in contents['exports']:
      symtab.add_export(s['file'], s['name'])
    for s in contents['imports']:
      symtab.add_import(s['file'], s['name'])
    for s in contents['global_exports']:
      # Here we assume that any symbol exported from shlib has potential outside uses
      # so can't be marked as static.
      # This is an over simplification because very often these exports are accidental.
      # But such cases should be checked by dedicated tool ShlibVisibilityChecker.
      symtab.add_import(s['file'], s['name'])

  if symtab.empty():
    return

  # Collect demangled names
  names = sorted(symtab.syms.keys())
  _, out, _ = run(['c++filt'], stdin='\n'.join(names))
  out = out.rstrip("\n")  # Some c++filts append newlines at the end
  for i, demangled_name in enumerate(out.split("\n")):
    # Find stem
    j = demangled_name.rfind('(')
    if j != -1:
      demangled_name = demangled_name[:j]
    j = demangled_name.rfind('::')
    if j != -1:
      demangled_name = demangled_name[j + 2:]
    symtab.syms[names[i]].demangled_name = demangled_name

  if VERBOSE:
    # This happens when several executables are linked from same objects
    for name, sym in sorted(symtab.syms.items()):
      if not sym.has_multiple_defs():
        continue
      if name[0] == '_':
        # Skip compiler-generated symbols
        continue
      if name in ('main',):
        # Skip duplicated symbols
        continue
      warn("symbol %s is defined in multiple files:\n  %s"
           % (name, '\n  '.join(sorted(sym.defs))))

  # Collect unimported symbols
  bad_syms = []
  for name, sym in symtab.syms.items():
    if sym.is_system_symbol():
      # Skip system files
      continue
    if sym.demangled_name in header_syms:
      continue
    if sym.is_imported():
      continue
    bad_syms.append(sym)

  # Print report
  sys.stdout.flush()
  sys.stderr.flush()
  if bad_syms:
    print("Global symbols not imported by any file:")
    for org, name in sorted((sym.first_origin(), sym.name) for sym in bad_syms):
      print(f"  {name} ({org})")
  else:
    print(f"No violations found (in {len(reports)} linker invocations)")

def find_headers(roots):
  headers = []
  for root in roots:
    for path, _, files in os.walk(root):
      for file in files:
        ext = os.path.splitext(file)[1]
        if ext in ('.h', '.hpp', '.hh'):
          headers.append(os.path.join(path, file))
  return headers

def index_headers(headers):
  # TODO: skip comments
  syms = set()
  pat = re.compile(r'\b([a-z_][a-z_0-9]*)\s*[\[(;]|#\s*define\s.*\b([a-z_][a-z_0-9]*)\b', re.I)
  for i, h in enumerate(headers):
    with open(h, errors='replace') as f:
      contents = f.read()
      for first, second in pat.findall(contents):
        syms.add(first)
        syms.add(second)
    if VERBOSE and i > 0 and i % 100 == 0:
      print(f"{me}: indexed {i}/{len(headers)} headers...")
  return syms

def collect_logs(cmd, args, log_dir):
  # Add linker wrappers to PATH
  bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'bin'))

  path = os.environ['PATH']
  os.environ['PATH'] = bin_dir + os.pathsep + path if path else bin_dir

  # Clang ignores PATH when looking for linker so try harder
  compiler_path = os.environ.get('COMPILER_PATH', '')
  os.environ['COMPILER_PATH'] = bin_dir + os.pathsep + compiler_path if compiler_path else bin_dir

  # Pass settings via environment
  os.environ['LOCALIZER_DIR'] = log_dir
  os.environ['LOCALIZER_VERBOSE'] = str(VERBOSE)

  # TODO: preserve interactive stdout/stderr
  rc, out, err = run(['bash', '-c', ' '.join([cmd] + args)])
  sys.stdout.write(out)
  sys.stderr.write(err)

  return rc

def main():
  class Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass
  parser = argparse.ArgumentParser(description="Find symbols which may be marked as static",
                                   formatter_class=Formatter,
                                   epilog=f"""\
Examples:
  $ python {me} make -j10
""")
  parser.add_argument('--keep', '-k',
                      help="Do not remove temp files",
                      dest='keep', action='store_true', default=False)
  parser.add_argument('--no-keep',
                      help="Inverse of --keep",
                      dest='keep', action='store_false')
  parser.add_argument('--tmp-dir',
                      help="Store temp files in directory")
  parser.add_argument('--ignore-header-symbols', metavar='DIR',
                      help="Do not report symbols that are present in headers in directory",
                      action='append', default=[])
  parser.add_argument('--ignore-retcode',
                      help="Ignore non-zero error code from build command",
                      action='store_true', default=False)
  parser.add_argument('--verbose', '-v',
                      help="Print diagnostic info (can be specified more than once)",
                      action='count', default=0)
  parser.add_argument('cmd_or_dir',
                      help="Program to run OR directory with pre-collected logs", metavar='ARG')
  parser.add_argument('args',
                      nargs=argparse.REMAINDER, default=[])

  args = parser.parse_args()

  global VERBOSE
  VERBOSE = args.verbose

  headers = find_headers(map(os.path.abspath, args.ignore_header_symbols))
  header_syms = index_headers(headers)

  if os.path.isdir(args.cmd_or_dir):
    log_dir = args.cmd_or_dir
  else:
    # Collect logs

    log_dir = args.tmp_dir or tempfile.mkdtemp(prefix='find-locals-')
    if os.path.exists(log_dir):
      shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    if not args.keep:
      atexit.register(lambda: shutil.rmtree(log_dir))
    else:
      sys.stderr.write(f"{me}: intermediate files will be stored in {log_dir}\n")

    rc = collect_logs(args.cmd_or_dir, args.args, log_dir)
    if rc and not args.ignore_retcode:
      sys.stderr.write(f"{me}: not collecting data because build has errors\n")
      return rc

  reports = [os.path.join(log_dir, report) for report in os.listdir(log_dir)]
  analyze_reports(reports, header_syms)

  return 0

if __name__ == '__main__':
  sys.exit(main())
