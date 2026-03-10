---
name: analyze
description: Run analytic passes on extracted source content and produce structured distillation output with project interpretation.
---

# Source Analysis

This skill runs the analytic core of the distillation pipeline. It assumes the `extract` skill has already run and produced raw text in `[distillation_dir]/raw/[Source-Label].txt`.

## Prerequisites

Before running any analytic pass, verify the project configuration is loaded:

1. **Context check** — the parent `distill` skill reads the project config once. Verify these values are already in conversation context before re-reading the file:
   - `project_name` — used in interpretation file headers
   - `project_map_type` — one of `concept_convergence`, `thematic`, `narrative`, `custom`, `none`
   - `pure_mode` — boolean; if `true`, skip Pass 4 and interpretation file entirely
   - `terminology_glossary` — project-specific term definitions that inform Pass 4 mappings
   - `interpretations_dir` — where interpretation files are written
   - `distillation_dir` — where distillation files are written
   - `custom_schema` — (only if `project_map_type = custom`) the user-defined interpretation template

   If running standalone (not invoked by the parent skill), read the project config at `<repo>/.claude/skills/distill/SKILL.md`.

2. **Verify extraction artifacts** — confirm that raw text exists at `[distillation_dir]/raw/[Source-Label].txt`. If missing, abort with a clear message directing the user to run `extract` first.

3. **Load source metadata** — read extraction header (source type, page count, scan notes, figure manifest) to inform citation format and conditional sections.

## Analytic Passes

Five passes from raw extraction to project integration. The analytic pass asks "what are the parts, and what does each part *do*?" The anolytic pass asks "how do the parts constitute a whole, and what does that whole *produce*?" The overall register is operational: capture not just what a source says but what it shows the world to do — the productivity of its claims, the structural work of its concepts, the motions of its argument. Neither pass editorializes or relates to the project — they read the source on its own terms. The relational pass then brings the project into dialogue with the reconstructed source.

**Pass 1 — Extraction**: Raw text from the PDF pipeline, web fetch, or image decomposition. Raw material for all subsequent passes. (Already completed by the `extract` skill — this pass confirms the artifact is present and usable.)

