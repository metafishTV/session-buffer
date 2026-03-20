---
name: off
description: Write session handoff to sigma trunk. Run at session end or when context is getting full.
---

# Session Handoff

**Architecture reference**: For sigma trunk layer schemas, size constraints, ID rules, and the consolidation protocol, read `docs/architecture.md` in the plugin directory (only when you need schema details for validation or writing).

## Instance Primer

You are running `/buffer:off`. Extract every decision, open thread, concept
mapping, and unresolved question from this session. Nothing implicit survives
the handoff — if it matters, it's in the alpha stash or it's gone.

**Key principles**:
- The warm layer should get **denser** each session, not just longer. Consolidate:
  compress descriptions using established vocabulary, merge overlapping entries.
- `suggest: null` is preferred. Don't invent mappings to fill fields.
- Instance notes are colleague-to-colleague. Be honest — flag confusion, forced
  mappings, things that surprised you.
- If a project skill exists, it overrides this file entirely.

**What you produce**: `handoff.json` (hot), `handoff-warm.json` (warm), `handoff-cold.json` (cold) in `.claude/buffer/`, plus updates to `alpha/` if concept map entries changed, plus a git commit.

**ENFORCEMENT RULE — applies to every step below**: Any step that requires user input MUST use the `AskUserQuestion` tool. Do NOT substitute plain text questions, do NOT infer the user's answer from context, and do NOT skip the question because the answer seems obvious. You MUST call `AskUserQuestion`, you MUST wait for the response, and you MUST NOT continue past that step until the user has answered. Steps requiring `AskUserQuestion` are marked with **⚠ MANDATORY POPUP**.

## Script Tooling

**`scripts/buffer_manager.py`** handles the plumbing (JSON merge, ID assignment, conservation, sync). You produce the content; the script handles the mechanics.

**Primary**: `handoff --buffer-dir DIR --input changes.json --warm-max N --memory-path PATH --project-name NAME` — Chains update + migrate + sync in one call. Preferred workflow.

**Standalone** (debugging only): `update`, `migrate`, `validate`, `sync`, `next-id` — see script `--help`.

> **Full + Alpha mode**: If `buffer_mode` is `"full"` AND `alpha/` exists, also read `skills/off/full-ref.md` for alpha tooling, concept map validation (Step 6), consolidation (Step 6b), MEMORY.md sync (Step 11), grid rebuild (Step 14b), and resolution check (Step 14c).

### Workflow (target: ~5 tool calls after cognitive steps)

1. Read hot layer (1 call) + gather git metadata (1 parallel call)
2. Compose `_changes.json` in `.claude/buffer/` (1 Write call)
3. Run `handoff` pipeline (1 Bash call)
4. Commit (1 Bash call)

### changes.json schema

The alpha stash — crystallized session learnings ready for merge. Omit sections with no changes.

```json
{
  "session_meta": { "date", "commit", "branch", "files_modified": [], "tests" },
  "active_work": { "current_phase", "completed_this_session": [], "in_progress", "blocked_by", "next_action" },
  "new_decisions": [ { "what", "chose", "why" } ],
  "open_threads": [ { "thread", "status", "ref?" } ],
  "instance_notes": { "from", "to", "dialogue_style", "remarks": [], "open_questions": [] },
  "natural_summary": "2-3 plain-language sentences.",
  "concept_map_changes": [ "..." ],   // Full + Alpha only — see full-ref.md
  "convergence_web_changes": [ "..." ], // Full + Alpha only — see full-ref.md
  "validation_log_entries": [ "..." ]   // Full + Alpha only — see full-ref.md
}
```

---

## Mode Selection (FIRST)

**⚠ MANDATORY POPUP**: You MUST call `AskUserQuestion` before proceeding. Do NOT default to Totalize. Do NOT infer the mode from context. The user chooses.

Options:
- **Totalize** — Complete end-of-session handoff (all steps below)
- **Quicksave** — Fast sigma trunk checkpoint (~3 tool calls)
- **Targeted** — Save specific items the user names (~4 tool calls)

**Wait for the user's response before doing anything else.** Then follow the selected mode. All modes begin with the **Shared Preamble**.

## Shared Preamble (all modes)

**Read-first ordering** — scan existing sigma trunk before dialogue to prevent duplication:

1. Read hot + warm + cold layers (parallel if possible)
2. Scan dialogue for new content
3. Compute the **alpha stash**: items from this session NOT already captured in any layer

After preamble, branch by mode:
- **Totalize** → continue to Step 0 below
- **Quicksave** → jump to "Quicksave Mode" at end of file
- **Targeted** → jump to "Targeted Mode" at end of file

---

## First-Run Detection

