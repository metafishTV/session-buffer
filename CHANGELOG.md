# Changelog

All notable changes to buffer are documented here.

## [buffer 3.7.0 / distill 3.1.0] - 2026-03-19

### Managed rules deployment (both plugins)
- **`.claude/rules/` deployment** — both plugins now deploy managed rules files to the project's `.claude/rules/` directory on SessionStart via setup hooks. Rules files are always loaded into Claude's system prompt and survive context compaction (re-read from disk each turn). This is the missing persistence layer — previously, behavioral directives only lived in SKILL.md files (loaded on demand) and plugin CLAUDE.md (which wasn't actually loading into context).
- **`buffer-compact-protocol.md`** — post-compaction recovery protocol, user interaction gates (AskUserQuestion enforcement, FULL STOP), autonomy boundaries (no autonomous buffer skill invocation, no routing bypass, no auto-resolve/auto-modify), data integrity (no silent drops, overflow guard, tower file consent), worker session directives (standing orders, full field, dialogue style), epistemic conduct (honest instance notes).
- **`distill-pipeline-enforcement.md`** — pipeline enforcement (never write distill/interpretation files without skill), extraction prohibition (absolute — no ad-hoc PyMuPDF/fitz), redistillation detection (all four checks mandatory), FULL STOP protocol, forward notes with reserved range protection, figure vs equation policy, distillation voice & atom markers, template-first principle, infrastructure protection (never modify bundled scripts).
- **`setup_hook.py` (buffer)** — new script, registered on SessionStart. Health checks (stale handoff, orphaned distill marker, alpha consistency) plus managed rules deployment. Version-tagged, idempotent (skips if content unchanged), fail-safe.
- **`setup_hook.py` (distill)** — new script, registered on SessionStart. Managed rules deployment only. Same idempotent/fail-safe pattern.
- **Audit-driven content** — rules content assembled from thorough audit of both plugins' SKILL.md files, architecture docs, and agent definitions. 13 buffer directives and 7 distill directives promoted from skill-specific locations to always-loaded rules.

## [buffer 3.6.0] - 2026-03-18

### Multi-ball football + intercept
- **Multi-ball mode** — throw multiple footballs to parallel workers. Each ball gets a human-readable ID (`MMDD-slug-N`, e.g. `0318-alpha-repair-1`). Registry tracks all balls and their states.
- **Target types** — balls can target a separate Claude Code `instance` or a dispatched `subagent`. Set via `--target` flag on throw.
- **`intercept` command** — recover from dead workers or redirect balls. Packs the prior worker's partial progress (completed tasks, decisions, flags) onto the ball as `prior_worker_progress`. Intercepts chain — a ball can pass through multiple workers.
- **`catch` with selection** — when multiple balls are in flight, returns an `"action": "choose"` response with ball descriptions for the skill layer to present as a popup.
- **Backward compatible** — no registry file = legacy single-ball mode, unchanged. First `--multiball` throw creates the registry.
- **Schema update** — `football.schema.json` adds `ball_id`, `target`, `intercepted`, `prior_worker_progress` fields.
- **README** — documents single-ball, multi-ball, intercept, CLI reference, and file layout.

### Alpha bin auto-increment bug fix
- **`buffer_manager.py` `alpha_max_id()`** — now scans both `entries` dict AND `sources` dict in index.json, preventing stale-counter collisions after external rebuilds.
- **`_alpha_disk_max_ids()`** — new safety net in `alpha-write`: scans .md file headers on disk to find the true max ID, independent of the index.

## [buffer 3.5.0] - 2026-03-17

### Reliability: encoding, BOM, locking, hollow pipe audit
- **48-bug hollow pipe remediation** — worker football audit found and fixed 48 bugs across 10 classes (torn writes, TOCTOU, hollow pipes, orphaned markers, monotonicity, semantic narrowing, version drift, timezone skew, unbounded growth, idempotency) in 17 files.
- **safe_io.py** — new shared I/O safety utility: atomic writes (temp+rename via `os.replace`), validated reads (`HollowFileError`), schema version forward-compat checks, marker TTL enforcement, atomic counters, cross-platform file locking.
- **BOM-safe reads** — all JSON reads across 13 scripts now use `utf-8-sig` encoding, transparently stripping BOM if present (old Windows Notepad adds BOM to UTF-8 files). Writes remain `utf-8` (no BOM produced).
- **Encoding fix** — `buffer_football.py` had 10 bare `open()` calls defaulting to cp1252 on Windows, crashing on any unicode content (em-dashes, etc.). All now specify encoding explicitly.
- **File locking** — `safe_io.file_lock()` context manager using atomic `O_CREAT|O_EXCL` lock files with stale-lock detection. Wired into `atomic_read_modify_write_json` and `atomic_increment_counter` to prevent concurrent hook write races.
- **Headroom telemetry rewired** — statusline detects tier crossings (it receives `context_window` data), sigma_hook injects warnings. Previously sigma_hook tried to do both but never received the data (hollow pipe).
- **UTC standardization** — all timestamps across 25+ call sites in 8 files now use UTC.

## [buffer 3.4.0] - 2026-03-17

### Onboarding + Help
- **Returning user gate** — first-run now asks "Have you used the buffer plugin before?" to skip orientation for experienced users.
- **Welcome orientation** — new users see a plain-text overview of all skills, modes, and what they can change later, before the configuration popups begin.
- **`/buffer:help`** — new skill. Mode-aware reference card showing all available skills, current configuration, upgrade paths (lite users), remote backup setup (local-only users), and tips.

## [buffer 3.3.2] - 2026-03-17

### Marketplace + onboarding fixes
- **Fix marketplace.json versions** — marketplace manifest was stuck at buffer 1.1.0 / distill 1.2.0, causing new installs to report stale versions. Now matches actual plugin versions.
- **Private repos by default** — first-run onboarding now creates GitHub repos as private unless user explicitly requests public.

## [buffer 3.3.1] - 2026-03-17

### Bugfix: throw/catch skill visibility
- **Fix throw/catch skill names** — skills had double-prefixed names (`buffer:buffer:throw`) preventing them from appearing in slash command list. Now correctly register as `/buffer:throw` and `/buffer:catch`.
- **Sanitize examples** — replace project-specific references in SKILL.md examples and CONVENTIONS.md with generic placeholders for public release.
- **Gitignore** — add `_distill_*` temp file patterns.

## [buffer 3.3.0] - 2026-03-14

### Headroom Check + Telemetry (Layers 2-3)
- **Headroom check (Layer 2):** Context pressure tier detection (watch/warn/critical at 70/85/93%) with universal sigma hook injection on tier crossing. Informs, never blocks.
- **Statusline `ctx:XX%`:** Passive context pressure indicator for CLI users — `ctx:72%` (watch), `ctx:87%!` (warn), `ctx:95%!!` (critical).
- **Telemetry (Layer 3):** Append-only `.claude/buffer/telemetry.jsonl` with three event types: `compact` (emitted by pre-compact hook), `headroom_warning` (emitted by sigma hook on tier crossing), `session_end` (emitted by `/buffer:off`).
- **`telemetry.py`:** Shared utility with `emit()`, `tier_from_percentage()`, `cache_ratio()`, and `session-end` CLI subcommand. Fail-silent — telemetry never breaks hooks.
- **21 new tests** (17 telemetry + 4 headroom), all passing.

## [buffer 3.2.0] - 2026-03-14

### buffer:football — Cross-Session Task Delegation
- **`/buffer:throw`** — dyadic skill: planner packs football (heavy = full context + dialogue style, lite = task only); worker returns results (lite = output diff, heavy = full micro-hot-layer).
- **`/buffer:catch`** — dyadic skill: worker initializes micro-session (adopts `dialogue_style` silently from first response); planner absorbs results, reviews flagged items, digests into trunk.
- **`buffer_football.py`** — script backing both skills: `status` (session detection), `pack`, `unpack`, `validate`, `flag`, `archive`. Importlib-based buffer_utils integration.
- **`schemas/football.schema.json`** — new schema for football envelope (heavy/lite, planner/worker payloads, flagged_for_trunk items).
- **`schemas/hot-layer.schema.json`** — adds optional `football_in_flight` boolean and `dialogue_style` to `instance_notes.properties`.
- **`/buffer:off` guard** — warns when a football is in flight before saving trunk.
- **18 new tests**, all passing.

## [buffer 3.1.0] - 2026-03-14

### Dialogue Continuity + Compaction Directives
- **Dialogue style continuity** — `instance_notes.dialogue_style` field (≤2 sentences) captures session conversational register — tone, cadence, level of formality. `/buffer:off` writes it; `/buffer:on` Step 7 reads it and adopts it silently from the first response. No tonal reset between sessions.
- **Layer 1 compaction directives** — PostCompact hook wired; `generate_directive_context()` reads `compact-directives.md` and `.session_active`, injects depth-adaptive guidance into every compaction event. Session vocabulary section (ephemeral neologisms/project terms) survives mid-session compactions, wiped at next `/buffer:on`.
- **`/buffer:status` command** — On-demand health report: buffer state, directives file presence, CLAUDE.md compaction section, session depth.
- **Session depth tracking** — `.session_active` tracks `off_count`; four display states: `buf:--`, `buf:saved`, `buf:on`, `buf:off xN`. Depth-adaptive guidance scales with compaction count.
- **Registry-primary buffer discovery** — `buffer_utils.py` shared module with `is_git_repo`, `match_cwd_to_project`, `read_registry`, `find_buffer_dir`. `sigma_hook.py` and `compact_hook.py` delegate to it. Git-guarded walk-up fallback.
- **CLAUDE.md** — Version bump checklist for contributors.
- **Architecture docs** — `dialogue_style` schema and size limits; lite mode behavior documented.
- **10 new compaction tests**, all passing.

## [buffer 3.0.0 + distill 3.0.0] - 2026-03-13

### Plugin Portability — First-Run Gate, Lite Mode, Upgrade Path
- **First-run gate (distill)** — PreToolUse hook blocks distill skills until `/distill:differentiate` has configured the project. Checks for `SKILL.md` or `distill.config.yaml`. Fails open on errors.
- **Lite mode (buffer)** — Sigma hook hot-layer-only mode: skips alpha, regime, prediction error, grid, CW-boost. `detect_buffer_mode()` reads hot layer. Lite alpha: Claude-native document indexing with `mode:lite` marker.
- **Upgrade path** — Three trigger points (`buffer:on`, `differentiate`, `integrate`) detect lite alpha entries and offer/perform upgrade to full analysis.
- **Architecture docs** — Lite mode behavior, config file contracts, upgrade path.
- **430 tests** (30 new), all passing.

## [buffer 2.6.0 + distill 2.2.0] - 2026-03-13

### Plugin Standardization — Schemas, Contracts, Validation
- **Shared schema directory** (`schemas/`) — 8 JSON Schema files (draft 2020-12) defining all cross-plugin data formats: alpha-entry, convergence-web, alpha-index, manifest-source, forward-note, hot-layer, distill-stats, redistill-changelog.
- **Cross-plugin contract** (`schemas/CROSS_PLUGIN_CONTRACT.md`) — Three handoff points documented: alpha entry creation, convergence web creation, sigma hook reads. Formal interface spec for distill→buffer data flow.
- **Conventions doc** (`schemas/CONVENTIONS.md`) — 8 non-machine-validatable rules: source label naming, folder naming, concept key normalization, ID formatting, synthesis tags, relationship types, voice rules, atom markers.
- **Canonical normalize_key()** (`schemas/normalize.py`) — Single source of truth. Both `distill_manifest.py` and `buffer_manager.py` import from here (with inline fallback for standalone invocation). Eliminates 3 duplicated implementations.
- **Validation tooling** (`schemas/validate.py`) — Advisory CLI validator: `python validate.py all <project-root>` scans alpha index, manifest, forward notes, hot layer, distill stats. Exit code 0/1.
- **Redistill popup fix** — Extract skill's L2b redistillation check was never firing because `interpretations_dir` was missing from prerequisites. Fixed prerequisites + made all 4 existence checks explicit with concrete commands.
- **Redistill changelog** — New `.redistill_changelog` JSON artifact produced during re-distillation (Step 2c in integrate skill). Records concept diff (added/removed/retained/modified) and alpha changes (new/updated/orphaned IDs). Schema: `redistill-changelog.schema.json`. Analyze skill now shows "Changes from previous distillation" in interpretation summary.
- **Manifest redistill_history** — Per-source manifest entries gain `redistill_history` array tracking date, mode, concept count, and changelog path across re-distillation passes.
- **40 new tests** across 3 test files (test_normalize: 8, test_validate: 27, test_redistill_changelog: 5). All passing.

## [buffer 2.5.0] - 2026-03-12

### Cooldown Timer
- **Sigma hook cooldown gate** — New `check_cooldown()` function prevents rapid re-firing when the AI cycles on idle. Uses `.sigma_last_fire` timestamp file with 30-second minimum interval between firings. Eliminates token waste from repeated no-op sigma hook invocations during inactive periods.
- **4 new tests** for cooldown behavior (first fire, blocked within window, expired cooldown, missing marker). Total: 133 buffer tests, all passing.

## [distill 2.1.0] - 2026-03-12

### Agent Delegation, Slide Extraction, Batch Mode, UX Improvements
- **Explicit agent delegation** — Extract skill now instructs the AI to dispatch the `source-extractor` agent (haiku) for PDF sources >5 pages. Reduces token cost by offloading mechanical extraction to a cheaper model.
- **Batch distillation** — New `--batch` flag processes multiple independent sources in parallel. Dispatches up to 3 concurrent `source-extractor` agents, then runs analyze/integrate sequentially. Independent batch mode also available via Multi-Source popup.
- **Slide extraction script** — New `distill_slides.py` extracts unique slides from lecture/presentation videos using SSIM-based frame comparison. Dependencies: opencv-python-headless (~30MB, demand-install) + yt-dlp (existing). Outputs slide PNGs + manifest JSON. Integrated into Route R (recordings) as Step R3a, with manual keyframe capture as fallback.
- **Extractor agent sync** — Updated `agents/extractor.md` to match current pipeline: added Phase 1.7 (tool manifest), Phase 1.8 (simple PDF gate), Phase 1.9 (timeout batching), FULL STOP gate protocol, and partial-result return format for parent-agent coordination.
- **Glossary template** — Integrate skill now includes inline glossary format template with explicit instructions for both README and project SKILL.md updates. Eliminates redundant file reads to learn the format. Maximum 5 new terms per distillation.
- **Author folder suggestion** — After integration, if any first-author has 3+ distillations in the flat directory, offers to organize into a subdirectory. User can accept or decline (persisted via `.author_folders_declined` marker).
- **opencv demand-install** — Added opencv-python-headless to the Demand-Install Protocol tool registry with probe support.

## [buffer 2.4.0] - 2026-03-11

### Regime Accumulator, Directional Asymmetry, CW-Boost, SWM Groundwork
- **Session regime accumulator** — Sigma hook now maintains `.sigma_regime` state file tracking per-concept activation levels across the session. Shannon entropy H gauges session focus: low entropy (focused conversation) lowers the firing threshold, high entropy (exploratory) raises it. Decay rate 0.85 (half-life ~4.3 prompts). Inspired by Tafazoli et al.'s "task belief" signal in LPFC.
- **Directional asymmetry** — On-step (concept entering conversation) gets persistence penalty (0.5x), requiring sustained mention to fire. Off-step (concept leaving) handled by natural decay — no special code. Inspired by Mangan & Alon's FFL sign-sensitive delay: coherent FFLs reject brief transients in one direction.
- **Pulse generation** — Strong first-contact concepts (regime activation == 0, score >= 1.3x threshold) bypass persistence penalty and get 1.5x boost. Weak first contacts still face persistence detection. Models the incoherent FFL's pulse generation for novel strong signals.
- **CW-graph neighbor boost** — When a concept scores above threshold, its convergence web neighbors get 30% of its score as uplift. Rich-get-split splash: concepts exceeding 1.3x threshold (saturation cap) redistribute excess to the highest sub-threshold concept within 15% eligibility band. Max 5 cascade iterations. Inspired by Wright et al.'s local synaptic coactivity.
- **Ambiguity signal** — When no concepts match, scans for the highest-scoring concept within 90-100% of threshold. If found, emits `sigma: near [concept] — consider /buffer-on`. ~10 tokens, zero cost on the hot path.
- **D_KL tracking (SWM groundwork)** — KL divergence between current and previous regime activation distributions computed on each update. Stored as `_dkl` (current) and `_dkl_cumulative` (session total) in `.sigma_regime`. Purely diagnostic — the SWM's "becoming rate" is now measurable.
- **31 new tests** across 8 test classes (entropy, threshold modifier, regime update, directional asymmetry, CW-boost, ambiguity signal, D_KL, integration). Total: 125 tests, all passing.

## [distill 2.0.0] - 2026-03-11

### Stateful Knowledge System — Manifest, Quality Metrics, Graph Math, RIP Feedback
- **Distillation manifest** — New `distill_manifest.py` engine (~620 lines) with 8 commands: `init`, `update`, `query`, `health`, `quality`, `repass`, `adjacency`, `export`. Produces `manifest.json` at `<repo>/.claude/skills/distill/` — single source of truth for all distillation state. Polymorphic consumer views (pass4, integrate, sigma, health) return tailored projections.
- **Quality metrics** — Per-source quality assessment: concept_density, coverage_ratio, cross_ref_density, forward_note_yield, convergence_contribution, composite_quality (harmonic mean). Quality cards displayed during integration. Sources below 0.20 composite flagged for review.
- **Source-source adjacency matrix** — Built from convergence web edges. Structurally isomorphic to sigma-TAP's L-matrix at the source level. Hub scores (normalized degree), clustering coefficients, isolation detection.
- **Graph Laplacian** — L = D - A computed with numpy (graceful fallback without). Algebraic connectivity (Fiedler value) measures graph cohesion. Eigenvalue analysis detects near-disconnected components.
- **Spreading activation** — When a source is updated, activation propagates through the adjacency graph with exponential decay (0.5) and threshold (0.2). Sources exceeding threshold are added to the repass queue. Bounds recursion naturally.
- **Information gain** — Per-concept: `-log2(prior_frequency / total_concepts)`. Novel mappings get maximum IG, well-confirmed ones get low IG. Stored in manifest per concept.
- **RIP feedback loops** — Recursion (repass queue), Iteration (convergence criterion, cap 3), Persistence (manifest JSON). Feedforward: new distillations trigger re-pass of prior sources via spreading activation. Feedback: prior open questions resolved by new sources. Polyvocal: multiple triggers merged.
- **Re-pass mode** — New `/distill --repass` flag. Analyze runs concept-level targeted re-analysis using triggering sources' perspectives. Only revisits specified concepts, not full distillation. Integration updates manifest and alpha entries.
- **Living differentiate** — Step 0 now reads manifest stats when presenting project config. New "Verify & update" option re-scans adjacency and quality metrics.
- **Integrate manifest steps** — Steps 5c (manifest update) and 5d (quality card + repass report) added after grid rebuild.
- **Test suite** — 59 tests across 10 test classes covering IO, metrics, graph math, spreading activation, repass queue, bootstrap, parsing, and stats.
- **Sigma-TAP bootstrap** — Manifest initialized with 33 sources, 309 concepts, 86 cw edges, 5 hubs (Cortes, Emery, Lizier, Levinas, Sartre), 15 isolated sources.
- **New dispatcher flags** — `--repass`, `--manifest`, `--quality [source]`.

## [distill 1.13.0] - 2026-03-11

### Forward Note Consolidation
- **Forward note health analysis** — New `distill_forward_notes.py` script scans `forward_notes.json` for consolidation clusters (related notes via Jaccard + alpha concept overlap), supersession candidates (self-identified redundancy, cross-references, implemented status), and source density. Invoke via `/distill --notes-health` or directly.
- **Consolidation** — `consolidate` command merges specified notes: surviving note gets updated description, absorbed notes get `status: "merged_into"` with pointer. Always user-reviewed — never auto-consolidates.
- **Integrate step enhancement** — Step 4c added to integrate SKILL.md: after writing new forward note candidates, runs similarity check against existing notes. Flags potential consolidation targets in the integration report. Status lifecycle extended with `merged_into`.
- **check-new command** — Lightweight similarity check for integrate step: compares a new candidate description against all existing notes, returns matches above threshold. Uses both direct word overlap (Jaccard) and concept-mediated overlap (alpha concept_index cross-reference).

## [buffer 2.3.0] - 2026-03-11

### Kirsanov Intelligence Layer (Predictive Coding + Resonator Dynamics)
- **Prediction error tracking** — Sigma hook now records prediction errors to `.sigma_errors` (JSONL). Two error types: *gaps* (keywords with high signal but no alpha match — the buffer's blind spots) and *false positives* (grid predicted relevance but user never engaged). `alpha-health` reports top gap keywords, surfacing concepts the user discusses that alpha doesn't yet have. Inspired by Kirsanov's predictive coding: prediction errors drive both inference and learning.
- **Resonator dynamics** (temporal co-activation) — Sigma hook records co-activation pairs to `.sigma_coactivation` when multiple concepts fire in the same hit. Co-firing frequency builds resonance weights. `compute_spread()` now weights neighbors by both structural adjacency AND temporal co-activation history — concepts that historically fire together spread more strongly. `alpha-health` reports top resonance pairs. Inspired by Kirsanov's Neural Dynamics: resonators detect temporal coincidence.
- **Continuous score adjustment (W')** — Each sigma hit incrementally adjusts concept scores in `.sigma_scores`, creating real-time learning between batch `alpha-reinforce` runs. Tracks W' (wholeness gradient) — the derivative of the energy function. Grid builder reads these scores as alpha score boosts (capped at 3x). The user's insight: continuous adjustment IS W' — the rate of change of wholeness. W is the energy, W' is the gradient, prediction errors drive the gradient.
- **Incremental grid updates** — Sigma hook records grid cell confirmations to `.grid_adjustments` (JSONL). Grid builder reads and applies these as score nudges (+0.05 per confirmation, -0.05 per disconfirmation), then clears the file. Prevents catastrophic forgetting — accumulated sigma feedback persists across rebuilds. Grid schema bumped to v3.
- **Buffer phase portrait** — `alpha-reinforce` now computes and records a buffer state vector (W, W', active concepts, clusters, hit rate, error rate) to `.buffer_trajectory` (JSONL, one snapshot per day). `alpha-health` displays the last 5 trajectory snapshots as a phase portrait table. Tracks the buffer's dynamical evolution over sessions. Inspired by Kirsanov's Neural Dynamics: qualitative properties emerge from phase space geometry.

## [buffer 2.2.0] - 2026-03-11

### Wholeness, Spreading Activation, and Upward Promotion
- **Wholeness (W)** — Dynamic rolling energy scalar measuring coherence of the active concept field. W = count of convergence web edges where both endpoints are sigma-activated. Computed by `alpha-reinforce`, updated incrementally by sigma hook on every activation. Reported in `alpha-health`. Inspired by Alexander's Wholeness (geometric coherence) formalized via Hopfield energy function.
- **Spreading activation** — Sigma hook now propagates matched concepts to 1-hop convergence web neighbors. Uses `.cw_adjacency` cache (written by `alpha-reinforce`) for O(degree) spreading without loading full index. Neighbors activated by multiple source concepts rank higher. Injection format: `| spread: w:73 rhizomatic`. Creates Hopfield-style pattern completion through the convergence web — mentioning one concept surfaces structurally adjacent concepts.
- **Upward promotion** (anopressive channel) — `alpha-health` now reports concepts with 3+ sigma hits as promotion candidates. `/buffer:off` conservation step includes upward promotion check: frequently activated concepts in cold/warm can be promoted to `concept_map_digest.flagged` for immediate access. Closes the anapressive-anopressive loop (conservation pushes down, promotion pulls up based on operational relevance).
- **Adjacency cache** — `alpha-reinforce` now writes `.cw_adjacency` (compact adjacency list + concept names) alongside index.json. Enables sigma hook spreading activation and incremental W updates without loading full index.

## [distill 1.12.1] - 2026-03-11

### Plugin Cache Fix
- **No code changes** — version bump only. The 1.12.0 cache sync missed `.claude-plugin/plugin.json` (glob `*` skips hidden directories), causing distill skills to not appear in Claude Desktop's autocomplete. Updating to 1.12.1 forces a clean re-cache.

## [distill 1.12.0] - 2026-03-11

### Cross-Distillation Intelligence Layer
- **Integration recovery** — New `distill_recover_integration.py` script scans all interpretation files, detects orphaned distillations (sources that ran in File-Only Mode), and generates alpha-write compatible JSON to backfill missing cross_source and convergence_web entries. Supports `--dry-run` preview. Invoke via `/distill --recover`.
- **Forward note registry** — New `forward_notes.json` at `<repo>/.claude/skills/distill/` tracks forward note number allocation with collision prevention and lifecycle tracking (`candidate` → `accepted` → `implemented` → `superseded`). Written by integrate, read by Pass 4 before assigning new §5.NN numbers.
- **Pass 4 cross-distillation awareness** — Before writing the interpretation, Pass 4 now reads the forward note registry (collision prevention), scans prior open questions (resolution check), and checks existing alpha mappings (duplicate prevention). Best-effort checks — candidates flagged for user review.
- **Integration health check** — Post-integration report now counts interpretation files vs alpha-indexed sources. Reports orphan gap with recovery instructions when detected.
- **Recovery mode** — New `/distill --recover` path skips normal pipeline and routes to integrate's Recovery Mode (Steps R1–R4): dry-run preview → mandatory review → alpha-write execution → grid rebuild.

## [distill 1.11.0] - 2026-03-11

### Config Discovery + Runtime Install Verification + Multi-Source
- **Project root discovery** — Dispatcher and differentiate now search CWD → git root → sibling directories → parent directory for `.claude/skills/distill/SKILL.md`. Fixes the root cause of "started questionnaire from scratch" when CWD differs from project root. All path resolution uses discovered `project_root`.
- **Lightweight tool detection** — Docling check in `distill_setup.py` changed from heavy `DocumentConverter` import to `importlib.metadata.version()`. Prevents false "not installed" when the package is present but a transitive dependency fails to load.
- **Extract runtime pre-check** — Phase 1.7 Tool Manifest and Demand-Install Protocol now verify tool installation at runtime (`importlib.metadata`) before consulting the project tooling profile. If a tool is installed but the profile says `demand-install`, the profile is updated silently. Eliminates false install popups across sessions.
- **Multi-source handling** — Dispatcher now detects multiple source inputs and prompts: "Series/sequence" (ordered, linked, compound label) vs "Independent items" (batch). Series mode offers combined vs separate transcript options. Prevents false cross-referencing between unrelated sources.

## [distill 1.10.0] - 2026-03-11

### Distillation Fidelity + Efficiency Fixes
- **Language correction** — Changed "summarize" to "distill" in differentiate setup (Pure mode option). Distillation preserves information density at fewer tokens; it does not simplify or summarize.
- **Dependency install pre-check** — Q6-Q10 install questions now gated by Step 1's runtime audit results, not just the tooling profile text. If a tool is already installed, the question is skipped entirely. Universal across all paths (fresh start, integrate, re-differentiate).
- **Template-first principle** — Sub-skills now use inline templates directly for all output formats (interpretation files, INDEX.md, alpha-write JSON, README rows). Existing files are only read when updating, not to learn patterns. Reduces redundant file reads per distillation.
- **Existence-check-first directives** — INDEX.md, README, and error log operations now branch on file existence: create-from-template vs read-for-update. Eliminates the generate-then-read-to-verify pattern.

## [2.1.0] - 2026-03-10

### Instruction Weight Reduction + Lite Mode Fix
- **SKILL.md split** — Full+alpha content (concept map validation, consolidation, pointer following, full-scan protocol, grid rebuild, resolution check, tower archival) extracted into companion `full-ref.md` files. Core SKILL.md files are self-contained for Lite mode and standard Full sessions. Full+alpha instances get a directive to also read `full-ref.md`. on/SKILL.md: 547→444 lines (19% reduction). off/SKILL.md: 532→395 lines (26% reduction).
- **Steps 3-5 Lite mode fix** — "Summarize active work", "Log decisions", and "List open threads" were incorrectly gated as Full-only in `/buffer:off`, despite the Lite schema including `active_work`, `recent_decisions`, and `open_threads`. A Lite Totalize handoff would not refresh these fields. Now available in all modes; Lite omits `see` pointer arrays (no concept map cross-references).
- **Beta/sigma confirmed mode-agnostic** — beta bin, briefing, sigma hook, and dialogue trace are correctly available in both Lite and Full modes without distill. Only alpha bin requires the distill plugin (gated by directory existence, not by mode).

## [2.0.0] - 2026-03-10

### Beta Bin + Narrative Transfer Architecture
- **Beta bin** (β) — narrative microbin with relevance-weighted rolling capture. `beta/narrative.jsonl` (JSONL, append-only) stores 1–5 sentence narrative entries with AI-assigned relevance scores (0.0–1.0). Relevance weighting is orthogonal to hot/warm/cold's recency weighting — beta preserves significance, sigma trunk preserves recency.
- **Relevance scoring heuristics** — user correction +0.3, convergence +0.3, user emphasis +0.3, named decision +0.2, surprise +0.2, framework touch +0.2, base 0.2. Signals additive, capped at 1.0.
- **Adaptive promotion threshold** — starts at 0.6, auto-adjusts: >10 promotions → +0.05 (too loose), 0 promotions → -0.05 (too tight), clamped [0.4, 0.8]. Stored in hot layer `beta_config.threshold`.
- **Session briefing** (`briefing.md`) — free-form narrative colleague-to-colleague handoff document (15–40 lines Totalize, 5–15 lines Quicksave/Targeted). Written at handoff (Step 7b), read first at `/buffer:on` (Step 2b). Narrative orients understanding before structured data provides precision.
- **Dialogue trace revival** — cold-layer `dialogue_trace.sessions` gets new entries each Totalize handoff (Step 7c), distilled from the briefing. Restores the session-over-session narrative history that was lost during the v2 migration.
- **Lightweight mesh** (v1) — at handoff, promoted beta entries with r >= 0.8 annotate matching decisions/alpha entries with a `narrative` field (1–2 sentences). Connects narrative to structure at the point of relevance.
- **Autosave beta capture** — each autosave writes a 1–3 sentence narrative entry with relevance score. Skip if nothing narratively significant happened (no noise entries).
- **Narrative-first presentation** — `/buffer:on` reads briefing → beta → structured state → concept map → alpha. The narrative answers "how did we get here?" before structure answers "what's the current state?"
- **Beta commands** — `beta-append` (JSON on stdin), `beta-read` (filters: `--min-r`, `--limit`, `--since`), `beta-promote` (marks entries above threshold, adjusts threshold), `beta-purge` (removes promoted+old and low-r+old, `--max-age`). Soft cap 100, hard cap 200 entries.
- **Compact hook integration** — PostCompact injection now includes session briefing (up to 20 lines) and recent high-relevance beta narrative (last 5 entries with r >= 0.5). Post-compaction recovery gets both structural state AND narrative context.
- **Alpha/beta/sigma naming** — α = reference knowledge (static, query-on-demand), β = narrative knowledge (dynamic, relevance-weighted), σ = real-time injection (per-message hook).

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
