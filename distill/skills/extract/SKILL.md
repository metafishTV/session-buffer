---
name: extract
description: Extract raw content from source documents (PDF, image, web, audio). Handles route selection, figure extraction, and tool installation.
---

# Source Extraction

Extract raw content from source documents and prepare it for analytic passes.

## Prerequisites

Before starting extraction, read the project distill config at `<repo>/.claude/skills/distill/SKILL.md`. You need:
- **Output paths**: `distillation_dir`, `figures_dir`, and `raw` archive location
- **Tooling profile**: Which specialist tools are installed, demand-install, or declined
- **GROBID mode**: Whether scholarly paper processing is enabled

If no project config exists, the parent `distill` skill handles differentiation first. If running in pure mode, paths are resolved by the parent skill before invoking extract.

---

## Source Label Convention

**Resolve the Source Label FIRST, before any extraction.** This label propagates to the distillation filename, interpretation filename, figures subdirectory, raw text archive, INDEX.md row, and all buffer entries. Decide it once here -- do not invent ad hoc names later.

**Step L1: Attempt automatic extraction** -- Based on source type:
- **PDF**: Read the first 2 pages. Extract author(s), title, and year from the title page, header, or metadata (`pymupdf.open(path).metadata`).
- **Web**: Extract author, title, publication/site name, and date from the page content or HTML metadata.
- **Recording (YouTube)**: Extract uploader/channel, title, and upload date via `yt-dlp --dump-json`.
- **Recording (local file)**: Extract metadata from file tags if available (`ffprobe`), otherwise skip to L2.
- **Image**: No metadata expected. Skip to Step L2.

**Step L2: Construct the label** -- Use the first applicable rule:

| Metadata available | Label format | Example |
|---|---|---|
| Author + Title + Year | `Author_ShortTitle_Year_Type` | `Smith_MachineLearning_2024_Paper` |
| 2 authors + Title + Year | `Author1_Author2_ShortTitle_Year_Type` | `Smith_Jones_MachineLearning_2024_Paper` |
| 3+ authors + Title + Year | `FirstAuthor_etal_ShortTitle_Year_Type` | `Smith_etal_MachineLearning_2024_Paper` |
| Author + Title (no year) | `Author_ShortTitle_Type` | `Garcia_QuantumComputing_Book` |
| Site/Org + Title (web) | `Site_ShortTitle_Website` | `SEP_Phenomenology_Website` |
| No metadata (image, informal) | Ask user (see Step L3) | `NetworkDiagram_Image` |

**Type values**: `Paper` | `Book` | `Chapter` | `Excerpt` | `Website` | `Slideshow` | `Chart` | `Table` | `Image` | `Recording`

**ShortTitle rules**: 2-4 words from the title, CamelCase, no articles/prepositions. "A Survey of Machine Learning Methods" -> `MachineLearning`.

**Step L3: User confirmation** --

**⚠ MANDATORY POPUP**: You MUST use `AskUserQuestion` to confirm the source label. Do NOT proceed without user confirmation.

- If metadata found: Present via `AskUserQuestion` with options: "[Constructed label] — use this" / "I'll provide a different label". Example label: `Smith_Jones_MachineLearning_2024_Paper`.
- If no metadata: Use `AskUserQuestion` to ask for a descriptive label (2-4 words) — e.g., `NetworkDiagram_Image`, `WhiteboardSessionMarch_Image`.

**⚠ FULL STOP** — see parent skill ENFORCEMENT RULE. Your turn ends after the AskUserQuestion call.

**Step L4: Record and propagate** -- The confirmed label becomes `[Source-Label]` for all subsequent steps:
- Source file: `[source_dir]/[Source-Label].[ext]` (multi-part: `[Source-Label]_pg[range].[ext]`)
- Distillation: `[distillation_dir]/[Source-Label].md`
- Interpretation: `[interpretations_dir]/[Source-Label].md`
- Figures: `[figures_dir]/[Source-Label]/`
- Raw text (web/recording): `[distillation_dir]/raw/[Source-Label].txt`
- INDEX.md row, buffer entries, error log references

**Step L5: Rename source file** -- If the source is a local file and its filename does not match the confirmed label, rename to `[Source-Label].[ext]` (multi-part: `_pg[start]-[end]`, numbered: `_part[n]`). Use `git mv` if tracked, `mv` otherwise. Report the rename. Skip if URL or already matching.

---

## Analytic Passes Overview

Extraction is Pass 1 of five. This skill handles Pass 1 only. The remaining passes are handled by the `analyze` skill, listed here for orientation:

