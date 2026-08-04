---
title: Install-all source discovery during updates
type: feature
authors:
  - mavam
  - codex
prs:
  - 19
created: 2026-08-04T06:31:13.925907Z
---

`skeel update` now refreshes each install-all source once and discovers skills added upstream since the previous install:

```yaml
sources:
  mavam/skills:
    pin: main
```

```sh
skeel -g update
```

Explicit skill entries continue to update independently, and a source-and-skill selector remains targeted to that skill. Immutable tag and commit pins report `current` when their content is unchanged.
