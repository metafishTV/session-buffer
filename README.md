# session-buffer

Three-layer session memory for Claude Code. Preserves decisions, open threads, concept maps, and working context across sessions.

## Install

```
/plugin marketplace add metafishTV/session-buffer
/plugin install session-buffer@session-buffer-marketplace
```

Or add via the Claude app using the git URL: `https://github.com/metafishTV/session-buffer.git`

## How it works

The **sigma trunk** holds your accumulated project knowledge in three layers:

- **Hot** (~200 lines) -- Current session state. Always loaded.
- **Warm** (~500 lines) -- Decisions archive, concept maps. Loaded selectively via pointers.
- **Cold** (~500 lines) -- Historical record. On-demand only.

Each session, you compute the **alpha stash** (what's new since the last handoff) and merge it into the trunk. Content migrates downward (hot -> warm -> cold -> tower) when size bounds are exceeded.

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

Upgrade from Lite to Full anytime. No data loss.

## Remote backup

First-run setup offers to connect a GitHub repo for automatic backup on every handoff.

## Compact hooks

Includes automatic context preservation hooks. When Claude Code compacts your conversation, the hooks save hot-layer state before compaction and inject sigma trunk recovery after.

## Requires

Python 3.10+ on PATH (`python3` or `python`). Scripts use stdlib only -- no pip installs.

## License

MIT
