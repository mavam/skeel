---
title: Desired-state editing and JSON output
type: feature
authors:
  - mavam
created: 2026-06-14T20:20:00.575876Z
---

The CLI can now inspect and edit desired state directly.

```sh
skeel list
skeel add tenzir/skills tenzir-docs@main
skeel remove tenzir/skills tenzir-docs
skeel add mavam/quarto-brief --apply
```

`skeel list` shows each manifest skill and whether it is installed. `skeel add` upserts a source or skill into the manifest, and `skeel remove` removes a skill or the whole source. Passing `--apply` to either editing command reconciles installed skills immediately after saving the manifest.

Use `--json` with `list`, `diff`, `apply`, `add`, `remove`, and `update` to get one machine-readable JSON object on stdout for scripts and automation.
