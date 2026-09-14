---
title: Default agent targets in manifests
type: feature
authors:
  - mavam
created: 2026-09-14T12:01:43.604922Z
---

You can now select default agent targets in a manifest and manage them together:

```yaml
agents:
  - universal
  - claude-code

sources:
  anthropics/skills:
    - skill-creator
```

With this user manifest, `skeel -g apply` and `skeel -g update` manage both
`~/.agents/skills` and `~/.claude/skills`. Inventory commands and manifest edits
with `--apply` use the same targets. An explicit `--agent` or `--dir` overrides
the defaults, and targets sharing a directory are processed only once.
