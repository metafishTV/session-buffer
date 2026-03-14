# Layer 1: Compaction Directives — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the buffer plugin's compaction hooks to inject context-aware directives after every compaction event, making compaction summaries smarter without user intervention.

**Architecture:** Two-pronged delivery. (1) A `## Compaction Guidance` section in CLAUDE.md influences the summarizer during compaction. (2) PostCompact injection via `compact_hook.py` restores structured context after compaction. A directives file (`compact-directives.md`) provides the source data. SKILL.md instructions tell Claude when to write/update these files.

**Tech Stack:** Python 3 (compact_hook.py), Markdown (SKILL.md, compact-directives.md), JSON (hooks.json)

**Spec:** `docs/superpowers/specs/2026-03-14-layer1-compaction-directives-spec.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugin/scripts/compact_hook.py` | Modify | Add `generate_directive_context()`, integrate into `build_compact_summary()` |
| `plugin/hooks/hooks.json` | Verify/Modify | Ensure PostCompact event is wired (may already be covered by SessionStart) |
| `plugin/skills/on/SKILL.md` | Modify | Add Step 0d-b: write compact-directives.md + CLAUDE.md compaction section |
| `plugin/skills/off/SKILL.md` | Modify | Add Step 12b: update directives, migrate vocabulary |
| `plugin/skills/status/SKILL.md` | Modify | Add compaction directives section to health report |
| `tests/test_compact_hook.py` | Modify | Add tests for `generate_directive_context()` and integration |
| `.claude/buffer/compact-directives.md` | Runtime | Written by Claude during `/buffer:on` (not committed to repo) |

---

## Chunk 1: PostCompact Wiring + Directive Generator

### Task 1: Verify and wire PostCompact in hooks.json

The existing `hooks.json` has `SessionStart` calling `compact_hook.py post-compact`. The spec says we may also need an explicit `PostCompact` entry. Check and add if missing.

**Files:**
- Modify: `plugin/hooks/hooks.json`

- [ ] **Step 1: Inspect current hooks.json**

Current state (confirmed by reading the file):
- `PreCompact` → `compact_hook.py pre-compact` (manual + auto matchers) ✓
- `SessionStart` → `compact_hook.py post-compact` ✓
- No explicit `PostCompact` entry

The `SessionStart` hook fires after compaction (confirmed by the existing `.compact_marker` guard logic in `cmd_post_compact`). However, the spec notes that `PostCompact` fires *immediately* after compaction with `compact_summary` in its input, while `SessionStart` fires at broader session-start events. Adding an explicit `PostCompact` entry ensures the directive injection happens via the officially documented compaction-specific event.

- [ ] **Step 2: Add PostCompact entry to hooks.json**

Add a `PostCompact` section alongside the existing entries. The command is identical to SessionStart — `compact_hook.py post-compact` handles both cases via the `.compact_marker` guard.

No matcher needed — fires unconditionally (matching the SessionStart pattern):

```json
"PostCompact": [
  {
    "hooks": [{
      "type": "command",
      "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/run_python\" \"${CLAUDE_PLUGIN_ROOT}/scripts/compact_hook.py\" post-compact",
      "timeout": 30
    }]
  }
]
```

- [ ] **Step 3: Commit**

```bash
git add plugin/hooks/hooks.json
git commit -m "chore: wire PostCompact hook for directive injection"
```

---

### Task 2: Write tests for `generate_directive_context()`

**Files:**
- Modify: `tests/test_compact_hook.py`
- Modify: `tests/conftest.py` (add fixture for directives file)

- [ ] **Step 1: Add buffer_dir_with_directives fixture to conftest.py**

After the existing `full_buffer_dir` fixture (~line 101), add:

```python
@pytest.fixture
def buffer_dir_with_directives(buffer_dir):
    """Buffer directory with a compact-directives.md file."""
    directives = buffer_dir / 'compact-directives.md'
    directives.write_text(
        "# Compaction Directives\n\n"
        "## On Disk\n"
        "- Sigma trunk: .claude/buffer/handoff.json\n"
        "- Alpha bin: .claude/buffer/alpha/\n\n"
        "## Active Threads\n"
        "- Layer 1 implementation (compact_hook.py)\n"
        "- PostCompact hook wiring (hooks.json)\n\n"
        "## Already Persisted\n"
        "- Session state saved in handoff.json\n\n"
        "## Session Vocabulary\n"
        "- placenta: living connective tissue between plugin and LLM\n"
        "- headroom: remaining context capacity before compaction\n",
        encoding='utf-8'
    )
    return buffer_dir
```

