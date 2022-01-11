#!/usr/bin/env python3

# Copyright 2021-2022 Yury Gribov
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

def run(cmd, **kwargs):
  """
  Simple wrapper for subprocess.
  """
  if 'fatal' in kwargs:
    fatal = kwargs['fatal']
    del kwargs['fatal']
  else:
    fatal = False
  if 'tee' in kwargs:
    tee = kwargs['tee']
    del kwargs['tee']
  else:
    tee = False
  if isinstance(cmd, str):
    cmd = cmd.split(' ')
#  print(cmd)
  with subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, **kwargs) as p:
    out, err = p.communicate()
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

class Symtab:
  def __init__(self):
    self.syms = {}
    self.imports = {}
    self.exports = {}

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
    with open(report) as f:
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

  # Warn about duplicated definitions
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
  for name, sym in sorted(symtab.syms.items()):
    if sym.is_system_symbol():
      # Skip system files
      continue
    if name in header_syms:
      continue
    if not sym.is_imported():
      bad_syms.append(sym)

  # Print report
  sys.stdout.flush()
  sys.stderr.flush()
  if bad_syms:
    print("Global symbols not imported by any file:")
    for sym in bad_syms:
      first_origin = next(iter(sym.defs))
      print(f"  {sym.name} ({first_origin})")
  else:
    print(f"No violations found (in {len(reports)} linker invocations)")

def find_headers(roots):
  headers = []
  for root in roots:
    for path, _, files in os.walk(root):
      for file in files:
        ext = os.path.splitext(file)[1]
        if ext in ('.h', '.hpp'):
          headers.append(os.path.join(path, file))
  return headers

def index_headers(headers, v):
  syms = set()
  pat = re.compile(r'\b([a-z_][a-z_0-9]*)\s*[\[(;]|#\s*define\s.*\b([a-z_][a-z_0-9]*)\b', re.I)
  for i, h in enumerate(headers):
    with open(h) as f:
      contents = f.read()
      for first, second in pat.findall(contents):
        syms.add(first)
        syms.add(second)
    if v and i > 0 and i % 100 == 0:
      print(f"{me}: indexed {i}/{len(headers)} headers...")
  return syms

def collect_logs(cmd, args, log_dir, v):
  # Add linker wrappers to PATH
  bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'bin'))
  os.environ['PATH'] = bin_dir + os.pathsep + os.environ['PATH']

  # Pass settings via environment
  os.environ['LOCALIZER_DIR'] = log_dir
  os.environ['LOCALIZER_VERBOSE'] = str(v)

  # TODO: preserve interactive stdout/stderr
  rc, out, err = run(['bash', '-c', ' '.join([cmd] + args)], fatal=True)
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
  parser.add_argument('--verbose', '-v',
                      help="Print diagnostic info (can be specified more than once)",
                      action='count', default=0)
  parser.add_argument('cmd_or_dir',
                      help="Program to run OR directory with pre-collected logs", metavar='ARG')
  parser.add_argument('args',
                      nargs=argparse.REMAINDER, default=[])

  args = parser.parse_args()

  if os.path.isdir(args.cmd_or_dir):
    log_dir = args.cmd_or_dir
  else:
    # Collect logs

    log_dir = args.tmp_dir or tempfile.mkdtemp(prefix='find-locals-')
    shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    if not args.keep:
      atexit.register(lambda: shutil.rmtree(log_dir))
    else:
      sys.stderr.write(f"{me}: intermediate files will be stored in {log_dir}\n")

    rc = collect_logs(args.cmd_or_dir, args.args, log_dir, args.verbose)
    if rc:
      sys.stderr.write(f"{me}: not collecting data because build has errors\n")
      return rc

  headers = find_headers(map(os.path.abspath, args.ignore_header_symbols))
  header_syms = index_headers(headers, args.verbose)

  reports = [os.path.join(log_dir, report) for report in os.listdir(log_dir)]
  analyze_reports(reports, header_syms)

  return 0

if __name__ == '__main__':
  sys.exit(main())
