---
title: Install-all source discovery during updates
type: feature
authors:
  - mavam
  - codex
prs:
  - 19
  - 20
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

Updates of pinned install-all sources also prune skills removed upstream. Skeel only removes a directory when its `github-repo` matches the source exactly and its `github-path` is absent upstream, leaving metadata-less, malformed, and differently owned directories untouched. Dry runs preview each removal.
