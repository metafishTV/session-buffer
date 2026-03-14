# Compaction Directives Design

**Date:** 2026-03-14
**Updated:** 2026-03-14 (post-API research, resolved open questions)
**Status:** Designed — ready for implementation scoping

---

## Core Metaphor

Plugins act as the **brain** (focused, specialized, persistent memory). The underlying LLM architecture acts as the **nervous system** (general processing, ephemeral context). Compaction directives are the **placenta** — the living connective tissue between brain and nervous system that automatically picks things up from one context and puts them down in the next.

Unlike `/buffer:off` (which fires at session end by user choice), the compaction directive layer fires on **every** compaction event — user-initiated `/compact`, automatic system compaction when context fills, mid-session compactions during long work. It's an always-on micro-buffer that bootstraps onto the existing compaction process invisibly, making it:

- **(a) More robust** — nothing important drops silently between contexts
- **(b) More thorough** — plugin-aware summarization knows what's on disk vs what must be preserved
- **(c) More personal** — adapts to session depth, active work threads, and user patterns
- **(d) More substantive & corrective** — reduces entropy across compaction boundaries; each compaction summary is shaped by what the brain knows, not just what the nervous system remembers

The user never sees this working. It's invisible plumbing — a lifter agent that ensures continuity.

---

## The Five Layers

### Layer 0: Marker-Relay (exists today)

Buffer saves state to disk (`handoff.json`, `.session_active`, `.buffer_loaded`). SessionStart hook injects summary after compaction. Works, but **blind** — doesn't know when compaction will hit or what the compactor kept/dropped. One-directional: disk → context. No feedback loop.

### Layer 1: Compaction Directives (primary implementation target)

The brain tells the nervous system what to preserve and what to let go — automatically, on every compaction event.

**Architecture (corrected 2026-03-14 — PreCompact has no output channel):**

Two-pronged delivery:

```
  PRONG 1: CLAUDE.md Compaction Section (influences summarization)
  ──────────────────────────────────────────────────────────────────
  /buffer:on writes "## Compaction Guidance" section to CLAUDE.md
  → CLAUDE.md survives compaction (re-read from disk, re-injected)
  → Compactor SEES this guidance while summarizing
  → Influences WHAT gets preserved in the summary

  PRONG 2: PostCompact Injection (restores context)
  ──────────────────────────────────────────────────────────────────
  compaction triggers → PreCompact saves state to disk → compaction runs
  → PostCompact hook fires → compact_hook.py post-compact
  → Reads compact-directives.md + .session_active + handoff.json
  → Injects directive context via additionalContext JSON
  → Post-compaction Claude has buffer state + vocabulary + threads
```

**Key correction:** PreCompact hooks have NO output channel — they can only save state to disk and exit. PostCompact hooks have context injection via `additionalContext` JSON. CLAUDE.md fully survives compaction (re-read from disk). This means we use CLAUDE.md to influence the compactor and PostCompact to restore context afterward.

**Directive storage:** `.claude/buffer/compact-directives.md` — a separate file for the detailed directives (threads, vocabulary, on-disk inventory). CLAUDE.md gets a small (~15 line) compaction guidance section managed by `/buffer:on`. Both are read by the PostCompact hook for injection.

**Trigger scope:** Fires on ALL compaction events:
- User types `/compact` → hook fires
- User types `/compact [focus text]` → hook fires, appends plugin directives to user's focus
- System auto-compacts at token threshold → hook fires
- Mid-session compaction during long agentic work → hook fires

The user never needs to know. The directives silently improve every compaction.

**Depth-adaptive content:**

| Session depth | Directive strategy |
|---|---|
| `off x0` (fresh) | Preserve full thread detail, decisions, code context, rationale |
| `off x1` | Preserve thread continuity + key decisions; details available in git |
| `off x2` | Preserve continuity thread + active work focus; trunk has detail |
| `off x3+` | Preserve only: what we're doing, why, and next step. Everything else is on disk. |

