# Full Mode + Alpha Reference — /buffer:on

> **Load condition**: Read this file only when `buffer_mode` is `"full"` AND `alpha/index.json` exists in the buffer directory. Lite mode and Full-without-alpha sessions do not need this content.

## Alpha Bin Tooling

These commands extend the core `buffer_manager.py` tooling for reference memory operations:

- `alpha-read --buffer-dir .claude/buffer/` — Read alpha bin index, output summary. For Step 1b.
- `alpha-query --buffer-dir .claude/buffer/ --id w:218` — Retrieve specific referent by ID. For Step 4 pointer resolution.
- `alpha-query --buffer-dir .claude/buffer/ --source Sartre` — List all entries from a source.
- `alpha-query --buffer-dir .claude/buffer/ --concept totalization` — Search by concept name.
- `alpha-validate --buffer-dir .claude/buffer/` — Check alpha bin integrity (index vs files on disk).
- `alpha-write --buffer-dir .claude/buffer/` — Write new alpha entries (JSON on stdin -> `.md` files + `index.json` update). Used by `/distill` and `/buffer:off`.
- `alpha-delete --buffer-dir .claude/buffer/ --id w:N cw:N` — Remove alpha entries (files + index cleanup). Used by `/buffer:off` consolidation.
- `alpha-reinforce --buffer-dir .claude/buffer/` — Compute reinforcement scores + cw_graph from convergence_web adjacency.
- `alpha-clusters --buffer-dir .claude/buffer/` — Compute cluster analysis from cw_graph (requires `alpha-reinforce` first).
- `alpha-neighborhood --buffer-dir .claude/buffer/ --id w:N [--hops 2]` — Traverse convergence_web neighborhood.
- `alpha-health --buffer-dir .claude/buffer/` — Health report (Youn ratio, primes, clusters, staleness, wholeness, promotion candidates).
- `alpha-grid-build --buffer-dir .claude/buffer/` — Build mesological relevance grid (pre-computed alpha*sigma scores).

**Convergence types**: `[convergence]` (default), `[divergence]`, `[tension]`, `[wall]` (anti-conflation — marks concepts that look similar but MUST NOT be conflated; acts as an inhibitory edge that breaks conceptual feedback loops).

### Wholeness, Spreading Activation, and Promotion

Three dynamic features operate on the alpha-sigma boundary:

**Wholeness (W)**: A rolling energy scalar measuring coherence of the active concept field. W = count of convergence web edges where both endpoints are active (via sigma hits). Computed by `alpha-reinforce` and updated incrementally by the sigma hook on every activation. Higher W = more coherent session engagement with the convergence web. Reported in `alpha-health`.

**Spreading activation**: When the sigma hook matches a concept, it propagates to 1-hop neighbors in the convergence web (via `.cw_adjacency` cache). Neighbors activated by multiple source concepts rank higher. Injection format: `sigma grid [cell]: w:62 alterity (levinas) | spread: w:73 rhizomatic`. This creates Hopfield-style pattern completion — mentioning one concept surfaces structurally adjacent concepts the user didn't explicitly name.

**Upward promotion** (anopressive channel): `alpha-health` reports concepts with 3+ sigma hits as promotion candidates. During `/buffer:off`, review these: frequently activated cold/warm entries may deserve promotion to a more accessible layer. This closes the anapressive-anopressive loop — conservation pushes down (anapressive), promotion pulls up based on operational relevance (anopressive).

### Predictive Coding + Resonator Dynamics (v2.3.0)

Five features from Kirsanov's Neural Dynamics and Brain Learning analysis:

**Prediction error tracking**: Sigma hook records errors to `.sigma_errors` (JSONL). *Gaps* = keywords the user discusses that alpha doesn't have. *False positives* = grid predicted relevance but no IDF match. `alpha-health` reports top gap keywords. Prediction errors drive both inference (spreading) and learning (W').

**Resonator dynamics**: When multiple concepts fire in the same sigma hit, their co-activation pair is recorded in `.sigma_coactivation`. Co-firing frequency builds resonance weights. `compute_spread()` weights neighbors by structural adjacency AND temporal co-activation — concepts that historically fire together spread more strongly. `alpha-health` reports top resonance pairs.