- [ ] **Step 2: Write test class for generate_directive_context**

Add to `tests/test_compact_hook.py`:

```python
from compact_hook import generate_directive_context


class TestGenerateDirectiveContext:
    """Tests for generate_directive_context()."""

    def test_no_directives_file_returns_empty(self, buffer_dir):
        """No compact-directives.md -> returns empty string."""
        result = generate_directive_context(str(buffer_dir))
        assert result == ''

    def test_with_directives_file_includes_sections(self, buffer_dir_with_directives):
        """Directives file present -> output includes all sections."""
        result = generate_directive_context(str(buffer_dir_with_directives))
        assert 'COMPACTION DIRECTIVES' in result
        assert 'CONTEXT ON DISK' in result
        assert 'handoff.json' in result
        assert 'ACTIVE THREADS' in result
        assert 'Layer 1 implementation' in result
        assert 'SESSION VOCABULARY' in result
        assert 'placenta' in result

    def test_session_depth_zero(self, buffer_dir_with_directives):
        """No .session_active -> depth 0, full detail guidance."""
        result = generate_directive_context(str(buffer_dir_with_directives))
        assert 'SESSION DEPTH: 0' in result
        assert 'Full thread detail' in result

    def test_session_depth_two(self, buffer_dir_with_directives):
        """off_count=2 -> deep session guidance."""
        marker = Path(buffer_dir_with_directives) / '.session_active'
        marker.write_text(
            json.dumps({"date": "2026-03-14", "off_count": 2}),
            encoding='utf-8'
        )
        result = generate_directive_context(str(buffer_dir_with_directives))
        assert 'SESSION DEPTH: 2' in result
        assert 'deep session' in result

    def test_depth_from_session_active(self, buffer_dir_with_directives):
        """Write .session_active with off_count=3 -> critical depth guidance."""
        marker = Path(buffer_dir_with_directives) / '.session_active'
        marker.write_text(
            json.dumps({"date": "2026-03-14", "off_count": 3}),
            encoding='utf-8'
        )
        result = generate_directive_context(str(buffer_dir_with_directives))
        assert 'SESSION DEPTH: 3' in result
        assert 'Significant context recycling' in result

    def test_malformed_session_active_treated_as_zero(self, buffer_dir_with_directives):
        """Malformed .session_active JSON -> depth treated as 0."""
        marker = Path(buffer_dir_with_directives) / '.session_active'
        marker.write_text('not json at all', encoding='utf-8')
        result = generate_directive_context(str(buffer_dir_with_directives))
        assert 'SESSION DEPTH: 0' in result

    def test_empty_directives_file_returns_empty(self, buffer_dir):
        """Empty compact-directives.md -> returns empty string."""
        directives = Path(str(buffer_dir)) / 'compact-directives.md'
        directives.write_text('', encoding='utf-8')
        result = generate_directive_context(str(buffer_dir))
        assert result == ''

    def test_directives_without_vocabulary_section(self, buffer_dir):
        """Directives file with no Session Vocabulary -> no vocabulary block."""
        directives = Path(str(buffer_dir)) / 'compact-directives.md'
        directives.write_text(
            "# Compaction Directives\n\n"
            "## On Disk\n"
            "- Sigma trunk: .claude/buffer/handoff.json\n\n"
            "## Active Threads\n"
            "- Working on tests\n",
            encoding='utf-8'
        )
        result = generate_directive_context(str(buffer_dir))
        assert 'COMPACTION DIRECTIVES' in result
        assert 'SESSION VOCABULARY' not in result
```

- [ ] **Step 3: Add integration test for directives in build_compact_summary**