**Session Vocabulary (ephemeral keyword preservation):**

The directives file includes a `## Session Vocabulary` section for neologisms, repurposed terms, and project-specific shorthand that carry specific meaning in the current session. These are terms that would be opaque or lose their meaning if compaction drops the conversation where they were defined.

**What belongs:** Neologisms or repurposed terms with project-specific meaning, coined acronyms/shorthand, concepts that were explored and adopted (not just mentioned). **What doesn't:** Standard technical vocabulary, terms already in the alpha bin/concept map (on disk), things mentioned once and dropped. Cap at ~5-10 entries.

**Lifecycle:** Ephemeral — exists to survive compaction, not sessions.
```
/buffer:on  → fresh directives file (no vocabulary)
  ... work, terms emerge, Claude adds them ...
  compaction #1 → hook reads vocabulary, tells compactor to preserve terms
  ... more work, more terms ...
  compaction #2 → hook reads updated vocabulary, same deal
/buffer:off → terms either migrate to trunk/alpha or expire
next /buffer:on → clean slate
```

Terms that matter across sessions belong in the alpha bin or concept map — not here.

**Example generated directive (off x1):**

```
Preserve: active work threads (plugin standardization, compaction directives design),
key decisions made this session, user preferences expressed, and current task state.
Release: specific file contents already read (retrievable via tools), completed task
details (in git history), distillation data (persisted to .claude/buffer/handoff.json),
and verbose code snippets (recoverable from filesystem). Open threads with context:
- Compaction directives Layer 1 implementation (design doc at docs/plans/2026-03-14-...)
- Session depth tracking (implemented, 4 buffer states working)
The buffer plugin will re-inject essential context via SessionStart if needed.
```

### Layer 2: Headroom Check Context Check

Before expensive operations (distillation, long code generation), estimate context headroom.

**Data sources:**
- Statusline JSON: `remaining_percentage`, `used_percentage`
- Session depth (`off_count` from `.session_active`)
- Operation cost estimates (from Layer 3 telemetry, when available)

**Thresholds (informed by observed data — 93% → 97% in ~3 exchanges):**

| Context % | Behavior |
|---|---|
| < 70% | Proceed normally |
| 70-85% | Passive note: "context at X%, consider compacting before large ops" |
| 85-93% | Active recommend: "compact recommended before starting [operation]" |
| 93%+ | Strong suggest with pre-generated focus: "compact now — directives ready" |

**Behavior:** Warn with recommendation, never block. The user is the decision-maker. The plugin suggests, doesn't gatekeep.

**Distill integration:** At launch of a distillation, check context %. If above 70%, recommend compacting first with directives that preserve the distillation setup context.

### Layer 3: Telemetry

**Approach: emit, don't mine.** Rather than parsing huge JSONL transcript files, we emit lightweight data points as they happen:

- **`PreCompact` hook** appends to `.claude/buffer/telemetry.jsonl`:
  ```json
  {"ts": "2026-03-14T15:30:00Z", "event": "compact", "context_pct": 93, "off_count": 1, "threads": 3}
  ```
- **`SessionEnd` / `Stop` hook** appends session summary:
  ```json
  {"ts": "...", "event": "session_end", "compactions": 2, "off_count": 3, "duration_min": 45}
  ```

Tiny file, always current. No need to load or parse full transcripts. Can be read by headroom check checks (Layer 2) and praxes (Layer 4) with minimal cost.

**Claude-native actions:** Where possible, leverage Claude's own tool calls rather than writing custom parsing code. The telemetry file is small enough to read directly when needed.

### Layer 4: Praxes (Self-tuning)

After enough telemetry, headroom check thresholds become learned rather than hardcoded. "Last 5 distillations averaged 40% context consumption, current headroom is 35%, compact first."

