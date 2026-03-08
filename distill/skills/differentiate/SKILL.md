---
name: differentiate
description: One-time project setup for the distillation pipeline. Scans tooling, project structure, and user preferences to generate a project-level distill config.
---

# Differentiation

One-time project setup that generates a project-specific distillation skill at `<repo>/.claude/skills/distill/SKILL.md`. This runs ONCE per project, not per source. The output is a self-contained project skill with configuration, tooling profile, and terminology glossary.

---

## Step 0: Check for Project Skill

Check if `<repo>/.claude/skills/distill/SKILL.md` exists:

1. **If it exists**: Read the project skill's Configuration section (project name, map type, paths). **MANDATORY POPUP**: You MUST present this choice via `AskUserQuestion`. Do NOT auto-select. Wait for the user's response.

   Options:
   - **Use this configuration** -- "I found an existing distill configuration for **[project name]** ([map type] tracking, [N] distillations so far). Proceed with it."
   - **Switch project** -- Use a different project's configuration.
   - **Pure distillation** -- Just extract and summarize this one source, no project tracking.
   - **Re-differentiate** -- Reconfigure this project from scratch (preserves glossary, known issues, and existing distillations).

   - If "Use this configuration": follow that project skill for the distillation.
   - If "Switch project": read `~/.claude/buffer/projects.json` for the registered project list. **MANDATORY POPUP**: present the list via `AskUserQuestion` and let the user pick (include a "Name another project" option). Wait for response. If no registry exists or it's empty, present "Pure distillation" or "Re-differentiate" as options via `AskUserQuestion`.
   - If "Pure distillation": set `pure_mode = true`, proceed to Pure Distillation Fast Path.
   - If "Re-differentiate": proceed to Differentiation below.
2. **If it does not exist**: Scan for pre-existing project infrastructure (see Step 0a), then proceed to Differentiation.

### Step 0a: Pre-Existing Infrastructure Detection (lightweight)

Quick check for existing project infrastructure -- just enough to offer "Integrate vs. Start fresh." The comprehensive scan happens in Step 2.

1. Check if `.claude/buffer/handoff-warm.json` exists -- if yes, note "buffer found"
2. Glob for `docs/references/distilled/`, `docs/distilled/`, `distilled/` -- if any match, count `.md` files

If either is found -- **MANDATORY POPUP**: You MUST present this choice via `AskUserQuestion`. Do NOT auto-select "Integrate." Do NOT skip. Wait for the user's response.

Options:
- **Integrate with existing** -- "I found existing project infrastructure (buffer and/or [N] distillation files). I'll scan the details and wire into your existing setup."
- **Start fresh** -- Ignore existing infrastructure and configure from scratch.

Record the user's choice as `integrate_mode: existing | fresh`. Step 2 (Project Scan) performs the detailed scan. Step 3 (Questionnaire) uses the scan results + `integrate_mode` to pre-populate or skip questions:
- If `existing`: pre-populate Q2 from detected map type, Q5 from detected paths, skip Q6-Q9 if tooling profile exists
- If `fresh`: proceed with the full questionnaire as normal

---

## Upgrade Detection

If a project skill already exists but was generated with an older pipeline -- **MANDATORY POPUP**: You MUST offer the upgrade via `AskUserQuestion`. Do NOT silently skip upgrades.
- If the tooling profile has fewer than 7 entries: options = "Upgrade distill skill (your glossary, known issues, and config are preserved)" / "Keep current skill"
- If no `project_map_type` in Configuration: options = "Add project map type (concept mapping, thematic, narrative, or none)" / "Keep current skill"
- Wait for the user's response. If the user declines, the existing project skill continues to work as-is.

---

## Step 1: Tooling Audit (automatic, no user interaction)

**Script shortcut**: Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_setup.py audit-tools` -- outputs a JSON tooling profile with all 9 tool checks. Skip the manual checks below.

<details><summary>Manual checks (if script unavailable)</summary>

```bash
# Check PyMuPDF
python -c "import pymupdf; print(f'PyMuPDF {pymupdf.__version__}')"

# Check pdftotext (Poppler)
pdftotext -v 2>&1 | head -1

# Check pdfplumber
python -c "import pdfplumber; print(f'pdfplumber {pdfplumber.__version__}')"

# Check Pillow
python -c "from PIL import Image; import PIL; print(f'Pillow {PIL.__version__}')"

# Check Docling
python -c "from docling.document_converter import DocumentConverter; from importlib.metadata import version; print(f'Docling {version(\"docling\")}')"

