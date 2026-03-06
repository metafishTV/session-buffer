# Changelog

All notable changes to buffer are documented here.

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