**Continuous score adjustment (W')**: Each sigma hit nudges concept scores in `.sigma_scores` (DELTA=0.1 per hit). Tracks W' (wholeness gradient) — the derivative of the energy function. Grid builder reads these as score boosts (capped at 3x). W is energy, W' is gradient, prediction errors drive the gradient.

**Incremental grid updates**: Sigma hook records cell confirmations to `.grid_adjustments` (JSONL). Grid builder applies nudges (+0.05 per confirmation, -0.05 per disconfirmation), then clears the file. Prevents catastrophic forgetting of accumulated sigma feedback.

**Buffer phase portrait**: `alpha-reinforce` computes a state vector (W, W', active concepts, clusters, hit rate, error rate) and records it to `.buffer_trajectory` (JSONL, one snapshot per day). `alpha-health` displays the last 5 trajectory snapshots. Tracks the buffer's dynamical evolution.

---

## Step 1b: Alpha Bin Detection

> Runs after Step 1 (read hot layer). Requires Full mode + alpha directory.

Check for alpha bin (reference memory separated from working memory):

```bash
scripts/buffer_manager.py alpha-read --buffer-dir .claude/buffer/
```

**If alpha exists**, present a one-line summary:
```
Alpha: N referents across M sources (fw: X, cs: Y, cw: Z)
```

Do **not** load any alpha content yet — individual referents are loaded on-demand via
pointer resolution (Step 4) or explicit `alpha-query`. The index is lightweight metadata
only.

**If alpha does not exist** and warm layer is over its cap, note:
```
Note: Warm layer is over cap. Consider running the alpha migration to separate
reference memory from session state.
```

---

## Step 4: Follow Flagged Pointers

> Runs after Step 3 (present session state). Full mode only — Lite mode skips.

Selective loading from warm/cold layers using the pointer-index system:

**For each entry in `concept_map_digest.flagged` and `concept_map_digest.recent_changes`:**

1. Collect all referenced IDs from `"see"` arrays (these will be `w:N` or `cw:N` IDs)
2. **If alpha bin exists**, check alpha index first — run `alpha-query --id [id]` to retrieve from alpha bin. Most `w:N` and `cw:N` IDs live in alpha after migration.
3. **Fall back to warm** — if not in alpha, read `handoff-warm.json` and extract matching entries
4. If a warm entry has `"see_also"` references, read `handoff-cold.json` and extract those entries
5. **Max cascade depth: 3** (hot -> alpha/warm -> cold, then stop)
6. **Visited set**: track all followed IDs to prevent circular references
7. **Broken ref**: if an ID is not found in any layer or alpha, log `"Broken reference: [id] not found"` and continue
8. **Tombstone**: if an entry has `"archived_to"`, note: `"[id] was archived to [tower file]. Ask user if retrieval is needed."`
9. **Redirect tombstone**: if an entry has `"migrated_to"`, follow the redirect to the indicated layer and load the target entry

**For each `open_thread` with `"see"` pointers:**
- Follow into warm layer, present relevant context

Present flagged/changed concepts:
```
## Concept Map Changes
- [NEW] [summary] (see w:N)
- [CHANGED] [summary] (see w:N)
- [NEEDS_USER_INPUT] [summary] (see w:N)
```

---

## Step 5: Check Full-Scan Threshold

> Runs after Step 4. Full mode only — Lite mode skips.

If `sessions_since_full_scan >= full_scan_threshold`:

**MANDATORY POPUP**: You MUST present this choice via `AskUserQuestion`. Do NOT auto-skip. Do NOT decide for the user.

Options:
- **Full scan** — "It's been [N] sessions since a full sigma trunk scan (threshold: [T]). Run a complete review of warm + cold layers now."
- **Skip** — "Continue with selective loading. I'll ask again next session."

Wait for the user's response before continuing.

- If Full scan: read all layers, surface stale/orphaned entries, reset `sessions_since_full_scan` to 0 in the hot layer
- If Skip: continue with selective loading

**Promotion check** (only during full scan, only if `memory_config.integration` is `"full"`):

After the full scan completes, identify warm-layer entries that:
1. Have not changed in the last `full_scan_threshold` sessions (stable)
2. Were pointer-loaded in 3+ consecutive sessions (frequently referenced)

**MANDATORY POPUP**: If any qualify, you MUST present them to the user via `AskUserQuestion`. Do NOT auto-promote. Do NOT skip this step.

Options:
- **Promote** — "These sigma trunk entries are stable and loaded nearly every session. Promoting them to MEMORY.md makes them available without /buffer:on: [list concepts with unchanged N sessions, loaded M times]. Max 10 lines per cycle."
- **Decline** — "Skip promotion this session."

Wait for the user's response before continuing.

If approved:
- Add/update a `## Stable Definitions` section in MEMORY.md (before `## Sigma Trunk Integration`)
- Each promoted entry: one-line definition
- Cap: 10 lines promoted per cycle
- The warm entry remains the source of truth — MEMORY.md gets a read-only copy
- Mark warm entry: `"promoted_to_memory": "YYYY-MM-DD"`
- `/buffer:off`'s MEMORY.md sync step keeps promoted copies current

If declined or no candidates: continue.

---

## Autosave: concept_map_digest

In Full mode, autosave also updates:
- `concept_map_digest` — update if concept map changed this autosave interval

Lite mode skips `concept_map_digest` entirely.

---

## MEMORY.md Integration: Concept Map Migration

> Part of Step 0f (first-run setup). Only relevant for Full mode with existing MEMORY.md.

If full integration is chosen during first-run setup and MEMORY.md contains theoretical concept definitions:

- **Migrate to sigma trunk**: theoretical concept definitions to warm `concept_map` entries (new `w:N` IDs), philosophical reference summaries to `concept_map` cross_source entries, forward note details to `open_threads` or warm entries with `ref` fields
- Update `concept_map_digest` in hot to reflect any migrated entries
