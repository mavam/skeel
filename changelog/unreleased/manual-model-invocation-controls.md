---
title: Manual model invocation controls
type: feature
authors:
  - mavam
prs:
  - 24
created: 2026-08-26T05:10:33.92072Z
---

You can now make an explicitly selected skill manual-only with the canonical `disable-model-invocation` field. Skeel applies the setting during installation and updates, and reconciles later drift:

```yaml
sources:
  owner/skills:
    skills:
      - name: deploy
        disable-model-invocation: true
```

This keeps the skill user-invocable without allowing Claude Code to load it automatically. The `diff` command reports configured values that haven't been applied yet.
