---
name: distill
description: Distill source documents (PDF, image, web) with project integration. Routes to sub-skills for extraction, analysis, and integration.
---

# Source Distillation

**ENFORCEMENT RULE — applies to all sub-skills invoked below.**

Sub-skills use two interaction levels:

| Marker | When | How |
|--------|------|-----|
| **⚠ MANDATORY POPUP** | Quick binary/ternary decisions (source label, install offer, proceed/stop) | `AskUserQuestion` with 2-3 short options |
| **⚠ MANDATORY REVIEW** | Dense information the user needs to read (scan summary, interpretation review, integration results) | Print information as **plain text** first, then `AskUserQuestion` with brief decision options only. The popup is the decision; the information is the plain text above it. |

**⚠ FULL STOP protocol — applies to BOTH levels:**

After calling `AskUserQuestion`, you MUST stop generating. Do not continue to the next step. Do not prefetch, prepare, or begin any subsequent work. Do not write "while we wait" or "in the meantime." Your turn ENDS with the `AskUserQuestion` call. The next step begins ONLY in your next turn, AFTER the user has responded. This is a hard gate, not a courtesy pause. If you catch yourself writing anything after the `AskUserQuestion` call, STOP IMMEDIATELY.

**⚠ EXTRACTION PROHIBITION — absolute, no exceptions.**

You MUST NOT extract text, images, or figures from source documents outside the `distill:extract` sub-skill pipeline. This means:

- **NO** direct PyMuPDF / `fitz.open()` / `pdfplumber` / `pdf2image` calls in Bash or subagents
- **NO** ad-hoc text extraction scripts that bypass `distill_scan.py`
- **NO** "quick" or "lightweight" extraction that skips figure budget gating
- **NO** subagent-based extraction that circumvents the 6 mandatory checkpoints

The extract skill exists because raw extraction misses figures, skips quality gates, and produces incomplete distillations. Every source — no matter how "simple" — goes through the full extract pipeline: `distill_scan.py` → figure budget gate → route selection → extraction → crop verification → stats output.

If you find yourself writing `import fitz` or `import pdfplumber` in a Bash command during a distillation, **STOP**. You are bypassing the pipeline. Invoke `distill:extract` instead.

A PreToolUse hook enforces this structurally — ad-hoc extraction commands will be blocked with an error message.

Distill a source document into structured reference knowledge.

## Project Discovery

Before routing, resolve the **project root** — the directory containing `.claude/skills/distill/SKILL.md`. Search in this order (stop at first hit):

1. **CWD**: check `[CWD]/.claude/skills/distill/SKILL.md`
2. **Git root**: run `git rev-parse --show-toplevel 2>/dev/null` — if it returns a directory different from CWD, check there
3. **Sibling directories**: check `[CWD]/*/. claude/skills/distill/SKILL.md` (one level deep — catches `repo-name/` sitting next to CWD)
4. **Parent directory**: check `[CWD]/../.claude/skills/distill/SKILL.md`

If found, set `project_root` to the directory containing `.claude/`. All subsequent path resolution (distillation_dir, figures_dir, etc.) is relative to `project_root`, NOT CWD.

If not found in any location, this is a first-time project — proceed to step 2.

## Routing

1. **Check for project config** (silent): use the Project Discovery path above to locate `.claude/skills/distill/SKILL.md`.

2. **If no project config exists**:
   - This is a first-time distillation for this project.
   - Invoke the `distill:differentiate` skill to run one-time setup.
   - After differentiation completes, continue to step 3.

3. **Read the project config ONCE**: `.claude/skills/distill/SKILL.md` — this has the project-specific terminology, output paths, and tooling profile. Extract and hold in working context:
   - `project_name`, `project_map_type`, `pure_mode`
   - `distillation_dir`, `figures_dir`, `interpretations_dir`
   - `terminology_glossary` (for Pass 4 mappings)
   - `tooling_profile` (installed/demand-install/never per tool)
   - `memory_config`, `custom_schema` (if applicable)

   **Context passing**: Each sub-skill's "Read project config" step becomes a **verification check** — confirm the config values are already loaded in the conversation context from this step, rather than re-reading the file. The parent skill reads once; the sub-skills use the loaded context. This eliminates redundant file reads per distillation.

   **Template-first principle**: Sub-skills provide inline templates for all output formats (interpretation files, INDEX.md rows, alpha-write JSON, README rows, Known Issues rows). Use the inline template directly — do NOT read existing output files to learn the pattern. Only read existing files when you need to UPDATE them (e.g., adding a row to an existing INDEX.md). For creation, the template IS the pattern.

