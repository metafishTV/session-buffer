---
name: on
description: Reconstruct session context from sigma trunk. Run at session start.
---

# Session On Hand

**Architecture reference**: For sigma trunk layer schemas, size constraints, ID rules, and the consolidation protocol, read `docs/architecture.md` in the plugin directory (only when you need schema details for validation or writing).

## Instance Primer

You are running `/buffer:on`. Reconstruct context from the sigma trunk so you can
work effectively without the user re-explaining everything.

The sigma trunk has three layers: Hot (~200 lines, always loaded), Warm (~500 lines,
selectively loaded via pointers), Cold (~500 lines, on-demand only), plus an optional
Alpha bin (reference memory — static, query-on-demand, no size cap). Load the minimum
needed to orient.

**Key principles**:
- Load the minimum needed to orient. Hot always, warm selectively, cold rarely.
- **Verify against git state.** The sigma trunk records a commit hash. If commits
  happened outside a session, flag the discrepancy — the trunk may be stale.
- Instance notes are the previous instance's honest observations. Read them carefully.
- After reconstruction, **arm autosave**.
- If a project skill exists, it adds project-specific priorities on top.

**What you produce**: A reconstructed context in your working memory, an armed autosave, and a clear presentation to the user of where things stand and what comes next.

**ENFORCEMENT RULE — applies to every step below**: Any step that requires user input MUST use the `AskUserQuestion` tool. Do NOT substitute plain text questions, do NOT infer the user's answer from context, and do NOT skip the question because the answer seems obvious. You MUST call `AskUserQuestion`, you MUST wait for the response, and you MUST NOT continue past that step until the user has answered. Steps requiring `AskUserQuestion` are marked with **⚠ MANDATORY POPUP**.

## Script Tooling

**`scripts/buffer_manager.py`** (plugin-relative) handles mechanical sigma trunk operations. Use it instead of manually parsing JSON.

- `read --buffer-dir .claude/buffer/` — Parse hot layer, resolve warm pointers (tombstones, redirects), output formatted reconstruction. Covers Steps 1, 3, 4. Add `--warm-max N` for project overrides.
- `validate --buffer-dir .claude/buffer/` — Check layer sizes, schema version, required fields, alpha integrity.
- `next-id --buffer-dir .claude/buffer/ --layer warm` — Get next sequential ID (scans alpha too to prevent collisions).
- `beta-read --buffer-dir .claude/buffer/` — Read beta bin entries with optional filters (`--min-r`, `--limit`, `--since`).
- `beta-append --buffer-dir .claude/buffer/` — Append narrative entry to beta bin (JSON on stdin).

> **Full + Alpha mode**: If `buffer_mode` is `"full"` AND `alpha/` exists, also read `skills/on/full-ref.md` for alpha tooling, pointer following (Step 4), and full-scan protocol (Step 5). Those steps are factored out to keep this file lean for standard sessions.

**Manual steps**: git grounding (2), instance notes presentation (6), MEMORY.md (7), autosave arming (8).

---

## Step 0: Project Routing

**⚠ MANDATORY POPUP**: Always show the project selector via AskUserQuestion before loading anything.
Never auto-load a trunk without user confirmation.

### 0a: Locate project context

Determine what projects are available. Do NOT load any trunk data at this point.

1. Try `git rev-parse --show-toplevel` from the current working directory.
   - **If success**: cwd is inside a git repo. Note the repo root. Check if
     `<repo-root>/.claude/buffer/handoff.json` exists — if so, this is a
     local project with a buffer.

2. **If cwd is NOT a git repo** (git rev-parse fails):
   - Scan **immediate children** of cwd (one level deep only) for directories
     containing `.git/`.
   - For each git-repo child, compute a score:
     | Signal | Score |
     |--------|-------|
     | Has `.claude/buffer/handoff.json` | +1.0 |
     | Has `.git/` | +0.5 |
     | Matches a `projects.json` entry | +0.3 |
   - Sort by score descending.

3. Also read `~/.claude/buffer/projects.json` (if it exists) for entries whose
   `repo_root` is under the current cwd. Merge with filesystem results from
   step 2, deduplicate by repo root path.

