#!/bin/sh

set -eu
if set -o | grep -q pipefail; then set -o pipefail; fi

cd $(dirname $0)

CC=${CC:-gcc}

$CC -c lib.c
ar rcs lib.a lib.o
$CC -c main.c
$CC main.o lib.a
