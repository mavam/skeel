---
title: Default manifest at ~/.agents/skills.yaml
type: change
authors:
  - mavam
created: 2026-06-14T11:54:48.661443Z
---

The default manifest path is now `~/.agents/skills.yaml` instead of `~/.agents/.skill.yaml`.

```sh
skeel path
```

Use `--manifest` or `SKEEL_MANIFEST` to point at an existing manifest during migration.
