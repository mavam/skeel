---
title: Per-skill update results
type: change
authors:
  - mavam
created: 2026-06-14T20:20:02.025294Z
---

`skeel update` now checks installed manifest skills one at a time and reports the outcome for each skill.

```sh
skeel update
skeel update --dry-run
```

The human output marks updated skills with `✔`, skills that were already current with `•`, and installed skills that were left unchanged with `→`. When GitHub provenance is available, update output also shows version changes such as `main@oldsha → main@newsha`.
