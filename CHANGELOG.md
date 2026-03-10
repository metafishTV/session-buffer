# Changelog

All notable changes to buffer are documented here.

## [1.9.0] - 2026-03-10

### Atom Marker Architecture — Script-Based Sectional Retrieval
- **Atom markers in distillations** — `<!-- SECTION:name -->`, `<!-- CONCEPT:key -->`, and `<!-- FIGURE:id -->` HTML comment markers embedded in distillation output. Enables zero-token-cost extraction of individual sections, concepts, or figures from master distillation files. Concept key normalization: lowercase, strip parentheticals/special chars, spaces→underscores, truncate 40 chars.
- **Retrieval script** — `distill_retrieve.py` extracts marked sections from distillation files. Modes: `--section`, `--atoms` (batch), `--figure`, `--list-sections`. Heading-based fallback for unmarked files. Single-pass batch extraction for multiple concepts.
- **Marker-based alpha-query** — `alpha-query --id` now checks for `distillation` and `marker` fields in index.json. When present, extracts concept content directly from marked distillation files (single file read per source, batch-capable). Falls back to reading alpha `.md` files for legacy entries. ~63% token reduction for typical multi-concept queries.
- **Thin alpha entries** — integrate skill updated: alpha entries are now thin pointers (`body: null`) with `distillation` + `marker` fields. Content lives in the distillation file behind the marker. Optional short body (<10 lines) for project-specific integration notes only.
- **Backfill script** — `distill_backfill_markers.py` inserts markers into existing distillation files and updates alpha index.json. Safe dry-run mode. Applied to all 26 sigma-TAP distillations: 360 concept markers, 71 figure markers, 80 alpha entries linked.
- **Distillation voice directive** — codified: distillations optimized for AI reprocessing (dense, structured, no prose filler). Interpretations for human consumption. Compact figure references (2-3 lines) replace verbose inline descriptions; full decomposition in `_manifest.json`.
- **Figure reference pattern** — figures section uses compact format: `filename | 1-sentence summary | Concepts: key1, key2`. Detailed descriptions stored in `_manifest.json` in the figures folder.

## [1.8.0] - 2026-03-10

### Extraction Intelligence
- **Time estimates** — after PDF scan, extraction time is calculated from per-page timing benchmarks (PyMuPDF ~0.1s, RapidOCR ~2-5s, Vision OCR ~3-8s, etc.) and displayed in the scan summary. Users see `Estimated time: ~X-Y min` before committing to extraction.
- **Timeout batching** — if estimated extraction time exceeds 500s for any route, pages are auto-batched with dynamic Bash timeout settings. Prevents timeouts on large PDFs (500+ scanned pages). Merge protocol concatenates batch results in page order.
- **RapidOCR API autocheck** — `distill_ocr.py --probe` silently detects the installed OCR backend and version in ~2 seconds. Result cached in the project tooling profile (`ocr_backend: <backend> <version>`) — subsequent distillations skip the probe. Handles `rapidocr` v3+ / `rapidocr_onnxruntime` v1.x API differences transparently.
- **Figure auto-classification** — `distill_scan.py` now classifies figures by type: photo candidates (large raster, >30% page area), vector diagrams (>20 drawing operations), and small rasters. Classification appears in the scan summary — no new popup. Informs the Figure Budget Gate and extraction approach.

## [1.7.0] - 2026-03-10

### Template Consistency
- **Canonical INDEX.md template** — full structure with headers, category tables, and row format (column-by-column specification) added to integrate SKILL.md. No more reverse-engineering from existing files.
- **Canonical distillation header** — unified header format across all source types (PDF/web/image/recording) with consistent key order. Per-type Source line variations documented. Extract skill headers now reference the canonical format.
- **Figure naming harmonization** — removed `visual_{seq}_p{P}.png` fallback variant. Single convention: `{type}_{NN}_p{P}.png` with `page_{P}.png` fallback. Consistent between extract and analyze skills.
- **Known Issues full format** — 3-column template (Issue / Workaround / Status) with both clean-run and issue-found examples. Status values: RESOLVED / OPEN / WORKAROUND.
- **README row format** — canonical row template for Sources Distilled and Glossary tables in integrate SKILL.md.
- **Glossary row example** — example entry in differentiate template showing operational definition format and Source-Label reference.
- **Open Questions counting rule** — discrete bullet points in interpretation's Open Questions section, countable for `.distill_stats`. Free-text paragraphs count as 1 each.

