---
name: integrate
description: Post-distillation updates to project indexes, session buffer, and reference bin. Detects buffer plugin silently — works standalone or with full buffer integration.
---

# Post-Distillation Integration

Update project indexes, session buffer, and reference bin after distillation completes.

## Cross-Plugin Script Discovery

`buffer_manager.py` belongs to the **buffer plugin**, not this plugin. Locate it once at skill start:

```bash
find ~/.claude/plugins/cache -name buffer_manager.py -path "*/buffer/*/scripts/*" 2>/dev/null | head -1
```

Store the result as `<buffer_scripts>` for all `buffer_manager.py` commands below. If not found, enter File-Only Mode.

## Mode Detection

Detect buffer plugin availability **silently** — no error messages if absent.

```
Buffer plugin detected = ALL of:
  1. buffer_manager.py found via cross-plugin discovery above
  2. .claude/buffer/ directory exists with at least handoff.json
```

- **Full Integration Mode**: buffer plugin detected — write to reference bin, update convergence network, manage marker file.
- **File-Only Mode**: no buffer plugin — produce output files, update INDEX.md and README only.

---

## Full Integration Mode

### Step 0: Write Distill-Active Marker

Before any buffer writes, set the marker that prevents the live matching hook from firing:

```bash
echo "active" > .claude/buffer/.distill_active
```

MUST be written before Step 2 and removed in cleanup. If integration fails mid-way, cleanup still removes it.

**Crash safety**: The sigma hook has a 4-hour TTL on this marker. If the skill crashes and the marker is not cleaned up, sigma will auto-recover after 4 hours. However, you MUST still attempt cleanup on any failure path — run `rm -f .claude/buffer/.distill_active` before reporting errors to the user. The TTL is a last-resort safety net, not a substitute for explicit cleanup.

### Step 1: INDEX.md Update

**Existence check first**: Check if the project index file exists before reading or generating.
- **If it exists**: Read it, find the correct category table, and add/update the row using the row format below.
- **If it does not exist**: Create it from the canonical structure below. Do NOT generate a custom format.

**Canonical INDEX.md structure** (use this when creating a new index — this IS the pattern, do not read existing files to learn it):

```markdown
# Source Material Index

Status key: `unread` | `partial` | `mapped` | `foundational` | `distilled`

All distilled versions are in `distilled/` subdirectory.

## [Category Name]

| File | Author | Status | Distilled | Mapped To | Notes |
|---|---|---|---|---|---|
| [source filename] | [Author(s)] | distilled | [Source-Label.md](distilled/[Source-Label].md) | [comma-separated concept mappings, e.g., "concept_a→framework_x, concept_b→framework_y"] | [interpretation link if exists] + [key stats: N key concepts, M project mappings (X confirms, Y extends, Z novel). N figures. N alpha entries (w:NNN–w:MMM), N convergence web entries (cw:NNN–cw:MMM). 1-2 sentence summary of what this source contributes] |

## [Another Category]

| File | Author | Status | Distilled | Mapped To | Notes |
|---|---|---|---|---|---|
```

**Category assignment**: Group sources by domain (e.g., "TAP Literature", "Philosophical Sources", "Empirical", "Web Resources"). If the source doesn't fit an existing category, create a new one. Each category has its own table with identical column headers.

**Row format rules**:
- `Mapped To`: Comma-separated `source_concept→project_element` pairs, truncated to ~5 most significant. Use `---` if `project_map_type = none` or `pure_mode`.
- `Notes`: Start with interpretation link `[interpretation](interpretations/[Source-Label].md)` if one exists. Then key distillation stats. Then 1-2 sentences of substantive summary. This field IS the primary discovery interface — make it information-dense.
- If redistilled, prefix notes with `**Re-distilled**`.

If no index file exists, create one with the header above and the first row. INDEX.md always runs regardless of mode.

### Step 2: Buffer Update

