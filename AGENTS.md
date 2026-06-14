# skeel

`skeel` is a Python 3.14 CLI for declarative agent skill management. It reads a
YAML desired-state manifest and applies it through backends, such as `gh skill`.

## Repository Layout

- `.github/workflows/` — CI and release/publish workflows
- `changelog/` — release notes managed via `tenzir-ship`
- `examples/` — example manifests
- `src/skeel/` — package source (`cli.py`, `manifest.py`, `backends.py`)
- `tests/` — pytest suite

## Setup

Install Lefthook once per clone:

```bash
uvx lefthook install
```

Pushing runs the pre-push quality gate automatically.