### Differentiation
- **GROBID demand-install** — Q9 now offers three options (Install now / Install later / Never) matching all other heavy tools. "Install later" records `GROBID: demand-install` for Route F on-demand setup.
- **Five-mode distillation** — Q4 reworked: Comprehensive (extract everything), Focused (AI autonomously prioritizes), Ask me each time (user chooses per-source), Automated-simple (zero popups, distill only), Automated-robust (zero popups, full pipeline with auto-install).
- **_v* count filtering** — Step 0 distillation count now excludes `_v[N]_` suffixed files (archived redistillations) from the tally.

## [1.6.0] - 2026-03-09

### Performance
- **Merged redistill + label popups** — redistillations now confirm both the action (archive/update/delete) AND the source label in a single popup instead of two sequential FULL STOP gates. First-time distillations unchanged.
- **Tool manifest (Phase 1.7)** — after PDF scan, determines ALL specialist tools needed upfront and batches demand-install offers into a single popup. Eliminates per-route install interruptions.
- **Simple PDF gate (Phase 1.8)** — gated cascade pattern (from sigma hook) skips all specialist routing for text-only PDFs. If scan shows no tables/layout/scans/equations/images, goes straight to PyMuPDF text. Zero specialist overhead.
- **Parallel figure decomposition** — cropped images now read in batches of 5-10 via parallel Read calls instead of one-by-one. 3-5x speedup for figure-heavy documents.
- **Unified vision OCR gating** — Route D's redundant budget gate for fully_scanned PDFs removed. Phase 1.5 Figure Budget Gate decision now propagates to all downstream routes (single decision point).
- **Pure_mode interpretation skip** — pure_mode distillations skip the interpretation review popup entirely (no interpretation file to review).
- **Context passing** — parent distill skill reads project config once and holds it in conversation context. Sub-skills verify loaded context rather than re-reading the file, eliminating 2 redundant file reads per distillation.

### Architecture
- **Dynamic concept scaling** — Key Concepts table depth scales with source length: 5-8 concepts for short sources (<20pp), 8-15 for medium (20-100pp), 15-25 for long (100+pp). Mirrors sigma hook's dynamic scalar pattern.
- **Robust template merging** — Figure↔Concept Contrast folded into Figures section (each figure now self-contained with concept mappings). Empirical Data folded into Theoretical & Methodological Implications as a conditional subsection with expanded guidance. Both merged sections are more substantive, not thinner.
- **Buffer→distill structural alignment** — three buffer patterns ported to distill: gated cascade (Phase 1.8), pre-computation (Phase 1.7 tool manifest), dynamic scalars (concept scaling)

## [1.5.0] - 2026-03-09

### Added
- **Resolution bin** — `alpha-resolve` command scans for unresolved concept entries (`concept="?"`) and presents resolution candidates with suggested names extracted from "Maps to" fields. Supports `--auto` flag for batch resolution of ready entries. Writes `.resolution_queue` for reference.
- **Tick counter** — sigma hook increments `.sigma_ticks` on every `UserPromptSubmit`. When threshold (50 messages) is reached, appends `resolution check due` to the hook's system message. Purely informational — the AI can choose to act on it or not.
- **Resolution check at session end** — Step 14c in buffer:off runs `alpha-resolve` after grid rebuild to surface unresolved entries. Informational only, never blocks.
- **Distill stats pipeline** — `.distill_stats` temp file flows through the distillation pipeline: extract writes (page counts, figure counts, routes used), analyze appends (concept count, mapping counts), integrate consumes and prints an end-to-end distillation report, then cleanup deletes it.
- **End-to-end distillation report** — integrate skill now prints a full report with source metadata, content breakdown, distillation summary, interpretation mappings, integration actions, and resolution queue count. Falls back to minimal summary when `.distill_stats` is absent.
- **Extraction agent** (scoped) — `distill/agents/extractor.md` defines a haiku-model autonomous agent for density-aware figure handling. Classifies documents as mathematical/empirical/philosophical/mixed and applies per-type figure density thresholds. Not yet wired into the pipeline — future work.
- **Lean project skill generation** — differentiate skill now explicitly instructs: do NOT duplicate pipeline code, templates, or troubleshooting into project skills. Content inclusion matrix updated.

### Architecture
- Resolution has three tiers: tick counter (per-message, lightweight), session end (buffer:off, informational), full-scan consolidation (every N sessions, with user confirmation)
- Resolution is NEVER automatic by default — always user-approved. `--auto` flag exists for batch operations but is not the default path
- `.distill_stats` is a pipeline artifact: created by extract, enriched by analyze, consumed+deleted by integrate
- Extraction agent uses density classification to avoid both under-extraction and over-extraction of figures