# Check Marker (lightweight check -- do NOT import converters, which trigger heavy model loading)
python -c "import marker; from importlib.metadata import version; print(f'Marker {version(\"marker-pdf\")}')"

# Check GROBID (Docker service)
docker ps -a --filter "name=grobid" --format "{{.Status}}" 2>/dev/null | head -1
# If empty, check for image:
docker images --filter "reference=*grobid*" --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | head -1

# Check yt-dlp (YouTube/video platform transcript extraction)
python -c "import yt_dlp; print(f'yt-dlp {yt_dlp.version.__version__}')" 2>/dev/null || yt-dlp --version 2>/dev/null

# Check faster-whisper (local audio/video transcription)
python -c "import faster_whisper; from importlib.metadata import version; print(f'faster-whisper {version(\"faster-whisper\")}')"
```

</details>

Record each as `"installed: <version>"` or `"not installed"`. For GROBID, record as "docker: running", "docker: image present (not running)", or "not available".

### Tool Categories

- **Required for PDFs**: PyMuPDF (scanner + primary), pdfplumber (table specialist)
- **Highly recommended for PDFs**: Docling (layout, OCR, complex tables -- demand-install)
- **Optional for PDFs**: Marker (equations -- demand-install), GROBID (scholarly papers -- Docker)
- **Fallback for PDFs**: pdftotext, Claude reader, user intervention
- **Required for Recordings**: yt-dlp (YouTube/platform captions + metadata + audio download)
- **Recommended for Recordings**: faster-whisper (local transcription when captions unavailable -- demand-install)
- **Built-in (no install)**: WebFetch (web sources), Read tool multimodal (images), browser MCP tools (JS-heavy web pages -- availability depends on user's environment)

Web and image source routes use only Claude's built-in tools. No specialist installs needed. Recording sources require yt-dlp for YouTube/platform videos; faster-whisper is demand-installed only when captions are unavailable and transcription is needed.

---

## Step 2: Project Scan (automatic, no user interaction)

**Script shortcut**: Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_setup.py scan-project --repo-dir /path/to/repo` -- outputs a JSON scan with all detected paths, buffer state, distillation counts, and map type. Skip the manual scan below.

Scan the repository for existing distillation infrastructure:

1. **Distillation directory**: Glob for `docs/references/distilled/`, `docs/distilled/`, `distilled/`, or similar
2. **Index file**: Glob for `**/INDEX.md`, `**/index.md` near the distillation directory
3. **Session buffer (warm layer)**: Read `.claude/buffer/handoff-warm.json` if it exists:
   - Check for `concept_map` -- record group names, total entry count, and whether `convergence_network` exists
   - Check for `themes` or `entities` schemas -- record which tracking type is in use
   - Record detected buffer map type: `concept_convergence` | `thematic` | `narrative` | `none`
   - If multiple schema types are present (e.g., both `concept_map` and `themes`), use the one with the most entries. If genuinely ambiguous, present all detected types to the user in Step 3 and let them choose.
4. **Session buffer (hot layer)**: Read `.claude/buffer/handoff.json` if it exists:
   - Check for `memory_config` -- record integration mode and MEMORY.md path
   - Check `orientation` for project context (avoids redundant Q1)
5. **Memory file**: Check for MEMORY.md in the repo or in `~/.claude/projects/*/memory/MEMORY.md`
6. **Existing distillations**: Count how many `.md` files exist in the distillation directory
7. **Interpretations directory**: Glob for `docs/references/interpretations/`, `interpretations/`, or similar
8. **Raw text archive**: Check for `[distillation_dir]/raw/` -- stores web source snapshots for reproducibility
9. **README / project description**: Read the repo's README for project context

Record all detected paths and infrastructure state. If nothing is found, record nulls -- the project skill will use default paths. Pass all findings to Step 3 (questionnaire) for pre-population based on the user's `integrate_mode` choice from Step 0a.

---

## Step 3: User Questionnaire (interactive)

**MANDATORY POPUP for each question below**: You MUST use `AskUserQuestion` for every multiple-choice question. Do NOT skip any question. Do NOT infer answers from context. Do NOT batch questions -- present each one, wait for the response, then proceed to the next. Free-text questions (Q1, Q11) may use AskUserQuestion or text input as appropriate.

### Pre-population Rules

If existing infrastructure was detected AND the user chose "Integrate with existing" in Step 0a:

