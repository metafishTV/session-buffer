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

**What you produce**: `handoff.json` (hot), `handoff-warm.json` (warm), `handoff-cold.json` (cold) in `.claude/buffer/`, plus updates to `alpha/` (reference memory) if concept map entries changed, plus a git commit.

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
  "instance_notes": { "from", "to", "remarks": [], "open_questions": [] },
  "natural_summary": "2-3 plain-language sentences.",
  "concept_map_changes": [ "..." ],   // Full + Alpha only — see full-ref.md
  "convergence_web_changes": [ "..." ], // Full + Alpha only — see full-ref.md
  "validation_log_entries": [ "..." ]   // Full + Alpha only — see full-ref.md
}
```

---

## Mode Selection (FIRST)

**⚠ MANDATORY POPUP**: You MUST call `AskUserQuestion` with the options below before proceeding.
Do NOT default to Totalize. Do NOT infer the mode from context. Do NOT skip this popup. The user chooses.

`AskUserQuestion` options:
- **Totalize** — Complete end-of-session handoff (all steps below)
- **Quicksave** — Fast sigma trunk checkpoint (~3 tool calls)
- **Targeted** — Save specific items the user names (~4 tool calls)

**Wait for the user's response before doing anything else.** Do NOT continue until the user has answered. Even if the session is ending and a full handoff seems obvious, the user may prefer a quicksave. Never assume.

Then follow the selected mode. All modes begin with the **Shared Preamble**.

## Shared Preamble (all modes)

**Read-first ordering** — scan existing sigma trunk before dialogue to prevent duplication:

1. Read hot + warm + cold layers (parallel if possible)
2. Scan dialogue for new content
3. Compute the **alpha stash**: items from this session NOT already captured in any layer

After preamble, branch by mode:
- **Totalize** -> continue to Step 0 below
- **Quicksave** -> jump to "Quicksave Mode" at end of file
- **Targeted** -> jump to "Targeted Mode" at end of file

---

## First-Run Detection

If `.claude/buffer/handoff.json` does not exist, this is a first-run.
Before proceeding, complete initial setup. Each numbered step below is a **⚠ MANDATORY POPUP** — you MUST use `AskUserQuestion` for each one, wait for the response, and only then proceed to the next:

1. **Scope** — **⚠ MANDATORY POPUP** via `AskUserQuestion`: "Buffer scope?"
   - **Full** — Concept maps, convergence webs, conservation, tower archival.
     For research projects, multi-source analysis, deep domain work.
   - **Lite** — Decisions and threads only. For everyday development,
     quick projects, session continuity without research infrastructure.
   Wait for response before continuing.

2. **Project identity** — **⚠ MANDATORY POPUP** via `AskUserQuestion` (Full only):
   "Project name + one-sentence core insight." Wait for response.

3. **Remote backup** — **⚠ MANDATORY POPUP** via `AskUserQuestion`:
   - Git remote detected -> "Auto-push buffer after each handoff?" (yes/no)
   - No remote -> "Connect a GitHub repo for remote backup? Your work
     deserves a backup that lives somewhere safe." (yes -> guide setup / no)
   - No git repo -> "Initialize git for your buffer?" (yes/no)

4. Store in hot layer: `"scope": "full"|"lite"`, `"remote_backup": true|false`
5. Initialize layers with scope-appropriate schemas
6. Register in global project registry
7. Proceed to first handoff (return to Mode Selection)

---

## Step 0: Check for Project Skill

Before doing anything else:

1. Determine the current repository root (via `git rev-parse --show-toplevel` or working directory)
2. Check if `<repo>/.claude/skills/buffer/off.md` exists
3. **If it exists**: read that file and follow its instructions instead. It contains project-specific schema, concept map structure, and terminology. Stop processing this file.
4. **If it does not exist**: continue with the generic process below.

---

## Process

### Step 1: Read existing hot layer

Read `.claude/buffer/handoff.json` to understand the current state.

- If the file does not exist, you are creating the first handoff. Initialize all layers fresh.
- If `schema_version` is missing or < 2, note that migration from v1 is needed. Rename the old file to `handoff-v1-archive.json`, then triage its contents into the three-layer schema (hot/warm/cold) before proceeding.

### Step 2: Gather session metadata

Collect via git commands:

- Today's date
- Current commit hash (`git rev-parse --short HEAD`)
- Current branch (`git branch --show-current`)
- Files modified this session (`git diff --name-only` against the commit hash in the previous buffer, or the last 5 commits if no previous buffer)
- Test status (run the project's test suite and capture the pass/fail summary line)

### Step 3: Summarize active work

Infer from the conversation (do NOT ask the user):

- What phase/stage is the project in?
- What was completed this session?
- What is currently in-progress?
- Is anything blocked? If so, by what?
- What is the recommended next action?

### Step 4: Log decisions

Review the conversation for decisions made this session. Write each to `recent_decisions` in the hot layer. For each decision:

- `what`: What was decided
- `chose`: What was chosen
- `why`: Brief rationale
- `session`: Today's date
- `see`: Array of warm-layer IDs if the decision relates to existing warm entries (Full mode only — Lite mode omits `see`)

If a decision relates to an existing warm entry, include the pointer. If not, `"see": []` is fine.

### Step 5: List open threads

Identify unresolved questions, deferred items, and next steps. Write each to `open_threads` in the hot layer. For each:

- `thread`: Description
- `status`: `noted` | `deferred` | `blocked` | `needs-user-input`
- `ref`: Reference (file, doc section, etc.) if applicable
- `see`: Array of warm-layer IDs for related context (Full mode only — Lite mode omits `see`)

### Step 6 + 6b: Concept Map + Consolidation (Full + Alpha only)

> If `buffer_mode` is `"full"` AND `alpha/index.json` exists: read `full-ref.md` and run Steps 6 and 6b from there. Otherwise skip to Step 7.

### Step 7: Write instance notes

Write the `instance_notes` section — personal remarks from you to the next instance. This replaces previous instance_notes entirely. **All modes** — instance notes are always valuable.

Include:

- **remarks**: Things you learned about working with this user, this codebase, or this project that are not captured in the structured data. Warnings, tips, things that surprised you.
- **open_questions**: Questions that occurred to you during the session but you did not get to raise. These help the next instance know where the edges of understanding are.
- **alpha_accessed**: (optional) List of alpha referent IDs loaded this session (e.g., `["w:218", "cw:83"]`). Helps the next instance know which referents were relevant to this session's work without loading everything.

Be honest. If something confused you, say so. If a mapping felt forced, flag it. The next instance benefits more from candor than from false confidence.

### Step 7b: Write session briefing

Write `.claude/buffer/briefing.md` — a free-form narrative document from you to the next instance. This is the colleague-to-colleague handoff. Not JSON, not structured fields. Natural language, honest, personal.

**All modes** write a briefing. Totalize writes a full briefing (15-40 lines). Quicksave/Targeted writes a shorter briefing (5-15 lines) covering at minimum: session arc and any key moments.

Include:

- **Session arc**: What was this session *about*? Not what was completed (that's in active_work) but what the intellectual trajectory was. How did the conversation develop? What direction did it take that wasn't planned?
- **Key moments**: Where did understanding shift? What corrections did the user make? What debates happened and how were they resolved? What would a 10-turn argument look like compressed to 2 sentences?
- **What surprised me**: Observations the structured data doesn't capture. Things that don't fit neatly into decision/thread/concept.
- **User working style**: Anything revealed this session about how the user thinks, communicates, or works that helps the next instance collaborate better.
- **What to watch for**: Tensions, unresolved confusions, things you'd want to double-check if you were continuing.

If the beta bin exists (`.claude/buffer/beta/narrative.jsonl`), read it first:
```bash
buffer_manager.py beta-read --buffer-dir .claude/buffer/ --min-r 0.0
```
Use the beta entries as source material — high-relevance entries (r >= 0.6) should be reflected in the briefing's key moments. Low-relevance entries provide timeline context. The briefing should be richer than any single beta entry — it's a *synthesis* of the rolling capture plus your full session context.

### Step 7c: Update dialogue trace (Totalize only)

> **Mode gate**: Totalize only. Quicksave and Targeted skip this step.

Compose a cold-layer `dialogue_trace` entry distilled from the briefing:

```json
{
  "id": "c:N",
  "session": "[brief session name, e.g. 'v1.9.0 atom markers + RH theory']",
  "arc": "[2-3 sentence narrative arc — distilled from the briefing]",
  "key_moments": ["[moment 1]", "[moment 2]", "[moment 3]", "[moment 4]"]
}
```

Append to cold `dialogue_trace.sessions`. Use the next sequential `c:N` ID (check existing entries).

Also: review `dialogue_trace.recurring_patterns` in the cold layer. If a new behavioral or intellectual pattern was observed this session (e.g., "User tests convergence by sharing source texts independently"), append it.

### Step 7d: Promote and purge beta (if beta exists)

> **Guard**: Only run if `.claude/buffer/beta/narrative.jsonl` exists.

Promote high-relevance beta entries:
```bash
buffer_manager.py beta-promote --buffer-dir .claude/buffer/
```
(Reads threshold from `beta_config.threshold` in hot layer, default 0.6. Adaptive — adjusts after each run.)

Then purge old/promoted entries:
```bash
buffer_manager.py beta-purge --buffer-dir .claude/buffer/ --max-age 3
```

**Lightweight mesh** (r >= 0.8 entries only): After promotion, scan promoted entries with r >= 0.8. For each, check if its `tags` or `text` reference a decision in `recent_decisions` (keyword match on `what` field) or an alpha concept (tag match). If match found, add/update a `narrative` field (1-2 sentences) on the target entry. This connects narrative to structure at the point of relevance. Most handoffs will have 0-2 mesh operations.

### Step 8: Write natural summary

Write 2-3 plain-language sentences summarizing the session state. No encoding, no abbreviations, no codex. This should be readable by anyone.

### Step 9: Conservation enforcement

Check each layer against its size bound and enforce migration.

**If hot > 200 lines:**
- Migrate oldest `recent_decisions` entries to warm `decisions_archive`
- Migrate resolved `open_threads` to warm
- Compact `orientation` if verbose
- Re-check. If still > 200, warn the user.

**If warm > max lines (default 500, project may override):**
- Migrate oldest `decisions_archive` entries to cold `archived_decisions`
- When migrating an entry from warm to cold:
  1. Assign it a new `c:N` ID in the cold layer
  2. Leave a **redirect tombstone** in the warm layer:
     ```json
     { "id": "w:78", "migrated_to": "c:15", "session_migrated": "YYYY-MM-DD" }
     ```
  3. Hot-layer `"see"` pointers continue to resolve via the tombstone
- Re-check. If still over, warn the user.

**If cold > 500 lines:**
- Full mode: see `full-ref.md` for the tower archival questionnaire.
- Lite mode: compress the oldest 30% by merging adjacent summaries, migrate compressed batch to cold.

**Upward promotion (anopressive channel — Full + Alpha only):**

After conservation enforcement (downward migration), check for upward promotion candidates:

1. Run `alpha-health --buffer-dir .claude/buffer/` and check the PROMOTION CANDIDATES section
2. Any concept with 3+ sigma hits is a candidate for promotion (it's being operationally used)
3. **⚠ MANDATORY POPUP**: If candidates exist, present to user via `AskUserQuestion`:
   - **Promote** — "These alpha concepts were activated [N]+ times this session. Promote to hot-layer `concept_map_digest.flagged` for immediate access next session: [list top 5 with hit counts]"
   - **Skip** — "Keep current layer assignments."
4. If promoted: add to `concept_map_digest.flagged` with `"reason": "sigma_promotion"`

This closes the anapressive-anopressive loop: conservation pushes entries down based on age/size (anapressive absorption), promotion pulls entries up based on operational relevance (anopressive expression).

### Step 10: Write all layers

> **Mode note**: Lite mode writes only the lite schemas (see SKILL.md). Full mode writes all schemas.

Write `handoff.json`, `handoff-warm.json`, and `handoff-cold.json` to `.claude/buffer/`.

**Before writing hot layer**: Check all fields against the Hot Layer Size Constraints (defined in SKILL.md). Compress any fields that exceed their limits — do not silently drop content. Use the warm concept_map as a glossary for compression.

**Project README**: If `.claude/README.md` does not exist (first handoff for this project), generate it now. This is user-facing documentation describing:

- What the buffer system does for this project
- The buffer architecture (hot/warm/cold/tower layers)
- What `/buffer:off` and `/buffer:on` do (step summaries)
- The concept map structure (groups, if a project skill defines them)
- File inventory (buffer files, skill files)
- How to configure (thresholds, concept map groups, MEMORY.md integration)
- FAQ (common questions)

If `.claude/README.md` already exists, update its file inventory section if new buffer files were created (e.g., a tower file). Do not rewrite the full README on every handoff — only update when structural changes occur (new files, new concept map groups, configuration changes).

Increment `sessions_since_full_scan` in the hot layer.

### Step 11: MEMORY.md sync (Full + Alpha only)

> If `buffer_mode` is `"full"` AND `alpha/` exists: read `full-ref.md` for MEMORY.md sync protocol. Otherwise skip.

### Step 12: Register in global project registry

Read (or create) `~/.claude/buffer/projects.json`. If the current project is not registered, add it:

```json
{
  "schema_version": 1,
  "projects": {
    "[project-name]": {
      "buffer_path": "[absolute path to .claude/buffer/]",
      "last_handoff": "YYYY-MM-DD",
      "project_context": "[one-sentence from orientation.core_insight]"
    }
  }
}
```

If already registered, update `last_handoff` to today's date. Write back.

The project name comes from the hot layer's `project_name` field (if present) or is inferred from the repo directory name.

### Step 13: Update session markers

Remove the sigma hook marker:
```bash
rm -f .claude/buffer/.buffer_loaded
```

Update `.claude/buffer/.session_active` — read the current JSON, increment `off_count` by 1, and write back:
```json
{"date": "YYYY-MM-DD", "off_count": N+1}
```
This tracks how many times the buffer has been saved this session. The statusline displays `buf:off×N` so the user can see session depth at a glance. At `off×3+`, consider suggesting a fresh session — context nuance erodes with each cycle.

### Step 14: Commit

```bash
git add .claude/buffer/handoff.json .claude/buffer/handoff-warm.json .claude/buffer/handoff-cold.json
git add .claude/buffer/briefing.md
# Include alpha changes if any referent files were added/modified
git add .claude/buffer/alpha/
# Include beta bin if it exists
git add .claude/buffer/beta/ 2>/dev/null || true
git commit -m "handoff: <brief description of session>"
```

If tower files were created, include them in the commit as well. MEMORY.md changes (from Step 11) are NOT committed — MEMORY.md lives outside the repo in the Claude projects directory and is managed separately.

### Step 14b + 14c: Grid Rebuild + Resolution Check (Full + Alpha only)

> If `alpha/index.json` exists: read `full-ref.md` for grid rebuild (Step 14b) and resolution check (Step 14c). Otherwise skip.

If `remote_backup` is true in the hot layer, follow the commit with `git push`.

### Step 15: Confirm

Run `validate --buffer-dir .claude/buffer/` to get layer sizes, then tell the user:

```
Handoff written and committed.
Hot: [N]/200 | Warm: [N]/[max] | Cold: [N]/500 | Alpha: [N] referents
[N] decisions, [N] threads, [N] concept map changes captured.
The next instance can run /buffer:on to pick up where you left off.
```

---

## Quicksave Mode

After the Shared Preamble (read all layers, scan dialogue, compute alpha stash):

1. **Update hot layer fields**: `active_work`, `recent_decisions`, `open_threads`, `instance_notes`, `natural_summary`, `session_meta`
2. **Write** `handoff.json` directly (1 Write call)
3. **Commit**: `git add .claude/buffer/handoff.json && git commit -m "buffer: quicksave"`
4. **Confirm**: "Quicksave written and committed. Hot: [N]/200 lines."

**Skips**: concept map (step 6), warm consolidation (6b), conservation (9), MEMORY.md sync (11), registry (12).

---

## Targeted Mode

After the Shared Preamble:

1. **⚠ MANDATORY POPUP**: Ask the user via `AskUserQuestion`: "What do you want to capture?" Wait for their response before continuing. Do NOT infer from the conversation what they want saved.
2. **Compose** entries from the user's description only — do not scan full dialogue
3. **Merge** into hot layer (add to `recent_decisions`, `open_threads`, or `instance_notes` as appropriate)
4. **Write** `handoff.json` directly (1 Write call)
5. **Commit**: `git add .claude/buffer/handoff.json && git commit -m "buffer: targeted save"`
6. **Confirm**: "Targeted save written and committed. Hot: [N]/200 lines."

**Same skips as Quicksave.** The difference: AI captures only what the user specified, not the full dialogue alpha stash.