1. **Extraction** (this skill): Raw text from the PDF pipeline, web fetch, or image decomposition.
2. **Analytic**: Decompose into parts -- concepts, claims, definitions, mechanisms. Capture what concepts *do*, not only what they *mean*.
3. **Anolytic**: Recompose into a whole -- reconstruct the argument as a coherent totality, what the source shows the world to *do*.
4. **Relational**: Read against the project framework. Adapts to project map type. Skipped in pure mode.
5. **Style**: Characterize register, tone, and density.

After extraction completes, hand off to the `analyze` skill with the extracted text and scan metadata.

---

## PDF Extraction Pipeline

Two-phase strategy: PyMuPDF scans every page first (fast content detection), then routes to specialist tools based on what it finds. Move to Route G ONLY if PyMuPDF itself fails to open the file.

### Phase 1: PyMuPDF Detection Scan

Run the bundled scan script:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_scan.py "<pdf_path>" --output _distill_scan.json
```

Read `_distill_scan.json` for structured scan data (page lists for tables, complex_layout, scanned, equations, text_pages, image_pages, total_images, fully_scanned).

**⚠ MANDATORY REVIEW**: Present the scan summary as **plain text** (not in a popup). Include:
- Page counts by category (text, tables, complex layout, scanned/empty, equations)
- Total embedded images and image page count
- Fully-scanned flag (if true, prominently note: "This PDF has NO text layer -- all content is in scanned images")
- Confidence notes (one line each)
- Which extraction routes will be used for which pages

Then call `AskUserQuestion` with ONLY: "Proceed with extraction" / "I have notes about this scan". The popup has ONLY the decision -- all information is in the plain text above. Low-confidence detections proceed normally but note them in the distillation header under `> Scan notes:`.

**⚠ FULL STOP** -- see parent skill ENFORCEMENT RULE. Your turn ends after the AskUserQuestion call. Do not proceed until the user responds.

### Phase 1.5: Figure Budget Gate

After the scan review, before text extraction, check if the document is image-heavy:

```
figure_candidates = len(scan["scanned"]) + len(scan["tables"]) +
                    len(scan["complex_layout"]) + len(scan["equations"]) +
                    len([p for p in scan["image_pages"] if p in scan["text_pages"]])
```

**If figure_candidates > 15**: **⚠ MANDATORY POPUP** with options:
- "Extract all [N] figures/pages"
- "Sample every [M]th page (~10-15 items)" -- compute M = max(1, N // 12)
- "OCR text only -- skip figure extraction entirely"
- "I'll specify which pages"

**⚠ FULL STOP** -- see parent skill. Wait for user response.

Store the user's choice as the extraction strategy. When sampling, modify the scan JSON passed to `distill_figures.py` to include only the sampled page indices. When "OCR text only," skip the Figure Handling Pipeline entirely. When "I'll specify," ask the user for page ranges and filter accordingly.

**If figure_candidates ≤ 15**: proceed normally (no gate).

### Phase 1.6: Text Extraction

**Text extraction**: Run the bundled extraction script (writes UTF-8 to file, never stdout):
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_extract.py "<pdf_path>" --scan _distill_scan.json --output _distill_text.txt
```

**Modification protocol**: If a script needs edge-case adaptation, copy it to the repo, modify the copy, note in Known Issues. Never modify the bundled copy in `${CLAUDE_PLUGIN_ROOT}/scripts/`.

### Phase 2: Content-Based Routing

Routes are NOT mutually exclusive -- a PDF can trigger multiple routes. Process each page with the highest-priority applicable specialist, then merge page-by-page.

**Priority order**: Docling (layout/OCR) > Marker (equations) > pdfplumber (tables) > PyMuPDF (text).

**Multi-feature pages**: Highest-priority specialist handles the whole page. If a secondary feature loses fidelity, re-process with the secondary specialist and merge. Log multi-specialist merges in Known Issues.

**Route A -- Clean text** (no flags on page)
Use PyMuPDF text directly. No specialist needed.

**Route B -- Tables detected** (`scan["tables"]` non-empty)
1. Use pdfplumber (REQUIRED) for table pages -- convert to markdown format.
2. If pdfplumber returns empty/malformed AND Docling installed -> retry with Docling.
3. If pdfplumber fails AND Docling is `demand-install` -> trigger Demand-Install Protocol.
4. If Docling unavailable -> use PyMuPDF text blocks as best-effort. Note: "Table on page N extracted as plain text."
5. Non-table text on same pages still comes from PyMuPDF.

