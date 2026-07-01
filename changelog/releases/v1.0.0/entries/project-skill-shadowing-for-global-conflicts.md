---
title: Project skill shadowing for global conflicts
type: bugfix
authors:
  - mavam
  - codex
created: 2026-07-01T19:46:30.799135Z
prs:
  - 15
---

Project-scoped skills now take precedence over user/global skills with the same name when both scopes are selected:

```sh
skeel apply -a
```

When a conflict occurs, `skeel` warns that the user/global skill was skipped and continues with the project-local skill. JSON output includes a `warnings` array so automation can see the same shadowing decision without parsing stderr.
