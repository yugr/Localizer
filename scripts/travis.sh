#!/bin/sh

# Copyright 2022-2026 Yury Gribov
# 
# Use of this source code is governed by MIT license that can be
# found in the LICENSE.txt file.

set -eu

if test -n "${TRAVIS:-}" -o -n "${GITHUB_ACTIONS:-}"; then
  set -x
fi

cd $(dirname $0)/..

# Run all child scripts via $PYTHON
if test -n "${PYTHON:-}"; then
  mkdir -p tmp
  # Handle multiple args
  set -- $PYTHON
  exe=$(which $1)
  shift
  cat > tmp/python3 <<EOF
#!/bin/sh
$exe $@ "\$@"
EOF
  chmod +x tmp/python3
  export PYTHON=python3
  export PATH=$PWD/tmp:$PATH
fi

errors=0
for d in tests/*; do
  test -d $d || continue
  if grep -q IGNORE_HEADER_SYMBOLS $d/run.sh; then
    OPTS="--ignore-header-symbols ."
  else
    OPTS=
  fi
  if ! (cd $d && ${PYTHON:-python3} ../../find-locals.py $OPTS ./run.sh >output.log 2>&1) \
      || ! diff -q $d/output.ref $d/output.log; then
    echo "$d: FAIL"
    diff $d/output.ref $d/output.log >&2 || true
    errors=$((errors + 1))
  fi
done

if test $errors -gt 0; then
  echo "Found $errors errors"
else
  echo SUCCESS
fi
