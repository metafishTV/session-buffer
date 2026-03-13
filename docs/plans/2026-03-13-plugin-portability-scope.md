# Plugin Portability & Lite Mode — Scoping Document

**Date**: 2026-03-13
**Status**: Scoped — ready for planning
**Affects**: buffer plugin (v2.3.0 → v3.0.0), distill plugin (v2.3.0 → v3.0.0)

---

## Problem

Both plugins contain project-specific content (sigma-TAP references, hardcoded source names, reserved numbering). A new Claude Pro user installing either plugin would encounter directives, examples, and scripts that assume a specific project context. The plugins must ship as engines, never as fuel.

## Principles

1. **Engine ≠ fuel.** Plugin-level files are generic. Project-specific content is generated at runtime by differentiate/bootstrap commands.
2. **Zero dependencies in lite mode.** Buffer lite uses no Python, no external tools. Claude's native capabilities only.
3. **Additive upgrade path.** Lite → full is additive (re-process existing entries), never destructive (discard and redo).
4. **Independent plugins.** Buffer and distill are usable alone. Together they integrate, but neither requires the other.

---

## A. Engine/Fuel Separation

### Audit Findings

| Plugin | File | Issue | Severity |
|--------|------|-------|----------|
| Buffer | `sigma_hook.py` | Levinas/DG in example output | Low |
| Buffer | `docs/architecture.md` | "sartre-early" folder, TAPS/RIP framework refs | Low |
| Buffer | `skills/on/full-ref.md` | "Kirsanov" reference, §5.1–§5.69 | Low |
| Buffer | `skills/off/full-ref.md` | §5.1–§5.69 reservation | Low |
| Distill | `CLAUDE.md` | §5.1–§5.69, glossary curation, voice directives | **High** |
| Distill | `create_missing_alpha.py` | Hardcoded Sartre sources, TAPS, L-matrix | **High** |
| Distill | `skills/analyze/SKILL.md` | Forward notes numbering in Pass 4 | Medium |

### Actions

1. **Buffer examples**: Replace project-specific names with generic placeholders (`author-early/`, `concept-A`, `concept-B`). Keep structure identical.
2. **Distill CLAUDE.md**: Remove from plugin. Rewrite as a *template* that `differentiate` generates into the target repo's `.claude/distill.config.md`. Generic directives (compression, no sycophancy, figure policy) stay in a minimal plugin-level CLAUDE.md. Project-specific directives (reserved numbering, glossary terms, voice) go into the generated file.
3. **`create_missing_alpha.py`**: Move to `sigma-TAP-repo/scripts/`. Not a plugin concern.
4. **`analyze/SKILL.md` Pass 4**: Replace hardcoded `§5.1–§5.69` with "check `forward_notes.json` for reserved ranges" — reads the registry rather than assuming specific numbers.

---

## B. First-Run Gate

### Mechanism

PreToolUse hook on all distill skill invocations. Checks for `.claude/distill.config.yaml` in the target repo.

```json
{
  "event": "PreToolUse",
  "hook_type": "prompt",
  "matcher": { "tool_name": "Skill", "input_contains": "distill:" },
  "prompt": "Check if .claude/distill.config.yaml exists in the project root. If it does NOT exist, respond with: 'BLOCK: Run /distill:differentiate first to configure distillation for your project.' If it DOES exist, respond with: 'ALLOW'."
}
```

### `/distill:differentiate` generates:

- `.claude/distill.config.yaml` — project metadata, mode (lite/full), source preferences
- `.claude/skills/distill/forward_notes.json` — empty registry (`{ "next_number": 1, "notes": {} }`)
- `.claude/skills/distill/manifest.json` — empty manifest skeleton
- `.claude/skills/distill/glossary.md` — empty glossary scaffold
- `.claude/distill.config.md` — project-specific CLAUDE.md directives (generated from user interview)

---

## C. Buffer Lite Mode

### What ships (lite):

