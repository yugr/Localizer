= What is this

Localizer is a simple experimental tool
which tries to detect symbols which could be marked as `static`
(or moved to anon. namespace).
It does so by intercepting calls to linker and
analyzing symbol imports and exports.

= How to run

Run your build script under `find-locals.py` script:
```
$ find-locals.py make -j10 clean all
```

= How to test

NYI

= TODO

* Run on real projects
* Collect imports/exports from static libs
* Run lint