## [1.4.0] - 2026-03-09

### Added
- **Wall inhibition** — `[wall]` convergence edges now actively inhibit: excluded from cluster computation (`compute_clusters` skips wall edges), marked as boundaries in traversal (`traverse_neighborhood` won't cross them), and counted in health report
- **TAP scoring** (adjacent possibility) — `tap_scoring()` replaces `default_scoring()` with temporal boost from sigma hits (ref_count, capped at 2x). Per-concept structural importance in the convergence web
- **TIP scoring** (included possible) — each grid cell now carries a `tip_score`: the composite of TAP scores at that contextual convergence point. Grid schema bumped to v2
- **Bidirectional sigma→alpha feedback** — `_read_sigma_hits()` parses `.sigma_hits` log and feeds ref_count/last_ref/trend into `compute_reinforcement()`. Sigma operational usage now strengthens alpha structural importance
- **Polyvocal provenance encoding** — `origin` field on all alpha entries: `distill` (diachronic, from source extraction) or `session` (synchronic, from dialogue). `backfill_convergence_tags()` retroactively tags existing entries
- **Convergence tag indexing** — `convergence_tag` extracted from `[tag]` in synthesis field and stored in index.json for all cw: entries (52 independent_convergence, 45 complementarity, 14 elaboration, 4 genealogy, 2 tension)
- **Grid rebuild on buffer:off** — Step 14b runs `alpha-reinforce → alpha-clusters → alpha-grid-build` before commit, ensuring the grid reflects the new session's orientation
- **Enhanced health report** — now shows wall edge count, provenance split (diachronic/synchronic), TAP distribution (adjacent/unadjacent), and temporal feedback count

### Architecture
- Alpha-sigma flow is bidirectional: alpha→sigma (grid gate injection) and sigma→alpha (temporal hit feedback)
- TAP = per-concept adjacency score; TIP = per-cell inclusion score (compositional)
- Walls enforce conceptual boundaries — anti-conflation, not disconnection
- Provenance is polyvocal: distill/session voices inhabit every layer, not separate containers

## [1.3.0] - 2026-03-09

### Added
- **Mesological relevance grid** — pre-computed alpha*sigma scoring replaces runtime O(n) IDF search with O(1) keyword lookup. New file `grid_builder.py` builds a relevance grid from reinforcement data + sigma orientation. Per-message cost: ~10ms.
- **Grid gate (Gate 0c)** in sigma hook — fires before IDF scoring. If grid exists and keywords match, injects 5 precisely targeted concepts and exits. Falls through to existing IDF if no grid or no match.
- **`alpha-reinforce`** command — computes reinforcement degree, source diversity, and prime status for all w: entries from convergence_web adjacency graph (83/117 edges resolved, 34 primes identified)
- **`alpha-clusters`** command — BFS connected components from cw: graph (23 clusters, largest = 14 members)
- **`alpha-neighborhood`** command — walk-weighted BFS traversal from any w:/cw: ID with configurable hop depth
- **`alpha-health`** command — diagnostic report: Youn ratio, prime rankings, cluster density, staleness tracking
- **`alpha-grid-build`** command — builds the relevance grid (thin wrapper delegating to `grid_builder.py`)
- **`[wall]` convergence type** — anti-conflation marker for concepts that look similar but must not be conflated (inhibitory edge)
- **Temporal hit tracking** — `.sigma_hits` log records which concepts the sigma hook activates; grid builder uses this for temporal relevance signatures
- **Post-integration grid rebuild** in distill integrate skill — automatically runs `alpha-reinforce` + `alpha-clusters` + `alpha-grid-build` after new entries are written
- **Improved concept resolution** — `_resolve_concept_to_wids` now normalizes separators (hyphens/underscores/slashes) and does substring matching as fallback, improving cw edge resolution from 55% to 71%
- **Pluggable scoring function** — `default_scoring(degree, diversity, is_prime)` interface allows future swap to Euler product formulation without changing surrounding code

### Architecture
- Alpha bin = diachronic metathesis (structural, accumulative, res)
- Sigma bin = synchronic metathesis (contextual, immediate, verba)
- Relevance grid = mesological function at the interaction point
- Net token impact: NEGATIVE (~100 tokens precise injection vs ~2000 generous dump)

## [1.2.0] - 2026-03-09

### Added
- **Scanned PDF handling** — Route D now offers pytesseract as intermediate OCR option between Docling and vision fallback. Vision OCR batches pages in chunks of 5 with progress reporting
- **Figure budget gate** — documents with >15 figure-candidate pages trigger a popup offering: extract all, sample every Nth page, OCR text only, or specify pages. Prevents runaway extraction on image-heavy documents
- **Scan script enhancements** — `distill_scan.py` now reports `total_images`, `image_pages`, and `fully_scanned` flag. Fully scanned PDFs are prominently flagged in the summary
- **MANDATORY REVIEW** interaction level — dense information (scan summary, interpretation review) now prints as plain text with a brief popup for decision only. Replaces cramming verbose data into narrow popup boxes
- **FULL STOP protocol** — all user interaction points (MANDATORY POPUP and MANDATORY REVIEW) now enforce a hard stop: the AI's turn ends with the AskUserQuestion call, preventing the pattern of asking but continuing to work
- **Integration results summary** — plain text summary of all integration actions (INDEX.md, alpha entries, convergence web, MEMORY.md, validation) printed after integration completes
- pytesseract added to demand-install inventory with platform-specific Tesseract binary links

## [1.1.0] - 2026-03-08

### Added
- **Alpha enrichment** — each alpha `.md` file is now a self-contained knowledge atom (30-80 lines) with Definition, Significance, Project Mapping, Related cross-references, and Source citation. Sigma never needs to read the full distillation to recall a concept
- `alpha-enrich` subcommand — enriches existing alpha entries in place (preserves header/mapping, replaces body). Accepts JSON array of `{id, body}` objects
- `--input` flag on `alpha-write` and `alpha-enrich` — reads JSON from file instead of stdin, bypassing Windows encoding issues with piped UTF-8
- **TERMINAL anti-entropy directive** — `<!-- TERMINAL: ... -->` HTML comment embedded in every enriched entry prevents downstream AI instances from following reference chains back to full distillation files
- `body` field support in `make_cross_source_md()` — appends rich content after Mapping section; backward-compatible (no body = thin stub)
- `context` field support in `make_convergence_web_md()` — appends `## Context` section after Tetradic Structure
- `distillation` field — renders as `**Distillation**: filename.md` for traceability
- **Enrichment guidelines** in integrate SKILL.md — future distillations auto-produce rich alpha entries
- `distill_backfill_alpha.py` — one-time backfill script parsing Key Concepts tables from distillation files
- `create_missing_alpha.py` — generates alpha-write JSON for sources with distillations but no prior alpha entries
- 12 new test cases for alpha-enrich

### Impact
- Alpha entries grow from ~7-line stubs to ~25-30 line knowledge atoms
- Sigma hook reads are terminal — one file, zero follow-up reads, massive token savings at recall
- 219 entries enriched with TERMINAL directive across sigma-TAP project
- 42 new entries created for 4 previously-unmapped sources

## [1.0.0] - 2026-03-07

### Added
- **Distill companion plugin** — source distillation extracted from monolithic skill into standalone `distill` plugin with 4 sub-skills: `differentiate`, `extract`, `analyze`, `integrate`
- **Alpha existence guards** — all alpha bin wiring in sigma_hook, on/off skills gated behind `os.path.isdir(alpha_dir)`. Buffer works without alpha (hot/warm/cold only); installing distill and running first distillation lights up alpha automatically
- **Post-compaction relay** — PreCompact writes `.compact_marker`, next UserPromptSubmit detects it and injects full buffer recovery into context, then erases marker. Closes mid-session compaction gap
- **Compact hook import guard** — `__name__ == '__main__'` guard on UTF-8 stream wrapping prevents IO corruption when sigma_hook imports compact_hook via importlib
- **Marketplace publishing** — both buffer and distill plugins listed in `.claude-plugin/marketplace.json`

### Changed
- Plugin version bumped to 1.0.0
- Global distill skill (`~/.claude/skills/distill/SKILL.md`) retired to 16-line redirect pointing users to the distill plugin
- Sigma hook gate numbering: Gate 0a = compact relay, Gate 0b = distill-active

## [0.3.0] - 2026-03-07

### Added
- **Dynamic scalar config** — layer limits (hot_max, warm_max, cold_max) stored in handoff.json as data, overridable per-project in skill config
- **Distill-active gate** — sigma_hook detects `.distill_active` marker to inject relevant alpha context during active distillation sessions
- **Configurable layer limits** — `detect_layer_limits()` and `resolve_limits()` in buffer_manager.py read project-level overrides from on.md skill config; CLI flags override everything

### Changed
- buffer_manager.py uses `resolve_limits(args)` consistently instead of hardcoded constants
- compact_hook.py reads project-level layer limits for accurate compact summaries

## [0.2.0] - 2026-03-07

### Added
- **Alpha bin** — separates reference memory (static, query-on-demand, no decay) from working memory (dynamic, session-facing, bounded, appropriate decay)
- `migrate_to_alpha.py` — one-time migration script to decompose warm layer concept_map/convergence_web into individual referent files under `alpha/`
- `alpha-read` command — read alpha bin index, output summary
- `alpha-query` command — retrieve referents by ID, source, or concept (loads individual files on demand)
- `alpha-validate` command — check alpha bin integrity (index vs files on disk)
- `rebuild_index` capability — self-healing index reconstruction from files on disk
- Schema normalization layer — handles variant entry schemas (key vs source field, missing attribution, ref-inferred routing)

### Changed
- `next-id` now scans both warm layer AND alpha bin to prevent ID collisions
- `validate` now includes alpha bin status and resolves see-refs against alpha
- Compact hook summary includes alpha bin referent count
- Architecture doc updated with alpha layer table and design documentation
- Distill skills (global + project) write to alpha bin when present, fall back to warm
- Buffer on/off skills updated for alpha-aware pointer resolution and consolidation

### Impact
- Warm layer shrinks from ~3,680 lines to ~274 lines (on sigma-TAP project)
- `/buffer:on` no longer loads ~52K tokens of reference material by default
- Individual referent files (30-80 lines each) loaded on demand via `alpha-query`

## [0.1.5] - 2026-03-06

### Changed
- Plugin renamed from `session-buffer` to `buffer` (invocation: `/buffer:on`, `/buffer:off`)
- Marketplace renamed from `session-buffer-marketplace` to `memory-tools-by-metafish`
- Updated 57+ references across repo files, local skills, and plugin infrastructure

## [0.1.4] - 2026-03-06

### Fixed
- Stale command references in architecture.md (7 instances of `/buffer:on`/`off` → `/buffer:on`/`off`)
- Stale skill directory names in README.md (`buffer-on/` → `on/`, `buffer-off/` → `off/`)
- Stale cross-reference in on skill ("see buffer-off" → "see off skill")
- Removed orphan YAML frontmatter from architecture.md (was a docs file, not a skill)
- Instance notes Step 7 incorrectly gated behind "Full mode only" — now runs in all modes

### Added
- Startup confirmation shows plugin version, scope mode, and days since last handoff
- Staleness warning when trunk is >7 days old
- Layer size summary after Totalize handoff (`Hot: N/200 | Warm: N/500 | Cold: N/500`)
- Hot layer size shown in Quicksave and Targeted confirmations

### Changed
- Compressed Script Tooling sections in both skills (net -24 lines)

## [0.1.3] - 2026-03-06

### Fixed
- Step 8 priority check could be skipped — agent would start working without asking
- Mode selector in off skill could be skipped — agent would default to Totalize

### Added
- MANDATORY popup guards with AskUserQuestion enforcement on both decision points

## [0.1.2] - 2026-03-06

### Fixed
- Parent `buffer` skill loaded 488 lines of architecture, letting agent improvise past operational skills

### Changed
- Buffer skill converted to 25-line thin dispatcher (routes to on/off, zero actionable knowledge)
- Architecture reference moved to `docs/architecture.md`

## [0.1.1] - 2026-03-06

### Changed
- Skills renamed: `buffer-on` → `on`, `buffer-off` → `off` (invocation: `buffer:on`, `buffer:off`)

### Fixed
- Project selector popup (Step 0c) now enforced as MANDATORY via AskUserQuestion

## [0.1.0] - 2026-03-06

### Added
- First working install via Claude desktop app git URL
- Three-layer sigma trunk (hot/warm/cold) with bounded sizes and downward migration
- Full and Lite scope modes
- Totalize, Quicksave, and Targeted handoff modes
- Multi-project support via global registry (`~/.claude/buffer/projects.json`)
- Automatic context preservation via PreCompact and SessionStart hooks
- Distillation-in-progress detection during compaction recovery
- Cross-platform Python shims (Unix + Windows)
- `buffer_manager.py`: handoff pipeline, validation, pointer resolution, ID assignment
- `compact_hook.py`: pre/post compaction marker system with context injection
- MEMORY.md integration (full or none) with promoted entry sync
- Autosave protocol with overflow guardrails
- Provenance-aware consolidation (self-integrated vs inherited entries)
- Tower archival with user-guided questionnaire
