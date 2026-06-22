---
title: Duplicate unscoped skill updates from home
type: bugfix
authors:
  - mavam
  - codex
prs:
  - 5
created: 2026-06-21T18:13:33.309136Z
---

Unscoped `skeel update` no longer runs the same user manifest twice when invoked from `$HOME`.

For example:

```sh
cd ~
uvx skeel update
```

When the default project and user paths both resolve to `~/.agents`, each installed skill is now checked and reported once.
