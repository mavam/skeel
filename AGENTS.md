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

## Releasing

- Use `tenzir-ship` for release engineering
- Add changelog entries for user facing changes
- Before releasing, ensure `main` is in sync with `origin/main`
- To release, dispatch .github/workflows/release.yaml with a title & intro
