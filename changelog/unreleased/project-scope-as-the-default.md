---
title: Project scope as the default
type: breaking
authors:
  - mavam
  - codex
created: 2026-07-01T17:52:54.57011Z
prs:
  - 13
---

Scope selection now defaults to project scope for every command. Commands that previously operated on project and user scopes by default now require `-a` or `--all` for the same broad behavior.

Before:

```sh
skeel update
```

After:

```sh
skeel update -a
```

Use `-g`, `--user`, `--global`, or `--scope user` to operate only on the user/global scope:

```sh
skeel update -g
```
