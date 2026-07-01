---
title: Unified scoped skill updates
type: bugfix
authors:
  - mavam
  - codex
created: 2026-07-01T15:45:57.076647Z
prs:
  - 12
---

The `update` command now schedules project- and user-scoped skills in one continuous run when both scopes are selected:

```sh
skeel update
```

This keeps live progress continuous instead of completing one scope before starting the next.
