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

`skeel update` now shows skills only while they are actively updating, then ends
with a compact summary:

```sh
skeel update
```

Updated rows use `↑`, skipped rows use `!`, and completed current rows disappear
from the normal view. Use `skeel update -v` to keep the full per-skill view,
including current rows. User-scope markers now stay next to the skill source,
before version transitions or diagnostic notes. When every skill is already
current, the command prints only the summary count.
