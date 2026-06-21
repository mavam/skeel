---
title: Scope indicator across all commands
type: change
authors:
  - mavam
  - claude
prs:
  - 6
created: 2026-06-21T20:08:26.109719Z
---

`skeel` now shows the `⌂` user-scope indicator in every command that can span both the project and user manifests — `list`, `update`, `apply`, `remove`, and `diff` — so you can always tell which scope a skill belongs to:

```sh
skeel diff
+ tenzir-docs tenzir/skills
+ wrangler cloudflare/skills ⌂
```

The `diff` JSON output gains a matching `scope` field on every entry.
