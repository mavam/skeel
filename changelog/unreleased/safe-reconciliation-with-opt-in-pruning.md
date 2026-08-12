---
title: Safe reconciliation with opt-in pruning
type: breaking
authors:
  - mavam
prs:
  - 21
created: 2026-08-12T05:40:32.78477Z
---

`skeel apply` now preserves installed skills that the manifest does not
declare. Pass `--prune` to restore the previous behavior of removing
undeclared extras; `apply --dry-run --prune` previews the removals first.

`skeel remove <skill> --apply` now deletes exactly the deselected skill
instead of pruning every undeclared skill in the target, so hand-authored
and built-in agent skills survive a targeted removal. Whole custom sources
remove each skill they declared. `--prune` is rejected with selective apply or
`--reinstall` instead of being silently ignored.

Deletion also gained execution-time safety guards: skeel verifies that the
planned target and skill directories have not been replaced, refuses symlinked
directories, paths outside the resolved target, the target root itself, and
directories without a regular `SKILL.md`. Pruning of skills removed upstream
from pinned install-all sources is managed-source drift and remains always-on
during `update`.
