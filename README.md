[![License](http://img.shields.io/:license-MIT-blue.svg)](https://github.com/yugr/Localizer/blob/master/LICENSE.txt)

# What is this

Localizer is a simple experimental tool
which tries to detect symbols which could localized within their module
i.e. be marked as `static` or moved to anon. namespace.

Localization of symbols is beneficial because it
[enables optimizations](https://embeddedgurus.com/stack-overflow/2008/12/efficient-c-tips-5-make-local-functions-static/)
and prevents interface pollution.

The tool works by intercepting calls to linker and
analyzing symbol imports and exports.

# How to run

Run your build script under `find-locals.py` script:
```
$ find-locals.py make -j10 clean all
```

If you want to ignore symbols which are present in headers, do
```
$ find-locals.py --ignore-header-symbols $PWD make ...
```

For more options, run `find-locals.py -h`.

# How to test

Run
```
$ test/run_tests.sh
```

# Limitations

By design the tool is unable to detect conditional uses of symbols
which are hidden under `#ifdef`s.

Sometimes compiler is also clever enough to optimize out function calls
even if they are present in text (e.g. by propagating constant arguments
into static functions). For this reason it's recommended to run the tool
on _unoptimized_ build. For Autotools-enabled projects just do
```
$ ./configure CFLAGS='-g -O0' CXXFLAGS='-g -O0'
```

Finally, in many cases symbols are exported so that they can be used in tests
so be sure to build tests as well:
```
$ find-locals.py 'make -j 10 && make check'
```

# TODO

* Test on real projects
* Do not report private class methods (even though they aren't used directly in other files)
* Integrate LGTM, Codecov and Travis
