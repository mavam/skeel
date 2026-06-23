---
title: Clarify successful skill removal output
type: change
authors:
  - mavam
prs:
  - 11
created: 2026-06-23T08:59:21.304393Z
---

The `add` and `remove` commands without `--apply` previously rendered manifest
edits with the green success check, which looked identical to `list` output and
made it hard to tell that anything changed. They now use the install (`+`) and
remove (`-`) glyphs, matching `diff` and `apply`, so a successful add or removal
clearly reads as a change.
