---
title: Agent-specific skill targets
type: feature
authors:
  - mavam
created: 2026-08-12T05:40:43.561556Z
---

Skeel can now manage skill directories for specific agents. Pass `--agent`
with any command to target an agent's own skill directory, or `--dir` for an
explicit directory:

```sh
skeel --agent claude-code apply
skeel --agent claude-code -g list
skeel --dir ./custom/skills diff
```

The new `skeel agents` command lists all supported agents with their project
and user skill directories, mirroring the GitHub CLI host registry. For a
named agent, project scope anchors at the enclosing git repository root so
skills land where the agent discovers them. Named agents reconcile project
and user scope independently: when the same skill appears in both, skeel
warns and lets the agent decide runtime precedence instead of skipping a
copy.

JSON output from `list` and `diff` now includes the target `agent` and
`directory`, and `diff` reports `"scope": "custom"` for `--dir` targets.

Custom `install:` commands receive `SKEEL_AGENT`, `SKEEL_SCOPE`,
`SKEEL_SKILLS_DIR`, and `SKEEL_MANIFEST` in their environment. Skeel verifies
that declared skills appear in `SKEEL_SKILLS_DIR` after the installer runs
and fails the step otherwise, so custom installers stay portable across
agents.
