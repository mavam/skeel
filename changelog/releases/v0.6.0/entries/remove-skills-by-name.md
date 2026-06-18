---
title: Remove skills by name
type: change
authors:
  - mavam
  - claude
  - codex
prs:
  - 2
created: 2026-06-18T07:49:53.950754Z
---

`skeel remove` now accepts a bare skill name. When a name unambiguously identifies a single skill, `skeel remove caveman` deletes it from its source. When multiple sources declare the same skill name, disambiguate with `skeel remove caveman --source <source>`. To remove a whole source, use `skeel remove --source <source>`.
