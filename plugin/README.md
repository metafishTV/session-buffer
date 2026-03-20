# buffer

Three-layer session memory for Claude Code. Preserves decisions, open threads, concept maps, and working context across sessions.

## How it works

The **sigma trunk** holds your accumulated project knowledge in three layers:

- **Hot** (~200 lines) -- Current session state. Always loaded.
- **Warm** (~500 lines) -- Decisions archive, concept maps. Loaded selectively via pointers.
- **Cold** (~500 lines) -- Historical record. On-demand only.

Each session, you compute the **alpha stash** (what's new since the last handoff) and merge it into the trunk. Content migrates downward (hot -> warm -> cold -> tower) when size bounds are exceeded.

## Install

```
/plugin install buffer
```

Requires Python 3.10+ on PATH (`python3` or `python`). Scripts use stdlib only -- no pip installs.

## Quick start

**End of session:**
```
/buffer:off
```
Choose your handoff mode:
- **Totalize** -- Complete handoff (concept maps, consolidation, full commit)
- **Quicksave** -- Fast checkpoint (~3 tool calls)
- **Targeted** -- Save specific items you name

**Start of session:**
```
/buffer:on
```
Select your project from the list. Context reconstructed automatically.

## Scope: Full vs Lite

First time you run `/buffer:off`, you choose your scope:

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

The plugin maintains a global project registry at `~/.claude/buffer/projects.json`. When you run `/buffer:on`, it presents your projects:

- Resume the most recent project
- Switch to a different project
- Start a new project (Full or Lite)
- Start a standalone lite session

Each project's sigma trunk lives in `<repo>/.claude/buffer/`. Standalone sessions without a repo use `~/.claude/buffer/standalone/<name>/`.

## Remote backup

First-run setup offers to connect a GitHub repo. If enabled, every handoff commit is followed by `git push`. Your accumulated knowledge deserves a backup that lives somewhere safe.

## Football: delegating work to other sessions

The **football** protocol lets a planner session throw tasks to worker sessions (separate Claude Code instances or subagents). Workers catch the football, do the work, and throw it back.

### Single-ball (basic)

```
/buffer:throw     # Planner packs a task and throws
/buffer:catch     # Worker catches, orients, works
/buffer:throw     # Worker returns results
/buffer:catch     # Planner absorbs results into trunk
```

### Multi-ball (parallel workers)

Throw multiple footballs to work on independent tasks in parallel:

```
/buffer:throw     # Planner throws ball 1 → worker A (separate terminal)
/buffer:throw     # Planner throws ball 2 → worker B (subagent)
```

Each ball gets a human-readable ID like `0318-alpha-repair-1`. Workers catch a specific ball or choose from a popup if multiple are in flight.

**Ball states:**
| State | Meaning |
|---|---|
| `in_flight` | Thrown, not yet caught (airborne) |
| `caught` | Worker has it, actively working (on the field) |
| `returned` | Worker threw it back, planner hasn't absorbed yet |
| `absorbed` | Archived, lifecycle complete |

**Target types** — when throwing, choose where the ball goes:
- **instance** — A separate Claude Code terminal window
- **subagent** — A dispatched agent within the same session

### Intercept (recovery from dead workers)

If a worker's context window caps out or you want to redirect a ball:

```bash
python plugin/scripts/buffer_football.py intercept --ball-id 0318-alpha-repair-1
```

Intercept:
1. Reads the dead worker's partial progress from its micro file (if any)
2. Packs that progress onto the ball as `prior_worker_progress`
3. Sets the ball back to `in_flight`
4. A new worker catches it and gets both the original task AND the prior worker's progress

Intercepts chain — a ball can pass through multiple workers, and each worker's partial progress is preserved in an array.

### Multi-ball CLI reference

| Command | What it does |
|---|---|
| `status` | All balls, their states, targets, staleness |
| `pack --side planner --multiball` | Create a new ball (auto-generates ID) |
| `pack --side planner --multiball --target subagent` | New ball targeted at a subagent |
| `catch` | Auto-catch if 1 ball in flight; prompts if multiple |
| `catch --ball-id X` | Catch a specific ball |
| `intercept` | Auto-select if 1 caught ball; prompts if multiple |
| `intercept --ball-id X` | Intercept a specific ball |
| `flag --ball-id X` | Flag items for trunk carry-over on a specific ball |
| `archive --ball-id X` | Archive a completed ball |

### Files (multi-ball)

| File | Purpose |
|---|---|
| `.claude/buffer/football-registry.json` | Ball index (ID → state, target, file path) |
| `.claude/buffer/footballs/{ball-id}.json` | Individual ball payload + worker output |
| `.claude/buffer/football-micro-{ball-id}.json` | Per-ball worker micro-hot-layer |

Multi-ball mode activates when the first `--multiball` throw is made. Legacy single-ball mode (`football.json`) continues to work when no registry exists.

## Alpha bin analysis

When combined with the distill plugin, the alpha bin accumulates structured knowledge (concept entries, convergence web). These commands analyze and operationalize that structure:

| Command | Purpose |
|---|---|
| `alpha-reinforce` | Score concepts by convergence web connectivity + source diversity. Identify primes. |
| `alpha-clusters` | BFS connected components from convergence graph. Hub detection, density metrics. |
| `alpha-neighborhood --id w:N` | Walk-weighted traversal from a concept. Returns connected subgraph with distances. |
| `alpha-health` | Diagnostic report: Youn ratio, prime rankings, cluster density, staleness. |
| `alpha-grid-build` | Build pre-computed relevance grid for O(1) sigma hook lookup. |

## Sigma hook + relevance grid

The **sigma hook** fires on every user message (`UserPromptSubmit`). It extracts keywords and injects relevant concepts:

- **Gate 0c (Grid)**: If a pre-computed relevance grid exists, keywords are matched via O(1) dictionary lookup. ~10ms, ~100 tokens injected.
- **Fallback (IDF)**: If no grid or no match, falls through to existing IDF-weighted scoring against the alpha concept index.

The grid is rebuilt by `alpha-grid-build` (runs automatically after each distillation integration).

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
buffer/
  skills/
    buffer/SKILL.md             Dispatcher (routes to on/off)
    on/SKILL.md                 Rehydration skill (project selector)
    off/SKILL.md                Handoff skill (Totalize/Quicksave/Targeted)
  hooks/hooks.json              Compact hooks + sigma hook (UserPromptSubmit)
  docs/architecture.md          Layer schemas, ID rules, consolidation protocol
  skills/
    throw/SKILL.md              Pack and throw (planner → worker or worker → planner)
    catch/SKILL.md              Catch and orient (detects session type automatically)
    status/SKILL.md             Session health display
  scripts/
    buffer_manager.py           Sigma trunk operations + alpha analysis commands
    buffer_football.py          Football lifecycle (single-ball + multi-ball + intercept)
    sigma_hook.py               Per-message context injection (gates + grid + IDF)
    grid_builder.py             Mesological relevance grid (pre-computed alpha*sigma)
    compact_hook.py             Compaction marker + context injection
    run_python                  Cross-platform Python shim (Unix)
    run_python.bat              Cross-platform Python shim (Windows)
```

## License

MIT