The system becomes self-tuning through practiced actions — hence "praxes" rather than "rules." This layer depends on Layer 3 having accumulated enough data points. Not scoped for initial implementation.

---

## API Research Findings (2026-03-14)

### Compaction API (beta: `compact-2026-01-12`)

Key parameters discovered from official docs:

| Parameter | Type | Default | Relevance |
|---|---|---|---|
| `type` | string | Required | `"compact_20260112"` |
| `trigger` | object | 150k tokens | When to trigger; min 50k tokens |
| `pause_after_compaction` | boolean | `false` | Pauses after summary, lets harness inject content before continuing |
| `instructions` | string | `null` | **Completely replaces** default summarization prompt |

**Critical finding:** The `instructions` parameter completely replaces the default prompt at the API level. However, **PreCompact hooks have no output channel** — they can only save state to disk. We use a two-pronged approach instead: CLAUDE.md (survives compaction, influences the summarizer) + PostCompact injection (restores context afterward). See spec for full corrected architecture.

**Default summarization prompt** (for reference):
```
You have written a partial transcript for the initial task above. Please write a
summary of the transcript. The purpose of this summary is to provide continuity
so you can continue to make progress towards solving the task in a future context,
where the raw history above may not be accessible and will be replaced with this
summary. Write down anything that would be helpful, including the state, next steps,
learnings etc. You must wrap your summary in a <summary></summary> block.
```

**Implication:** Our CLAUDE.md compaction section complements this default prompt — guiding what to preserve and release, while the default prompt handles summarization mechanics.

### `pause_after_compaction` — Future Opportunity

When enabled, the API returns with stop_reason `"compaction"` after generating the summary, allowing the harness to append additional content before continuing. Claude Code may use this internally. If exposed to plugins, this would let us inject post-compaction context (like a mini SessionStart) immediately after compaction, within the same session. Worth monitoring.

### Context Awareness (built into Opus 4.6, Sonnet 4.6)

Claude receives token budget info automatically:
```xml
<budget:token_budget>1000000</budget:token_budget>
```
After each tool call:
```xml
<system_warning>Token usage: 35000/1000000; 965000 remaining</system_warning>
```

This means Claude already knows its own context pressure. The headroom check check (Layer 2) can leverage this — Claude can self-assess headroom without external tooling.

### Context Editing (beta: `context-management-2025-06-27`)

Complementary server-side strategy for managing context growth:

**Tool result clearing** (`clear_tool_uses_20250919`):
- Clears oldest tool results in chronological order when context exceeds threshold
- Replaced with placeholder text so Claude knows content was removed
- Configurable: `trigger` (token threshold), `keep` (how many recent tool uses to retain), `clear_at_least` (minimum tokens to clear per pass), `exclude_tools` (tools to never clear)
- **Cache interaction:** Invalidates cached prompt prefixes when content is cleared. Use `clear_at_least` to ensure enough tokens are cleared to make cache invalidation worthwhile.

**Thinking block clearing** (`clear_thinking_20251015`):
- Controls thinking block preservation in extended thinking conversations
- Default: keeps only last assistant turn's thinking blocks
- Options: `keep: "all"` (maximize cache hits) or `keep: {type: "thinking_turns", value: N}`

**Key insight for directives:** Context editing is applied **server-side before the prompt reaches Claude**. Client maintains full history. This is orthogonal to compaction — they can be layered: clear old tool results + compact with plugin directives = maximally efficient context management. Both use the same `context_management.edits` array.

### Token Counting API (`/v1/messages/count_tokens`)

**Free to use**, subject to RPM rate limits (100-8000 depending on tier). Accepts same structured input as Messages API (system, tools, messages, images, PDFs, thinking blocks).

**Relevance to directives:**
- Could be used by headroom check checks (Layer 2) to estimate operation cost before starting
- Returns `{input_tokens: N}` — compare against context window size for headroom estimate
- Thinking blocks from previous turns are automatically excluded from count (same as Messages API)
- **Not** affected by prompt caching — provides raw estimate

