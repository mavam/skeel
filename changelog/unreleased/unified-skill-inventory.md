---
title: Unified skill inventory
type: change
authors:
  - mavam
  - codex
created: 2026-06-22T16:11:10.04516Z
---

The `list` command now shows a unified project and user inventory, including installed skills that are not declared in a manifest:

```sh
skeel list
```

Previously, `list` only displayed manifest entries, so manually installed project or user skills could be hidden from the default view. When both scopes have rows, human output now groups them under `project` and `user` headers. Unmanaged installed skills still use the same scope markers as managed skills, and JSON output marks them with `"managed": false`.