If `.claude/buffer/handoff.json` does not exist, this is a first-run. Run the same first-run setup as `/buffer:on` Step 0d (returning user check, scope selection, remote backup, initialization, registry, MEMORY.md integration). Then return to Mode Selection above.

---

## Step 0: Check for Project Skill + In-Flight Football

Before proceeding:

1. Check if `<repo>/.claude/skills/buffer/off.md` exists. **If it exists**: read and follow it instead. Stop processing this file.

2. Read `.claude/buffer/handoff.json`. If `football_in_flight == true`:
   **⚠ MANDATORY POPUP**: "A football is in flight. Saving now means the worker's return throw will need to be caught in a new session. Wait for /buffer:catch, or save anyway?" If wait → STOP. If save → continue.

---

## Parallel Batch 1: Read + Gather

Fire simultaneously:

1. **Read existing hot layer** (`.claude/buffer/handoff.json`). If missing, initialize fresh. If `schema_version` < 2, rename to `handoff-v1-archive.json` and triage into three-layer schema.
2. **Gather git metadata**: date, `git rev-parse --short HEAD`, `git branch --show-current`, `git diff --name-only` against previous commit hash, test suite status.

---

## Compose: Build the Alpha Stash

Infer all of the following from the conversation (do NOT ask the user):

**Active work** (Step 3):
- Current phase/stage, completed this session, in-progress, blocked by what, recommended next action.