**Practical limitation:** Only useful at API level, not directly from Claude Code hooks. But the statusline JSON already provides `used_percentage` and `remaining_percentage`, which serve the same purpose for our Layer 2 headroom check checks without needing an extra API call.

### Prompt Caching Interaction

- Cache ratio (`cache_read / total`) indicates context stability
- Compaction invalidates cache — but the new compacted context gets cached on next turn
- Low cache ratio + high context = compaction will be aggressive → directives should emphasize "preserve continuity, details are on disk"
- Cache minimum thresholds: Opus 4.6 = 4,096 tokens, Sonnet 4.6 = 2,048 tokens
- Cache lifetime: 5-minute default (ephemeral), 1-hour extended (2x base price)
- Cache writes cost 25% more than base input; cache reads cost only 10% of base — high cache ratio = significant cost savings

---

## Context Window Fields (from statusline JSON)

These fields are available to hooks and scripts:

| Field | Relevance to directives |
|---|---|
| `remaining_percentage` | Remaining context headroom |
| `used_percentage` | How full we are |
| `context_window_size` | 200k vs 1M — changes thresholds |
| `cache_read_input_tokens` | Cached = stable, survives turns better |
| `cache_creation_input_tokens` | Fresh cache writes |
| `input_tokens` | Non-cached input |
| `exceeds_200k_tokens` | Hard warning threshold |

**Cache ratio insight:** `cache_read / (cache_read + cache_write + input)` = how much context is cached. **Low cache + high context = compaction will be aggressive.** This is the signal for Layer 1 directives to say "preserve thread continuity, details are on disk."

---

## Session Depth Connection

`off_count` (from `.session_active`) tracks context recycling:
- `off x0`: Fresh session, full nuance
- `off x1`: One save cycle, minor degradation
- `off x2`: Two cycles, moderate degradation
- `off x3+`: Deep session, significant nuance erosion

Directives adapt automatically based on depth. See Layer 1 depth-adaptive table above.

---

## Implementation Hooks

| Hook point | What it does | Status |
|---|---|---|
| `PreCompact` | Save state to disk (marker, handoff update) — no output channel | **Exists** — no changes needed |
| `PostCompact` | Read directives + signals, inject context via additionalContext JSON | **Exists** (via SessionStart) — extend output |
| `SessionStart` | Smart re-injection based on what compaction dropped | **Exists** — make directive-aware |
| `UserPromptSubmit` | Intercept `/compact [text]`, append plugin directives to user's focus | **New** — lightweight string concat |
| `/buffer:status` | Shows context health + directive recommendations on demand | **Exists** — extend output |
| Statusline | Passive context awareness (CLI only) | **Exists** — no changes needed |

---

## Relationship to Existing Infrastructure

- **`compact_hook.py`**: Already fires on PreCompact. Currently does marker relay only. **Primary extension point** — add directive generation here.
- **Session marker** (`.session_active`): Already tracks `off_count`. Feeds depth-aware directive generation. No changes needed.
- **SessionStart hook**: Already injects post-compaction context. Make it aware of what directives were issued, so it can verify continuity.
- **`/buffer:status`**: Already shows health report. Extend to show directive readiness and last compaction telemetry.
- **Statusline**: Already reads context window data. Same JSON feeds headroom check checks. No changes needed.
- **`handoff.json`**: Already stores open threads, phase, mode. Read by directives to know what's active.

---

## Resolved Questions

