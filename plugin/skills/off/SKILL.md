---
name: off
description: Write session handoff to sigma trunk. Run at session end or when context is getting full.
---

# Session Handoff

**Architecture reference**: For sigma trunk layer schemas, size constraints, ID rules, and the consolidation protocol, read `docs/architecture.md` in the plugin directory (only when you need schema details for validation or writing).

## Instance Primer

You are running `/session-buffer:off`. Extract every decision, open thread, concept
mapping, and unresolved question from this session. Nothing implicit survives
the handoff — if it matters, it's in the alpha stash or it's gone.

**Key principles**:
- The warm layer should get **denser** each session, not just longer. Consolidate:
  compress descriptions using established vocabulary, merge overlapping entries.
- `suggest: null` is preferred. Don't invent mappings to fill fields.
- Instance notes are colleague-to-colleague. Be honest — flag confusion, forced
  mappings, things that surprised you.
- If a project skill exists, it overrides this file entirely.

**What you produce**: `handoff.json` (hot), `handoff-warm.json` (warm), `handoff-cold.json` (cold) in `.claude/buffer/`, plus a git commit.

## Script Tooling

**`scripts/buffer_manager.py`** handles mechanical buffer operations. You produce the CONTENT (decisions, summaries, concept entries); the script handles the PLUMBING (JSON merge, ID assignment, conservation, sync).

### Primary: `handoff` pipeline (Steps 9-12 in one call)

```
python buffer_manager.py handoff \
  --buffer-dir DIR --input changes.json \
  --warm-max N --memory-path PATH --project-name NAME
```

Chains `update -> migrate -> sync` in a single invocation. This is the **preferred** workflow — do NOT call update, migrate, sync separately unless debugging.

### Standalone commands (for debugging or partial runs)

| Command | What it does |
|---|---|
| `update --buffer-dir DIR --input changes.json` | Merge session changes into hot+warm layers |
| `migrate --buffer-dir DIR --warm-max N` | Conservation enforcement: hot->warm->cold |
| `validate --buffer-dir DIR` | Check layer sizes, schema version |
| `sync --buffer-dir DIR --memory-path PATH` | MEMORY.md status sync + project registry |
| `next-id --buffer-dir DIR --layer warm` | Get next sequential ID |

**Usage**: `python scripts/buffer_manager.py <command> [options]`

### Compressed Workflow (target: ~7 tool calls total)

Steps 1-8 are YOUR cognitive work. Then:

1. **Read hot layer** (1 tool call)
2. **Gather metadata** (1 parallel call — git + tests)
3. **Compose** `_changes.json` in `.claude/buffer/` (1 Write call — see schema below)
4. **Run `handoff` pipeline** (1 Bash call — does update + migrate + sync)
5. **Commit** (1 Bash call)

### changes.json schema

The changes.json file IS the alpha stash — the crystallized session learnings ready for merge.

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

Omit sections with no changes (e.g., skip `concept_map_changes` for tooling-only sessions). The script handles ID assignment, decision migration, conservation, MEMORY.md sync, and registry updates.

---

## Mode Selection (FIRST)

Present this choice to the user via AskUserQuestion:

- **Totalize** — Complete end-of-session handoff (all steps below)
- **Quicksave** — Fast sigma trunk checkpoint (~3 tool calls)
- **Targeted** — Save specific items the user names (~4 tool calls)

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
Before proceeding, complete initial setup via AskUserQuestion popups:

1. **Scope** (popup): "Buffer scope?" ->
   - **Full** — Concept maps, convergence webs, conservation, tower archival.
     For research projects, multi-source analysis, deep domain work.
   - **Lite** — Decisions and threads only. For everyday development,
     quick projects, session continuity without research infrastructure.

2. **Project identity** (popup, Full only):
   Project name + one-sentence core insight (seeds orientation.core_insight)

3. **Remote backup** (popup):
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

Read the warm layer's `concept_map`. For each decision from Step 4, check if it touches a concept mapping:

- If a mapping **changed**: update the warm entry, add to hot `concept_map_digest.recent_changes` with status `CHANGED`
- If a **new concept** was introduced: add a new warm entry with a new `w:N` ID, add to digest as `NEW`
- If a **suggestion was confirmed** by the user: promote `suggest` to `equiv`, log as `PROMOTED`
- If a **foundational concept** was questioned: log as `NEEDS_USER_INPUT`, do NOT auto-change

Update `concept_map_digest._meta.total_entries` and `last_validated`.

**IMPORTANT**: `suggest: null` is the PREFERRED state. Do NOT feel pressure to populate suggest fields. Only flag genuine structural parallels noticed during the session. The user must confirm any suggestion before it becomes an equiv.

### Step 6b: Warm consolidation

> **Mode gate**: Full only. Lite mode skips this step.

