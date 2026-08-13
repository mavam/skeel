---
title: Idempotent reconciliation of linked agent skills
type: bugfix
authors:
  - mavam
prs:
  - 23
created: 2026-08-13T07:17:34.852454Z
---

Agent-specific reconciliation now recognizes skill-directory symlinks as installed. Commands such as

```sh
skeel -g apply --agent claude-code --prune
```

therefore remain idempotent when agent skills link to the universal skill directory. Pruning an undeclared linked skill removes only the link and preserves its destination.