- **Skip Q1** if the hot layer's `orientation.core_insight` provides sufficient project context. **MANDATORY POPUP**: Still confirm via `AskUserQuestion`: "From your existing buffer, your project is: '[core_insight]'. Is that right?" Options: "Yes, that's right" / "I'd describe it differently." Wait for response.
- **Skip Q2** -- use `detected_map_type` from Step 2. **MANDATORY POPUP**: Still confirm via `AskUserQuestion`: "Your existing buffer uses [concept convergence / thematic / narrative] tracking with [N] entries. I'll wire the distill skill into this." Options: "Correct" / "Change tracking type." Wait for response.
- **Skip Q6-Q9** if a tooling profile already exists in a previous project skill or buffer metadata.
- Still ask Q3 (framework name), Q4 (comprehensive/focused), Q5 (path confirmation), and Q10 (anything else).

### Questions

**Q1** (unless pre-populated, open-ended): "Tell me about your project -- what are you working on?"
- Free text response. This gives context for all subsequent questions.
- Use the answer to inform suggested names (Q3), tracking type recommendations (Q2), and path interpretation (Q5).

**Q2** (unless pre-populated): "How do you want distillations to be tracked for your project?"
- Options:
  - **[Concept convergence mapping]** -- Track cross-source concept relationships with structured inter-source linkages. Best for: theoretical synthesis, interdisciplinary research, philosophical grounding. Generates: concept map (cross-reference entries), convergence network (inter-source links), interpretation files with Project Significance table.
  - **[Thematic tracking]** -- Track themes, arguments, and evidence across sources. Best for: literature reviews, academic writing, topic research. Generates: theme registry, per-distillation theme tags, interpretation files with Thematic Relevance table.
  - **[Narrative tracking]** -- Track characters, plot elements, worldbuilding, timelines. Best for: fiction writing, game design, worldbuilding. Generates: entity registry (characters, places, factions), timeline events, plot threads, interpretation files with Narrative Elements table.
  - **[No tracking]** -- Just produce distillation files. No interpretation files, no buffer, no cross-referencing. Simplest pipeline -- just high-quality extractions and an INDEX.md.
  - **[Combination or something else]** -- Describe what you need and the skill will build a custom tracking schema.
- If user selects "Combination or something else": **MANDATORY POPUP**: ask a follow-up via `AskUserQuestion` (free-text) to understand what they want. Wait for response. Then build a custom schema from available components (concept map, theme registry, entity registry, convergence network, timeline, etc.).
- Record as `project_map_type`: `concept_convergence` | `thematic` | `narrative` | `none` | `custom:[description]`

**Q3** (skip if Q2 = "No tracking"): "What should the project interpretation framework be called?"
- Options: Suggest a name based on Q1 context (e.g., "[Project Name] Integration Points", "[Project Name] Thematic Analysis", "[Project Name] Worldbuilding Notes") plus a "Custom name" option
- This names the interpretation file's framework heading

**Q4**: "Should distillations be comprehensive (extract everything) or focused (you specify what to prioritize each time)?"
- Options: [Comprehensive (Recommended)] [Focused] [Ask me each time]

**Q5**: Confirm detected paths:
- "I detected these paths -- correct?" and list what was found
- Allow override for any path
- If Q2 = "No tracking": skip buffer and interpretations directory paths

**Q6** (if pdfplumber not installed):
- "pdfplumber is the primary table extraction tool and is strongly recommended. Install it now? (`pip install pdfplumber`, <1MB)"
- Options: [Install (Recommended)] [Skip -- tables may extract poorly]
- If user accepts: run `pip install pdfplumber` and verify import
- If user declines: record `pdfplumber: not installed (user declined)` in project skill

**Q7** (if Docling not installed):
- "Docling handles complex layouts, multi-column PDFs, and scanned document OCR. It downloads ~500MB of AI models on first use, then runs locally. When would you like to install it?"
- Options: [Install now] [Install later when needed (Recommended)] [Never]
- If "Install later when needed": record `Docling: demand-install`
- If "Never": record `Docling: never`

**Q8** (if Marker not installed):
- "Marker converts equation-heavy PDFs to high-quality Markdown with LaTeX notation. When would you like to install it?"
- Options: [Install now] [Install later when needed (Recommended)] [Never]
- Same demand-install pattern as Q7

**Q9** (always ask):
- "Will you process journal articles, and do you need to distill citation data (structured bibliographies, author networks, section metadata)? This uses GROBID, which requires Docker (~2GB)."
- Options: [Yes, set up GROBID] [No, skip]
- If yes: record `GROBID mode: true` in project skill config