**Route C -- Complex layout** (`scan["complex_layout"]` non-empty)
1. If Docling installed -> use for layout-aware extraction.
2. If `demand-install` -> trigger Demand-Install Protocol ("Multi-column layout detected on [N] pages.").
3. If unavailable -> warn user, use PyMuPDF sorting blocks by y then x as best-effort.

**Route D -- Scanned pages** (`scan["scanned"]` non-empty)

Run the bundled OCR shim script:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_ocr.py "<pdf_path>" --scan _distill_scan.json --output _distill_ocr.pdf [--pages 0,1,5]
```

The script auto-detects the best available backend and reports which was used:

| Exit code | Meaning | Next step |
|-----------|---------|-----------|
| 0, `OUTPUT_TYPE: pdf` | OCRmyPDF succeeded — output is a searchable PDF | Re-run `distill_extract.py` on the OCR'd PDF instead of the original |
| 0, `OUTPUT_TYPE: text` | pytesseract succeeded — output is a text file | Use the text file directly (merge with `_distill_text.txt` for non-scanned pages) |
| 2 | No OCR backend available | Trigger Demand-Install Protocol (see below), then fall back to Vision OCR |
| 1 | OCR error | Log in Known Issues, fall back to Vision OCR |

**Demand-Install for OCR** (exit code 2):

**⚠ MANDATORY POPUP**: Offer OCR tool installation:
- "Install OCRmyPDF (~5MB + Tesseract binary)" — best option, adds text layer to PDF
- "Install pytesseract (~1MB + Tesseract binary)" — lighter, direct text extraction
- "Skip — use vision OCR instead" — expensive but no install needed

**⚠ FULL STOP** — see parent skill ENFORCEMENT RULE.

**If user specifies pages** (via `--pages`): pass only those page indices to the OCR script. This respects the Figure Budget Gate choices from Phase 1.5.

**Vision OCR fallback** (last resort for scanned pages — when OCR shim exits 1 or 2 and user declines install):
- Render pages as images via `page.get_pixmap(dpi=200)` and read via Claude vision.
- **Batch in chunks of 5 pages** (not one-by-one). Print progress: "OCR via vision: pages 1-5 of [N]..."
- After each batch: if pages are purely decorative (blank, dividers, repetitive headers), note and skip similar pages in remaining batches.
- **For fully_scanned PDFs with > 20 scanned pages**: the Figure Budget Gate (Phase 1.5) MUST fire first. Do NOT begin 20+ vision calls without user consent.
- Budget gate options for vision OCR: "Process all [N] pages" / "Sample every [M]th page" / "I'll specify pages" / "Skip -- I'll provide text manually".

**Route E -- Equations** (`scan["equations"]` non-empty)
1. If Marker installed -> use Marker (converts to Markdown with LaTeX).
2. If `demand-install` -> trigger Demand-Install Protocol ("Mathematical content on [N] pages.").
3. If unavailable -> PyMuPDF text + Figure Pipeline at dpi=200. Note: "Equations vision-extracted; verify notation."

**Route F -- Scholarly paper** (GROBID mode `true` in project config AND docker available)
1. Send full PDF to GROBID for structured TEI XML.
2. Use GROBID for structural metadata, PyMuPDF + specialists for full text.
3. If docker not running -> attempt `docker start grobid`. If fails -> warn, fall back.

**Route G -- PyMuPDF fails entirely** (`pymupdf.open()` throws)
Linear fallback:
1. pdftotext: `pdftotext -layout "source.pdf" -`
2. Claude reader: Read tool with `pages` parameter, 20-page chunks
3. User intervention: report which tools failed and why

---

## Non-PDF Source Handling

For non-PDF sources. These require NO specialist tools -- only Claude's built-in capabilities (WebFetch, Read, browser MCP tools if available).

### Route W -- Web Sources (URLs)

**Step W1: Primary extraction** -- Use WebFetch:
```
WebFetch(url="<URL>", prompt="Extract the complete article text, preserving all headings, subheadings, lists, tables, and block quotes. Include author, publication date, and any metadata visible on the page.")
```
If useful result returned, proceed to W3.

**Step W2: JavaScript fallback** -- If WebFetch returns < 200 words or only navigation text, use browser MCP tools if available:
1. `navigate(url="<URL>")` -- load in browser tab
2. `get_page_text(tabId=<tab>)` -- extract rendered text
3. For infinite scroll/lazy-load: use `computer(action="scroll", ...)` then re-extract.
4. If no browser tools: inform user, suggest pasting article text directly.

**Step W3: Save raw text** -- Write to `[distillation_dir]/raw/[Source-Label].txt`. Include URL and fetch date as header comment. Web pages change -- the raw capture is the archival artifact.

**Step W4: Figure capture** -- Check for references to diagrams, charts, figures, images. WebFetch extracts text only -- **do NOT skip this step just because W1 succeeded**.

If visual content likely present:
1. Open browser tab: `navigate(url)` + `computer(action="screenshot")` to survey
2. Crop individual figures: `computer(action="zoom", region=[x0,y0,x1,y1])`
3. For multi-page sites: navigate to each page with figures
4. Save to `[figures_dir]/[Source-Label]/web_fig_NN.png` + write `_manifest.json`

If no browser tools: note `> Figures: not captured -- browser tools unavailable` in header.

**Step W5**: Hand off to analyze skill.

**Distillation header for web sources**:
```
> Source: [Author], "[Title]", [Publication/Site], [date], URL: [url]
> Date fetched: [YYYY-MM-DD]
> Extraction: WebFetch [or browser render if W2 needed]
> Completeness: [complete / partial -- describe limitation]
```

### Route I -- Standalone Images (PNG, JPG, TIFF, etc.)

**Step I1: Read and decompose** -- Use the Read tool on the image file (multimodal vision). Extract:
- All visible text (headings, labels, captions, annotations)
- Data relationships (axes, scales, trends, comparisons)
- Structural elements (tables, hierarchies, flowcharts, networks)
- Legends, color coding, spatial layout

**Step I2: Multi-image handling** -- Multiple images as one source: read each sequentially, treat as multi-page, number as `img_01`, `img_02`, etc.

**Step I3: Save to figures directory** -- `[figures_dir]/[Source-Label]/img_[Source-Label]_NN.png`

**Step I4**: Hand off to analyze skill. The "extraction" IS the decomposition for images.

**Distillation header for image sources**:
```
> Source: [description]
> Image file(s): [filename(s)]
> Date distilled: [YYYY-MM-DD]
> Extraction: Claude vision (multimodal Read)
> Note: [if photo/scan] Text extraction approximate -- verify against original.
```

**No temp files created**: Web and image routes do not run bundled PDF scripts.

### Route R -- Recordings (YouTube, audio/video files)

**Step R1: Source detection**:
- **YouTube URL** (or yt-dlp-supported platform): proceed to R2
- **Local audio** (.mp3, .wav, .flac, .m4a, .ogg, .wma): proceed to R4
- **Local video** (.mp4, .mkv, .avi, .mov, .webm): proceed to R4

**Step R2: YouTube metadata + captions** -- Run bundled transcription script:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_transcribe.py "<URL>" --output _distill_meta.json --metadata-only
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_transcribe.py "<URL>" --output _distill_transcript.txt
```
Tries in order: (1) extract captions via yt-dlp, (2) download audio + transcribe with faster-whisper. If yt-dlp not installed, trigger Demand-Install Protocol (required for YouTube).

