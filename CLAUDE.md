# Session Buffer Plugin

## Version Bump Checklist

When bumping the plugin version in `plugin/.claude-plugin/plugin.json`:

1. **`plugin/.claude-plugin/plugin.json`** — canonical source of truth for version
2. **`plugin/skills/on/SKILL.md`** Step 8 — update the `buffer vX.Y.Z` string in the confirmation output template
3. **`.claude-plugin/marketplace.json`** — update the buffer version in `plugins[0].version` and `metadata.lastUpdated`
4. **`CHANGELOG.md`** — add a new section for the version
