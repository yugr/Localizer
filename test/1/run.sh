#!/bin/sh

set -eu
if set -o | grep -q pipefail; then set -o pipefail; fi

cd $(dirname $0)

gcc -c lib.c
ar rcs lib.a lib.o
gcc -c main.c
gcc main.o lib.a
