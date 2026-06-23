---
title: Dynamic source diff output
type: bugfix
authors:
  - mavam
  - codex
created: 2026-06-22T13:37:12.430644Z
prs:
  - 9
---

The `diff` command now reports dynamic sources that select all skills when they still need to be applied:

```sh
uvx skeel add example/skills
uvx skeel diff
```

This now shows `+ example/skills` instead of producing no output before `apply` installs the source.
