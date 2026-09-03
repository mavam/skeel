---
title: Local names for installed skills
type: feature
authors:
  - mavam
prs:
  - 25
created: 2026-09-03T19:11:10.503807Z
---

You can now install an explicitly selected skill under a different local name by combining the manifest's `spec` and `name` fields or by passing `--name` to `skeel add`:

```sh
skeel -g add elevenlabs/skills agents --name elevenlabs-agents
```

Skeel keeps the directory and `SKILL.md` name aligned, retains the upstream identity for updates, and migrates an existing matching installation in place.
