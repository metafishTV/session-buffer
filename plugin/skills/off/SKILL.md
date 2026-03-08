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

**Alpha bin**: `alpha-read`, `alpha-query --id/--source/--concept`, `alpha-validate` — reference memory queries. Use `next-id --layer warm` to get the next w:N ID (scans alpha to prevent collisions).

**Standalone** (debugging only): `update`, `migrate`, `validate`, `sync`, `next-id` — see script `--help`.

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
  "concept_map_changes": [ { "action": "add|update|flag|promote", ... } ],
  "convergence_web_changes": [ { "action": "add|update", ... } ],
  "validation_log_entries": [ { "check", "status", "detail", "session" } ]
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

> **Mode gate**: Lite mode skips this step.

Infer from the conversation (do NOT ask the user):

- What phase/stage is the project in?
- What was completed this session?
- What is currently in-progress?
- Is anything blocked? If so, by what?
- What is the recommended next action?

### Step 4: Log decisions

> **Mode gate**: Lite mode skips this step.

Review the conversation for decisions made this session. Write each to `recent_decisions` in the hot layer. For each decision:

- `what`: What was decided
- `chose`: What was chosen
- `why`: Brief rationale
- `session`: Today's date
- `see`: Array of warm-layer IDs if the decision relates to existing warm entries

If a decision relates to an existing warm entry, include the pointer. If not, `"see": []` is fine.

### Step 5: List open threads

> **Mode gate**: Lite mode skips this step.

Identify unresolved questions, deferred items, and next steps. Write each to `open_threads` in the hot layer. For each:

- `thread`: Description
- `status`: `noted` | `deferred` | `blocked` | `needs-user-input`
- `ref`: Reference (file, doc section, etc.) if applicable
- `see`: Array of warm-layer IDs for related context

### Step 6: Validate concept map

> **Mode gate**: Full only. Lite mode skips this step (no concept map).
>
> **Alpha gate:** Check if `alpha/` directory exists: `ls .claude/buffer/alpha/index.json 2>/dev/null`. If alpha bin does NOT exist — skip Steps 6 and 6b entirely. Concept map operations are deferred until the distill plugin provisions the alpha bin.

**Alpha-aware**: After migration, concept_map entries (cross_source, convergence_web, framework) live in the **alpha bin** (`alpha/` directory), not the warm layer. The warm layer retains only `decisions_archive` and `validation_log`.

1. Run `alpha-read --buffer-dir .claude/buffer/` to get the index summary
2. For each decision from Step 4, check if it touches a concept mapping:
   - If a mapping **changed**: update the alpha referent file directly, add to hot `concept_map_digest.recent_changes` with status `CHANGED`
   - If a **new concept** was introduced: use `alpha-write` to create it:
     ```bash
     echo '{"type":"cross_source","source_folder":"[kebab-case-source]","key":"Source:ConceptName","maps_to":"[mapping]","ref":"","suggest":null}' | scripts/buffer_manager.py alpha-write --buffer-dir .claude/buffer/
     ```
     Read the output JSON to get the assigned ID. Add to digest as `NEW`.
   - If a **suggestion was confirmed** by the user: update the referent file's `suggest` to `equiv`, log as `PROMOTED`
   - If a **foundational concept** was questioned: log as `NEEDS_USER_INPUT`, do NOT auto-change

3. Update `concept_map_digest._meta.total_entries` and `last_validated`
4. If alpha doesn't exist (pre-migration project), fall back to warm-layer concept_map operations

**IMPORTANT**: `suggest: null` is the PREFERRED state. Do NOT feel pressure to populate suggest fields. Only flag genuine structural parallels noticed during the session. The user must confirm any suggestion before it becomes an equiv.

### Step 6b: Consolidation

> **Mode gate**: Full only. Lite mode skips this step.
>
> **Alpha gate:** If alpha bin does NOT exist — skip this step entirely.

**Alpha-aware**: With reference memory in the alpha bin, consolidation operates differently:

**Warm layer consolidation** (decisions_archive + validation_log):
- Warm is now small (~274 lines). Consolidation means compressing verbose decision/validation entries using established vocabulary.
- Log all changes in `validation_log` with status `CONSOLIDATED`.

**Alpha referent consolidation** (individual .md files):
For alpha entries the current instance **created or meaningfully modified this session**:

- **Vocabulary compression**: Replace multi-word descriptions with established terms
- **Same-concept merge**: If two referent files describe the same structural relationship, merge into one file and delete the absorbed entry via `alpha-delete`:
     ```bash
     scripts/buffer_manager.py alpha-delete --buffer-dir .claude/buffer/ --id w:218
     ```
     Then update the surviving entry's `.md` file with merged content.
- **Description tightening**: Shorten explanatory prose to referential shorthand

Alpha files are self-contained and small (30-80 lines each), making targeted consolidation natural — edit a single file, update the index. No need to parse/rewrite large JSON arrays.

**Periodic deep consolidation** (at `full_scan_threshold`):

When `sessions_since_full_scan >= full_scan_threshold`, scan alpha index for:
1. Self-integrated entries -> apply deeper consolidation with confidence (automated)
2. Inherited entries -> identify candidates, **⚠ MANDATORY POPUP**: present proposals via `AskUserQuestion`, wait for the user's response — do NOT auto-approve
3. Apply ONLY the changes the user explicitly approved
4. Reset `sessions_since_full_scan` to 0

**Rules (all consolidation):**
- Never consolidate across source folders (folder boundaries are structural)
- Never auto-consolidate framework entries without `NEEDS_USER_INPUT`
- All consolidations logged in warm `validation_log` with status `CONSOLIDATED` and both entry IDs
- Absorbed entries: delete the file, remove from `alpha/index.json`
- When in doubt, don't merge — false merges lose meaning, missed merges just cost tokens

