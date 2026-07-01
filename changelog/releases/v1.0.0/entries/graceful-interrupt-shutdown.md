---
title: Graceful interrupt shutdown
type: bugfix
authors:
  - mavam
  - codex
prs:
  - 12
created: 2026-07-01T16:45:15.204658Z
---

`skeel` now shuts down cleanly when interrupted with `Ctrl+C`:

```sh
skeel update
```

Interrupted runs terminate child commands and suppress cleanup-time `KeyboardInterrupt` tracebacks from temporary-file finalizers, so users see the normal `interrupted` message instead of Python internals.
