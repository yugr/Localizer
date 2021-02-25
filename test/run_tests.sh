#!/bin/sh

set -eu
if set -o | grep -q pipefail; then set -o pipefail; fi

cd $(dirname $0)

tmp=$(mktemp)
trap "rm -f $tmp" EXIT

for d in *; do
  if test -d $d; then
    ../find-locals.py $d/run.sh >$tmp 2>&1
    if ! diff run.log $d/output.ref; then
      echo "$d: FAIL"
    else
      echo "$d: SUCCESS"
    fi
  fi
done
