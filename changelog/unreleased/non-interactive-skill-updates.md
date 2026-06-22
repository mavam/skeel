---
title: Non-interactive skill updates
type: bugfix
authors:
  - mavam
  - codex
prs:
  - 7
created: 2026-06-22T05:12:59.429356Z
---

`skeel update` now applies available GitHub skill updates in non-interactive runs instead of failing with a confirmation prompt from `gh skill`.

For example:

```sh
uvx skeel update
```

When a declared skill has an update, the command updates it directly and keeps reporting per-skill results.
