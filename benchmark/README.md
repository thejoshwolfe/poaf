# benchmark

TODO

compare poaf (with default stream split threshold) against `zip` (Info-ZIP) and `tar` for `.tar.gz`:

* compression speed
* decompression speed
* archive size
* speed extracting one item at a time in reverse listed order (don't ask TAR to do this).

for data sets:
* one empty file
* a million empty files (with names `000/000` to `999/999`)
* one 16GiB file (containing repeating byte values 0-255)
* some git repos:
    * https://github.com/ziglang/zig tag `0.15.1`
    * https://github.com/python/cpython tag `v3.13.7`
    * git://gcc.gnu.org/git/gcc.git tag `releases/gcc-15.2.0`
    * this repo, `main` branch