**Guard**: Verify `.claude/buffer/` exists with at least `handoff.json`. If missing, skip all buffer updates and log: "Buffer update skipped: no handoff buffer found." All buffer writes are **alpha-aware**: check for `alpha/index.json` first, fall back to warm-layer writes if alpha does not exist.

#### Lite Alpha Upgrade (automatic)

Before any alpha write, check if `alpha/index.json` has existing entries for this source with `"mode": "lite"`. If found:

1. Inventory the lite entries (IDs, concept keys, source reference)
2. The full distillation supersedes them — delete the lite entries:
   ```bash
   python <buffer_scripts>/buffer_manager.py alpha-delete --buffer-dir .claude/buffer/ --id w:N [w:M ...]
   ```
3. Proceed to the standard alpha write below — new full entries replace the lite ones
4. Log in warm `validation_log`:
   ```json
   {"check": "lite_upgrade", "status": "UPGRADED", "detail": "Source [label]: [N] lite entries replaced by [M] full entries", "session": "[date]"}
   ```

This is seamless — no user interaction needed. The full distillation naturally produces richer entries that subsume the lite sketch. The lite `source` reference was used to locate the original document; its job is done.

#### Redistillation Alpha Handling (if redistill_mode is set)

**Guard**: Only run this section if the extraction step passed a `redistill_mode` value (`archive`, `update`, or `delete`). If `redistill_mode` is `null` or absent, skip to the standard alpha write below.

**Step 2a: Inventory existing entries** — Scan `alpha/index.json` for all entries where `source` matches the source folder (kebab-case of source label). Collect their IDs, concept keys, and file paths.

```bash
python <buffer_scripts>/buffer_manager.py alpha-query --buffer-dir .claude/buffer/ --source [kebab-case-source]
```

**Step 2b: Handle by mode**:

**`archive` mode**:
1. Existing alpha `.md` files are left in place (they reference the archived distillation via `_v[N]` suffix).
2. Add `"redistill_archived": "[date]"` to each existing entry in `index.json`. These entries are still valid — they reference the older version.
3. Proceed to standard alpha write below for the new distillation's concepts. New entries get fresh IDs.
4. After new entries are written, scan for concept key overlaps between old and new. For each overlap, add a `"supersedes": "w:OLD"` field to the new entry and a `"superseded_by": "w:NEW"` field to the old entry. This preserves the convergence web while linking versions.

**`update` mode**:
1. For each concept in the new interpretation's Project Significance table, check if an existing alpha entry has the same concept key (case-insensitive, separator-normalized).
2. **Match found**: Update the existing entry's `.md` file body in place. Preserve the original w: ID. Use `alpha-enrich` to replace the body content:
   ```bash
   echo '[{"id":"w:NNN","body":"## Definition\n...updated content..."}]' | python <buffer_scripts>/buffer_manager.py alpha-enrich --buffer-dir .claude/buffer/
   ```