**Step R3: YouTube keyframe capture** -- If browser MCP tools available:
1. Navigate to video URL, pause at key moments (intro, slide transitions)
2. Screenshot and crop relevant frames (slides, diagrams, whiteboard content)
3. Save to `[figures_dir]/[Source-Label]/frame_NN_[MM-SS].png`

If purely talking-head: skip, note `> Figures: none (talking-head format)`.

**Step R4: Local file transcription**:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_transcribe.py "<file_path>" --output _distill_transcript.txt
```
Uses faster-whisper. If not installed, trigger Demand-Install Protocol (`pip install faster-whisper`, ~150MB model on first use).

**Step R5: Save raw transcript** -- Write to `[distillation_dir]/raw/[Source-Label].txt` with source metadata as header comments.

**Step R6**: Hand off to analyze skill. The timestamped transcript IS the extraction.

**Distillation header for recordings**:
```
> Source: [Speaker], "[Title]", [Platform/Format], [date], URL: [url or path]
> Duration: [HH:MM:SS]
> Date distilled: [YYYY-MM-DD]
> Extraction: [yt-dlp captions | yt-dlp + faster-whisper | faster-whisper (local)]
> Language: [detected or specified]
> Completeness: [complete / partial -- e.g., "auto-captions, ~90% accuracy"]
> Source type: Recording
```

---

## Figure Handling Pipeline

**When to trigger**: Figure/table pages from Phase 1 scan, Route D fallback (scanned), Route E fallback (equations), or standalone image.

### Cropped Figure Extraction (default)

Run the bundled figure extraction script:
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/distill_figures.py "<pdf_path>" --scan _distill_scan.json --outdir <figures_dir> --manifest _manifest.json
```

