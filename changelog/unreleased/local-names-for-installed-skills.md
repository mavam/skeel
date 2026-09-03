---
title: Local names for installed skills
type: feature
authors:
  - mavam
created: 2026-09-03T18:56:47.928325Z
---

You can now install an explicitly selected skill under a different local name by combining the manifest's `spec` and `name` fields or by passing `--name` to `skeel add`:

```sh
skeel -g add elevenlabs/skills agents --name elevenlabs-agents
```

Skeel keeps the directory and `SKILL.md` name aligned, retains the upstream identity for updates, and migrates an existing matching installation in place.
