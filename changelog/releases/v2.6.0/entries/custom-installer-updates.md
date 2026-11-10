---
title: Custom installer updates
type: bugfix
authors:
  - mavam
prs:
  - 31
created: 2026-11-10T08:27:40.135484Z
---

`skeel update` now refreshes skills with custom `install` commands instead of skipping them with a missing GitHub metadata warning:

```sh
skeel update -g rex
```

The installer runs once per target, with the same environment as `apply`. Selecting one skill refreshes the whole custom source. Commands run in order and stop on failure, while unchanged files report `current`.