```python
class TestBuildCompactSummaryWithDirectives:
    """Tests that build_compact_summary includes directive context when available."""

    def test_summary_includes_directives(self, buffer_dir_with_directives, hot_minimal):
        """build_compact_summary appends directive context when directives file exists."""
        result = build_compact_summary(
            hot_minimal, str(buffer_dir_with_directives), 200, 500, 500
        )
        assert 'COMPACTION DIRECTIVES' in result
        assert 'POST-COMPACTION SIGMA TRUNK RECOVERY' in result
        assert 'placenta' in result

    def test_summary_without_directives_unchanged(self, buffer_dir, hot_minimal):
        """build_compact_summary without directives file -> no directive block."""
        result = build_compact_summary(hot_minimal, str(buffer_dir), 200, 500, 500)
        assert 'COMPACTION DIRECTIVES' not in result
        # Existing content still present
        assert 'POST-COMPACTION SIGMA TRUNK RECOVERY' in result
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_compact_hook.py -v`
Expected: FAIL — `generate_directive_context` not yet defined, import error

- [ ] **Step 5: Commit test file**

```bash
git add tests/test_compact_hook.py tests/conftest.py
git commit -m "test: add tests for generate_directive_context"
```

---

### Task 3: Implement `generate_directive_context()` in compact_hook.py

**Files:**
- Modify: `plugin/scripts/compact_hook.py`

- [ ] **Step 1: Add `generate_directive_context()` function**

Insert after the `read_hook_input()` function (after line 69) and before `detect_layer_limits()`:

```python
def generate_directive_context(buffer_dir):
    """Generate compaction directive context from compact-directives.md and session depth.

    Returns a formatted string to append to the post-compaction injection.
    Returns empty string if no directives file exists or it's empty.
    """
    directives_path = os.path.join(buffer_dir, 'compact-directives.md')

    # Read directives file
    try:
        with open(directives_path, 'r', encoding='utf-8') as f:
            directives_text = f.read().strip()
    except (FileNotFoundError, OSError):
        return ''

    if not directives_text:
        return ''

    # Parse sections from the markdown
    sections = {}
    current_section = None
    current_lines = []

    for line in directives_text.split('\n'):
        if line.startswith('## '):
            if current_section:
                sections[current_section] = '\n'.join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = '\n'.join(current_lines).strip()

    # Read session depth from .session_active
    depth = 0
    session_active_path = os.path.join(buffer_dir, '.session_active')
    try:
        with open(session_active_path, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
            depth = int(session_data.get('off_count', 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        depth = 0

    # Build output
    lines = []
    lines.append('--- COMPACTION DIRECTIVES ---')
    lines.append('')

    # On Disk section
    on_disk = sections.get('On Disk', '')
    if on_disk:
        lines.append('CONTEXT ON DISK (recoverable via tools):')
        for item in on_disk.split('\n'):
            item = item.strip()
            if item.startswith('- '):
                lines.append(item)
        lines.append('')

    # Active Threads section
    threads = sections.get('Active Threads', '')
    if threads:
        lines.append('ACTIVE THREADS:')
        for item in threads.split('\n'):
            item = item.strip()
            if item.startswith('- '):
                lines.append(item)
        lines.append('')

    # Session Vocabulary section
    vocab = sections.get('Session Vocabulary', '')
    if vocab and vocab.strip():
        lines.append('SESSION VOCABULARY:')
        for item in vocab.split('\n'):
            item = item.strip()
            if item.startswith('- '):
                lines.append(item)
        lines.append('')

    # Session depth and adaptive guidance
    lines.append(f'SESSION DEPTH: {depth} save cycles.')
    if depth <= 1:
        lines.append(
            'Full thread detail and rationale should be available '
            'in the compaction summary above.'
        )
    elif depth == 2:
        lines.append(
            'This is a deep session. Prioritize continuity and active focus. '
            'Details are in git and the buffer trunk.'
        )
    else:
        lines.append(
            'Significant context recycling. Focus on: what we are doing, why, '
            'and the next step. All detail is on disk.'
        )
    lines.append('')

    lines.append(
        'The buffer plugin has re-injected essential context above. '
        'Use /buffer:on if you need full trunk reconstruction.'
    )

    return '\n'.join(lines)
```

- [ ] **Step 2: Integrate into `build_compact_summary()`**