**Pass 2 — Analytic**: Decompose the whole into parts: concepts, claims, definitions, mechanisms, boundary conditions, evidence. For each key concept, identify its *role* in the author's argument (premise, mechanism, implication, boundary condition, conclusion) AND the *structural work* it performs — what it blocks, enables, replaces, or transforms; why the author needs it at that juncture; what would collapse without it. The register is operational, not merely definitional: capture what concepts *do* in the text's architecture, not only what they *mean*. Feeds Key Concepts table (term, definition, operational significance). **Voice**: Write in direct assertive register — state what the concepts ARE and what they DO, not that "the author defines" or "the paper introduces" them. The attribution is structural (it's in the filename and header). The analytic pass captures the source's conceptual architecture, not a report about it.

**Pass 3 — Anolytic**: Recompose the parts into a whole: reconstruct the argument as a coherent totality — how claims relate to each other, what the source *means* beyond its enumerable parts. Trace the operational motions of the text: how each concept functions as a device in the argument's architecture, what philosophical or theoretical moves the author makes *through* these concepts, and what the source shows the world to *do* (not only what it describes). The anolytic register asks not just "what does this text say?" but "what does this text *produce*?" Feeds Core Argument, Theoretical & Methodological Implications, Equations & Formal Models. **Voice**: The reconstructed whole should read as the argument itself, condensed — not as a commentary on the argument. "Causal textures constitute four ideal types" not "The paper argues that causal textures constitute four ideal types." When the source presents competing positions or other thinkers' views, use the source's own framing: "Three theories compete: X, Y, Z. The evidence favors Z because..." — this is how the source itself handles internal attribution. The distiller does not add a meta-layer.

**Pass 4 — Relational** (skip if `project_map_type = none` or `pure_mode = true`): Read the reconstructed whole against the project framework. The question adapts to the project map type:
- `concept_convergence`: Map to existing framework elements — confirm, extend, or challenge. A minor source concept may be a major project discovery. Feeds Integration Points and candidate forward notes.
- `thematic`: Identify which themes from the theme registry this source speaks to. Note new themes not yet tracked. Feeds Thematic Relevance table.
- `narrative`: Identify characters, events, places, factions, worldbuilding elements, and plot connections. Note new entities and timeline events. Feeds Narrative Elements table.
- `custom`: Follow the custom schema's interpretation template.

**Pass 5 — Style**: Characterize the source's register, tone, and density. Always runs (style is source-intrinsic, not project-dependent). Record in the distillation header:
- **Register**: analytic philosophy / continental phenomenology / empirical social science / formal-mathematical / practitioner-applied / mixed
- **Tone**: personal/reflexive vs. impersonal/objective
- **Density**: technical (specialist audience) vs. accessible (general audience)

Interpretive frame varies by register — style detection prevents misreading concepts across traditions.

## Atom Marker Protocol

**Purpose**: Distillation files are the single source of truth for all concept content. HTML comment markers embedded at write time enable script-based section retrieval (`distill_retrieve.py`) — a Python script extracts only the marked content at zero token cost, eliminating the need for full-file reads. These markers are invisible in normal markdown rendering.

**Two levels of markers:**

1. **Section markers** — wrap every `##` section:
   ```
   <!-- SECTION:section_name -->
   ## Section Heading
   [content]
   <!-- /SECTION:section_name -->
   ```
   Names: `core_argument`, `key_concepts`, `figures`, `equations`, `theoretical_implications`

2. **Concept markers** — wrap each concept's row within Key Concepts:
   ```
   <!-- CONCEPT:concept_key -->
   | Concept | Definition | Significance | Source Ref |
   <!-- /CONCEPT:concept_key -->
   ```

3. **Figure markers** — wrap each figure subsection:
   ```
   <!-- FIGURE:fig_id -->
   ### Figure N: Title
   [content]
   <!-- /FIGURE:fig_id -->
   ```

**Concept key normalization**: lowercase, spaces to underscores, strip parentheses and special chars, truncate at 40 chars. Examples: `"Wholeness (W)"` → `wholeness_w`, `"Cross-metathesis"` → `cross_metathesis`, `"Degrees of life"` → `degrees_of_life`.

**Why concept keys, not w:IDs**: w:IDs are assigned during integration (after distillation). Concept keys are stable names derived from the Key Concepts table at write time. The index.json maps `w:ID → marker key → content in distillation file`.

## Distillation Voice Directive

**Distillations are optimized for AI reprocessing**, not human consumption. They serve as the canonical knowledge source from which the retrieval script extracts atoms for future AI instances. Interpretations are the human-facing documents.

- Use tables and structured fields over narrative paragraphs
- Core Argument: 1-3 paragraphs max, direct assertive register
- Significance column: operational work (what it blocks/enables/transforms), not importance
- No meta-commentary ("the author argues that..." → state the claim directly)
- No redundancy — the distillation IS the source for alpha retrieval; content here is not duplicated into alpha `.md` files
- The concept map / alpha bin is the AI's pointer layer to this content; interpretations are the human's access point

## Output Template

Produce the distillation in this exact structure. Mandatory sections ALWAYS appear. Conditional sections appear ONLY when the source contains relevant content. **All `##` sections, concept rows, and figure subsections MUST have atom markers** — see Atom Marker Protocol above.

```markdown
# [Source Label] — Distillation

> Source: [see source-type-specific header from extraction metadata]
> Date distilled: [YYYY-MM-DD]
> Distilled by: Claude (via distill skill)
> Register: [analytic / continental / empirical / formal-mathematical / practitioner / mixed]
> Tone: [personal-reflexive / impersonal-objective / mixed]
> Density: [technical-specialist / accessible-general / mixed]
> Source type: [PDF / web / image / recording]

<!-- SECTION:core_argument -->
## Core Argument

[1-3 paragraphs in direct assertive register: State the argument AS the source states it, condensed. Trace the operational motions: what each major move blocks, enables, or transforms. Do not frame claims as "the author argues" or "this paper proposes" — the header carries attribution. Write as if the source itself is speaking in compressed form: its logic chain, its moves, its productivity. When the source attributes claims to others, preserve THAT attribution ("Against Heidegger: being is not neutral"). Do not editorialize. **Include inline source citations** for each major claim — see Source Citation Rules below.]
<!-- /SECTION:core_argument -->

<!-- SECTION:key_concepts -->
## Key Concepts

| Concept | Definition | Significance | Source Ref |
|---------|-----------|--------------|------------|
<!-- CONCEPT:[concept_key] -->
| [term]  | [precise definition as used in this source] | [what structural work this concept performs in the argument — what it blocks, enables, replaces, or transforms; why the author needs it at this juncture] | [location in source — see Source Citation Rules] |
<!-- /CONCEPT:[concept_key] -->

[Scale concept depth dynamically with source length — this mirrors the sigma hook's dynamic scalar pattern:
- **Short sources** (< 20 pages / < 5k words): 5-8 concepts — tighter focus, each concept gets more operational depth
- **Medium sources** (20-100 pages / 5k-30k words): 8-15 concepts — standard depth
- **Long sources** (100+ pages / 30k+ words): 15-25 concepts — broader coverage, significance column can be more concise per entry
Use the source's own terminology. The Significance column captures operational function, not just importance — what each concept *does* in the text's architecture. The Source Ref column grounds every concept in a specific location in the original, enabling traceability without re-reading the full source.

**Each concept row MUST be wrapped in `<!-- CONCEPT:key -->` / `<!-- /CONCEPT:key -->` markers.** The concept key is derived from the Concept column using the normalization rules in the Atom Marker Protocol.]
<!-- /SECTION:key_concepts -->

<!-- SECTION:figures -->
## Figures, Tables & Maps                     ← CONDITIONAL: only if visual material exists

[For each figure/table/map — compact reference format. Full decomposition goes in `_manifest.json` in the figures folder:]

<!-- FIGURE:[fig_id] -->
### [Figure/Table N]: [Title or description] — p.[page]
`[filename.png]` | [1-sentence summary of what the figure shows] | Concepts: [concept_key_1], [concept_key_2]
<!-- /FIGURE:[fig_id] -->

[The figures folder (`[figures_dir]/[Source-Label]/`) contains the images and `_manifest.json` with full decomposition data. The distillation carries compact references only — the figure ID links to the manifest entry. This prevents inline duplication of figure descriptions that already exist in the figures folder.

**`_manifest.json` enrichment**: After figure extraction, enrich each manifest entry with:
```json
{
  "[filename.png]": {
    "page": NN,
    "caption": "Title",
    "type": "diagram|photo|table|equation",
    "description": "Full textual decomposition of visual content...",
    "data_points": "Specific values, relationships, patterns...",
    "argument_connection": "How this advances the core argument...",
    "concepts": ["concept_key_1", "concept_key_2"]
  }
}
```
If no `_manifest.json` exists (older extraction), create it. Retrieval: `distill_retrieve.py --figure [fig_id]` extracts from the manifest or from the marked section.]
<!-- /SECTION:figures -->

<!-- SECTION:equations -->
## Equations & Formal Models                  ← CONDITIONAL: only if mathematical content exists

[For each key equation, reproduce in LaTeX notation AND define every variable. Format:]

### [Equation Name or Label]
$$[equation in LaTeX] \tag{N}$$
- $[symbol]$: [definition — type (scalar/vector/matrix), units if applicable, constraints]
- $[symbol]$: [definition]

[**Variable definitions are MANDATORY.** An equation without its variable definitions cannot be reconstructed by a future instance. If a variable was defined in an earlier equation, a brief back-reference suffices (e.g., "$C$: connectivity matrix (see Eq. 1)"). Group equations sharing a derivation chain under a common heading.]
<!-- /SECTION:equations -->

<!-- SECTION:theoretical_implications -->
## Theoretical & Methodological Implications   ← MANDATORY

[What method does this source employ — dialectical, phenomenological, formal-mathematical, empirical-statistical, case-study, simulation, mixed? What are the methodological implications of the argument? What does the method assume, and what does it preclude? Every source has a method, even when unstated. **Include inline source citations** for methodological claims — see Source Citation Rules.]

### Empirical Grounding                        ← CONDITIONAL subsection: only if source is experimental/quantitative

[Data sources, sample sizes, methods, key findings with numbers. This subsection grounds the methodological discussion in concrete evidence: what data the method actually produced, how it was gathered, and what the numbers show. Without this, the methodological claims above remain abstract — with it, they are evidenced. Include: data sources and provenance, sample characteristics (N, selection criteria, representativeness), measurement instruments and their validity, key quantitative findings with effect sizes and confidence, limitations the data imposes on the claims.]
<!-- /SECTION:theoretical_implications -->
```

**Figure storage convention**: Rendered figures saved in `[distillation_dir]/figures/[Source-Label]/`. File naming by source type:
- **PDF figures**: `{type}_{NN}_p{P}.png` — e.g., `fig_02_p16.png` (Figure 2, page 16), `tab_03_p34.png` (Table 3, page 34), `eq_01_p9.png` (Equation 1, page 9). Fallback: `page_{P}.png` (full-page render when cropping fails).
- **Web figures**: `web_fig_NN.png` — numbered sequentially as captured from the page.
- **Recording keyframes**: `frame_NN_[MM-SS].png` — numbered sequentially with timestamp of capture.
- **Image sources**: `img_[Source-Label]_NN.png` (or original extension).

**Canonical source header by type** (consistent key order across all source types):

```markdown
> Source: [Author(s)], "[Title]", [Publication/Venue], [Year], [page count] pp.
> Date distilled: [YYYY-MM-DD]
> Distilled by: Claude (via distill skill)
> Extraction: [PyMuPDF / pdfplumber+PyMuPDF / WebFetch / browser render / Claude vision / yt-dlp+faster-whisper]
> Register: [analytic / continental / empirical / formal-mathematical / practitioner / mixed]
> Tone: [personal-reflexive / impersonal-objective / mixed]
> Density: [technical-specialist / accessible-general / mixed]
> Source type: [PDF / web / image / recording]
> Completeness: [complete / partial -- describe limitation]
> Scan notes: [any low-confidence detections or extraction issues, or "clean"]
```

**Type-specific Source line variations** (first line only — all other header lines are identical):
- **PDF**: `> Source: [Author(s)], "[Title]", [Publication], [Year], [page count] pp.`
- **Web**: `> Source: [Author(s)], "[Title]", [Site/Publication], [Date], URL: [url]` + add `> Date fetched: [YYYY-MM-DD]`
- **Image**: `> Source: [Description of image content]` + add `> Image file(s): [filename(s)]`
- **Recording**: `> Source: [Speaker(s)], "[Title]", [Platform], [Date], URL: [url or path]` + add `> Duration: [HH:MM:SS]` and `> Language: [detected or specified]`

**NOTE**: The distillation file contains NO project-specific interpretation. It is a neutral, portable scholarly artifact. Project-specific readings go in the interpretation file (see below).

## Style Conventions

**Optimization target**: Maximum fidelity in minimum tokens. These distillations are machine-readable knowledge artifacts for future Claude instances — the human reads the original source. Optimize for density and zero-attrition reconstruction, not for human readability.

**Default throughout all sections** — use concise symbolic notation:
- Comparisons: `>$1M`, `<50 chars`, `~5 years`, `≈0.5`
- Statistics: `R²=0.98`, `±0.07`, `N=41`, `p<0.01`
- Operations: `×2`, `÷3`, `→` for "leads to" or "maps to"
- Ranges: `1790–1880`, `2–4×`
- Percentages and ratios: `54%`, `3:1`
- Lists over paragraphs where content is enumerable
- Tables over prose where content has parallel structure

**Exception — full prose ONLY where symbolic notation genuinely cannot capture the nuance**: Core argumentative logic chains (Core Argument section) and methodological reasoning (Theoretical & Methodological Implications) where causal/temporal relationships require natural language to avoid ambiguity. Even in these sections, prefer concise sentences over verbose exposition.

Equations section uses LaTeX notation throughout.

## Voice Rule: Direct Assertive Register

Distillations speak AS the source, not ABOUT the source. The file header (author, title, year, register, tone) handles all attribution. The body text states claims directly.

**Eliminate**:
- "The paper argues/proposes/claims that..."
- "According to X..." / "X argues that..."
- "The authors demonstrate/show that..."
- "This source presents..." / "The text establishes..."
- Passive attributions: "...is described as..." / "...is presented as..."

**Use instead**:
- Direct assertion: "Causal textures constitute four ideal types." [§2, p. 4]
- Source-internal attribution (when the source cites others): "Against Hegel: the totality suppresses the Other." [§I.A, p. 34]
- Operational framing: "The feedback channel captures environment-environment transactions that no single agent controls." [§4, p. 12]

**Edge case — internal polyvocality**: When a source surveys competing views, use the source's own devices: "Three theories compete: X holds..., Y counters..., Z synthesizes..." The distiller does not add meta-commentary ("The paper surveys three theories...").

**Rationale**: Token compression (10-15% savings), reduced entropy, higher operational utility for future instances. The meta-descriptive frame adds no information beyond what the header provides.

## Source Citation Rules

Every claim in the distillation must be traceable to a specific location in the original source. This enables any future reader — human or instance, on any project — to verify, go deeper, or assess confidence without re-reading the entire source.

**Citation format by source type:**

| Source type | Format | Example |
|-------------|--------|---------|
| Paper (PDF) | `§N.N, p. NN` or `§N, pp. NN-NN` | `§3.2, p. 147` |
| Book | `Ch. N, pp. NN-NN` | `Ch. 15, pp. 497-503` |
| Chapter/Excerpt | `p. NN` (within the excerpt range) | `p. 118` |
| Website (multi-page) | `[Page Title]` or URL path | `[Design Principles]` or `/key-concepts/design-principles/` |
| Website (single page) | `[Section heading]` or `¶N` (paragraph) | `[Environmental causal texture]` or `¶3` |
| Slideshow | `slide N` | `slide 14` |
| Recording | `[MM:SS]` or `[HH:MM:SS]` or range `[12:34-15:20]` | `[12:34]` or `[1:02:15-1:05:30]` |
| Image/Chart | `[region]` or caption reference | `[upper-left quadrant]` |

**Where citations appear:**

1. **Key Concepts table** — `Source Ref` column (mandatory for every row). Each concept must cite where in the source it is defined or introduced. If a concept appears across multiple locations, cite the primary definition and note others: `§2, p. 8 (also §5, p. 31)`.

2. **Core Argument** — Inline citations after each major claim. Format: `[§3, p. 12]` or `[Design Principles page]`. One citation per claim minimum. For synthesized claims drawing on multiple locations: `[§2-3, pp. 8-19]` or `[Design Principles + Six Criteria pages]`.

3. **Theoretical & Methodological Implications** — Inline citations for methodological claims and assumptions. Same format as Core Argument.

4. **Equations & Formal Models** — Cite the equation's location in the source: `(Source: §4.2, Eq. 7, p. 23)`.

5. **Figures, Tables & Maps** — Already implicitly cited by figure number and page. Add source section if the figure appears in a different section than the surrounding discussion.

**For multi-page web sources**: The instance must process each page distinctly enough to know which claims come from which page. A distillation that says "the website argues X" without indicating which page is insufficiently cited. Each page of a multi-page website should be represented in the distillation — not necessarily with equal depth, but at minimum as a Source Ref value in the Key Concepts table or an inline citation in the prose.

**Citation of Q&A, interviews, or dialogue content**: When a source contains questions and answers (interviews, Q&A sections, dialogues), cite specific questions or topics: `[Q&A: question on climate change]` or `[Interview, Q3: "What about AI?"]`. Do not compress an entire Q&A section into a single summary sentence — the specific claims made in answers are individually citable content.

## Project Interpretation File

**Skip this entire section if `project_map_type = none` or `pure_mode = true`.** For all other types, write a SEPARATE file for the project's reading of this source. This file lives in the project's interpretations directory (set during differentiation via `interpretations_dir`).

**Why separate?** The distillation is polyvocal (non-determined flow — usable by any project in any direction). The interpretation is biunivocal (determined flow — simultaneously toward the source and toward the project). Hold both directions concurrently when writing the interpretation.

Write to: `[interpretations_dir]/[Source-Label].md`

The interpretation file template varies by project map type:

### Template: concept_convergence

```markdown
# [Source Label] — [Project Name] Interpretation

> Distillation: [relative link to distillation file]
> Date interpreted: [YYYY-MM-DD]
> Project: [project name]

## Project Significance

[Pass 4 output: For each key concept from the distillation, what does it mean for this project? Does it map to something in the framework? Does it challenge, extend, or confirm an existing mapping? Use the project's terminology glossary to identify correspondences.]

| Concept (from distillation) | Project Mapping | Relationship |
|----------------------------|----------------|--------------|
| [source term] | [project framework element it maps to, or "novel"] | [confirms / extends / challenges / novel] |

## Integration Points

[For each integration point:]
- **[concept/mechanism]**: [how it maps, what it implies for the project]
- **Candidate forward notes**: [if this suggests new theoretical development, note it]
- **Cross-source mappings**: [candidate mappings to other distilled sources]

## Open Questions

[Any concepts from the distillation whose project significance is uncertain. Flag for user review.]
```

### Template: thematic

```markdown
# [Source Label] — [Project Name] Thematic Analysis

> Distillation: [relative link to distillation file]
> Date interpreted: [YYYY-MM-DD]
> Project: [project name]

## Thematic Relevance

| Theme | Evidence from this source | Strength |
|-------|--------------------------|----------|
| [existing theme from registry] | [key argument, finding, or quote reference] | [strong / moderate / peripheral] |
| [NEW: theme not yet in registry] | [evidence] | [strength] |

## Key Arguments

[For each major argument relevant to the project:]
- **[argument]**: [summary, how it relates to project themes]
- **Supports/challenges**: [which themes it strengthens or complicates]

## Open Questions

[Thematic connections that are uncertain or need further sources to establish.]
```

### Template: narrative

```markdown
# [Source Label] — [Project Name] Narrative Elements

> Distillation: [relative link to distillation file]
> Date interpreted: [YYYY-MM-DD]
> Project: [project name]

## Entities

| Entity | Type | Description | Relationships |
|--------|------|-------------|---------------|
| [name] | [character/place/faction/item/concept] | [key details] | [connections to other entities] |

## Timeline Events

| Event | When | Entities Involved | Significance |
|-------|------|-------------------|--------------|
| [event] | [temporal marker] | [entity refs] | [plot/worldbuilding importance] |

## Plot Threads

- **[thread name]**: [status: open/resolved/abandoned] — [how this source advances or introduces this thread]

## Worldbuilding Notes

[Any setting details, rules, lore, or atmospheric elements relevant to the project.]

## Open Questions

[Narrative elements that need further development or cross-referencing.]
```

### Template: custom

Use the custom schema defined during differentiation (loaded from `custom_schema` in the project config). The interpretation file should follow whatever structure the user specified, adapted from the components above.

**Guard**: If `pure_mode = true`, no interpretation file was written — skip the review below entirely and proceed directly to Analysis Stats Output.

**⚠ MANDATORY REVIEW**: After writing the interpretation file, present a **plain text summary** to the user:
- Number of concepts mapped and their relationship types (confirms/extends/challenges/novel)
- Key integration points identified
- Any flags or open questions
- The output file path so the user can open and review the full document

Then call `AskUserQuestion` with ONLY: "Looks good — proceed with integration" / "I have feedback." The popup is the decision; the summary is the plain text above. Do NOT proceed to integration until the user has responded. Do NOT assume acknowledgment from silence. They should see and review the project reading before post-updates fire.

**⚠ FULL STOP** — see parent skill ENFORCEMENT RULE. Your turn ends after the AskUserQuestion call.

## Analysis Stats Output

**After analysis completes** (all passes done, interpretation written), append analysis statistics to `.claude/buffer/.distill_stats` for the end-to-end distillation report.

Read the existing `.distill_stats` file (written by the `extract` skill), then add the `analysis` key:

```json
{
  "analysis": {
    "key_concepts": 0,
    "equations": 0,
    "figures_decomposed": 0,
    "register": "[analytic / continental / empirical / formal-mathematical / practitioner / mixed]",
    "interpretation": {
      "mappings": 0,
      "confirms": 0,
      "extends": 0,
      "challenges": 0,
      "novel": 0,
      "open_questions": 0
    }
  }
}
```

**Guard**: Only write if `.claude/buffer/.distill_stats` exists. If the extract skill didn't write it (no buffer directory), skip silently.

Populate counts from the actual distillation and interpretation outputs:
- `key_concepts`: rows in Key Concepts table
- `equations`: equations in Equations & Formal Models section (0 if section absent)
- `figures_decomposed`: figures in Figures section (0 if section absent)
- `interpretation.mappings`: rows in Project Significance table (0 if pure_mode)
- Relationship counts from the Relationship column of the Project Significance table
- `open_questions`: count discrete bullet points (`- ` lines) in the Open Questions section of the interpretation file. Each bullet = 1 question. If Open Questions section is absent or empty, count = 0. Free-text paragraphs without bullet points count as 1 question each.

## Troubleshooting Decision Tree

**DO NOT blindly retry tools.** Follow this tree on errors:

```
PDF won't open:
+-- Error contains "password" or "encrypted"
|   -> Ask user for password. If none, skip file.
+-- Error contains "corrupt" or "invalid"
|   -> Try pdftotext fallback (Route G step 1). If that fails, try Claude reader (Route G step 2).
+-- Error contains "codec" or "encoding"
|   -> Try: pymupdf.open(path, filetype="pdf"). If fails, try pdftotext fallback.
+-- Error contains "not found" or "No such file"
    -> Verify path with user. Check for typos, spaces in path.

Text extraction returns empty string:
+-- Check multiple pages (not just page 0)
|   +-- ALL pages empty -> Scanned PDF. Route ALL pages to Figure Pipeline.
|   +-- SOME pages empty -> Mixed PDF. Extract text where possible, screenshot empty pages.
+-- Check if DRM-protected
|   -> pymupdf metadata check. If protected, inform user and ask for manual intervention.
+-- Try pdftotext as cross-check
    -> If pdftotext also returns empty, confirmed scanned. Figure Pipeline.

Figure extraction fails:
+-- cluster_drawings() returns empty on page with known figure
|   -> Increase tolerance: try x/y_tolerance=10, then 15.
|     If still empty -> unusual encoding. Fall back to full-page render.
+-- cluster_drawings() returns too many clusters (fragments)
|   -> Decrease tolerance to 3. Or merge overlapping/adjacent (within 20pt) clusters.
+-- Caption not matched to visual element
|   -> Increase CAPTION_SEARCH_PTS from 80 to 120. Check caption format
|     (some PDFs use "Fig." or "TABLE" -- extend regex if needed).
+-- get_pixmap(clip=...) throws MemoryError
|   -> Reduce DPI to 150, then 100. Cropped renders use less memory than full-page.
+-- get_images() + cluster_drawings() both return empty but page has visuals
|   -> Unusual PDF encoding. Fall back to full-page render for that page.
+-- Pure-text items (equations, text tables): cluster_drawings() AND get_images() both return zero
|   -> These items have no vector/raster elements -- they're PDF text only.
|     Use text-block coordinate cropping: get_text("dict") -> scan lines for caption/equation
|     markers by y-position -> build manual crop Rect -> get_pixmap(clip=rect, dpi=200).
|     This is the THIRD extraction channel alongside vector and raster detection.
+-- Table detection misses a table
|   -> Table lacks standard caption prefix. Fall back to full-page for that page.
+-- Read tool can't parse the cropped image
    -> Note for user: "Figure on page N could not be decomposed. Manual review needed."

Claude reader issues:
+-- "pdftoppm" not found / not recognized
|   -> The Read tool's PDF rendering depends on pdftoppm (part of Poppler utilities).
|     If not installed: use PyMuPDF's get_pixmap() to render pages as images instead,
|     then read the images via the Read tool. This is the Figure Pipeline approach and
|     produces equivalent results. Alternatively, install Poppler:
|     Linux: apt install poppler-utils / Windows: choco install poppler or scoop install poppler
+-- "exceeds" or "too large"
|   -> Use pages parameter. Chunk: "1-20", "21-40", etc.
+-- "cannot read" or empty result
|   -> Try explicit pages: "1-5" first. If works, continue chunking. If not,
|     fall back to PyMuPDF text extraction + Figure Pipeline for image pages.
|     Report failure to user only if all extraction routes fail.
+-- Timeout or very slow
    -> Reduce chunk size to 10 pages. Try again.

pdfplumber issues:
+-- ImportError or ModuleNotFoundError
|   -> Not installed. Trigger Demand-Install Protocol.
+-- extract_tables() returns empty on page with visual tables
|   -> Tables may be image-based (not text-based). Route page to Figure Pipeline.
+-- extract_tables() returns malformed data (wrong columns, lost merged cells)
|   -> Complex table. If Docling available, retry with Docling on this page.
|     Else, render page as image and decompose via Claude vision.
|     Note: "Table on page N was vision-extracted; verify structure."
+-- pdfplumber crashes or hangs on specific page
    -> Skip that page with pdfplumber. Extract via PyMuPDF text blocks.
      Log in Known Issues with page number and error.

Docling issues:
+-- ImportError or model download fails
|   -> Check network connectivity. Offer retry or fall back to PyMuPDF + Figure Pipeline.
+-- OCR returns garbage text (low confidence)
|   -> Fall back to Figure Pipeline for those pages (render + Claude vision).
|     Note OCR quality issue in Known Issues.
+-- Docling processing exceeds 60s per page
|   -> Kill process. Fall back to PyMuPDF for remaining pages. Log in Known Issues.
+-- Layout extraction reorders text incorrectly
    -> Fall back to PyMuPDF with y-then-x block sorting. Flag for user review.

Marker issues:
+-- ImportError
|   -> Not installed. Trigger Demand-Install Protocol.
+-- LaTeX output contains broken or incomplete equations
|   -> Render equation pages at dpi=200, decompose via Claude vision.
|     Cross-check both outputs; use whichever is more complete.
+-- Marker crashes or hangs
    -> Fall back to PyMuPDF text + Figure Pipeline for equation pages.
      Log in Known Issues.

GROBID issues:
+-- Docker not running or container not found
|   -> Attempt: docker start grobid. If fails, skip GROBID, use standard pipeline.
+-- GROBID returns incomplete TEI XML
|   -> Use what was parsed (title, abstract, bibliography). Fill gaps from PyMuPDF.
+-- GROBID timeout (>120s for the PDF)
    -> Skip GROBID. Log in Known Issues. Proceed with standard pipeline.

Encoding / platform issues:
+-- UnicodeEncodeError with Greek, math, or diacritical characters
|   -> NEVER print extracted text to stdout. Always write to file with encoding="utf-8".
|     This is a Windows console limitation (cp1252 cannot represent Unicode math/Greek).
|     Read the output file with the Read tool instead.
+-- Inline Python regex fails with "unbalanced parenthesis" or similar
|   -> Bash string escaping mangles regex backslashes and braces.
|     Always write Python code to a temporary .py script file and execute it.
|     Delete the script after use.
+-- Path contains spaces (common on Windows: "C:\Users\user\Documents\New folder\...")
    -> Always quote file paths in Python scripts and bash commands.
      Use raw strings or forward slashes in Python: r"C:\path\to\file" or "C:/path/to/file".
```
