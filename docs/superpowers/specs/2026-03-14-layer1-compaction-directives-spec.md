# Layer 1: Compaction Directives — Implementation Spec

**Date:** 2026-03-14
**Updated:** 2026-03-14 (corrected after hooks docs + community research)
**Status:** Approved for implementation
**Design doc:** `docs/plans/2026-03-14-compaction-directives-design.md`

---

## Overview

Extend the buffer plugin's compaction hooks to inject context-aware directives after every compaction event. A directives file (`.claude/buffer/compact-directives.md`) provides static context about what's on disk; the PostCompact hook reads this file plus live session signals and injects a rich context block into the fresh post-compaction session.

The user never sees this working. It bootstraps onto the existing compaction process invisibly.

### Architecture Correction

**PreCompact hooks have no output channel** — they can only save state to disk and exit. They cannot inject text into the compaction prompt or influence the summarization process. This was confirmed by official Claude Code hooks documentation.

**PostCompact hooks DO have context injection** — via the `additionalContext` JSON output protocol. The existing `compact_hook.py post-compact` already uses this, firing on SessionStart after compaction. PostCompact input also includes `compact_summary` (what the compactor produced), which could be used for verification.

**CLAUDE.md survives compaction** — it is re-read from disk and re-injected fresh after every compaction. This means static directives (like "when compacting, preserve X") can live in CLAUDE.md and influence the compactor directly, since CLAUDE.md is part of the context being summarized.

**Two-pronged approach:**
1. **CLAUDE.md dynamic section** — written by `/buffer:on`, contains compaction guidance that the compactor sees during summarization (influences WHAT gets preserved)
2. **PostCompact injection** — `compact_hook.py post-compact` injects buffer context after compaction (ensures HOW context is restored)

## Goals

- **(a) More robust** — nothing important drops silently between contexts
- **(b) More thorough** — plugin-aware summarization knows what's on disk vs what must be preserved
- **(c) More personal** — adapts to session depth, active work threads, and session vocabulary
- **(d) Less entropic** — each compaction summary is shaped by what the brain (plugin) knows, not just what the nervous system (LLM) remembers

## Components

| Component | Type | Change |
|---|---|---|
| `plugin/scripts/compact_hook.py` | Python | Extend `post-compact` to include directives in injected context |
| `.claude/buffer/compact-directives.md` | Markdown (runtime) | New file — written by Claude via SKILL.md instructions |
| `plugin/skills/on/SKILL.md` | Instruction | Add step: write fresh directives file + CLAUDE.md compaction section |
| `plugin/skills/off/SKILL.md` | Instruction | Add step: update directives, migrate vocabulary |
| `plugin/skills/status/SKILL.md` | Instruction | Show directive state in health report |

**Not changed:** sigma_hook.py, plugin.json. Hooks.json may need a `PostCompact` entry if not already wired.

---

## 1. Two-Pronged Directive Delivery

### Prong 1: CLAUDE.md Compaction Section (influences summarization)

`/buffer:on` writes a dynamic section to the project's CLAUDE.md:

```markdown
## Compaction Guidance

When compacting this conversation, follow these priorities:

- ALREADY ON DISK (do not reproduce in summary):
  - Session buffer trunk: .claude/buffer/handoff.json (threads, decisions, state)
  - Alpha bin: .claude/buffer/alpha/ (concept definitions, glossary)
  - Git history: recoverable via tools
- PRESERVE IN SUMMARY (context-only, not on disk):
  - Active thread of work and current task state
  - Decisions made since last save
  - User preferences or corrections expressed this session
  - Session vocabulary (terms with specific meaning coined this session)
- End your summary with 1-2 sentences capturing exactly what was being
  discussed in the most recent exchange — the immediate context the user
  will expect to resume from.
- Project glossary and concept definitions are in the alpha bin. Standard
  project terms can be used without re-defining. Only preserve definitions
  for terms coined THIS session.
```

