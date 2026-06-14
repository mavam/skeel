---
title: Dry-run command handling
type: bugfix
authors:
  - mavam
created: 2026-06-14T12:28:40.918798Z
---

The `--dry-run` flag now works after mutating subcommands and prints dry-run-specific status messages.

For example, both forms are accepted:

```sh
skeel --dry-run apply
skeel apply --dry-run
```

Dry runs now say what skeel would do and finish with a dry-run completion message instead of reporting that skills were applied or updated.
