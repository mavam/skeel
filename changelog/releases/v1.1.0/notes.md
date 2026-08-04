Skeel now refreshes install-all sources during updates, discovers newly added skills, and safely prunes skills removed upstream. It preserves targeted updates and protects directories with missing or mismatched ownership metadata.

## 🚀 Features

### Install-all source discovery during updates

`skeel update` now refreshes each install-all source once and discovers skills added upstream since the previous install:

```yaml
sources:
  mavam/skills:
    pin: main
```

```sh
skeel -g update
```

Explicit skill entries continue to update independently, and a source-and-skill selector remains targeted to that skill. Immutable tag and commit pins report `current` when their content is unchanged.

Updates of pinned install-all sources also prune skills removed upstream. Skeel only removes a directory when its `github-repo` matches the source exactly and its `github-path` is absent upstream, leaving metadata-less, malformed, and differently owned directories untouched. Dry runs preview each removal.

*By @mavam and @codex in #19 and #20.*
