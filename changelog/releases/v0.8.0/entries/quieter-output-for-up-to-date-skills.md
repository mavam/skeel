---
title: Quieter output for up-to-date skills
type: change
authors:
  - mavam
  - claude
prs:
  - 6
created: 2026-06-21T20:08:29.580065Z
---

`skeel update` no longer repeats the version label for skills that are already up to date. Unchanged skills render without version noise, so the output highlights only what actually changed.