### 0b: Project selector (ALWAYS shown)

**⚠ MANDATORY POPUP**: You MUST call `AskUserQuestion` before proceeding.
Do NOT load any trunk data until the user responds.

The popup adapts to what was found in 0a:

**One result with score >= 1.0:**
- Resume [project name] at [repo path] (Recommended) (last handoff: [date])
- Start new project
- Start lite session

**Multiple results with score >= 1.0:**
- Present as ranked list (score descending), top entry pre-selected
- Start new project
- Start lite session

**Results found but all below 1.0 (git repos without buffers):**
- Initialize buffer in [repo name] (highest-scoring)
- Start new project
- Start lite session

**No results + registry has entries:**
- Resume [most recent project from registry] (last handoff: [date])
- Switch to another project (shows full list)
- Start new project
- Start lite session

**No results + no registry (first run):**
- Proceed directly to first-run setup (0d)

If user selects an existing project: load its buffer_path and proceed to Step 0c.
If user selects "Start new project" or "Start lite session": proceed to 0d.

### 0c: Check for project skill

After the user selects a project, check if the selected repo has
`<repo>/.claude/skills/buffer/on.md`.

- **If it exists**: read that file and follow its instructions instead. Stop
  processing this file.
- **If not**: continue with Step 1 (standard on-hand process).

### 0d: First-run setup

No sigma trunk found anywhere. Initialize a new project:

1. **⚠ MANDATORY POPUP** via AskUserQuestion: "Buffer scope?" — Full / Lite
   - Full — Concept maps, convergence webs, conservation, tower archival.
     For research projects, multi-source analysis, deep domain work.
   - Lite — Decisions and threads only. For everyday development,
     quick projects, session continuity without research infrastructure.
   Wait for response before continuing.
2. **⚠ MANDATORY POPUP** via AskUserQuestion (Full only): "Project name + one-sentence core insight." Wait for response.
3. **⚠ MANDATORY POPUP** via AskUserQuestion: "Remote backup?" (see off skill first-run flow). If creating a new repo, default to **private** (`gh repo create <name> --private`). Only create public if user explicitly requests it. Wait for response.
4. Initialize `.claude/buffer/` with scope-appropriate schemas:
   - **Target directory**: If a git repo was found (via Step 0a), create the
     buffer inside the git repo's `.claude/buffer/`, even if cwd is a parent
     directory. If no git repo was found, create in cwd (lite users without git).
   - **Lite**: `buffer_mode`, `session_meta`, `active_work`, `open_threads`, `recent_decisions`, `instance_notes`, `natural_summary`
   - **Full**: Full schema including `concept_map_digest`
5. Write `.claude/buffer.config.yaml` — machine-readable mode marker:
   ```yaml
   # Generated by /buffer:on first-run — do not edit manually
   mode: lite | full
   project: [project name]
   created: [YYYY-MM-DD]
   ```
   This file is read by the sigma hook and other tools to determine buffer mode
   without parsing the full hot layer.
6. Register in global project registry (see Step 0e)
7. Configure MEMORY.md integration (see Step 0f)
8. Confirm: "Sigma trunk initialized in [scope] mode. Ready to go."
9. Arm autosave (see Autosave Protocol below)
10. **Stop here** — no previous state to reconstruct. Wait for user direction.

### 0e: Register in global project registry

Read (or create) `~/.claude/buffer/projects.json`:

```json
{
  "schema_version": 2,
  "projects": {
    "[project-name]": {
      "repo_root": "[absolute path to git repo root, from git rev-parse --show-toplevel]",
      "buffer_path": "[repo_root]/.claude/buffer",
      "scope": "full | lite",
      "last_handoff": "YYYY-MM-DD",
      "project_context": "[one-sentence description]"
    }
  }
}
```

For lite users without a git repo, `repo_root` equals the working directory.
Add the current project if not already registered. Write back.

### 0f: MEMORY.md integration (first-run only)

After registering the project, configure how MEMORY.md and the sigma trunk coexist. This runs **once** during first-run setup.

1. Locate MEMORY.md (check repo root, `.claude/`, `~/.claude/projects/*/memory/`)