4. **Check for `--recover` flag**: If the user invoked `/distill --recover`, skip the normal pipeline and route directly to `distill:integrate` in Recovery Mode (Steps R1–R4). Do not invoke extract or analyze.

5. **Check for `--notes-health` flag**: If the user invoked `/distill --notes-health`, skip the normal pipeline and run forward note health analysis:
   ```bash
   python [plugin-scripts]/distill_forward_notes.py health \
     --notes [repo]/.claude/skills/distill/forward_notes.json \
     --alpha-dir .claude/buffer/alpha
   ```
   Present the report to the user. If consolidation clusters are found, offer: "Would you like to consolidate any of these clusters? Use `--merge` to specify notes."

6. **Check for `--repass` flag**: If the user invoked `/distill --repass`, skip the normal pipeline and process the re-pass queue:
   ```bash
   python [plugin-scripts]/distill_manifest.py repass \
     --manifest [repo]/.claude/skills/distill/manifest.json
   ```
   Present the queue to the user. Ask which source(s) to re-analyze. Route selected sources to `distill:analyze` in re-pass mode, then to `distill:integrate` for manifest update.

7. **Check for `--manifest` flag**: If the user invoked `/distill --manifest`, display manifest health:
   ```bash
   python [plugin-scripts]/distill_manifest.py health \
     --manifest [repo]/.claude/skills/distill/manifest.json
   ```
   Present the report to the user.

8. **Check for `--quality` flag**: If the user invoked `/distill --quality [source]`:
   ```bash
   python [plugin-scripts]/distill_manifest.py quality \
     --manifest [repo]/.claude/skills/distill/manifest.json \
     [--source [source-label]] --format card
   ```
   If no source specified, use `--format table` for the full distribution.

9. **Run the pipeline** in sequence, passing config context forward:
   a. Invoke `distill:extract` — extracts raw content from the source document
   b. Invoke `distill:analyze` — runs analytic passes and produces the distilled output
   c. Invoke `distill:integrate` — updates project indexes, buffer, and reference bin

## Fast Path

If the user provides a source path directly (e.g., `/distill docs/references/Author_Title_2024.pdf`), skip the greeting and go straight to step 3 (or step 2 if no project config).

## Multi-Source Handling

If the user provides **multiple sources** (multiple URLs, files, or a mix):

**⚠ MANDATORY POPUP**: Present via `AskUserQuestion`:

- **"Series / sequence"** — These are parts of a whole (lecture series, book chapters, essay sequence). Process in order. Later items may reference earlier ones. Use a parent label (e.g., `Author_SeriesName_Year`) with part suffixes (`_Part01`, `_Part02`). Single compound INDEX.md entry.
- **"Independent items (batch)"** — Unrelated sources. Process each independently with its own label, distillation, and INDEX.md entry.

**⚠ FULL STOP** — see ENFORCEMENT RULE. Wait for user response.

For **series**: also ask whether the user wants:
- Combined transcript/text (single `.md` with part headings) — better for tracing cross-part arguments
- Separate files per part (individual `.md` files) — better for targeted retrieval

For **independent batch**: process each source through the full pipeline sequentially. No cross-referencing between items.

## Arguments

The source path can be provided as an argument or the user will be asked for it during the extract step.

**`--recover`**: Skip the normal distillation pipeline and run **integration recovery** instead. This scans all interpretation files, detects orphaned sources (distilled but never integrated into the alpha bin), and backfills missing entries. Routes directly to the integrate skill's Recovery Mode (Steps R1–R4). Requires buffer plugin and alpha bin to exist.

**`--notes-health`**: Run forward note health analysis without a full distillation. Scans the forward note registry for consolidation clusters (related notes that may warrant merging), supersession candidates (notes that reference or duplicate others), and source density. Outputs a diagnostic report. Optionally cross-references against alpha concept_index for semantic similarity.

**`--repass`**: Process the re-pass queue. Shows all queued sources with their triggering sources, activation levels, and target concepts. Asks the user which to process. Routes to `distill:analyze` in re-pass mode — only the specified concepts are re-analyzed, not the full distillation. After re-analysis, integration runs to update alpha entries and the manifest. Iteration cap: 3 per source.

**`--manifest`**: Display manifest health summary — sources, concepts, cw edges, forward notes, hub scores, isolated sources, quality distribution, repass queue depth, and graph Laplacian metrics. Shorthand for `distill_manifest.py health --manifest [path]`.

**`--quality [source]`**: Show quality card for a specific source, or quality distribution table for all sources. Each card shows: concept_density, coverage_ratio, cross_ref_density, forward_note_yield, convergence_contribution, and composite_quality (harmonic mean). Use `--quality` (no source) for the full table sorted by composite quality.
