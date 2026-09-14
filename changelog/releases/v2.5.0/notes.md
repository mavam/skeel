You can now select every skill from a source with an explicit all selector, including alongside pinned revisions. Existing manifests remain compatible, and the CLI writes the clearer syntax for whole-source additions.

## 🚀 Features

### Explicit all-skills selectors

You can now write `all` explicitly to install every skill from a source instead of leaving its value empty:

```yaml
sources:
  mavam/quarto-brief: all
  mavam/skills:
    pin: main
    skills: all
```

The CLI writes explicit selectors when you add or select an entire source. Existing empty values and options mappings without `skills` remain supported. Lists still select individual skills, so `[all]` selects a skill named `all`.

*By @mavam in #28.*
