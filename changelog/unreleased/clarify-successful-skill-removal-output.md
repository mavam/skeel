---
title: Clarify successful skill removal output
type: change
authors:
  - mavam
created: 2026-06-23T08:59:21.304393Z
---

The `remove` command without `--apply` previously rendered manifest edits with
the green success check, which looked identical to `list` output and made it
hard to tell that anything changed. It now uses the red remove glyph, matching
`diff` and `apply`, so a successful removal clearly reads as a deletion.
