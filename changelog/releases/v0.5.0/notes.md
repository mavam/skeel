Skeel now lets you update a specific manifest source or skill. Manifest-scoped commands also fail clearly when a selector does not match any declared source or skill.

## 🚀 Features

### Selective skill updates

The `update` command can now be scoped to a manifest source or a single skill:

```sh
skeel update tenzir/skills
skeel update tenzir/skills tenzir-docs
```

*By @mavam and @codex in #1.*

## 🔧 Changes

### Errors for unmatched manifest selectors

Commands that take a manifest selector now fail when the requested source or skill is not declared in the manifest:

```sh
skeel apply tenzir/skills typo
skeel remove unknown/source
```

This affects `apply`, `update`, and `remove`, making typos fail clearly instead of silently succeeding with no changes.

*By @mavam and @codex in #1.*
