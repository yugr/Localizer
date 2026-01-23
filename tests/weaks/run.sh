#!/bin/sh

set -eu
if set -o | grep -q pipefail; then set -o pipefail; fi

cd $(dirname $0)

rm -f a.out *.o

CC=${CC:-gcc}

$CC main.c other.c