**Why this works:** CLAUDE.md is part of the context the compactor summarizes. By including compaction guidance here, it directly influences what the summarizer preserves — without needing PreCompact stdout (which doesn't exist).

**Why a separate section, not the whole CLAUDE.md:** The section is small (~15 lines), clearly scoped, and `/buffer:on` manages it. It doesn't pollute the rest of CLAUDE.md. The skill instructions tell Claude to replace this section (not append) on each `/buffer:on`.

### Prong 2: PostCompact Injection (restores context)

`compact_hook.py post-compact` already fires after compaction and injects context via `build_compact_summary()`. Extend this to also include:

1. **Directives context** from `.claude/buffer/compact-directives.md`:
   - Active threads (what we're working on)
   - Session vocabulary (terms and their meanings)
   - On-disk inventory (what can be recovered via tools)

2. **Depth-adaptive guidance** from `.claude/buffer/.session_active`:
   - Read `off_count` to determine session depth
   - Append depth-appropriate context recovery advice

The existing `build_compact_summary()` output remains — directive context is appended to it, not replacing it.

### Inputs for PostCompact directive generation

| Source | What it provides | Required? |
|---|---|---|
| `.claude/buffer/compact-directives.md` | Static context: on-disk paths, active threads, session vocabulary | No — fallback to defaults |
| `.claude/buffer/.session_active` | Session depth (`off_count`) | No — assume 0 if missing |
| `handoff.json` | Open threads, active work, natural summary | Yes — already loaded |

### PostCompact output addition

Appended to existing `build_compact_summary()` output:

```
--- COMPACTION DIRECTIVES ---

CONTEXT ON DISK (recoverable via tools):
- Session buffer trunk: .claude/buffer/handoff.json
- Warm/cold layers: handoff-warm.json, handoff-cold.json
- Alpha bin: .claude/buffer/alpha/
[additional paths from directives file]

ACTIVE THREADS:
- [thread from directives file]
- [thread from directives file]

SESSION VOCABULARY:
- [term]: [definition]
- [term]: [definition]

SESSION DEPTH: [off_count] save cycles today.
[depth-adaptive guidance]

The buffer plugin has re-injected essential context above. Use /buffer:on
if you need full trunk reconstruction.
```

### Depth-adaptive guidance

| off_count | Guidance appended |
|---|---|
| 0-1 | "Full thread detail and rationale should be available in the compaction summary above." |
| 2 | "This is a deep session. Prioritize continuity and active focus. Details are in git and the buffer trunk." |
| 3+ | "Significant context recycling. Focus on: what we are doing, why, and the next step. All detail is on disk." |

### Fallback behavior

- No directives file → directives section omitted from output, existing summary still injected
- Missing `.session_active` → depth treated as 0
- Malformed JSON in any file → skip that section, continue with rest
- Hook must never crash — all file reads wrapped in try/except

---

## 2. compact-directives.md — File Format

Written by Claude following SKILL.md instructions. Stored at `.claude/buffer/compact-directives.md`.

```markdown
# Compaction Directives

## On Disk
- Sigma trunk: .claude/buffer/handoff.json
- Warm layer: .claude/buffer/handoff-warm.json
- Cold layer: .claude/buffer/handoff-cold.json
- Alpha bin: .claude/buffer/alpha/
- Briefing: .claude/buffer/briefing.md
- Forward notes: .claude/buffer/forward_notes.json

## Active Threads
- [thread description] ([location/reference])
- [thread description] ([location/reference])

## Already Persisted
- [what was saved and where]

## Session Vocabulary
- [term]: [1-sentence definition as used in this session]
```

### Lifecycle

```
/buffer:on  → write fresh file (vocabulary empty) + write CLAUDE.md compaction section
  ... session work, terms emerge, Claude adds vocabulary entries ...
  compaction #1 → CLAUDE.md section guides summarizer; PostCompact injects directives
  ... more work, more terms ...
  compaction #2 → same flow, updated vocabulary preserved
/buffer:off → update threads/persisted, migrate worthy vocab to trunk
next /buffer:on → overwrite both directives file and CLAUDE.md section
```

---

## 3. SKILL.md Changes

### /buffer:on — Add Step 0d-b (after Mark session active)

```markdown
### Step 0d-b: Write compaction directives

Create `.claude/buffer/compact-directives.md` with four sections:

1. **On Disk** — list every buffer file that actually exists on disk:
   handoff.json, handoff-warm.json, handoff-cold.json, alpha/ directory,
   briefing.md, forward_notes.json. Only list files you confirmed exist.

2. **Active Threads** — copy from `open_threads` in the handoff.json you
   just loaded. One line per thread with its status and any reference.

3. **Already Persisted** — note what data is already saved in the trunk
   from previous sessions.

4. **Session Vocabulary** — leave empty. Terms will be added during the
   session as novel concepts emerge.

Also, ensure the project's CLAUDE.md contains a `## Compaction Guidance`
section. If it doesn't exist, add it. If it exists, update it. The section
should contain:
- List of on-disk paths (from the On Disk section above)
- Instruction to preserve context-only items in summaries
- Instruction to end summaries with what was just being discussed
- Note that alpha bin terms don't need re-defining in summaries

This section tells the compaction summarizer what to prioritize. Keep it
under 20 lines.

During this session, if you coin or adopt a term with specific meaning
(neologism, repurposed word, project-specific shorthand), add it to the
Session Vocabulary section of compact-directives.md with a 1-sentence
definition. Keep to ~5-10 entries. Standard technical vocabulary and terms
already in the alpha bin don't belong here.
```

### /buffer:off — Add Step 12b (before Step 13)

```markdown
### Step 12b: Update compaction directives

Update `.claude/buffer/compact-directives.md`:

1. **Active Threads** — refresh to match what you just saved in
   handoff.json open_threads.

2. **Already Persisted** — update to reflect everything saved in this
   /buffer:off cycle.

3. **Session Vocabulary** — review each term:
   - If it belongs in the project long-term, migrate it to the appropriate
     trunk layer (concept_map in alpha, or a warm entry definition).
   - If it was session-specific and already captured in the natural
     summary, leave it — it will be overwritten next /buffer:on.
   - If it's neither, remove it.

The file stays on disk for reference. Next /buffer:on overwrites it.
```

### /buffer:status — Extend output

```markdown
### Compaction directives

Read `.claude/buffer/compact-directives.md` if it exists.
- If missing: report "Directives: not configured"
- If present: report "Directives: active" with count of listed on-disk
  files, active threads, and vocabulary terms.

Check if CLAUDE.md contains a `## Compaction Guidance` section.
- If missing: report "CLAUDE.md compaction section: not present"
- If present: report "CLAUDE.md compaction section: active"
```

---

## 4. hooks.json Changes

Check if `PostCompact` is already wired in `hooks/hooks.json`. The existing config has:
- `PreCompact` → `compact_hook.py pre-compact` (manual + auto matchers)
- `SessionStart` → `compact_hook.py post-compact`

**If PostCompact is not wired:** Add it alongside the existing SessionStart entry. Both should call `compact_hook.py post-compact` — the script already handles the full post-compaction flow. PostCompact fires immediately after compaction; SessionStart fires at session begin. Having both ensures coverage.

**If PostCompact IS already wired via SessionStart:** No hooks.json changes needed. The existing SessionStart hook fires after compaction and already calls `compact_hook.py post-compact`. We just need to extend what that function outputs.

---

## 5. What This Does NOT Do

- **Does not modify sigma_hook.py** — no per-prompt tracking (deferred as pulse enhancement)
- **Does not replace the default compaction prompt** — CLAUDE.md section guides it; PostCompact restores context after
- **Does not block compaction** — directives are additive guidance, not gates
- **Does not persist vocabulary across sessions** — ephemeral by design

---

## 6. Testing Strategy

### Manual testing

1. Run `/buffer:on` → verify `compact-directives.md` created + CLAUDE.md has compaction section
2. Add a vocabulary term → verify it appears in directives file
3. Trigger `/compact` → verify post-compaction context includes directive block
4. After compaction, verify Claude knows what's on disk and what threads are active
5. Check that session vocabulary terms survived compaction
6. Run `/buffer:off` → verify directives file updated
7. Run `/buffer:on` again → verify file overwritten fresh, CLAUDE.md section refreshed

### Edge cases

- Compact without `/buffer:on` (no directives file) → existing behavior unchanged
- `.session_active` missing → depth treated as 0
- `.session_active` malformed JSON → depth treated as 0
- Directives file exists but empty/malformed → skip directives section, inject existing summary only
- CLAUDE.md has no compaction section → compaction uses default behavior

### Regression check

- Existing `build_compact_summary()` output must be unchanged
- Existing PreCompact save behavior must be unchanged
- sigma_hook.py must be completely untouched

---

## 7. Implementation Sequence

1. **Verify PostCompact wiring** — check hooks.json, confirm `compact_hook.py post-compact` fires after compaction
2. **Extend `compact_hook.py`** — add `generate_directive_context()` function, append output to existing summary
3. **SKILL.md changes** — add Step 0d-b to on, Step 12b to off, extend status
4. **Test CLAUDE.md section** — verify compaction guidance section survives compaction and influences summarization
5. **Manual test cycle** — run through full lifecycle
6. **Edge case testing** — verify all fallbacks
7. **Commit and push**

---

## 8. Key Research Findings

### Official hooks documentation confirms:
- PreCompact: no output channel, can only save state to disk
- PostCompact: has context injection via `additionalContext` JSON, receives `compact_summary`
- PostCompact matchers: `manual` and `auto` (same as PreCompact)

### CLAUDE.md and compaction:
- CLAUDE.md fully survives compaction — re-read from disk and re-injected fresh
- CLAUDE.md content is part of what the compactor summarizes
- Best practices doc recommends: "Customize compaction behavior in CLAUDE.md with instructions like 'When compacting, always preserve the full list of modified files'"

### Community pattern (Nick Porter):
- Uses PostToolUse with `"compact"` matcher to cat a context-essentials.md file
- Official docs say PostToolUse only matches tool names — this may be an undocumented feature or may have changed
- Our approach is more robust: PostCompact hook (officially documented) + CLAUDE.md section (officially recommended)