2. **If MEMORY.md exists** — **⚠ MANDATORY POPUP**: You MUST present the following options via `AskUserQuestion`. Do NOT choose for the user. Do NOT skip this step. Wait for the response before continuing.

   Options:
   - **Full integration** — Restructure MEMORY.md into a lean orientation card
     (~50-60 lines): project location, architecture, parameters, preferences,
     and a pointer to the sigma trunk. Theoretical definitions and source mappings
     migrate to the trunk's concept_map. No content is lost.
   - **No integration** — Leave MEMORY.md as-is. The sigma trunk operates
     independently. Duplicate content may load in /buffer:on sessions.

3. Record the choice in the hot layer:
   ```json
   "memory_config": {
     "integration": "full" | "none",
     "path": "[resolved MEMORY.md path]"
   }
   ```

4. **If full integration**:
   - Read MEMORY.md completely
   - **Keep in MEMORY.md**: project location, architecture, key parameters, user preferences, completed stages (compress to one line per stage)
   - **Migrate to sigma trunk**: current status/next action to `active_work` (already in hot), forward note details to `open_threads` or warm entries with `ref` fields. In Full mode with alpha, also migrate theoretical concept definitions — see `full-ref.md` for concept map migration details.
   - Rewrite MEMORY.md in orientation card format:
     - Keep sections listed above
     - Add `## Status` one-liner: `**Status**: [current_phase]. Next: [next_action].`
     - Add `## Sigma Trunk Integration` pointer:
       ```
       Theoretical framework, cross-source mappings, and session state live in
       `.claude/buffer/`. Run `/buffer:on` for full working context. This file is the
       orientation card — enough for standalone sessions, no duplication with the trunk.
       ```

5. **If no integration**: skip.

6. **If MEMORY.md does not exist**: create a minimal orientation card with project location (from git/cwd) and a sigma trunk pointer. Set `memory_config.integration` to `"full"`.

---

## Standard On-Hand Process

Run these steps when a sigma trunk was found (Steps 0a-0c succeeded).

### Step 0d: Mark session active

Read `.claude/buffer/.session_active` if it exists. It's a JSON file: `{"date": "YYYY-MM-DD", "off_count": N}`.

- If it **doesn't exist** or the `date` is **not today**: write `{"date": "[today]", "off_count": 0}` — fresh session.
- If it **exists** and the `date` **is today**: keep the existing `off_count` — this is a continuation of the same session (e.g., after a reload or compaction recovery).

This marker tells the statusline (and other tools) that the buffer is loaded and active. The `off_count` tracks how many times `/buffer:off` has been run this session — a signal of session depth and context recycling.

### Step 0d-b: Write compaction directives

Create `.claude/buffer/compact-directives.md` with four sections:

1. **On Disk** — list every buffer file that actually exists on disk:
   handoff.json, handoff-warm.json, handoff-cold.json, alpha/ directory,
   briefing.md, forward_notes.json. Only list files you confirmed exist.

2. **Active Threads** — copy from `open_threads` in the handoff.json you
   just loaded. One line per thread with its status and any reference.

3. **Already Persisted** — note what data is already saved in the trunk
   from previous sessions.

4. **Session Vocabulary** — leave empty. Terms will be added during the
   session as novel concepts emerge.

Also, ensure the project's CLAUDE.md contains a `## Compaction Guidance`
section. If it doesn't exist, add it. If it exists, replace it. The section
content:

```
## Compaction Guidance

When compacting this conversation, follow these priorities:

- ALREADY ON DISK (do not reproduce in summary):
  - Session buffer trunk: .claude/buffer/handoff.json (threads, decisions, state)
  - Alpha bin: .claude/buffer/alpha/ (concept definitions, glossary)
  - Git history: recoverable via tools
- PRESERVE IN SUMMARY (context-only, not on disk):
  - Active thread of work and current task state
  - Decisions made since last save
  - User preferences or corrections expressed this session
  - Session vocabulary (terms with specific meaning coined this session)
- End your summary with 1-2 sentences capturing exactly what was being
  discussed in the most recent exchange — the immediate context the user
  will expect to resume from.
- Project glossary and concept definitions are in the alpha bin. Standard
  project terms can be used without re-defining. Only preserve definitions
  for terms coined THIS session.
```