Uses three detection channels (vector drawings, raster images, caption-based), associates captions within 80pt, crops at dpi=200. Read `_manifest.json` to drive decomposition.

**File naming**: `{type}_{NN}_p{P}.png` -- e.g., `fig_02_p16.png`, `tab_03_p34.png`, `eq_01_p9.png`, `page_{P}.png` (fallback).

**Tolerance tuning**: Default `x/y_tolerance=5`. If zero clusters on a known-figure page -> copy script to repo, adjust (10-15 for zero, 3 for fragments), note in Known Issues.

### Full-Page Fallback

Triggers when: cropped extraction finds zero figures on a page that should have them, scanned pages (Route D), or equation pages (Route E). Use `page.get_pixmap(dpi=150)` standard, `dpi=200` for equations.

### Crop Verification Gate (mandatory)

**Run AFTER extraction, BEFORE decomposition. Do NOT skip.**

Read EVERY extracted PNG via multimodal Read tool. Check for full-page indicators:
- **FAIL**: Running headers/footers, body text paragraphs, excessive whitespace margins
- **PASS**: Only figure/chart/table/equation content + caption visible

**If full-page detected** -> auto-fix: use `page.get_text("dict")` to get text-block y-positions, identify content boundaries, re-crop with `page.get_pixmap(clip=rect, dpi=200)`, re-verify. Log fix in Known Issues.

**If auto-fix fails**: keep as `page_{P}.png`, note in distillation, log in Known Issues.

**Pure-text items** (equations, text-only tables) with zero vector/raster elements: use text-block coordinate cropping via `page.get_text("dict")` to build manual crop Rect.

**The user should NEVER have to point out a full-page render.** If they do, log the failure mode immediately.

**Batch verification**: For 10+ figures, read images in parallel. Group by likely-pass/fail to prioritize attention. Gate is mandatory for ALL images.

### Post-Extraction Steps

1. **Decompose**: Read each cropped image. Extract caption, axes, data relationships, structure, legend.
2. **Describe**: Write image reference + textual description in Figures section.
3. **Cross-reference**: Map to Key Concepts.
4. **Flag failures**: Note unparseable figures for user review.
5. **Equation figures**: Render at dpi=200, note vision-extraction caveat.

For **non-PDF images**: Use Read tool directly (multimodal decomposition).

---

## Demand-Install Protocol

When a specialist tool is needed but not installed, and its tooling profile status is `demand-install`:

**⚠ MANDATORY POPUP**: You MUST use `AskUserQuestion` to offer tool installation. Do NOT install without explicit user consent. Do NOT skip — present the offer and wait.

**⚠ FULL STOP** — see parent skill ENFORCEMENT RULE. Your turn ends after the AskUserQuestion call.

1. **Explain what was detected**: "This PDF contains [tables / multi-column layout / scanned pages / equations]."
2. **Explain what the tool does**: One sentence on its capability for this content.
3. **Offer install** via `AskUserQuestion` with options: "Install [tool] now" / "Skip — use fallback". For tools that may be needed later, add "Install later when needed" as a third option. Include exact command and size:
   - pdfplumber: `pip install pdfplumber` (<1MB)
   - ocrmypdf: `pip install ocrmypdf` (~5MB) + Tesseract binary (Windows: https://github.com/UB-Mannheim/tesseract/wiki; Linux: `apt install tesseract-ocr`; macOS: `brew install tesseract`). **Recommended for scanned PDFs** — adds invisible text layer, then PyMuPDF reads normally
   - Docling: `pip install docling` (~500MB model on first use)
   - Marker: `pip install marker-pdf` (~200MB, optional GPU)
   - pytesseract: `pip install pytesseract` (<1MB) + Tesseract binary (same as ocrmypdf)
   - GROBID: `docker pull lfoppiano/grobid:0.8.1 && docker run -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.1` (~2GB)
   - yt-dlp: `pip install yt-dlp` (~10MB, required for YouTube)
   - faster-whisper: `pip install faster-whisper` (<5MB install, ~150MB model on first use)
4. **If user accepts**: Install, verify import, update tooling profile (`demand-install` -> `installed: <version>`), proceed.
5. **If user declines**: Fall back gracefully per-route. Do NOT ask again this session.
6. **If user says "never"**: Update profile to `never`. Not offered again unless manually changed.
