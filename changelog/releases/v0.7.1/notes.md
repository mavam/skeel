This release stabilizes the interactive update progress display. Long-running update steps now finish with a single final status list instead of duplicate completed rows.

## 🐞 Bug fixes

### Stable live progress output for updates

`skeel update` no longer leaves duplicate completed rows in interactive terminals when one update step runs for a long time.

For example:

```sh
uvx skeel update
```

The command still runs each update once; the live progress display now finishes with a single final status list.

*By @mavam and @codex.*
