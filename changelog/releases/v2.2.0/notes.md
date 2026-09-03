This release lets you install selected skills under custom local names while preserving their upstream identity. Existing matching installations migrate in place, keeping local directories and skill metadata aligned.

## 🚀 Features

### Local names for installed skills

You can now install an explicitly selected skill under a different local name by combining the manifest's `spec` and `name` fields or by passing `--name` to `skeel add`:

```sh
skeel -g add elevenlabs/skills agents --name elevenlabs-agents
```

Skeel keeps the directory and `SKILL.md` name aligned, retains the upstream identity for updates, and migrates an existing matching installation in place.

*By @mavam in #25.*
