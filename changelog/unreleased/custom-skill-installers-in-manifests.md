---
title: Custom skill installers in manifests
type: feature
authors:
  - mavam
created: 2026-06-14T20:19:59.799607Z
---

Manifest sources can now define custom install commands for skills that are not installed through `gh skill`:

```yaml
sources:
  slack-clacks/clacks:
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal --force
```

When `install` is present, skeel treats those commands as the complete install command set for the source. This keeps non-GitHub skill installers in the same desired-state manifest as regular `gh skill` sources.
