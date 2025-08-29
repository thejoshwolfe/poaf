# poaf examples

These are still in development.

The idea is to have 4 implementations using every combination of two languages and two scopes.

Languages:

* Python - concise logic focusing on demonstrating the poaf archive format with little regard for performance.
* Zig - low-level, high-performance code focusing on efficient system resource utilization and optimal algorithmic complexity.

Scopes:

* Full - support for all optional features.
* Minimal - create archives with no optional stream splitting; extract with no file name filtering and no Index Region verification. Still support file name validation, all file types, and crc32 checking.

Status:

* `full-python` - nearly done; a few known bugs and missing tests.
* `minimal-python` - done.
* `full-zig` - in progress.
* `minimal-zig` - not started.
