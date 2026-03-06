# session-buffer

Three-layer session memory for Claude Code. Preserves decisions, open threads, concept maps, and working context across sessions.

## How it works

The **sigma trunk** holds your accumulated project knowledge in three layers:

- **Hot** (~200 lines) -- Current session state. Always loaded.
- **Warm** (~500 lines) -- Decisions archive, concept maps. Loaded selectively via pointers.
- **Cold** (~500 lines) -- Historical record. On-demand only.

Each session, you compute the **alpha stash** (what's new since the last handoff) and merge it into the trunk. Content migrates downward (hot -> warm -> cold -> tower) when size bounds are exceeded.

## Install

```
/plugin install session-buffer
```

Requires Python 3.10+ on PATH (`python3` or `python`). Scripts use stdlib only -- no pip installs.

## Quick start

**End of session:**
```
/session-buffer:off
```
Choose your handoff mode:
- **Totalize** -- Complete handoff (concept maps, consolidation, full commit)
- **Quicksave** -- Fast checkpoint (~3 tool calls)
- **Targeted** -- Save specific items you name

**Start of session:**
```
/session-buffer:on
```
Select your project from the list. Context reconstructed automatically.

## Scope: Full vs Lite

First time you run `/session-buffer:off`, you choose your scope:

| | Full | Lite |
|---|---|---|
| Decisions, threads, instance notes | yes | yes |
| Concept maps, convergence webs | yes | no |
| Conservation (hot -> warm -> cold) | yes | no |
| Tower archival | yes | no |
| MEMORY.md sync | yes | optional |

- **Full** -- For research projects, multi-source analysis, deep domain work.
- **Lite** -- For everyday development, quick projects, session continuity without research infrastructure.

Upgrade from Lite to Full anytime. No data loss.

## Multi-project support

The plugin maintains a global project registry at `~/.claude/buffer/projects.json`. When you run `/session-buffer:on`, it presents your projects:

- Resume the most recent project
- Switch to a different project
- Start a new project (Full or Lite)
- Start a standalone lite session

Each project's sigma trunk lives in `<repo>/.claude/buffer/`. Standalone sessions without a repo use `~/.claude/buffer/standalone/<name>/`.

## Remote backup

First-run setup offers to connect a GitHub repo. If enabled, every handoff commit is followed by `git push`. Your accumulated knowledge deserves a backup that lives somewhere safe.

## Compact hooks

The plugin includes automatic context preservation hooks. When Claude Code compacts your conversation (to manage context length), the hooks:

1. **Before compaction**: Save current hot layer state + write a marker
2. **After compaction**: Inject sigma trunk summary into AI context

This happens invisibly. The AI gets full orientation recovery after compaction. You never need to configure or think about it.

## Project overrides

For project-specific customization, create `<repo>/.claude/skills/buffer/off.md`. This overrides the plugin's generic handoff skill for that repo.

Use overrides to define:
- Concept map groups specific to your domain
- Custom terminology and orientation templates
- Warm-max threshold adjustments
- Mode defaults

## Files

| File | Purpose |
|---|---|
| `.claude/buffer/handoff.json` | Hot layer (current session state) |
| `.claude/buffer/handoff-warm.json` | Warm layer (concept maps, decisions archive) |
| `.claude/buffer/handoff-cold.json` | Cold layer (historical record) |
| `.claude/buffer/handoff-tower-NNN-*.json` | Sealed archive (user-approved) |
| `~/.claude/buffer/projects.json` | Global project registry |

## Plugin contents

```
session-buffer/
  .claude-plugin/plugin.json    Plugin manifest
  skills/
    buffer/SKILL.md             Architecture reference
    buffer-off/SKILL.md         Handoff skill (Totalize/Quicksave/Targeted)
    buffer-on/SKILL.md          Rehydration skill (project selector)
  hooks/hooks.json              Compact hooks (PreCompact + SessionStart)
  scripts/
    buffer_manager.py           Sigma trunk operations
    compact_hook.py             Compaction marker + context injection
    run_python                  Cross-platform Python shim (Unix)
    run_python.bat              Cross-platform Python shim (Windows)
```

## License

MIT