During this session, if you coin or adopt a term with specific meaning
(neologism, repurposed word, project-specific shorthand), add it to the
Session Vocabulary section of compact-directives.md with a 1-sentence
definition. Keep to ~5-10 entries. Standard technical vocabulary and terms
already in the alpha bin don't belong here.

### Step 1: Read hot layer only

Read `.claude/buffer/handoff.json` (~200 lines). This is the only mandatory read at startup.

- If `schema_version` is missing or < 2, inform the user: "Found v1 sigma trunk. Run `/buffer:off` first to migrate to v2 format."

### Step 1b: Alpha bin detection (Full + Alpha only)

> If `buffer_mode` is `"full"` AND `alpha/index.json` exists: read `full-ref.md` and run the alpha detection protocol there. Otherwise skip to Step 1c.

### Step 1c: Lite alpha upgrade detection

> Runs after Step 1b. Checks if lite alpha entries exist that could be upgraded.

If `alpha/index.json` exists, scan sources for any with `"mode": "lite"`:

1. Count lite entries: sources where `mode` is `"lite"` in the alpha index
2. **If zero lite entries**: skip to Step 2
3. **If lite entries found AND `buffer_mode` is `"full"`**:

   **⚠ MANDATORY POPUP** via AskUserQuestion:
   - **Upgrade now** — "Found [N] lite alpha entries from [M] sources. These were indexed via Claude's native reading. The distill plugin can re-analyze them through full five-pass extraction for deeper concept mapping and convergence web linking. This takes ~2-5 minutes per source."
   - **Upgrade later** — "Keep lite entries as-is. They work for basic sigma matching. You can upgrade anytime by running `/distill` on the original sources."
   - **Never upgrade these** — "Mark these entries as lite-permanent. They won't be offered for upgrade again."

   Wait for response.

   - If **Upgrade now**: For each lite source, check the `source` field:
     - If path exists → queue for distillation: "Ready to re-distill [N] sources. Run `/distill` to process them."
     - If URL → note for fetch: "Source [label] is a URL — will fetch during distillation."
     - If "ask user" → **⚠ MANDATORY POPUP**: "Where is the source document for [entry title]?"
   - If **Upgrade later**: continue to Step 2
   - If **Never upgrade**: add `"lite_permanent": true` to each lite source entry in `alpha/index.json`, continue to Step 2

4. **If lite entries found AND `buffer_mode` is `"lite"`**: note silently:
   ```
   Alpha: N lite entries across M sources (install distill plugin for full analysis)
   ```

### Step 2: Git grounding

Ground the session in actual repo state:

```bash
git log --oneline <session_meta.commit>..HEAD   # commits since last handoff
git status                                       # current working tree
git diff --stat                                  # uncommitted changes
```

Present the results:
```
## Repo state
**Sigma trunk recorded**: [commit] on [branch] ([date])
**Current HEAD**: [commit] on [branch]
**Commits since handoff**: [count] — [one-line summaries if any]
**Working tree**: [clean / N modified files]
```

If there are commits or changes not recorded in the sigma trunk, flag them — the trunk may be stale.

### Step 2b: Read session briefing

If `.claude/buffer/briefing.md` exists, read it and present its contents. This is the previous instance's colleague-to-colleague handoff — narrative context for how the last session developed. Present it before the structured state.

```
## Briefing from previous instance
[contents of briefing.md — presented as-is, not summarized]
```

If no `briefing.md` exists but `.claude/buffer/beta/narrative.jsonl` does, fall back to the beta bin:

```bash
buffer_manager.py beta-read --buffer-dir .claude/buffer/ --min-r 0.5 --limit 10
```

Present the high-relevance entries as a timeline narrative:
```
## Session narrative (from beta bin)
[entries formatted as: timestamp — text]
```

If neither exists, continue to Step 3 without narrative context.

### Step 3: Present session state

From the hot layer only:

