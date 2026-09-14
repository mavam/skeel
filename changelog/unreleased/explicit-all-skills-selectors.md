---
title: Explicit all-skills selectors
type: feature
authors:
  - mavam
prs:
  - 28
created: 2026-09-14T13:24:26.131489Z
---

You can now write `all` explicitly to install every skill from a source instead of leaving its value empty:

```yaml
sources:
  mavam/quarto-brief: all
  mavam/skills:
    pin: main
    skills: all
```

The CLI writes explicit selectors when you add or select an entire source. Existing empty values and options mappings without `skills` remain supported. Lists still select individual skills, so `[all]` selects a skill named `all`.
