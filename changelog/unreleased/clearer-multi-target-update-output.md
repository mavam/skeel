---
title: Clearer multi-target update output
type: change
authors:
  - mavam
created: 2026-11-10T08:27:40.852166Z
---

Updates across multiple installation directories now collapse identical results into one row with muted target names instead of repeating the same skill. For example, `skeel update -g` with universal and Claude Code targets can show:

```text
↑ ⌂ rex  custom installer  universal, claude-code
```

A compact legend maps target names to directories. Aligned skill, source, status, and target columns replace ragged labels. Bold skill names, cyan sources, status colors, and muted targets establish a visual hierarchy without brackets or middle-dot separators. Different outcomes and failures remain separate. Narrow terminals stack secondary fields, and the output remains readable without color.

Pinned skills now use a neutral `=` marker rather than a warning. A single summary line counts every operation and distinguishes intentional pinned skips from other skipped updates, for example: `38 operations across 2 targets: 32 current, 6 pinned`.

Execution progress and apply results also identify the target. JSON retains separate execution steps with `directory` and, for known agents, `agent`.
