---
title: Stable live progress output for updates
type: bugfix
authors:
  - mavam
  - codex
created: 2026-06-21T08:25:30.002733Z
---

`skeel update` no longer leaves duplicate completed rows in interactive terminals when one update step runs for a long time.

For example:

```sh
uvx skeel update
```

The command still runs each update once; the live progress display now finishes with a single final status list.
