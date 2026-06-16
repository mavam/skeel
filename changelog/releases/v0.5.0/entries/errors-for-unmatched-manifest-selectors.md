---
title: Errors for unmatched manifest selectors
type: change
authors:
  - mavam
  - codex
prs:
  - 1
created: 2026-06-16T09:43:28.12171Z
---

Commands that take a manifest selector now fail when the requested source or
skill is not declared in the manifest:

```sh
skeel apply tenzir/skills typo
skeel remove unknown/source
```

This affects `apply`, `update`, and `remove`, making typos fail clearly instead
of silently succeeding with no changes.
