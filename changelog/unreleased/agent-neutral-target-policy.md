---
title: CLI-controlled install targets
type: change
authors:
  - mavam
created: 2026-06-14T11:54:43.920441Z
---

Shared manifests no longer need to choose an agent or install directory. Backend-managed installs now delegate placement to `gh skill`, defaulting to `.agents/skills` in the current repository:

```sh
skeel apply
```

which runs backend installs with:

```sh
gh skill install <repo> <skill> --dir .agents/skills --force
```

Use `-g` for global installs into `~/.agents/skills`, or pass an explicit `--agent` when a run should delegate placement to a backend agent:

```sh
skeel -g apply
skeel --agent claude-code --scope user apply
```

For the default target, `skeel diff` compares project scope against `.agents/skills` in the current repository and global scope against `~/.agents/skills`, using the same `gh skill --dir` target as installs.

This keeps team manifests independent of each user’s preferred agent and removes built-in Claude-specific symlink handling.
