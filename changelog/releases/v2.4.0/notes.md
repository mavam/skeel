Configure default agents in your manifest to apply and update skills across multiple agent directories with one command. Explicit target overrides and shared-directory deduplication keep reconciliation predictable.

## 🚀 Features

### Default agent targets in manifests

You can now select default agent targets in a manifest and manage them together:

```yaml
agents:
  - universal
  - claude-code

sources:
  anthropics/skills:
    - skill-creator
```

With this user manifest, `skeel -g apply` and `skeel -g update` manage both `~/.agents/skills` and `~/.claude/skills`. Inventory commands and manifest edits with `--apply` use the same targets. An explicit `--agent` or `--dir` overrides the defaults, and targets sharing a directory are processed only once.

*By @mavam in #27.*
