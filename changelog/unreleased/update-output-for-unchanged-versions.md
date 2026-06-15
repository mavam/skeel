---
title: Update output for unchanged versions
type: change
authors:
  - mavam
  - codex
created: 2026-06-15T05:33:55.216624Z
---

`skeel update` now shows unchanged skill versions only once instead of printing a redundant before-and-after transition.

For example, a skill that is already current now appears as:

```sh
main@688c17e
```

instead of:

```sh
main@688c17e → main@688c17e
```
