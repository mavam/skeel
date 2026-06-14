---
title: Fast pinned GitHub skill reinstalls
type: bugfix
authors:
  - mavam
  - codex
created: 2026-06-14T20:23:54.454099Z
---

Reinstalling pinned GitHub skill sources is now fast enough for large skill repositories:

```sh
skeel apply --reinstall tenzir/skills
```

Pinned entries still show up as GitHub-managed skills with source and version metadata after reinstalling. Unpinned entries keep GitHub CLI's default version resolution behavior.
