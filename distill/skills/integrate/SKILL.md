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

Read the project index file. Add or update a row in the appropriate category table:

```markdown
| [Source-Label] | [Author(s)] | [source type] | [distilled/[Source-Label].md](distilled/[Source-Label].md) | [mapped concepts] | [notes] |
```

For `project_map_type = none` or `pure_mode`: use `---` in mapped concepts column. If no index file exists, create one with a standard header and first row. INDEX.md always runs regardless of mode.

### Step 2: Buffer Update

**Guard**: Verify `.claude/buffer/` exists with at least `handoff.json`. If missing, skip all buffer updates and log: "Buffer update skipped: no handoff buffer found." All buffer writes are **alpha-aware**: check for `alpha/index.json` first, fall back to warm-layer writes if alpha does not exist.

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

Type tags: `[independent_convergence]`, `[complementarity]`, `[elaboration]`, `[tension]`, `[genealogy]`.

After writing entries, update hot layer `convergence_web_digest`:
- Increment `_meta.total_entries`
- If new entry creates a new thematic cluster, add to `clusters` array

### Step 5: Remove Marker and Validate

```bash
rm -f .claude/buffer/.distill_active
buffer_manager.py alpha-validate --buffer-dir .claude/buffer/
```

If validation fails, log the failure in Known Issues but do NOT revert writes.

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

1. **Sources Distilled table**: add a row (label, date, route used, notes).
2. **Glossary section**: mirror new terms added to the project skill's terminology glossary.
3. **Tools Available table**: update if a new tool was installed during this distillation.

If the README does not exist, generate it from the template established during differentiation.

---

## Error Logging (mandatory)

**Every distillation MUST end with an error log update.** This is not optional.

After each distillation, record in the project skill's Known Issues table:

1. **Source type and extraction route** (PDF Route A-G, Route W for web, Route I for image)
2. **Extraction tier used** (for PDFs: which detection channels succeeded/failed; for web: WebFetch vs browser render; for images: Read tool multimodal)
3. **Troubleshooting paths taken** (what was tried, what worked, what did not)
4. **New issues discovered** (with resolution or "OPEN" if unresolved)
5. **Verification gate results** (PDFs: items passed first check, re-cropped, or fell back; web: content completeness; images: text extraction confidence)

If no issues encountered, add a single row:

```
| [Source Label]: clean run | [source type], all extraction channels nominal | [date] |
```

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

Cleanup command:

```bash
rm -f _distill_scan.json _distill_text.txt _manifest.json .claude/buffer/.distill_active
```

The bundled scripts in the skills directory are permanent -- do NOT delete them. Only their output files are temporary.

**If the distillation errored mid-way**: cleanup is still required. Leftover temp files confuse future sessions. If you cannot determine which exist, glob for `_distill_*` in the project root and delete all matches.

**Do NOT delete**: distillation output files, interpretation files, figure PNGs, or INDEX.md -- these are permanent artifacts.
