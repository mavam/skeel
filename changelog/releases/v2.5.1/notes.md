Skeel now preserves declared skills with custom local names during pruning. Renamed skills such as elevenlabs-agents no longer appear as extras or get deleted by apply --prune.

## 🐞 Bug fixes

### Safe pruning of renamed skills

`skeel apply --prune` now preserves declared skills installed under a different local name, such as `elevenlabs-agents` from the upstream `agents` skill. Previously, these skills could appear as extras in `skeel diff` and be deleted during pruning.

*By @mavam in #29.*
