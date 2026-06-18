This release improves skill manifest management by making default removals cover both project and user scopes. It also clarifies missing skill errors during archive-based updates so users can identify the manifest source that failed.

## 🔧 Changes

### Remove skills from user scope by default

`skeel remove` now searches both project and user manifests when no explicit `--scope` or `--manifest` is set, so globally managed skills in `~/.agents/skills.yaml` are covered by the default command. If a target exists in multiple scopes, skeel asks for `--scope project` or `--scope user`.

*By @mavam and @codex in #3.*

## 🐞 Bug fixes

### Clarify missing skill update errors

Missing skills during archive-based updates now report the manifest source, such as `example/skills`, instead of repeating the requested skill selector.

*By @mavam and @codex in #3.*
