---
title: Reliable agent applies over symlinked skills
type: bugfix
authors:
  - mavam
prs:
  - 22
created: 2026-08-12T14:50:13.327018Z
---

Agent-specific applies now replace existing symlinked skills without failing or altering the symlink destination. For example, a Claude Code user target populated with links to universal skills can be reconciled normally:

```sh
uvx skeel --agent claude-code apply -g
```
