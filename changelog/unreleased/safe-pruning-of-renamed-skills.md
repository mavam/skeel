---
title: Safe pruning of renamed skills
type: bugfix
authors:
  - mavam
prs:
  - 29
created: 2026-09-25T05:47:10.107992Z
---

`skeel apply --prune` now preserves declared skills installed under a different local name, such as `elevenlabs-agents` from the upstream `agents` skill. Previously, these skills could appear as extras in `skeel diff` and be deleted during pruning.