3. **No match** (genuinely new concept): Create via standard `alpha-write` below.
4. **Orphaned** (old entry's concept key not in new interpretation): Add `"orphaned_by_redistill": "[date]"` to the entry in `index.json`. Clear `distillation` and `marker` fields (the old distillation no longer has this concept). The entry falls back to `.md` file reading via `alpha-query`. Do NOT delete the entry — convergence web edges may depend on it. Log in validation_log with status `ORPHANED`.

**`delete` mode**:
1. Delete all existing alpha `.md` files for this source:
   ```bash
   python <buffer_scripts>/buffer_manager.py alpha-delete --buffer-dir .claude/buffer/ --id w:NNN
   ```
   Repeat for each entry ID from the inventory.
2. Scan convergence web entries (`cw:` IDs) for any that reference the deleted w: IDs in their `thesis.ref` or `athesis.ref` fields. For each dangling reference:
   - If BOTH sides are deleted: delete the cw: entry too.
   - If ONE side is deleted: mark the cw: entry with `"dangling": "w:NNN deleted [date]"`. Do NOT auto-delete — the surviving side may still be meaningful.
3. Proceed to standard alpha write below for the fresh distillation.

After any redistillation mode, log the action in warm `validation_log`:
```json
{"check": "redistill", "status": "[mode]", "detail": "Source [label]: [N] existing, [M] updated/orphaned/deleted, [K] new", "session": "[date]"}
```

**Step 2c: Generate redistill changelog** — After all alpha writes/updates/deletes for a redistillation are complete, write a `.redistill_changelog` JSON file to the source's alpha folder (`[alpha_dir]/[kebab-case-source]/.redistill_changelog`):

```json
{
  "source_label": "[Source-Label]",
  "redistill_date": "[today ISO date]",
  "mode": "[archive|update|delete]",
  "iteration": [N],
  "previous": {
    "date": "[date of last distillation from manifest]",
    "concept_count": [count from inventory],
    "concept_keys": ["key1", "key2"]
  },
  "current": {
    "concept_count": [new count],
    "concept_keys": ["key1", "key3"]
  },
  "diff": {
    "added": ["key3"],
    "removed": ["key2"],
    "retained": ["key1"],
    "modified": []
  },
  "alpha_changes": {
    "new_ids": ["w:NNN"],
    "updated_ids": ["w:MMM"],
    "orphaned_ids": ["w:OOO"]
  }
}
```

Schema: `schemas/redistill-changelog.schema.json`. The `iteration` field is the manifest source's `iteration` count (should be >= 2 for any redistillation). The `previous` data comes from the Step 2a inventory. The `diff` is computed by comparing previous and current concept key sets.

**Manifest update**: After writing the changelog, update the source's manifest entry to include a `redistill_history` record:
```json
{"date": "[today]", "mode": "[mode]", "concept_count": [new count], "changelog_path": "[alpha_dir]/[source]/.redistill_changelog"}
```
Use `distill_manifest.py update` with the `--redistill-history` flag (if available) or append directly to the source entry's `redistill_history` array.

#### concept_convergence type (alpha path)

Draw mappings from the interpretation file's Project Significance table and Integration Points. For each concept mapping, build a **thin** JSON object with marker reference and pipe to `alpha-write`. The complete schema is specified below — do NOT read existing alpha entries to learn the format:

```bash
echo '[
  {"type":"cross_source","source_folder":"[kebab-case-source]",
   "distillation":"[Source-Label].md",
   "marker":"[concept_key]",
   "key":"Source:ConceptName","maps_to":"[project framework mapping]",
   "ref":"[source citation]","suggest":null,
   "body":null},
  {"type":"cross_source","source_folder":"[kebab-case-source]",
   "distillation":"[Source-Label].md",
   "marker":"[another_concept_key]",
   "key":"Source:AnotherConcept","maps_to":"[mapping]",
   "ref":"","suggest":null,
   "body":null}
]' | python <buffer_scripts>/buffer_manager.py alpha-write --buffer-dir .claude/buffer/
```

**Marker reference**: The `marker` field is the concept key matching `<!-- CONCEPT:[key] -->` markers in the distillation file. Derive it: lowercase, remove parentheticals, strip special chars, spaces→underscores, truncate at 40 chars. Example: `"Wholeness (W)"` → `wholeness_w`.

**Body = null**: The distillation file content behind the marker IS the canonical recall artifact. `alpha-query --id` extracts it via marker-based retrieval (single file pass, batch-capable). No duplication needed.

**When body is NOT null**: If the concept needs project-specific integration notes beyond what's in the distillation (e.g., codebase parameter mappings, implementation context), include a short body (<10 lines). This supplements marker retrieval, not replaces it.

The command auto-assigns IDs, writes `.md` files (body content if provided, stub if null), and updates `alpha/index.json` with `distillation` and `marker` fields. Read the output JSON to get assigned IDs.

#### Alpha Entry Retrieval Architecture

Alpha entries are **thin pointers** into marked distillation files. Content retrieval works via `alpha-query --id`, which:
1. Checks index.json for `distillation` and `marker` fields
2. If present: extracts content between `<!-- CONCEPT:[key] -->` markers from the distillation file (single file pass, batch-capable, ~10-20 lines returned per concept)
3. If absent: falls back to reading the alpha `.md` file directly

**Token economics**: 5 concepts via marker extraction ≈ 275 tokens (vs ~750 tokens reading 5 enriched `.md` files). The distillation file is the single source of truth — no content duplication.

**When to include a body**: Only when the concept needs project-specific integration notes that are NOT in the distillation (e.g., codebase parameter mappings, implementation-specific context). Keep body <10 lines. Most entries should have `body: null`.

**Legacy compatibility**: Old entries with enriched `.md` files (body ≠ null, no marker field) continue to work. `alpha-query` falls back to file reading automatically.

After `alpha-write` succeeds, update hot layer: add `"status": "NEW"` entry to warm `validation_log`; increment `total_entries` in hot `concept_map_digest` and add new IDs to `recent_changes`.

#### concept_convergence type (warm fallback)

Read `handoff-warm.json`. In `concept_map.cross_source`, add a mapping entry per concept:

```json
"Source:ConceptName": {
  "maps_to": "[project framework mapping]",
  "ref": "[forward note reference if applicable]",
  "suggest": null
}
```

Do NOT write distillation run summaries to `validation_log` -- concept map changes only.

#### thematic type

From the interpretation file's Thematic Relevance table: update `themes.entries[].sources[]` for existing themes with "strong" evidence; add new entries for NEW themes; increment `themes._meta.total_themes` accordingly.

#### narrative type

From the interpretation file's Entities, Timeline, and Plot Threads: add new entities to `entities.entries[]`, timeline events to `timeline[]`, plot threads to `plot_threads[]`. Increment counts in `_meta`.

#### custom type

Follow the custom schema's update rules defined during differentiation.

### Step 3: MEMORY.md Update

**Guard**: Check `memory_config.integration` in the handoff buffer:
- `"none"` or field missing: skip entirely.
- `"minimal"`: skip -- pointer section managed by the handoff skill.
- `"full"`: ONLY add to `## Stable Definitions`. Respect the 200-line MEMORY.md cap; if exceeded, skip and log.

When proceeding: from the **interpretation file**, ONLY add concepts that are genuinely new, significant, and project-relevant. Maximum 3 entries per distillation.

### Step 4: Convergence Network Update

**concept_convergence type ONLY.** All other types skip this step.

From the interpretation file's Project Significance table and Integration Points, identify inter-source connections:
- For each concept mapped with relationship "confirms" or "extends": check if the confirmed/extended concept came from a DIFFERENT source.

#### Alpha path

Use `python <buffer_scripts>/buffer_manager.py alpha-write` for convergence network entries:

```bash
echo '{"type":"convergence_web","source_folder":"[source-folder]",
  "thesis":{"ref":"w:X","label":"SourceA:Concept"},
  "athesis":{"ref":"w:Y","label":"SourceB:Concept"},
  "synthesis":"[type_tag] What RELATES them -- shared structural ground (involutory)",
  "metathesis":"What EACH does independently in its own domain (evolutory)",
  "context":"[1-2 sentences explaining why this convergence matters for the project — what architectural or theoretical insight it unlocks]"}' | python <buffer_scripts>/buffer_manager.py alpha-write --buffer-dir .claude/buffer/
```

Auto-assigns `cw:N` IDs, writes canonical `.md` files (with optional `## Context` section), updates `alpha/index.json` atomically.

#### Warm fallback

Create the entry in the warm handoff buffer at `convergence_web.entries[]`.

#### Entry structure (both paths)

```json
{
  "id": "cw:N",
  "thesis": { "ref": "w:X", "label": "SourceA:Concept" },
  "athesis": { "ref": "w:Y", "label": "SourceB:Concept" },
  "synthesis": "[type_tag] What RELATES them -- shared structural ground (involutory)",
  "metathesis": "What EACH does independently in its own domain (evolutory)"
}
```

Type tags: `[independent_convergence]`, `[complementarity]`, `[elaboration]`, `[tension]`, `[genealogy]`, `[wall]` (anti-conflation — concepts look similar but MUST NOT be conflated; inhibitory edge).

After writing entries, update hot layer `convergence_web_digest`:
- Increment `_meta.total_entries`
- If new entry creates a new thematic cluster, add to `clusters` array

### Step 4b: Forward Note Registry

**Guard**: Only run if the interpretation file contains forward note candidates (lines matching `§5.\d+`).

After convergence network writes, scan the interpretation for forward note candidates and update the project-level registry at `<repo>/.claude/skills/distill/forward_notes.json`.

**If registry exists**: Read it, add new candidates, increment `next_number`.
**If registry does not exist**: Create it with this structure:

```json
{
  "next_number": 70,
  "notes": {}
}
```

For each `§5.NN` reference in the interpretation file, add an entry if `5.NN` is not already in the registry:

```json
"5.NN": {
  "source": "[Source-Label]",
  "description": "[one-line description from the interpretation]",
  "status": "candidate",
  "date": "[YYYY-MM-DD]"
}
```

After adding all candidates, set `next_number` to `max(existing next_number, highest_seen_number + 1)`.

Status lifecycle: `candidate` → `accepted` → `implemented` → `superseded` → `merged_into`. Integration only writes `candidate`. Other transitions are manual or via consolidation.

### Step 4c: Forward Note Consolidation Check

**Guard**: Only run if new forward note candidates were written in Step 4b.

After writing new candidates, check each against existing notes for potential consolidation. Uses `distill_forward_notes.py check-new` for similarity detection:

```bash
python [plugin-scripts]/distill_forward_notes.py check-new \
  --notes [repo]/.claude/skills/distill/forward_notes.json \
  --description "[new candidate description]" \
  --alpha-dir .claude/buffer/alpha \
  --threshold 0.2
```

**If matches found** (similarity >= 0.2): Append a one-line note to the integration report:

```
Forward notes: N candidates registered. ⚠ §5.XX may relate to §5.YY (similarity: 0.35) — review with /distill --notes-health
```

**Do NOT auto-consolidate.** Only flag for user review. Consolidation is always a manual decision via:

```bash
python [plugin-scripts]/distill_forward_notes.py consolidate \
  --notes [repo]/.claude/skills/distill/forward_notes.json \
  --merge 5.XX 5.YY --into 5.XX --dry-run
```

**Periodic health check**: At integration end (Step 6), if the registry has 20+ notes, append:

```
Forward notes health: run `python distill_forward_notes.py health --notes [path] --alpha-dir [path]` for cluster analysis.
```

### Step 5: Remove Marker and Validate

```bash
rm -f .claude/buffer/.distill_active
python <buffer_scripts>/buffer_manager.py alpha-validate --buffer-dir .claude/buffer/
```

If validation fails, log the failure in Known Issues but do NOT revert writes.

### Step 5b: Rebuild Relevance Grid

**Guard**: Only run if alpha bin exists AND new entries were written in Steps 2/4.

After writing new entries, the reinforcement scores, clusters, and relevance grid are stale. Rebuild them:

```bash
python <buffer_scripts>/buffer_manager.py alpha-reinforce --buffer-dir .claude/buffer/
python <buffer_scripts>/buffer_manager.py alpha-clusters --buffer-dir .claude/buffer/
python <buffer_scripts>/buffer_manager.py alpha-grid-build --buffer-dir .claude/buffer/
```

These run silently (~100ms total for typical corpus). The grid rebuild ensures the sigma hook's per-message O(1) lookup reflects the newly added entries immediately. If any command fails, log it in Known Issues but continue — the sigma hook falls through to IDF scoring gracefully when the grid is absent or stale.

### Step 5c: Manifest Update

**Guard**: Only run if `<repo>/.claude/skills/distill/manifest.json` exists OR can be created.

After alpha writes, grid rebuild, and forward note registry updates, update the distillation manifest:

```bash
python [plugin-scripts]/distill_manifest.py update \
  --manifest [repo]/.claude/skills/distill/manifest.json \
  --source-label [Source-Label] \
  --interp-file [interpretations-dir]/[Source-Label].md \
  --alpha-dir .claude/buffer/alpha \
  --alpha-ids [comma-separated w: IDs from Step 2] \
  --cw-ids [comma-separated cw: IDs from Step 4] \
  --forward-notes [repo]/.claude/skills/distill/forward_notes.json
```

This command:
1. Adds/updates the source entry in the manifest with concept mappings, alpha IDs, cw IDs, and forward notes
2. Computes quality metrics (concept_density, coverage_ratio, cross_ref_density, forward_note_yield, convergence_contribution, composite_quality)
3. Checks for re-pass triggers via spreading activation on the source-source adjacency graph
4. Updates manifest stats

If the manifest does not exist, skip this step silently — manifest bootstrap (`distill_manifest.py init`) should be run first.

### Step 5d: Quality Card & Re-pass Report

**Guard**: Only run if Step 5c succeeded (manifest was updated).

Read the manifest update output (JSON from Step 5c). Append to the integration report:

```
Quality Card: [Source-Label]
  composite_quality: [value]
  concept_density: [value]  coverage_ratio: [value]
  cross_ref_density: [value]  convergence_contribution: [value]
```

If `composite_quality < 0.20`, also append:
```
Quality alert: [Source-Label] composite_quality=[value] — low integration density.
Consider: Is this source peripheral, or should integration be deepened?
```

If the repass queue is non-empty after the update, append:
```
Repass queue: [N] entries. Run /distill --repass to review.
```

### Step 6: Integration Results Summary

Print an **end-to-end distillation report** summarizing the full pipeline. This is informational — no popup or user decision needed. The pipeline proceeds to cleanup automatically.

**Stats collection**: Read `.claude/buffer/.distill_stats` if it exists. This file is written by the `extract` skill (extraction stats) and appended by the `analyze` skill (analysis stats). If the file doesn't exist, fall back to the minimal summary format below.

**Full report** (when `.distill_stats` is available):

```
═══════════════════════════════════════════════════
DISTILLATION REPORT: [Source-Label]
═══════════════════════════════════════════════════

Source:      [filename] ([page count] pages)
Label:       [Source-Label]
Extracted:   [date]

Content:
  Text pages:    [N]
  Tables:        [N] (via [route])
  Figures:       [N] extracted, [M] skipped
  Equations:     [N] pages with math content

Distillation:
  File:          [distillation-dir]/[Source-Label].md
  Key concepts:  [N] identified
  Top concepts:  [list top 5 by significance]

Interpretation:
  File:          [interpretations-dir]/[Source-Label].md
  Mappings:      [N] concepts mapped to project framework
  Relationship:  [N] confirms, [N] extends, [N] challenges, [N] novel

Integration:
  INDEX.md:      [updated | already present]
  Alpha w:       [N] entries (w:XXX–w:YYY)
  Alpha cw:      [N] entries (cw:XXX–cw:YYY)
  Grid rebuild:  [N] primes, [M] clusters
  MEMORY.md:     [updated N defs | skipped]
  Resolution:    [N] entries queued for concept resolution

Forward notes: [N candidates registered (§5.XX–§5.YY) | no candidates]
Known Issues:    [clean run | N issues logged]
═══════════════════════════════════════════════════
```

**Integration health check**: After printing the report, count interpretation files in `[interpretations-dir]/*.md` and compare against alpha-indexed sources. If any interpretation files lack corresponding alpha entries, append:

```
⚠ Integration gap: N interpretation files have no alpha entries.
  Run /distill --recover to backfill missing sources.
```

This is informational only — do not auto-recover.

**Author folder suggestion**: After printing the report, count distillation files per first-author prefix in `[distillation_dir]`. If any author has 3+ distillations and their files are NOT already in a subdirectory, append:

```
📁 [Author] has [N] distillations. Consider organizing into [distillation_dir]/[Author]/?
```

This is a suggestion only — present via `AskUserQuestion` with options "Organize into folder" / "Keep flat". If the user accepts, move the distillation files, interpretation files, and figure directories, then update INDEX.md paths accordingly. If declined, do not ask again for this author (write a `.author_folders_declined` marker with the author name).

**Minimal summary** (when `.distill_stats` is not available — e.g., File-Only Mode):

```
--- Integration Complete ---
INDEX.md: [updated — row added for [Source-Label] | already present — no change]
Alpha entries: [N cross_source written (IDs: w:XXX–w:YYY) | skipped — no buffer]
Convergence web: [M entries written (IDs: cw:XXX–cw:YYY) | 0 new connections found]
Grid rebuild: [N primes, M clusters, K grid cells | skipped — no new entries]
MEMORY.md: [updated — N definitions added | skipped — cap exceeded | skipped — minimal mode]
Validation: [passed | FAILED — see Known Issues]
Known Issues: [clean run | N issues logged]
```

**Resolution queue**: After printing the report, check for unresolved concept entries:
```bash
python <buffer_scripts>/buffer_manager.py alpha-resolve --buffer-dir .claude/buffer/
```
If any entries have `concept="?"`, include the count in the "Resolution" line of the report. Do NOT auto-resolve — just report the count.

Include the summary even in File-Only Mode (with buffer items reported as "skipped — no buffer").

---

## File-Only Mode

When no buffer plugin is detected:

1. **Produce output files**: distilled `.md` and interpretation `.md` in the configured output directory.
2. **INDEX.md Update**: same as Full Integration Step 1.
3. **Project README Update**: same as below.
4. **Skip all buffer/alpha operations silently** -- no warnings, no errors, no "buffer not found" messages.

---

## Recovery Mode

When the user invokes `/distill --recover`, run the integration recovery pipeline to backfill orphaned distillations — sources that were distilled in File-Only Mode and never had their concept mappings written to the alpha bin.

### Step R1: Dry Run

Run the recovery script in preview mode:

```bash
python [plugin-scripts]/distill_recover_integration.py \
  --interp-dir [interpretations-dir] \
  --distill-dir [distillation-dir] \
  --alpha-dir .claude/buffer/alpha \
  --dry-run
```

### Step R2: Present Results for Review

Present the dry-run output as **MANDATORY REVIEW** using the same table format as the interpretation summary:

```
### Recovery Preview — [N] orphaned sources

| Source | Concept Mappings | Forward Notes | CW Entries |
|--------|-----------------|---------------|------------|
| [label] | [N] | [N] | [N] |

Total: [N] cross_source entries, [M] convergence_web entries, [P] forward notes
```

**Wait for user approval before proceeding.** The user may exclude sources or adjust entries.

### Step R3: Execute Recovery

On approval, run the recovery script for real:

```bash
python [plugin-scripts]/distill_recover_integration.py \
  --interp-dir [interpretations-dir] \
  --distill-dir [distillation-dir] \
  --alpha-dir .claude/buffer/alpha \
  --output _recovery.json \
  --forward-notes-out [repo]/.claude/skills/distill/forward_notes.json
```

Then pipe the recovery entries to `alpha-write`:

```bash
cat _recovery.json | python <buffer_scripts>/buffer_manager.py alpha-write --buffer-dir .claude/buffer/
```

### Step R4: Post-Recovery

1. Rebuild relevance grid (same as Step 5b).
2. Clean up: `rm -f _recovery.json`
3. Report: "Recovered N concepts, M convergence edges, P forward notes from Q sources."

---

## Project README Update

**Existence check first**: Check if `<project>/.claude/skills/distill/README.md` exists before reading or generating.
- **If it exists**: Read it, then update the specific sections below (Sources Distilled row, Glossary entries, Tools table). Do NOT regenerate the whole file.
- **If it does not exist**: Generate from the template established during differentiation.

After each distillation (both modes), update the project README:

1. **Sources Distilled table**: add a row using this format:
   ```
   | [Source-Label] | [YYYY-MM-DD] | [Route A-G / W / I / R] | [1-line: figures extracted, tools used, issues noted] |
   ```
   Example: `| Taalbi_LongRunPatterns_2025_Paper | 2026-03-01 | Route A | text-only, clean extraction, 12 key concepts |`

2. **Glossary section**: Add new terms from this distillation's key concepts. Use this template directly — do NOT read the project SKILL.md to learn the format:
   ```
   | [Term] | [1-2 sentence operational definition as used in THIS project] | [Source-Label] |
   ```
   **Which terms to add**: Only terms that appear in the interpretation's Key Concepts table AND are not already in the glossary. Check existing rows before adding. Skip generic terms that need no project-specific definition. Maximum 5 new terms per distillation.

   **Also update the project SKILL.md glossary** (`## Project Terminology Glossary` section) with the same entries in the same format:
   ```
   | [Term] | [1-2 sentence operational definition as used in THIS project] | [Source-Label] |
   ```
   The project SKILL.md glossary is the canonical source; the README mirrors it. Append new rows to the existing table — do NOT rewrite the section.

3. **Tools Available table**: update if a new tool was installed during this distillation. Change status from `demand-install` to `installed: [version]`.

If the README does not exist, generate it from the template established during differentiation.

---

## Error Logging (mandatory)

**Every distillation MUST end with an error log update.** This is not optional.

**Existence check first**: The project skill file MUST exist by this point (it was read during `/distill` dispatch). Do NOT re-read the entire file — you already have it in context. Append to the Known Issues table directly.

After each distillation, record in the project skill's Known Issues table.

**Canonical Known Issues row format** (3-column: Issue | Workaround | Status):

```markdown
## Known Issues

| Issue | Workaround | Status |
|-------|-----------|--------|
| [Source-Label]: [brief description of issue — e.g., "Table on p.12 extracted as plain text"] | [what was done — e.g., "pdfplumber returned empty; Docling not installed; used PyMuPDF text blocks"] | [YYYY-MM-DD] [RESOLVED / OPEN / WORKAROUND] |
| [Source-Label]: clean run | Route [X], all extraction channels nominal | [YYYY-MM-DD] |
```

**What to log** (populate from the actual distillation run):
1. **Source type and extraction route** (PDF Route A-G, Route W for web, Route I for image)
2. **Extraction tier used** (which detection channels succeeded/failed)
3. **Troubleshooting paths taken** (what was tried, what worked, what did not)
4. **New issues discovered** (with resolution status: RESOLVED if fixed, WORKAROUND if partially handled, OPEN if unresolved)
5. **Verification gate results** (figures: passed/re-cropped/fell-back; web: content completeness; images: text extraction confidence)

If no issues encountered, add a single clean run row as shown above.

The purpose of this log is cumulative learning. Each distillation makes the next one faster by pre-loading solutions.

---

## Temporary File Cleanup (mandatory)

**Run LAST, after error logging, regardless of whether the distillation succeeded or failed.**

Delete all temporary files created during this distillation:

| File | Created by | Always present? |
|------|-----------|----------------|
| `_distill_scan.json` | distill_scan.py output | Yes (PDF sources) |
| `_distill_text.txt` | distill_extract.py output | Yes (PDF sources) |
| `_manifest.json` | distill_figures.py output | Only if figures detected |
| `.claude/buffer/.distill_active` | integration marker | Yes (if buffer exists) |
| `.claude/buffer/.distill_stats` | extract + analyze stats | Yes (if buffer exists) |

Cleanup command:

```bash
rm -f _distill_scan.json _distill_text.txt _manifest.json .claude/buffer/.distill_active .claude/buffer/.distill_stats
```

The bundled scripts in the skills directory are permanent -- do NOT delete them. Only their output files are temporary.

**If the distillation errored mid-way**: cleanup is still required. Leftover temp files confuse future sessions. If you cannot determine which exist, glob for `_distill_*` in the project root and delete all matches.

**Do NOT delete**: distillation output files, interpretation files, figure PNGs, or INDEX.md -- these are permanent artifacts.