In `build_compact_summary()`, just before the `# --- Consistency check directive ---` comment (line 497), add:

```python
    # --- Compaction directives ---
    directive_context = generate_directive_context(buffer_dir)
    if directive_context:
        lines.append(directive_context)
        lines.append('')
```

- [ ] **Step 3: Update the import in test file**

In `tests/test_compact_hook.py`, update the import at line 8-14:

```python
from compact_hook import (
    build_compact_summary,
    detect_layer_limits,
    find_buffer_dir,
    generate_directive_context,
    read_json,
    write_json,
)
```

- [ ] **Step 4: Run tests**

Run: `cd session-buffer && python -m pytest tests/test_compact_hook.py -v`
Expected: ALL PASS (both old and new tests)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: ALL PASS — no regressions in existing tests

- [ ] **Step 6: Commit**

```bash
git add plugin/scripts/compact_hook.py tests/test_compact_hook.py tests/conftest.py
git commit -m "feat: add generate_directive_context to compact_hook

Reads compact-directives.md and .session_active to build a directive
block injected after compaction. Includes depth-adaptive guidance.
Appended to existing build_compact_summary output."
```

---

## Chunk 2: SKILL.md Changes

### Task 4: Add Step 0d-b to /buffer:on SKILL.md

**Files:**
- Modify: `plugin/skills/on/SKILL.md` (insert after line 202, after Step 0d)

- [ ] **Step 1: Insert Step 0d-b after the existing Step 0d block**

After line 202 (the last line of Step 0d about `off_count`), insert:

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
section. If it doesn't exist, add it. If it exists, replace it. The section
content:

```
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

During this session, if you coin or adopt a term with specific meaning
(neologism, repurposed word, project-specific shorthand), add it to the
Session Vocabulary section of compact-directives.md with a 1-sentence
definition. Keep to ~5-10 entries. Standard technical vocabulary and terms
already in the alpha bin don't belong here.
```

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/on/SKILL.md
git commit -m "feat: add Step 0d-b to /buffer:on — write compaction directives"
```

---

### Task 5: Add Step 12b to /buffer:off SKILL.md

**Files:**
- Modify: `plugin/skills/off/SKILL.md` (insert between Step 12 and Step 13, after line 342)

- [ ] **Step 1: Insert Step 12b**

After line 342 (end of Step 12), before Step 13 (line 344), insert:

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

- [ ] **Step 2: Commit**

```bash
git add plugin/skills/off/SKILL.md
git commit -m "feat: add Step 12b to /buffer:off — update compaction directives"
```

---

### Task 6: Extend /buffer:status SKILL.md

**Files:**
- Modify: `plugin/skills/status/SKILL.md` (add section after Step 2, before Step 3)

- [ ] **Step 1: Add compaction directives check**

After the Step 2 marker checks section (after line 22), insert:

```markdown
## Step 2b: Check compaction directives

Read `.claude/buffer/compact-directives.md` if it exists.
- If missing: note "Directives: not configured"
- If present: count on-disk files listed, active threads listed, and vocabulary terms listed. Note "Directives: active"

Check if CLAUDE.md contains a `## Compaction Guidance` section.
- If missing: note "CLAUDE.md compaction section: not present"
- If present: note "CLAUDE.md compaction section: active"
```

- [ ] **Step 2: Add directives line to the output format**

In the Step 4 output format block (line 33-48), add after the `Markers:` line:

```
Directives: [active (N files, M threads, K vocab) | not configured]
CLAUDE.md:  [compaction section active | not present]
```

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/status/SKILL.md
git commit -m "feat: extend /buffer:status with compaction directives state"
```

---

## Chunk 3: Verification

### Task 7: Automated verification

Smoke tests and regression checks for the code changes.

- [ ] **Step 1: Verify compact_hook.py runs without errors**

Run: `cd session-buffer && python plugin/scripts/compact_hook.py --help`
Expected: Usage message printed, exit 0

- [ ] **Step 2: Test generate_directive_context with nonexistent path**

Run: `cd session-buffer && python -c "import tempfile, os; from compact_hook import generate_directive_context; print(repr(generate_directive_context(os.path.join(tempfile.gettempdir(), 'nonexistent_buffer_dir'))))"`
Expected: `''` (empty string)

