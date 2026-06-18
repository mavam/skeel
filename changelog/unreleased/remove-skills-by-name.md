---
title: Remove skills by name
type: change
authors:
  - mavam
  - claude
created: 2026-06-18T07:49:53.950754Z
---

`skeel remove` now accepts a bare skill name, not just a source. When a name unambiguously identifies a single skill, `skeel remove caveman` deletes it from its source. The command only fails when the name is ambiguous (declared in multiple sources), in which case it asks you to disambiguate with `skeel remove <source> <skill>`. Source names (owner/repo) continue to work as before.