### Step 7: Write instance notes

Write the `instance_notes` section — personal remarks from you to the next instance. This replaces previous instance_notes entirely. **All modes** — instance notes are always valuable.

Include:

- **remarks**: Things you learned about working with this user, this codebase, or this project that are not captured in the structured data. Warnings, tips, things that surprised you.
- **open_questions**: Questions that occurred to you during the session but you did not get to raise. These help the next instance know where the edges of understanding are.
- **alpha_accessed**: (optional) List of alpha referent IDs loaded this session (e.g., `["w:218", "cw:83"]`). Helps the next instance know which referents were relevant to this session's work without loading everything.

Be honest. If something confused you, say so. If a mapping felt forced, flag it. The next instance benefits more from candor than from false confidence.

### Step 8: Write natural summary

Write 2-3 plain-language sentences summarizing the session state. No encoding, no abbreviations, no codex. This should be readable by anyone.

### Step 9: Conservation enforcement

> **Mode note**: In lite mode, conservation is simplified — only session summaries migrate between layers. See SKILL.md for compression rules.

Check each layer against its size bound and enforce migration. See SKILL.md for layer size limits.

**If hot > 200 lines:**
- Migrate oldest `recent_decisions` entries to warm `decisions_archive`
- Migrate resolved `open_threads` to warm
- Compact `orientation` if verbose
- Re-check. If still > 200, warn the user.

**If warm > max lines (default 500, project may override):**
- Migrate oldest `decisions_archive` entries to cold `archived_decisions`
- Migrate oldest `validation_log` entries to cold
- When migrating an entry from warm to cold:
  1. Assign it a new `c:N` ID in the cold layer
  2. Leave a **redirect tombstone** in the warm layer:
     ```json
     { "id": "w:78", "migrated_to": "c:15", "session_migrated": "YYYY-MM-DD" }
     ```
  3. Hot-layer `"see"` pointers continue to resolve via the tombstone
- Re-check. If still over, warn the user.

  **Note (alpha-aware):** After alpha migration, warm contains only `decisions_archive` + `validation_log` (~274 lines). Conservation rarely triggers. If it does, it's because decisions/validation entries accumulated beyond the cap — migrate the oldest to cold as above. The concept_map lives in the alpha bin (no size cap, no decay) and is not subject to warm conservation.

**If cold > 500 lines:**
- Trigger the archival questionnaire. Each step is a **⚠ MANDATORY POPUP** — you MUST use `AskUserQuestion` for each, wait for the response, and only then proceed to the next:

  **Questionnaire Step 1 — Full scan + dependency map:**
  Read entire cold layer. For each entry, compute nesting depth (how many other entries reference it). **⚠ MANDATORY POPUP**: Present results via `AskUserQuestion` — show depth-0 entries marked as safe to archive and depth > 0 entries showing what references them. Wait for the user to acknowledge before continuing.

  **Questionnaire Step 2 — Pick ratio AND direction:**
  **⚠ MANDATORY POPUP**: Present ratio choices via `AskUserQuestion` — options: 20/80, 33/66, 50/50. User also chooses which portion goes to the tower (smaller or larger). This is bidirectional — the user has full sovereignty. Wait for response.

  **Questionnaire Step 3 — Pick entries:**
  **⚠ MANDATORY POPUP**: Present entry list via `AskUserQuestion`. User selects specific entries for archival, informed by the dependency map. Wait for response. Do NOT auto-select entries.

- Create a tower file: `handoff-tower-NNN-YYYY-MM-DD.json` in `.claude/buffer/`
- Leave tombstones in cold for archived entries:

  ```json
  {
    "id": "c:7",
    "archived_to": "tower-001",
    "was": "Brief description of archived entry",
    "session_archived": "YYYY-MM-DD"
  }
  ```

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

### Step 11: MEMORY.md sync

Sync the project's MEMORY.md with current buffer state. Skip this step entirely if `memory_config` doesn't exist or `memory_config.integration` is `"none"`.

**Status sync** (if integration is `"full"` or `"lite"`):
- Read MEMORY.md at `memory_config.path`
- Find the `## Status` section
- Update to: `**Status**: [active_work.current_phase]. Next: [active_work.next_action].`
- If no `## Status` section exists, add one before `## Buffer Integration` (or at end of file)

**Promoted entry sync** (only if integration is `"full"` and promoted entries exist):
- Check warm entries with `"promoted_to_memory"` field
- If any changed since their promotion date: update the corresponding line in MEMORY.md's `## Stable Definitions` section
- If a promoted entry migrated to cold (now a tombstone): remove its line from `## Stable Definitions` and clear the `"promoted_to_memory"` field from the tombstone

This step is lightweight — at most a few line edits to MEMORY.md. It keeps the orientation card current without a full rewrite.

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

### Step 13: Clean up session markers

Remove the sigma hook session marker (created by `/buffer:on`):
```bash
rm -f .claude/buffer/.buffer_loaded
```

### Step 14: Commit

```bash
git add .claude/buffer/handoff.json .claude/buffer/handoff-warm.json .claude/buffer/handoff-cold.json
# Include alpha changes if any referent files were added/modified
git add .claude/buffer/alpha/
git commit -m "handoff: <brief description of session>"
```

If tower files were created, include them in the commit as well. MEMORY.md changes (from Step 11) are NOT committed — MEMORY.md lives outside the repo in the Claude projects directory and is managed separately.

If `remote_backup` is true in the hot layer, follow the commit with `git push`.

### Step 14: Confirm

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