**Q10** (if yt-dlp not installed):
- "Will you distill YouTube videos, lectures, or audio recordings? This requires yt-dlp for caption extraction and metadata."
- Options: [Install now (Recommended)] [Install later when needed] [Never]
- Install: `pip install yt-dlp` (~10MB)
- Record as `yt-dlp: installed: <version>` | `demand-install` | `never`
- Note: faster-whisper (for transcription when captions unavailable) is always demand-installed on first need -- no upfront question needed. (~150MB model download on first use)

**Q11** (always, open-ended): "Is there anything else you'd like for your distillation workflow that wasn't covered above?"
- Free text response. If the user has additional needs, incorporate them into the project skill's Configuration section and adapt operational sections as needed.
- If user says no or has nothing to add, proceed to skill generation.

---

## Step 4: Generate Project Skill

**Script shortcut**: Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_setup.py generate-skill --repo-dir /path/to/repo --input answers.json` where `answers.json` contains the questionnaire results from Step 3. Outputs the project SKILL.md from template. Review the output and make manual edits (glossary, known issues) as needed.

Write `<repo>/.claude/skills/distill/SKILL.md` using the template below, filling in values from Steps 1-3.

### Description Field

Adapts to project map type:
- `concept_convergence`: "Distill source documents for [project name] with [framework name] concept convergence mapping."
- `thematic`: "Distill source documents for [project name] with [framework name] thematic tracking."
- `narrative`: "Distill source documents for [project name] with [framework name] narrative tracking."
- `none`: "Distill source documents for [project name]."
- `custom`: "Distill source documents for [project name] with [custom description] tracking."

### Project Skill Template

```
---
name: distill
description: [type-specific description -- see above]
---

# [Project Name] -- Source Distillation

Project-specific distillation skill generated by the global distill skill.

## Configuration

- **Project context**: [from Q1 -- 1-2 sentence summary of what the user is working on]
- **Project map type**: [from Q2: concept_convergence | thematic | narrative | none | custom]
- **Integration framework**: [from Q3] <-- omit line if type=none
- **Distillation mode**: [from Q4]
- **Distillation directory**: [detected or specified path]
- **Figures directory**: [distillation_dir]/figures/ (auto-created per source)
- **Raw text archive**: [distillation_dir]/raw/ (web source snapshots -- auto-created on first web distillation)
- **Interpretations directory**: [detected or specified path] <-- omit line if type=none
- **Index file**: [detected or specified path]
- **Session buffer**: [detected or specified path] <-- omit line if type=none
- **Memory file**: [detected or specified path] <-- omit line if type=none
- **GROBID mode**: [true/false -- from Q9]
- **Custom notes**: [from Q11, if any -- omit line if nothing was added]

## Tooling Profile

- PyMuPDF: [version or "not installed"] (SCANNER + PRIMARY)
- pdftotext: [version or "not installed"] (FALLBACK)
- pdfplumber: [version or "not installed" or "not installed (user declined)"] (REQUIRED -- table specialist)
- Pillow: [version or "not installed"]
- Docling: [version or "demand-install" or "never"] (layout + OCR + complex tables)
- Marker: [version or "demand-install" or "never"] (equations -> LaTeX)
- GROBID: ["docker: running" or "docker: image present" or "not available" or "never"] (scholarly papers)
- yt-dlp: [version or "demand-install" or "never"] (YouTube/platform captions + metadata)
- faster-whisper: [version or "demand-install" or "never"] (local audio/video transcription)

## Project Terminology Glossary

(This section grows as distillations add project-relevant terms)

| Term | Definition | First seen in |
|------|-----------|---------------|

## Known Issues

(Record tooling quirks, extraction failures, format edge cases encountered during distillations)

