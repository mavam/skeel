---
title: Remove skills from user scope by default
type: change
authors:
  - mavam
  - codex
prs:
  - 3
created: 2026-06-18T00:00:00Z
---

`skeel remove` now searches both project and user manifests when no explicit `--scope` or `--manifest` is set, so globally managed skills in `~/.agents/skills.yaml` are covered by the default command. If a target exists in multiple scopes, skeel asks for `--scope project` or `--scope user`.
