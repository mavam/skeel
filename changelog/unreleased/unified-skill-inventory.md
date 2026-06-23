---
title: Unified skill inventory
type: change
authors:
  - mavam
  - codex
created: 2026-06-22T16:11:10.04516Z
prs:
  - 10
---

The `list` command now shows a unified project and user inventory, including installed skills that are not declared in a manifest:

```sh
skeel list
```

Previously, `list` only displayed manifest entries, so manually installed project or user skills could be hidden from the default view. Human output now shows a single list, and every command renders scope the same way: a muted scope glyph after the action marker (`★` for project, `⌂` for user). Unmanaged installed skills appear alongside managed ones, and JSON output marks them with `"managed": false`.