- [ ] **Step 3: Run the full test suite**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: ALL PASS, no regressions

- [ ] **Step 4: Verify hooks.json is valid JSON**

Run: `cd session-buffer && python -c "import json; json.load(open('plugin/hooks/hooks.json')); print('Valid JSON')"`
Expected: `Valid JSON`

- [ ] **Step 5: Verify sigma_hook.py is untouched**

Run: `cd session-buffer && git diff plugin/scripts/sigma_hook.py`
Expected: No output (no changes)

- [ ] **Step 6: Verify build_compact_summary regression — no directives = unchanged output**

Run: `cd session-buffer && python -c "from compact_hook import build_compact_summary; r = build_compact_summary({}, '/tmp/no_buffer', 200, 500, 500); assert 'COMPACTION DIRECTIVES' not in r; print('Regression check passed')"`
Expected: `Regression check passed`

---

### Task 8: Manual lifecycle verification

These steps verify the SKILL.md-driven lifecycle. They require running `/buffer:on` and `/buffer:off` in a live Claude Code session — they cannot be automated in pytest. An implementor should run through them manually after all code changes are committed.

- [ ] **Step 1: /buffer:on creates directives file**

Run `/buffer:on` in a session with an existing sigma trunk.
Verify: `.claude/buffer/compact-directives.md` exists with On Disk, Active Threads, Already Persisted, and Session Vocabulary sections.

- [ ] **Step 2: /buffer:on writes CLAUDE.md compaction section**

Verify: CLAUDE.md contains a `## Compaction Guidance` section with on-disk paths and preservation instructions.

- [ ] **Step 3: Vocabulary term survives compaction**

During a session, add a term to compact-directives.md Session Vocabulary.
Trigger `/compact`. After compaction, verify the term appears in the post-compaction directive injection.

- [ ] **Step 4: /buffer:off updates directives**

Run `/buffer:off`. Verify: compact-directives.md Active Threads section is refreshed to match the handoff.json open_threads.

- [ ] **Step 5: Next /buffer:on overwrites directives**

Run `/buffer:on` again. Verify: compact-directives.md is overwritten fresh (Session Vocabulary is empty, Active Threads match current trunk state).

- [ ] **Step 6: Edge case — compact without /buffer:on**

In a session where `/buffer:on` was NOT run (no compact-directives.md), trigger `/compact`. Verify: existing compaction behavior is unchanged — no directive block in output, no errors.

- [ ] **Step 7: Edge case — .session_active missing or malformed**

Delete `.session_active` and trigger `/compact`. Verify: depth treated as 0, no crash. Then write invalid JSON to `.session_active` and repeat — same result.

- [ ] **Step 8: Edge case — CLAUDE.md has no compaction section**

Remove the `## Compaction Guidance` section from CLAUDE.md. Trigger `/compact`. Verify: compaction uses default behavior, no errors.

- [ ] **Step 9: Commit if any fixes were needed**

If any manual test revealed issues that required code changes, commit those fixes with specific file paths:

```bash
git add <specific files that changed>
git commit -m "fix: address issues found in manual lifecycle testing"
```

If no changes needed, skip this step.

---

## Summary of Changes

| Component | What Changed |
|---|---|
| `compact_hook.py` | New `generate_directive_context()` function; integrated into `build_compact_summary()` |
| `hooks.json` | Added `PostCompact` event with manual + auto matchers |
| `on/SKILL.md` | Added Step 0d-b: write compact-directives.md + CLAUDE.md compaction section |
| `off/SKILL.md` | Added Step 12b: update directives, migrate vocabulary |
| `status/SKILL.md` | Added Step 2b + output lines for directives state |
| `test_compact_hook.py` | 8 new tests for `generate_directive_context()` + 2 integration tests |
| `conftest.py` | 1 new fixture: `buffer_dir_with_directives` |

## What This Does NOT Touch

- `sigma_hook.py` — no per-prompt tracking (deferred to Layer 3/4)
- `plugin.json` — no manifest changes needed
- Default compaction prompt — CLAUDE.md guides it; directives restore after
- Vocabulary persistence across sessions — ephemeral by design
