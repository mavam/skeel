This release makes skill removal more convenient by allowing `skeel remove` to target an unambiguous skill name directly. It also keeps source-level removal available through the explicit `--source` option.

## 🔧 Changes

### Remove skills by name

`skeel remove` now accepts a bare skill name. When a name unambiguously identifies a single skill, `skeel remove caveman` deletes it from its source. When multiple sources declare the same skill name, disambiguate with `skeel remove caveman --source <source>`. To remove a whole source, use `skeel remove --source <source>`.

*By @mavam, @claude, and @codex in #2.*
