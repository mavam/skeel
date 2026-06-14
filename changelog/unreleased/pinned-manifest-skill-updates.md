---
title: Pinned manifest skill updates
type: bugfix
authors:
  - mavam
  - codex
created: 2026-06-14T20:31:33.918737Z
---

`skeel update` now refreshes pinned GitHub skills that are declared in the manifest instead of reporting them as skipped:

```sh
skeel update
```

This keeps pinned sources such as `tenzir/skills` updateable while preserving their GitHub source metadata.
