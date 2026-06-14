---
title: Compact GitHub source syntax
type: feature
authors:
  - mavam
created: 2026-06-14T11:54:35.84609Z
---

Manifests can now use compact GitHub source entries for common cases:

```yaml
sources:
  - tenzir/skills@tenzir-docs
  - mavam/quarto-brief
  - github: mattpocock/skills
    skills:
      - grill-me
```

Use `owner/repo@skill` for one skill, a bare `owner/repo` to install all skills from that repository, or `github:` when a source needs a full mapping such as multiple `skills`.
