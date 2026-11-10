---
title: Clearer multi-target update output
type: change
authors:
  - mavam
prs:
  - 31
created: 2026-11-10T08:27:40.852166Z
---

Updates across multiple installation directories now collapse identical results into one row with muted target names instead of repeating the same skill. For example, `skeel update -g` with universal and Claude Code targets can show:

```text
↑ ⌂ rex  custom installer  universal, claude-code
```

Output identifies the agents receiving each update without repeating installation paths or printing a directory legend. Aligned skill, source, status, and agent columns replace ragged labels. Scope glyphs distinguish project and user installs of the same agent; custom `--dir` targets still show their path. Bold skill names, cyan sources, status colors, and muted targets establish a visual hierarchy without brackets or middle-dot separators. Different outcomes and failures remain separate. Narrow terminals stack secondary fields, and the output remains readable without color.

Pinned skills now use a neutral `=` marker rather than a warning. A single summary line counts every operation and distinguishes intentional pinned skips from other skipped updates, for example: `38 operations: 32 current, 6 pinned  universal, claude-code`.

Execution progress and apply results also identify the agent. JSON retains separate execution steps with `directory` and, for known agents, `agent`.