| Issue | Workaround | Status |
|-------|-----------|--------|
```

### Type-Specific Content Pruning

After writing the template above, append the operational content from the global distill skill, **pruned to the user's chosen project map type**.

**Token minimization rule**: The global skill contains ALL type variants so it can generate ANY project skill. The generated project skill must contain ONLY the variant the user chose. Strip out:
- All type-conditional logic (`if type = none`, `skip if project_map_type = ...`, etc.) -- replace with direct instructions for the chosen type
- Interpretation templates for unchosen types -- include ONLY the chosen type's template
- Buffer schemas for unchosen types -- include ONLY the chosen type's schema
- Post-distillation update paths for unchosen types -- include ONLY the relevant steps
- Pass 4 variants for unchosen types -- include ONLY the relevant question
- The include/exclude table below (it is a generation guide, not operational content)

The goal: a user who chose `thematic` should never see convergence network instructions, narrative entity tracking, or concept_convergence mapping in their project skill. A user who chose `none` gets no interpretation template, no buffer updates, no Pass 4 at all. Every token in the project skill earns its place.

### Sections to Always Include (all types)

Extraction pipeline, figure handling, output template (distillation file), style conventions, demand-install protocol, troubleshooting decision tree, error logging.

### Content Inclusion Matrix (generation guide only -- do NOT include in project skill)

| Section | concept_convergence | thematic | narrative | none | custom |
|---------|:--:|:--:|:--:|:--:|:--:|
| Extraction pipeline | Y | Y | Y | Y | Y |
| Figure handling | Y | Y | Y | Y | Y |
| Pass 4 (relational) | Y | Y | Y | N | varies |
| Interpretation file | Y | Y | Y | N | varies |
| Post-updates: INDEX.md | Y | Y | Y | Y | Y |
| Post-updates: buffer | Y | Y | Y | N | varies |
| Post-updates: convergence network | Y | N | N | N | varies |
| Post-updates: MEMORY.md | Y | Y | Y | N | varies |
| Troubleshooting | Y | Y | Y | Y | Y |
| Error logging | Y | Y | Y | Y | Y |

### Buffer Schema by Type

Include the appropriate schema in the generated project skill's Configuration section.

**concept_convergence**: Use concept_map + convergence_network schema (see Post-Distillation Updates in the global skill).

**thematic**: Initialize buffer with:
```json
{
  "themes": {
    "_meta": { "total_themes": 0, "last_validated": "YYYY-MM-DD" },
    "entries": []
  }
}
```
Theme entry: `{ "id": "th:N", "theme": "[name]", "sources": [{ "ref": "[Source-Label]", "evidence": "[key quote/concept]" }], "notes": "[synthesis across sources]" }`

**narrative**: Initialize buffer with:
```json
{
  "entities": {
    "_meta": { "total_entities": 0, "last_validated": "YYYY-MM-DD" },
    "entries": []
  },
  "timeline": [],
  "plot_threads": []
}
```
Entity entry: `{ "id": "ent:N", "name": "[name]", "type": "character|place|faction|item|concept", "sources": [{ "ref": "[Source-Label]", "detail": "[description]" }], "relationships": [] }`
Timeline entry: `{ "id": "evt:N", "event": "[description]", "when": "[temporal marker]", "entities": ["ent:N"], "source": "[Source-Label]" }`
Plot thread: `{ "id": "pt:N", "thread": "[description]", "status": "open|resolved|abandoned", "events": ["evt:N"] }`

**none**: No buffer. Skip buffer initialization entirely.

**custom**: Build schema from user's description, combining available components as needed. Document the custom schema in the project skill's Configuration section.

---

## Step 4b: Generate Project README

**Script shortcut**: Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_setup.py generate-readme --repo-dir /path/to/repo --input config.json` where `config.json` contains the project configuration (project name, map type, paths, tooling profile). Outputs the project README.md from template.

Write `<repo>/.claude/skills/distill/README.md` alongside the project SKILL.md. This is user-facing documentation -- not instructions for Claude. It should describe:

- What the skill does for this specific project
- The chosen project map type and integration framework
- Which specialist tools are available and which are demand-install
- Where output files go (distillation directory, interpretations, figures, index)
- How to re-differentiate or change configuration
- How distillation integrates with the buffer system (if applicable)
- The current state: how many sources have been distilled, what is in the glossary

### README Template

```markdown
# Source Distillation -- [Project Name]

[1-2 sentence project context from Configuration]

## Setup

- **Map type**: [concept_convergence/thematic/narrative/none/custom]
- **Framework**: [framework name, if applicable]
- **Mode**: [Comprehensive/Focused/Ask each time]

## Tools Available

[Table of specialist tools with installed/demand-install/not available status]

## Output Locations

- Distillations: `[path]`
- Interpretations: `[path]` (if applicable)
- Figures: `[path]`
- Index: `[path]`

## Sources Distilled

(Updated after each distillation)

| Source Label | Date | Route | Notes |
|-------------|------|-------|-------|

## Glossary

(Mirrors the project skill's terminology glossary -- updated after each distillation)

## Configuration

To change settings, run `/distill` and choose "Re-differentiate."
To install additional specialist tools, they will be offered automatically when relevant content is detected.
```

This README is updated incrementally after each distillation (see Post-Distillation Updates in the global skill).

---

## Completion

After generating both the project SKILL.md and README.md:

1. Inform the user that differentiation is complete
2. Summarize the configuration: project name, map type, tooling profile, output paths
3. If a source was provided alongside the `/distill` invocation, proceed to the first distillation using the newly generated project skill
4. If no source was provided, prompt the user to provide one