```
## Last Session: [date]
**Commit**: [hash] on [branch]
**Phase**: [current_phase]
**Completed**: [list]
**In Progress**: [item or "nothing pending"]
**Next Action**: [next_action]

## Natural Summary
[natural_summary text]
```

### Step 4-5: Pointer following + Full-scan (Full + Alpha only)

> If `buffer_mode` is `"full"` AND `alpha/index.json` exists: read `full-ref.md` and run Steps 4 and 5 from there. Otherwise skip to Step 6.

### Step 6: Surface instance notes

> In lite mode, instance notes are still present — surface them if they exist.

If the hot layer has an `instance_notes` section, present it:

```
## Notes from the previous instance
[remarks — paraphrased naturally, not as a JSON dump]

**Open questions:**
- [question 1]
- [question 2]
```

These questions are worth surfacing — the user may want to address them.

**Dialogue style adoption**: If `instance_notes.dialogue_style` exists, read it and adopt that conversational register from your first response onward. Don't announce it ("I'll be casual now") — just *be* it. The goal is continuity: the user shouldn't feel a tonal shift between sessions.

### Step 7: Read MEMORY.md

Read the project memory file for baseline context. The sigma trunk is the session alpha stash; MEMORY.md is the project baseline.

If the memory file path is not specified in a project skill, look for:
- `MEMORY.md` in the repo root
- `.claude/MEMORY.md`
- `~/.claude/projects/*/memory/MEMORY.md`

### Step 8: Arm autosave and confirm

Compute the gap between today and `session_meta.date` from the hot layer.

Tell the user:

```
buffer v3.3.2 | [scope] mode | Alpha: N referents (if present) | W: [ratio]
Context reconstructed from [date] handoff ([N days ago]). Ready to continue from [current_phase].
Autosave armed — sigma trunk will stay current throughout the session.
```

If the handoff is >7 days old, add: "Note: trunk is [N] days stale — git state may have diverged significantly."

If `football_in_flight` is `true` in the hot layer, add after the confirmation line: "Note: a football is in flight (thrown [thrown_at date]). Run `/buffer:catch` when the worker returns."

Write the sigma hook session marker so the hook skips redundant hot-layer hints (the AI already has the full hot layer loaded):
```bash
echo "loaded" > .claude/buffer/.buffer_loaded
```

**⚠ MANDATORY POPUP**: You MUST present a priority check via `AskUserQuestion` before doing any work.
Do NOT start working on the next action, even if you know what it is. Do NOT skip this popup. The user decides what comes first.

`AskUserQuestion` options:
- Proceed with [next_action or first open_thread]
- Different priority (let user specify)

Even if the reconstructed context makes the next step obvious, **stop and ask**. The user may have a different priority today than when the last handoff was written.

---

## Autosave Protocol

Armed automatically when on-hand completes (Step 8). The instance fires autosaves silently at natural completion boundaries. **The user does not trigger these — they are automatic.**

### When to fire

- After a distillation pipeline completes (all post-distillation updates done)
- After a test suite passes following an implementation phase
- After a significant discussion produces a named decision
- When the user shifts to a different topic or task
- Before the context window is critically full (self-preservation)

### What to write (lightweight — NOT a full handoff)

Update the hot layer (`handoff.json`) only:

1. `session_meta.date` — current date
2. `session_meta.commit` — current HEAD
3. `active_work` — current phase, completed items, in-progress, next action
4. `recent_decisions` — append new decisions since last autosave
5. `open_threads` — update statuses (resolved, new threads)
6. `concept_map_digest` — Full mode only: update if concept map changed this autosave interval
7. `natural_summary` — one-sentence update appended: "[autosave] [brief note]"
8. **Beta narrative entry** — Write a 1-3 sentence narrative entry to the beta bin capturing what happened since the last autosave. Assign a relevance score (0.0-1.0) based on the heuristics below. If nothing narratively significant happened, skip the beta entry (don't write noise).

   ```bash
   echo '{"tick":"autosave","r":0.45,"text":"...","tags":["..."]}' | buffer_manager.py beta-append --buffer-dir .claude/buffer/
   ```

   **Relevance scoring heuristics** (additive, base=0.2, capped at 1.0):
   | Signal | +Score | Example |
   |--------|--------|---------|
   | User correction | +0.3 | "Term X means Y not Z" |
   | Named decision | +0.2 | "Chose inline extraction over cross-plugin" |
   | Convergence | +0.3 | "Source A and Source B converge on same structure" |
   | Surprise / unexpected | +0.2 | "Mapping was structural, not metaphorical" |
   | Framework touch | +0.2 | Relates to foundational concepts |
   | User emphasis | +0.3 | User explicitly flagged importance |
   | Routine progress | +0.0 | "Continuing implementation" |
   | Mechanical | +0.0 | "Tests pass", "committed" |

   **Examples:**
   - Low (r=0.2): `"Tests passing after routine fix. Moving to next phase."`
   - Medium (r=0.5): `"Decision: chose inline extraction over cross-plugin call. Avoids dependency."`
   - High (r=0.8): `"User corrected my interpretation of key term — it's X, not Y."`

Write hot layer (`handoff.json`) and beta entry only. Do not touch warm or cold layers.

**Mode-specific autosave:**
- **Lite**: Write `session_meta`, `active_work`, `open_threads`, `recent_decisions`, `instance_notes`, `natural_summary`. Skip `concept_map_digest`.
- **Full**: All fields including `concept_map_digest`. See `full-ref.md` for concept map autosave details.

### What to skip (reserved for full /buffer:off)

- Instance notes (these are end-of-session reflections)
- Full natural summary regeneration
- Warm/cold layer writes
- Git commit (autosaves are sigma trunk saves, not commit-worthy)

### Overflow guardrail

Before writing, check whether the updated hot layer exceeds 200 lines. If it does:

1. **Do NOT silently migrate** — autosave cannot push content to warm/cold on its own
2. **⚠ MANDATORY POPUP**: You MUST present these options via `AskUserQuestion`. Do NOT silently trim or skip.

   Options:
   - **Run /buffer:off** — "Hot layer is at [N] lines (limit: 200). Run a full handoff now to conserve with your input."
   - **Trim to essentials** — "Skip older decisions/threads and save only current state."
   - **Skip autosave** — "Sigma trunk stays at last state. Nothing written."

3. Wait for user choice before proceeding. Do NOT continue until the user has answered.

The same principle applies transitively: if a full `/buffer:off` would cascade warm to cold or cold to archival, those operations already require user input (the archival questionnaire in `/buffer:off` Step 9). Autosave simply refuses to start that cascade silently.

**Rule:** Autosave can *update* hot. Autosave cannot *overflow* hot. Overflow = user decision.

### How to fire

- **Silently** — no announcement unless the user has asked about sigma trunk state
- On success with no overflow, emit exactly: `(autosaved)` — nothing else, no elaboration
- If overflow detected, prompt the user (see guardrail above)
- If it fails (permission error, path issue), warn the user

### Post-Compaction Consistency Check

When context compaction occurs (the system injects a summary of earlier conversation), the instance has lost detailed dialogue context but retains the compaction summary and full access to sigma trunk files on disk.

**Hook-assisted activation**: If the project has compaction hooks configured, the hooks handle this automatically:

1. **PreCompact hook** fires *before* compaction — autosaves the hot layer with current commit hash and `[compacted]` marker
2. **SessionStart:compact hook** fires *after* compaction — injects a concise sigma trunk reconstruction (session state, orientation, threads, decisions, instance notes, layer sizes) as `additionalContext`, plus a directive to run the consistency check below

The post-compaction instance receives the sigma trunk context in a system-reminder and should see the "REQUIRED: Post-Compaction Consistency Check" directive. If hooks are NOT configured, this check is still **self-activating**: it fires whenever compaction is detected AND sigma trunk files exist on disk, regardless of whether `/buffer:on` was run or autosave was explicitly armed.

**Immediately after detecting compaction (whether via hook or self-detection), before resuming any other work:**

1. Read `handoff.json` (hot layer) — or use the hook-injected summary if available
2. Compare `active_work` and `open_threads` against the compaction summary:
   - Is `current_phase` still accurate?
   - Does `completed_this_session` reflect what the summary says was done?
   - Are `open_threads` statuses consistent with the summary?
   - Does `next_action` still make sense given what was discussed?
3. If any mismatches: update the hot layer in place (same write rules as autosave — hot only)
4. Verify `natural_summary` has `[compacted]` marker (the PreCompact hook adds this; if missing, append `"[compacted] Context compacted mid-session."`)
5. **Do NOT attempt warm-layer review** — the instance no longer has the full dialogue context that informed those entries. Warm-layer work with partial context risks losing distinctions the instance no longer remembers were important.
6. Arm autosave
7. Resume the user's work

**Principle**: Be transparent about operating on a summary. A post-compaction instance should treat inherited warm entries with the same caution as an inherited-entry review — propose changes to the user, don't auto-modify.

This check is lightweight (read hot, compare, fix mismatches) and honest about its limitations. It catches gross mismatches without pretending the instance still has full context.

**Hook setup**: The buffer plugin configures compact hooks automatically via
hooks/hooks.json. No manual configuration needed. If using the sigma trunk system without
the plugin, configure PreCompact (manual + auto matchers) and SessionStart hooks
pointing to compact_hook.py.

### Autosave vs Handoff vs Post-Compaction

| | Autosave | `/buffer:off` | Post-Compaction |
|---|---|---|---|
| **Trigger** | Automatic, at completion boundaries | Manual (`/buffer:off`) or end-of-session | Automatic, on compaction detection |
| **Scope** | Hot layer only | All layers (hot + warm + cold) | Hot layer only (consistency check) |
| **Conservation** | None — prompts user if overflow detected | Full migration + size enforcement | None |
| **Instance notes** | None | Written fresh | None |
| **Git commit** | No | Yes | No |
| **Warm-layer work** | No | Yes (consolidation) | **No** — insufficient context |
| **User interaction** | Only on overflow | Confirms completion | None (silent) |

---

## Lite Alpha: Document Indexing (Lite mode only)

> Skip this section entirely if `buffer_mode` is `"full"`. Full mode uses the distill plugin for document analysis.

Lite alpha lets users index documents without Python dependencies or the distill plugin. Claude reads the document natively and writes a simple w: entry.

### When to use

When a user shares a document (PDF, URL, image, text file) during a lite-mode session and says something like "remember this", "index this", "add this to the buffer", or otherwise indicates they want the content tracked.

### Process

1. Read the document using Claude's native capabilities (Read tool for PDFs/images/text, WebFetch for URLs)
2. Extract key concepts (3-7 per document, focus on what's operationally useful)
3. Write a w: entry to `.claude/buffer/alpha/` as a simple markdown file

### Entry format

```markdown
# w:[N] — [short title]

**Source**: [path, URL, or "ask user — shared in session [date]"]
**Mode**: lite
**Indexed**: [YYYY-MM-DD]

## Key Concepts
- [concept 1]: [1-sentence definition as used in this document]
- [concept 2]: [1-sentence definition]
- [concept 3]: [1-sentence definition]

## Summary
[2-4 sentences capturing the document's core contribution]
```

### Rules

- **Source is a reference, not a copy.** Never rename, move, or duplicate the original file. Store only the path or URL.
- **`mode: lite` marker** is mandatory. This tells the distill plugin (if installed later) that the entry was created via lite indexing and can be upgraded through full analysis.
- **No convergence web.** Lite entries are standalone — no `cw:` links, no cross-source mapping.
- **ID assignment**: Use `next-id` from `buffer_manager.py` if available. Otherwise, read existing files in `alpha/` and pick the next sequential number.
- **Index update**: If `alpha/index.json` exists, add the entry to `concept_index`. If not, create a minimal index:
  ```json
  {
    "sources": { "[source-label]": { "path": "[source-ref]", "mode": "lite" } },
    "concept_index": { "[concept-1]": ["w:N"], "[concept-2]": ["w:N"] }
  }
  ```
- **Max 7 concepts per entry.** Lite indexing is a quick sketch, not a deep analysis.
- **No figures.** Lite alpha does not extract or store figures.
