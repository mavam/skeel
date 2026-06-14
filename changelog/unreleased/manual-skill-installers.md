---
title: Manual skill installers
type: feature
authors:
  - mavam
created: 2026-06-14T11:00:08.49031Z
---

Manifest sources can now provide custom `install` commands for skills that are not installed through `gh skill`:

```yaml
sources:
  - source: downstairs-dawgs/clacks
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal
      - uvx --from slack-clacks clacks skill --mode claude
```

When `install` is present, skeel treats those commands as the complete install plan for the source. This makes it possible to manage skills with custom installers while still tracking them in the desired-state manifest.