| Component | Description |
|-----------|-------------|
| Hot/warm/cold layers | Session state tracking — what was referenced, what's decaying |
| Sigma hook (lite) | Temperature updates based on session activity. No prediction error. |
| `/buffer:on` | Reconstruct session context from trunk |
| `/buffer:off` | Write session handoff to trunk |
| Lite alpha | Document → simple w: entry via Claude native reading. No scripts. |
| Lite trunk | Flat structure. No convergence web. |
| Config | `.claude/buffer.config.yaml` with `mode: lite` |

### What full mode adds:

| Component | Description |
|-----------|-------------|
| Convergence web | Cross-source cw: linking |
| Prediction error | Expected vs actual tracking for sigma tuning |
| Full trunk | Hierarchical structure with framework layer |
| Full alpha | Populated by distill's five-pass analysis |
| Beta analytics | Usage patterns, retrieval statistics |

### Lite alpha behavior:

1. User shares a document (PDF, URL, image, text)
2. Claude reads it natively (no Python, no extraction scripts)
3. Writes a w: entry to `.claude/buffer/alpha/<source-folder>/`
4. Entry includes:
   - Key concepts extracted
   - `source:` field — path, URL, or "ask user" directive
   - `mode: lite` marker
5. Source file is **not** renamed or copied — only referenced
6. If distill is later installed, it detects lite entries via the `mode: lite` marker and offers to re-distill through full analysis, locating sources via the `source:` field

### Upgrade path (lite → full):

1. User installs distill plugin or switches buffer config to `mode: full`
2. System detects existing lite alpha entries
3. Offers: "Found N lite alpha entries. Re-distill through full analysis? This will take ~X minutes per entry."
4. For each entry, checks `source:` field:
   - If path exists → use it
   - If URL → fetch it
   - If "ask user" → prompt: "Do you have the source document for [entry]?"
5. Runs distill's five-pass analysis on located sources
6. Upgrades w: entries in place, adds cw: links, updates convergence web
7. No data loss — lite entries are a subset of full entries

### Model selection:

Uses whatever model the user is running. No forced model switching — not possible from within the plugin, and unnecessary. Lite alpha writes are within any model's capability.

---

## D. Plugin Independence

### Buffer alone (no distill):
- Full session memory (lite or full mode)
- Lite alpha for basic document indexing
- No extraction pipeline, no five-pass analysis
- Upgrade path: install distill later

### Distill alone (no buffer):
- Full extraction and analysis pipeline
- Writes distillations to `docs/references/distilled/`
- No session persistence, no hot/warm/cold, no sigma activation
- Upgrade path: install buffer later, existing distillations detected and indexed

### Both together:
- Distill populates buffer's alpha bin with full-depth analysis
- Buffer's sigma hook activates distilled content based on session context
- Convergence web links across sources
- Prediction error tunes activation patterns

---

## Phases

### Phase 1: Engine/fuel separation
- Genericize buffer examples (4 files, low severity)
- Move `create_missing_alpha.py` to sigma-TAP-repo
- Split distill CLAUDE.md into generic (plugin) + template (differentiate-generated)
- Fix analyze/SKILL.md Pass 4 hardcoded numbering

### Phase 2: First-run gate
- Implement PreToolUse hook for distill
- Update differentiate to generate all project-specific files
- Test: fresh install → any `/distill:*` command → gate fires → differentiate → gate passes

### Phase 3: Buffer lite mode
- Add `.claude/buffer.config.yaml` with mode flag
- Implement lite sigma hook (temperature only, no prediction error)
- Implement lite alpha (Claude-native document reading → w: entry)
- Implement lite trunk (flat structure)
- Gate full-mode features behind config check

### Phase 4: Upgrade path
- Lite → full detection and re-distill offer
- Source location via `source:` field (path/URL/ask-user)
- In-place entry upgrade (preserve existing, add cw: links)

### Phase 5: Testing & documentation
- Fresh-install test (both plugins, each alone, lite mode, full mode)
- Upgrade path test (lite → full with re-distill)
- README updates for both plugins
- Marketplace descriptions

---

## Version Targets

- **Buffer**: v2.3.0 → v3.0.0 (lite mode is a major feature)
- **Distill**: v2.3.0 → v3.0.0 (engine/fuel separation + first-run gate)