**Decisions** (Step 4):
- For each decision: `what`, `chose`, `why`, `session` (today's date), `see` (warm-layer IDs if related, Full mode only — Lite omits `see`).

**Open threads** (Step 5):
- For each unresolved item: `thread`, `status` (`noted`|`deferred`|`blocked`|`needs-user-input`), `ref` (if applicable), `see` (Full mode only).

**Concept map + Consolidation** (Steps 6+6b, Full + Alpha only):
> If `buffer_mode` is `"full"` AND `alpha/index.json` exists: read `full-ref.md` and run Steps 6 and 6b. Otherwise skip.

---

## Write: Instance Notes + Briefing + Summary

### Instance notes (Step 7, all modes)

Write `instance_notes` — personal remarks from you to the next instance. Replaces previous notes entirely.

- **dialogue_style**: 1-2 sentences characterizing this session's tone/register. The next instance should match it from the first message.
- **remarks**: Things you learned about working with this user/codebase not in structured data.
- **open_questions**: Questions that occurred to you but weren't raised.
- **alpha_accessed**: (optional) List of alpha IDs loaded this session.

Be honest. If something confused you, say so.

### Session briefing (Step 7b, all modes)

Write `.claude/buffer/briefing.md` — free-form narrative, colleague-to-colleague. Totalize: 15-40 lines. Quicksave/Targeted: 5-15 lines.

Include: session arc (intellectual trajectory, not just completions), key moments (understanding shifts, corrections, debates), what surprised you, user working style observations, what to watch for.

If beta bin exists, read it first (`beta-read --buffer-dir .claude/buffer/ --min-r 0.0`) and synthesize high-relevance entries (r >= 0.6) into key moments.

### Dialogue trace (Step 7c, Totalize only)

Compose a cold-layer `dialogue_trace` entry:
```json
{
  "id": "c:N",
  "session": "[brief session name]",
  "arc": "[2-3 sentence narrative arc]",
  "key_moments": ["[moment 1]", "[moment 2]", "[moment 3]", "[moment 4]"]
}
```
Append to cold `dialogue_trace.sessions`. Also review `recurring_patterns` — append if a new pattern was observed.

### Beta promote + purge (Step 7d, if beta exists)

```bash
buffer_manager.py beta-promote --buffer-dir .claude/buffer/
buffer_manager.py beta-purge --buffer-dir .claude/buffer/ --max-age 3
```

**Lightweight mesh** (r >= 0.8 entries only): After promotion, scan promoted entries with r >= 0.8. If `tags`/`text` match a decision in `recent_decisions` or an alpha concept, add/update a `narrative` field (1-2 sentences) on the target. Most handoffs: 0-2 mesh operations.

### Natural summary (Step 8)

2-3 plain-language sentences. No encoding, no abbreviations, no codex. Readable by anyone.

---

## Infrastructure: Conservation + Writes + Markers

### Conservation enforcement (Step 9)

**Hot > 200 lines**: Migrate oldest `recent_decisions` to warm `decisions_archive`, resolved `open_threads` to warm, compact `orientation`. Re-check; if still over, warn user.

**Warm > max lines** (default 500, project may override): Migrate oldest `decisions_archive` to cold `archived_decisions`. Leave redirect tombstones (`{ "id": "w:78", "migrated_to": "c:15", "session_migrated": "YYYY-MM-DD" }`). Re-check; if still over, warn user.

**Cold > 500 lines**: Full mode: see `full-ref.md` for tower archival questionnaire. Lite mode: compress oldest 30% by merging adjacent summaries.

**Upward promotion** (Full + Alpha only): Run `alpha-health --buffer-dir .claude/buffer/`, check PROMOTION CANDIDATES. Any concept with 3+ sigma hits is a candidate. **⚠ MANDATORY POPUP** if candidates exist: "Promote to hot-layer flagged for immediate access? [list top 5 with hit counts]" / "Skip". If promoted: add to `concept_map_digest.flagged` with `"reason": "sigma_promotion"`.

### Write all layers (Step 10)

Write `handoff.json`, `handoff-warm.json`, `handoff-cold.json` via `handoff` command (preferred) or Write tool directly. Before writing hot: check all fields against size constraints, compress if needed — never silently drop content.

**Project README**: If `.claude/README.md` doesn't exist (first handoff), generate it (buffer architecture, commands, file inventory, configuration, FAQ). If it exists, update file inventory only when structural changes occur.

Increment `sessions_since_full_scan` in hot layer.

### Parallel infrastructure (Steps 11-13)

Fire simultaneously after layers are written:

1. **MEMORY.md sync** (Step 11, Full + Alpha only): See `full-ref.md`. Skip if `memory_config` doesn't exist or integration is `"none"`.

2. **Project registry** (Step 12): Read/create `~/.claude/buffer/projects.json`. Add or update project entry with `repo_root` (from `git rev-parse --show-toplevel`), `buffer_path`, `scope`, `last_handoff`, `project_context`.

3. **Compaction directives** (Step 12b): Update `.claude/buffer/compact-directives.md` — refresh Active Threads, update Already Persisted, review Session Vocabulary (migrate durable terms to trunk, remove session-specific ones).

4. **Session markers** (Step 13): Remove `.buffer_loaded`, increment `off_count` in `.session_active`. Emit telemetry: `python plugin/scripts/telemetry.py session-end --buffer-dir .claude/buffer/` (fail-silent).

---

## Commit + Confirm

### Commit (Step 14)

```bash
git add .claude/buffer/handoff.json .claude/buffer/handoff-warm.json .claude/buffer/handoff-cold.json
git add .claude/buffer/briefing.md
git add .claude/buffer/alpha/ 2>/dev/null || true
git add .claude/buffer/beta/ 2>/dev/null || true
git commit -m "handoff: <brief description of session>"
```

Include tower files if created. MEMORY.md changes are NOT committed (lives outside repo).

### Grid rebuild + Resolution check (Steps 14b+14c, Full + Alpha only)

> If `alpha/index.json` exists: read `full-ref.md` for grid rebuild and resolution check.

If `remote_backup` is true, follow commit with `git push`.

### Confirm (Step 15)

Run `validate --buffer-dir .claude/buffer/` then tell user:
```
Handoff written and committed.
Hot: [N]/200 | Warm: [N]/[max] | Cold: [N]/500 | Alpha: [N] referents
[N] decisions, [N] threads, [N] concept map changes captured.
The next instance can run /buffer:on to pick up where you left off.
```

---

## Quicksave Mode

After the Shared Preamble:

1. Update hot layer fields: `active_work`, `recent_decisions`, `open_threads`, `instance_notes`, `natural_summary`, `session_meta`
2. Write `handoff.json` directly (1 Write call)
3. Write briefing.md (5-15 lines)
4. Commit: `git add .claude/buffer/handoff.json .claude/buffer/briefing.md && git commit -m "buffer: quicksave"`
5. Confirm: "Quicksave written and committed. Hot: [N]/200 lines."

**Skips**: concept map (6), warm consolidation (6b), conservation (9), MEMORY.md sync (11), registry (12).

---

## Targeted Mode

After the Shared Preamble:

1. **⚠ MANDATORY POPUP**: Ask via `AskUserQuestion`: "What do you want to capture?" Wait for response. Do NOT infer from conversation.
2. Compose entries from the user's description only — do not scan full dialogue
3. Merge into hot layer (`recent_decisions`, `open_threads`, or `instance_notes` as appropriate)
4. Write `handoff.json` directly (1 Write call)
5. Write briefing.md (5-15 lines)
6. Commit: `git add .claude/buffer/handoff.json .claude/buffer/briefing.md && git commit -m "buffer: targeted save"`
7. Confirm: "Targeted save written and committed. Hot: [N]/200 lines."

**Same skips as Quicksave.** The difference: AI captures only what the user specified, not the full dialogue alpha stash.
