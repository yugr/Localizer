[![License](http://img.shields.io/:license-MIT-blue.svg)](https://github.com/yugr/Localizer/blob/master/LICENSE.txt)

# What is this

Localizer is a simple experimental tool
which tries to detect symbols which could be marked as `static`
(or moved to anon. namespace).
It does so by intercepting calls to linker and
analyzing symbol imports and exports.

# How to run

Run your build script under `find-locals.py` script:
```
$ find-locals.py make -j10 clean all
```

# How to test

NYI

# Limitations

By design the tool is unable to detect conditional uses of symbols
which are hidden under `#ifdef`s.

# TODO

* Do not report virtual functions which aren't used directly
* Run on real projects
* Collect imports/exports from static libs
* Integrate LGTM, Codecov and Travis
