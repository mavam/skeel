Skeel now lets you customize frontmatter for explicitly selected skills directly in the manifest. It applies and reconciles these overrides during installation and updates, and reports unapplied values in diff output.

## 🚀 Features

### Skill frontmatter overrides

You can now customize an explicitly selected skill's frontmatter in the manifest. Skeel applies configured fields during installation and updates, and reconciles later drift:

```yaml
sources:
  owner/skills:
    skills:
      - name: deploy
        frontmatter:
          compatibility: Requires Docker
          disable-model-invocation: true
```

Top-level values replace their upstream counterparts, while `metadata` entries merge with existing metadata. The `diff` command reports configured values that haven't been applied yet.

*By @mavam in #24.*
