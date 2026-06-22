---
title: Clearer update summaries
type: change
authors:
  - mavam
  - codex
created: 2026-06-22T09:50:30.452171Z
---

`skeel update` now highlights changed and skipped skills before ending with a compact summary:

```sh
skeel update
```

When every skill is already current, the command prints only the summary count. Use `skeel update -v` to list every skill, including current rows.
