This release improves day-to-day CLI feedback with a new version flag and clearer apply output. It also validates the installed GitHub CLI version before reading skills, so users get an actionable upgrade message when needed.

## 🚀 Features

### Version flag

The CLI now supports `skeel --version` to print the installed package version and exit successfully.

*By @mavam.*

## 🐞 Bug fixes

### Diff-style apply output

`skeel apply` now uses diff-style markers to show the direction of each change:

```sh
+ openclaw/openclaw@openhue
- find-skills
```

Installs use a green `+`, while removals use a red `-`, making it clear which skills are added and which are removed.

*By @mavam and @codex.*

### GitHub CLI version check

Skeel now checks the installed GitHub CLI version before reading installed skills and reports a clear upgrade message when `gh` is older than 2.94.0.

*By @mavam.*
