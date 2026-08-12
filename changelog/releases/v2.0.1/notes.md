Skeel now reconciles agent-specific skill directories that contain symlinks to universal skills. Applying Claude Code user skills replaces each symlink safely without changing its destination.

## 🐞 Bug fixes

### Reliable agent applies over symlinked skills

Agent-specific applies now replace existing symlinked skills without failing or altering the symlink destination. For example, a Claude Code user target populated with links to universal skills can be reconciled normally:

```sh
uvx skeel --agent claude-code apply -g
```

*By @mavam in #22.*
