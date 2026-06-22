---
title: Clearer update summaries
type: change
authors:
  - mavam
  - codex
prs:
  - 8
created: 2026-06-22T09:50:30.452171Z
---

`skeel update` now highlights only changed and skipped skills before ending with
a compact summary:

```sh
skeel update
```

Updated rows use `↑`, skipped rows use `!`, and current rows are hidden unless
you run `skeel update -v`. When every skill is already current, the command
prints only the summary count.
