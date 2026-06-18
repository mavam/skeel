---
title: Clarify missing skill update errors
type: bugfix
authors:
  - mavam
  - codex
prs:
  - 3
created: 2026-06-18T00:00:00Z
---

Missing skills during archive-based updates now report the manifest source, such as `example/skills`, instead of repeating the requested skill selector.
