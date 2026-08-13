Skeel now keeps agent-specific reconciliation idempotent when skills link to the universal skill directory. It safely prunes undeclared linked skills without touching their destinations.

## 🐞 Bug fixes

### Idempotent reconciliation of linked agent skills

Agent-specific reconciliation now recognizes skill-directory symlinks as installed. Commands such as

```sh
skeel -g apply --agent claude-code --prune
```

therefore remain idempotent when agent skills link to the universal skill directory. Pruning an undeclared linked skill removes only the link and preserves its destination.

*By @mavam in #23.*
