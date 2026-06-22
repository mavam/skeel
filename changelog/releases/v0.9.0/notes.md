This release makes skill update output easier to scan by showing active work clearly and finishing with a compact summary. It also keeps user-scope markers next to their skill source across update states.

## 🔧 Changes

### Clearer update summaries

`skeel update` now shows skills only while they are actively updating, then ends with a compact summary:

```sh
skeel update
```

Updated rows use `↑`, skipped rows use `!`, and completed current rows disappear from the normal view. Use `skeel update -v` to keep the full per-skill view, including current rows. User-scope markers now stay next to the skill source, before version transitions or diagnostic notes, including while skills are actively updating. When every skill is already current, the command prints only the summary count.

*By @mavam and @codex in #8.*
