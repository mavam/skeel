---
title: Diff-style apply output
type: bugfix
authors:
  - mavam
  - codex
created: 2026-06-14T20:53:15.441039Z
---

`skeel apply` now uses diff-style markers to show the direction of each change:

```sh
+ openclaw/openclaw@openhue
- find-skills
```

Installs use a green `+`, while removals use a red `-`, making it clear which skills are added and which are removed.