After validating entries, perform a consolidation pass on the warm layer. The warm layer should *iterate* — same structure, richer each pass — not merely accumulate.

**Every-session consolidation** (automated, self-integrated entries only):

For entries the current instance **created or meaningfully modified this session**:

- **Vocabulary compression**: Replace multi-word descriptions with established terms from the concept_map
- **Same-concept merge**: If two entries describe the same structural relationship, merge (keep richer formulation, absorb unique content, leave redirect tombstone)
- **Description tightening**: Shorten explanatory prose to referential shorthand, using project vocabulary

Log all changes in `validation_log` with status `CONSOLIDATED`.

**Periodic deep consolidation** (at `full_scan_threshold`):

When `sessions_since_full_scan >= full_scan_threshold`, trigger the Provenance-Aware Consolidation Protocol (defined in SKILL.md):

1. Read all warm entries
2. Self-integrated entries -> apply deeper consolidation with confidence (automated)
3. Inherited entries -> identify candidates, present proposals to user, wait for approval
4. Apply only approved changes

This replaces the routine consolidation for this cycle. Reset `sessions_since_full_scan` to 0 after completion.

**Rules (all consolidation):**
- Never consolidate across concept_map groups (group boundaries are structural)
- Never auto-consolidate base-system entries without `NEEDS_USER_INPUT`
- All consolidations logged in `validation_log` with status `CONSOLIDATED` and both entry IDs
- Absorbed entries get redirect tombstones
- When in doubt, don't merge — false merges lose meaning, missed merges just cost tokens

### Step 7: Write instance notes

> **Mode gate**: Lite mode skips this step.

Write the `instance_notes` section — personal remarks from you to the next instance. This replaces previous instance_notes entirely.

Include:

- **remarks**: Things you learned about working with this user, this codebase, or this project that are not captured in the structured data. Warnings, tips, things that surprised you.
- **open_questions**: Questions that occurred to you during the session but you did not get to raise. These help the next instance know where the edges of understanding are.

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

  **Note:** The `concept_map` is not migrated — it is the structural backbone and should be preserved in warm. If the concept_map alone approaches the warm bound, consider: (a) archiving unused cross_source entries that haven't been referenced in 3+ sessions, or (b) raising the warm bound for this project in the project-level skill.

**If cold > 500 lines:**
- Trigger the archival questionnaire (3 steps):

  **Questionnaire Step 1 — Full scan + dependency map:**
  Read entire cold layer. For each entry, compute nesting depth (how many other entries reference it). Present to user with depth-0 entries marked as safe to archive and depth > 0 entries showing what references them.

  **Questionnaire Step 2 — Pick ratio AND direction:**
  Offer three ratio choices (20/80, 33/66, 50/50). User also chooses which portion goes to the tower (smaller or larger). This is bidirectional — the user has full sovereignty.

  **Questionnaire Step 3 — Pick entries:**
  User selects specific entries for archival, informed by the dependency map.

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
- What `/session-buffer:off` and `/session-buffer:on` do (step summaries)
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

### Step 13: Commit

```bash
git add .claude/buffer/handoff.json .claude/buffer/handoff-warm.json .claude/buffer/handoff-cold.json
git commit -m "handoff: <brief description of session>"
```

If tower files were created, include them in the commit as well. MEMORY.md changes (from Step 11) are NOT committed — MEMORY.md lives outside the repo in the Claude projects directory and is managed separately.

If `remote_backup` is true in the hot layer, follow the commit with `git push`.

### Step 14: Confirm

Tell the user: "Handoff written and committed. The next instance can run `/session-buffer:on` to pick up where you left off."

---

## Quicksave Mode

After the Shared Preamble (read all layers, scan dialogue, compute alpha stash):

1. **Update hot layer fields**: `active_work`, `recent_decisions`, `open_threads`, `instance_notes`, `natural_summary`, `session_meta`
2. **Write** `handoff.json` directly (1 Write call)
3. **Commit**: `git add .claude/buffer/handoff.json && git commit -m "buffer: quicksave"`
4. **Confirm**: "Quicksave written and committed."

**Skips**: concept map (step 6), warm consolidation (6b), conservation (9), MEMORY.md sync (11), registry (12).

---

## Targeted Mode

After the Shared Preamble:

1. **Ask user**: "What do you want to capture?" (AskUserQuestion, free-text)
2. **Compose** entries from the user's description only — do not scan full dialogue
3. **Merge** into hot layer (add to `recent_decisions`, `open_threads`, or `instance_notes` as appropriate)
4. **Write** `handoff.json` directly (1 Write call)
5. **Commit**: `git add .claude/buffer/handoff.json && git commit -m "buffer: targeted save"`
6. **Confirm**: "Targeted save written and committed."

**Same skips as Quicksave.** The difference: AI captures only what the user specified, not the full dialogue alpha stash.
