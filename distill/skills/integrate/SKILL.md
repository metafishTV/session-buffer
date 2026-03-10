---
name: integrate
description: Post-distillation updates to project indexes, session buffer, and reference bin. Detects buffer plugin silently — works standalone or with full buffer integration.
---

# Post-Distillation Integration

Update project indexes, session buffer, and reference bin after distillation completes.

## Mode Detection

Detect buffer plugin availability **silently** — no error messages if absent.

```
Buffer plugin detected = ALL of:
  1. buffer_manager.py exists in plugin scripts directory
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

### Step 1: INDEX.md Update

Read the project index file. Add or update a row in the appropriate category table.

**Canonical INDEX.md structure** (use this when creating a new index or verifying existing format):

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

#### Redistillation Alpha Handling (if redistill_mode is set)

**Guard**: Only run this section if the extraction step passed a `redistill_mode` value (`archive`, `update`, or `delete`). If `redistill_mode` is `null` or absent, skip to the standard alpha write below.

**Step 2a: Inventory existing entries** — Scan `alpha/index.json` for all entries where `source` matches the source folder (kebab-case of source label). Collect their IDs, concept keys, and file paths.

```bash
buffer_manager.py alpha-query --buffer-dir .claude/buffer/ --source [kebab-case-source]
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
   echo '[{"id":"w:NNN","body":"## Definition\n...updated content..."}]' | buffer_manager.py alpha-enrich --buffer-dir .claude/buffer/
   ```
3. **No match** (genuinely new concept): Create via standard `alpha-write` below.
4. **Orphaned** (old entry's concept key not in new interpretation): Add `"orphaned_by_redistill": "[date]"` to the entry in `index.json`. Do NOT delete — convergence web edges may depend on it. Log in validation_log with status `ORPHANED`.

**`delete` mode**:
1. Delete all existing alpha `.md` files for this source:
   ```bash
   buffer_manager.py alpha-delete --buffer-dir .claude/buffer/ --id w:NNN
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

#### concept_convergence type (alpha path)

Draw mappings from the interpretation file's Project Significance table and Integration Points. For each concept mapping, build a JSON object with **rich body content** and pipe to `alpha-write`:

```bash
echo '[
  {"type":"cross_source","source_folder":"[kebab-case-source]",
   "distillation":"[Source-Label].md",
   "key":"Source:ConceptName","maps_to":"[project framework mapping]",
   "ref":"[source citation]","suggest":null,
   "body":"## Definition\n[definition from Key Concepts table]\n\n## Significance\n[significance from Key Concepts table]\n\n## Project Mapping\n\n- **Maps to**: [mapping]\n- **Relationship**: [confirms/extends/challenges/novel]\n- **Integration**: [relevant detail from Integration Points]\n\n## Source\n[source citation from distillation header]"},
  {"type":"cross_source","source_folder":"[kebab-case-source]",
   "distillation":"[Source-Label].md",
   "key":"Source:AnotherConcept","maps_to":"[mapping]",
   "ref":"","suggest":null,
   "body":"## Definition\n..."}
]' | buffer_manager.py alpha-write --buffer-dir .claude/buffer/
```

The command auto-assigns IDs, writes canonical `.md` files (with self-contained body content and `<!-- TERMINAL -->` directive), and updates `alpha/index.json` atomically. Read the output JSON to get assigned IDs.

#### Alpha Entry Enrichment (mandatory)

Each `alpha-write` entry **MUST** include a `body` field with self-contained content extracted from the distillation and interpretation just produced. The body makes each alpha `.md` file a **standalone knowledge atom** — sigma should never need to read the full distillation to recall a concept.

Extract per-concept:
1. **Definition**: From the Key Concepts table, Definition column
2. **Significance**: From the Key Concepts table, Significance column
3. **In Context**: 1-2 paragraphs from Core Argument where this concept operates. If the concept is discussed across multiple paragraphs, extract the most operationally dense passage.
4. **Equations**: If the concept has associated equations, include the LaTeX + variable definitions
5. **Project Mapping**: From the interpretation's Project Significance table + Integration Points. Include relationship type and any codebase/parameter references.
6. **Source**: Full source citation from distillation header

Target: 30-80 lines per entry. Dense, self-contained, zero-attrition.

**Anti-entropy rule**: The distillation filename is included for TRACEABILITY (so a human or future instance can verify), NOT as a read instruction. The alpha entry IS the canonical recall artifact. The `body` field triggers a `<!-- TERMINAL -->` directive in the generated `.md` that prevents downstream instances from following the reference chain back to the full distillation. This is structural, not advisory — enriched entries are terminal reads.

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

Use `buffer_manager.py alpha-write` for convergence network entries:

```bash
echo '{"type":"convergence_web","source_folder":"[source-folder]",
  "thesis":{"ref":"w:X","label":"SourceA:Concept"},
  "athesis":{"ref":"w:Y","label":"SourceB:Concept"},
  "synthesis":"[type_tag] What RELATES them -- shared structural ground (involutory)",
  "metathesis":"What EACH does independently in its own domain (evolutory)",
  "context":"[1-2 sentences explaining why this convergence matters for the project — what architectural or theoretical insight it unlocks]"}' | buffer_manager.py alpha-write --buffer-dir .claude/buffer/
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

### Step 5: Remove Marker and Validate

```bash
rm -f .claude/buffer/.distill_active
buffer_manager.py alpha-validate --buffer-dir .claude/buffer/
```

If validation fails, log the failure in Known Issues but do NOT revert writes.

### Step 5b: Rebuild Relevance Grid

**Guard**: Only run if alpha bin exists AND new entries were written in Steps 2/4.

After writing new entries, the reinforcement scores, clusters, and relevance grid are stale. Rebuild them:

```bash
buffer_manager.py alpha-reinforce --buffer-dir .claude/buffer/
buffer_manager.py alpha-clusters --buffer-dir .claude/buffer/
buffer_manager.py alpha-grid-build --buffer-dir .claude/buffer/
```

These run silently (~100ms total for typical corpus). The grid rebuild ensures the sigma hook's per-message O(1) lookup reflects the newly added entries immediately. If any command fails, log it in Known Issues but continue — the sigma hook falls through to IDF scoring gracefully when the grid is absent or stale.

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

Known Issues:    [clean run | N issues logged]
═══════════════════════════════════════════════════
```

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
buffer_manager.py alpha-resolve --buffer-dir .claude/buffer/
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

## Project README Update

After each distillation (both modes), update the project README at `<project>/.claude/skills/distill/README.md`:

1. **Sources Distilled table**: add a row using this format:
   ```
   | [Source-Label] | [YYYY-MM-DD] | [Route A-G / W / I / R] | [1-line: figures extracted, tools used, issues noted] |
   ```
   Example: `| Taalbi_LongRunPatterns_2025_Paper | 2026-03-01 | Route A | text-only, clean extraction, 12 key concepts |`

2. **Glossary section**: mirror new terms added to the project skill's terminology glossary. Use the same table format:
   ```
   | [Term] | [1-2 sentence operational definition] | [Source-Label where first seen] |
   ```

3. **Tools Available table**: update if a new tool was installed during this distillation. Change status from `demand-install` to `installed: [version]`.

If the README does not exist, generate it from the template established during differentiation.

---

## Error Logging (mandatory)

**Every distillation MUST end with an error log update.** This is not optional.

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
