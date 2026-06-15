---
title: Parallel skill operations and clearer output
type: change
authors:
  - mavam
  - codex
created: 2026-06-15T05:59:32.112783Z
---

`skeel apply` and `skeel update` now run independent remote skill operations
in parallel while showing live progress for multiple active skills:

```sh
skeel apply
skeel update
```

Large manifests no longer wait for each install or update check to finish
before starting the next one.

Human output now uses a consistent status column, skill-first labels, and a
muted `⌂` suffix for user-scope skills:

```text
✔︎ skill-creator anthropics/skills main@3cf9a8d ⌂
✔︎ tenzir-docs tenzir/skills main@f3842c1
+ wrangler cloudflare/skills
- obsolete-skill installed
```

Completed update rows turn into check-marked results in place. `skeel list`
expands sources declared without a skill list into concrete installed skill
rows instead of showing `*`, and `skeel diff` renders flat install/remove rows.
Updated skills show only the resulting version, while unchanged skills show
their version once.