| # | Question | Resolution |
|---|---|---|
| 1 | CLAUDE.md vs separate file? | **Separate file** (`.claude/buffer/compact-directives.md`). Cleaner, no merge conflicts, plugin owns it. |
| 2 | `/compact` interception worth it? | **PreCompact hook is sufficient.** It fires on all compaction events (auto + manual). UserPromptSubmit interception rejected — redundant, risky to sigma_hook.py, and may not work mechanically for CLI commands. |
| 3 | Headroom Check thresholds? | **70% warn, 85% recommend, 93%+ strong suggest.** Based on observed data: 93% → 97% in ~3 exchanges. |
| 4 | Mining telemetry? | **Emit, don't mine.** Hooks append single-line JSON to a tiny telemetry.jsonl as events happen. No JSONL parsing needed. |
| 5 | Compaction parameters? | **Confirmed from docs:** `/compact` free text → `instructions` parameter, which **completely replaces** default summarization prompt. No `--flags` beyond free text. `trigger` and `pause_after_compaction` are API-level params, not CLI flags. |
| 6 | Block or warn? | **Warn with recommendation.** User is decision-maker; plugin suggests, doesn't gatekeep. |

---

## Approach Selection

Three approaches were evaluated for Layer 1:

### Approach A: PreCompact-Only (rejected — too minimal)
Extend `compact_hook.py` only. No directives file, no status integration. Everything generated dynamically at compact-time. Simple but not debuggable, no way to preview or inspect what directives will fire.

### Approach B: PreCompact + Directives File (selected)
Extend `compact_hook.py` AND maintain `.claude/buffer/compact-directives.md` that gets updated at key moments.

**Update points:**
- `/buffer:on` writes initial directives based on trunk state (what's on disk, what threads are active)
- `/buffer:off` updates directives with final session state before saving
- PreCompact hook reads directives file + live signals (`.session_active`, markers) → generates combined compaction instruction

**Why this wins:**
- Separation of static context (what's on disk) from dynamic signals (depth, markers)
- `/buffer:status` can display directive readiness
- Human-readable, inspectable, debuggable
- Directives survive between compactions within a session
- Doesn't touch sigma_hook.py

### Approach C: Full Hook Triangle (rejected — over-engineered)
Everything in B, plus intercept `/compact` via UserPromptSubmit in sigma_hook.py to merge user focus text with plugin directives. Rejected because PreCompact already fires on all compact events (auto and manual), making the UserPromptSubmit interception redundant. Also risks sigma_hook.py complexity and may not work mechanically (CLI commands vs LLM messages).

### Future Enhancement: Prompt Pulse Tracking

Considered but deferred: having sigma_hook.py update directives or emit a "pulse" on every user prompt, tracking conversational drift turn-by-turn. This would keep directives fresh with the actual focus of conversation, not just the state at `/buffer:on` time.

**Why deferred:** sigma_hook.py has a 5-second timeout and is designed to be fast/silent. Adding file writes risks timeout on slower machines. The basic directives (trunk state + live markers + session depth) already capture enough for Layer 1. If compaction quality still feels lossy after B is running, a lightweight pulse file (`.claude/buffer/.compact_pulse`) is a clean upgrade:

```
# compact_pulse — appended by sigma_hook.py, read by PreCompact
2026-03-14T15:30:00Z auth-refactor
2026-03-14T15:31:00Z auth-refactor
2026-03-14T15:35:00Z compaction-directives
```

PreCompact reads last 5-10 lines, most-frequent concept = current thread. Tiny writes, no timeout risk. This is a Layer 3/4 concern — telemetry feeding smarter directives. Build B first, evaluate, upgrade if needed.

---

## Implementation Priority

1. **Layer 1 (Compaction Directives)** — Highest leverage. Extend `compact_hook.py` to generate context-aware focus text on every compaction. Immediate, tangible improvement to compaction quality.
2. **Layer 2 (Headroom Check)** — Natural companion. Uses same signals as Layer 1. Can be added to `/buffer:status` output and skill prompts.
3. **Layer 3 (Telemetry)** — Low-cost emit-only. Add one-liners to existing hooks. Data accumulates passively.
4. **Layer 4 (Praxes)** — Depends on Layer 3 data. Future work.
