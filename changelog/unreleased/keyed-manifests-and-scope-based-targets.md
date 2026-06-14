---
title: Keyed manifests and scope-based targets
type: change
authors:
  - mavam
created: 2026-06-14T20:19:59.092769Z
---

The manifest format now uses source names as YAML keys and chooses install targets from CLI scope instead of manifest fields.

Before:

```yaml
shared_dir: ~/.agents/skills
agents:
  - claude-code
sources:
  - source: tenzir/skills
    skills:
      - tenzir-docs
```

After:

```yaml
sources:
  tenzir/skills:
    - tenzir-docs
  mavam/quarto-brief:
```

A list selects specific skills, an empty value installs all skills from that source, and a nested mapping is used for options such as `pin` and `install`. The previous list-of-source-objects shape and manifest-level target options such as `shared_dir`, `agents`, and `allow_hidden_dirs` are no longer supported.

Scope now determines both the implicit manifest path and the managed skill directory: project scope uses `.agents/skills.yaml` and `.agents/skills` in the current working directory, while user scope uses `~/.agents/skills.yaml` and `~/.agents/skills`.
