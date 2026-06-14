---
title: Simpler manifest options
type: change
authors:
  - mavam
created: 2026-06-14T11:54:54.28214Z
---

The manifest format no longer exposes `allow_hidden_dirs`. Standard GitHub installs use normal `gh skill` discovery, and sources that need custom behavior can use explicit `install` commands instead:

```yaml
sources:
  - skills:
      - custom-skill
    install:
      - custom installer command
```

This keeps the declarative schema focused on the common source and skill selection cases.
