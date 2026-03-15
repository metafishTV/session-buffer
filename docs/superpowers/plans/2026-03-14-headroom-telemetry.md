# Headroom Check + Telemetry (Layers 2-3) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add context pressure awareness (headroom check) and event logging (telemetry) to the buffer plugin, giving both users and AI visibility into when compaction should happen and recording events for future self-tuning.

**Architecture:** A new `telemetry.py` utility provides fail-silent event emission to `.claude/buffer/telemetry.jsonl`. The sigma hook gains headroom tier detection (70/85/93% thresholds) with once-per-crossing injection. The statusline gains a `ctx:XX%` segment. The compact hook emits a telemetry event on each compaction. `/buffer:off` emits a session-end summary.

**Tech Stack:** Python 3.8+, JSON/JSONL, existing importlib pattern for cross-script imports

**Spec:** `docs/superpowers/specs/2026-03-14-headroom-telemetry-design.md`

---

## Chunk 1: Telemetry Utility + Tests

### Task 1: Create `telemetry.py` with `emit()`, `tier_from_percentage()`, and `cache_ratio()`

**Files:**
- Create: `plugin/scripts/telemetry.py`
- Create: `tests/test_telemetry.py`

#### Core functions to implement

`telemetry.py` provides three pure functions and one I/O function:

```python
# plugin/scripts/telemetry.py
"""
Session Buffer — Telemetry Utility

Append-only event logging to .claude/buffer/telemetry.jsonl.
Imported by sigma_hook and compact_hook via importlib pattern.
Also provides a session-end CLI subcommand for /buffer:off.

Design principle: fail-silent. Telemetry must never break a hook.
"""

import json
import os
import sys
from datetime import datetime, timezone


def tier_from_percentage(used_pct):
    """Return headroom tier name from context usage percentage.

    Thresholds use >= boundaries:
      >= 93 → 'critical'
      >= 85 → 'warn'
      >= 70 → 'watch'
      < 70  → None
    """
    if used_pct >= 93:
        return 'critical'
    if used_pct >= 85:
        return 'warn'
    if used_pct >= 70:
        return 'watch'
    return None


def cache_ratio(cache_read, cache_creation, input_tokens):
    """Compute cache read ratio.

    Returns cache_read / (cache_read + cache_creation + input_tokens).
    Returns 0.0 if denominator is zero (avoids ZeroDivisionError).
    """
    total = cache_read + cache_creation + input_tokens
    if total == 0:
        return 0.0
    return cache_read / total


def emit(buffer_dir, event_dict):
    """Append a timestamped event to telemetry.jsonl.

    Auto-adds 'ts' field with ISO 8601 UTC timestamp.
    Creates file if it doesn't exist.
    Fail-silent: logs to stderr on error, never raises.
    """
    try:
        entry = dict(event_dict)
        entry['ts'] = datetime.now(timezone.utc).isoformat()
        telemetry_path = os.path.join(buffer_dir, 'telemetry.jsonl')
        with open(telemetry_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"telemetry: emit failed: {e}", file=sys.stderr)


def cmd_session_end(buffer_dir):
    """Compute and emit session-end summary from today's telemetry.

    Scans telemetry.jsonl for today's entries, computes:
      - compactions: count of 'compact' events today
      - warnings_emitted: count of 'headroom_warning' events today
      - peak_context_pct: max context_pct across today's events
      - off_count: from .session_active

    Called by /buffer:off Step 13.
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    telemetry_path = os.path.join(buffer_dir, 'telemetry.jsonl')

    compactions = 0
    warnings = 0
    peak_pct = 0

    try:
        with open(telemetry_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get('ts', '')
                if not ts.startswith(today):
                    continue
                event = entry.get('event', '')
                if event == 'compact':
                    compactions += 1
                elif event == 'headroom_warning':
                    warnings += 1
                pct = entry.get('context_pct', 0)
                if isinstance(pct, (int, float)) and pct > peak_pct:
                    peak_pct = pct
    except FileNotFoundError:
        pass  # No telemetry yet — still emit session_end with zeros
    except Exception as e:
        print(f"telemetry: session-end scan failed: {e}", file=sys.stderr)

    # Read off_count from .session_active
    off_count = 0
    session_active_path = os.path.join(buffer_dir, '.session_active')
    try:
        with open(session_active_path, 'r', encoding='utf-8') as f:
            sa = json.load(f)
            off_count = int(sa.get('off_count', 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        pass

    emit(buffer_dir, {
        'event': 'session_end',
        'compactions': compactions,
        'off_count': off_count,
        'warnings_emitted': warnings,
        'peak_context_pct': peak_pct,
    })


if __name__ == '__main__':
    # CLI interface for /buffer:off
    if len(sys.argv) >= 2 and sys.argv[1] == 'session-end':
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('command')
        parser.add_argument('--buffer-dir', required=True)
        args = parser.parse_args()
        cmd_session_end(args.buffer_dir)
    else:
        print("Usage: telemetry.py session-end --buffer-dir <path>",
              file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telemetry.py`:

```python
# tests/test_telemetry.py
"""Tests for telemetry utility — emit, tiers, cache ratio, once-per-crossing."""

import json
import os
import sys
import importlib.util
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Load telemetry module via importlib (same pattern as other buffer tests)
# ---------------------------------------------------------------------------

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'plugin', 'scripts'
)

_spec = importlib.util.spec_from_file_location(
    'telemetry', os.path.join(SCRIPTS_DIR, 'telemetry.py'))
telemetry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(telemetry)


# ---------------------------------------------------------------------------
# tier_from_percentage
# ---------------------------------------------------------------------------

class TestTierFromPercentage:
    def test_below_70_returns_none(self):
        assert telemetry.tier_from_percentage(0) is None
        assert telemetry.tier_from_percentage(50) is None
        assert telemetry.tier_from_percentage(69) is None

    def test_watch_tier(self):
        assert telemetry.tier_from_percentage(70) == 'watch'
        assert telemetry.tier_from_percentage(75) == 'watch'
        assert telemetry.tier_from_percentage(84) == 'watch'

    def test_warn_tier(self):
        assert telemetry.tier_from_percentage(85) == 'warn'
        assert telemetry.tier_from_percentage(90) == 'warn'
        assert telemetry.tier_from_percentage(92) == 'warn'

    def test_critical_tier(self):
        assert telemetry.tier_from_percentage(93) == 'critical'
        assert telemetry.tier_from_percentage(95) == 'critical'
        assert telemetry.tier_from_percentage(100) == 'critical'

    def test_exact_boundaries(self):
        """Boundaries use >= so exact values hit the higher tier."""
        assert telemetry.tier_from_percentage(70) == 'watch'
        assert telemetry.tier_from_percentage(85) == 'warn'
        assert telemetry.tier_from_percentage(93) == 'critical'


# ---------------------------------------------------------------------------
# cache_ratio
# ---------------------------------------------------------------------------

class TestCacheRatio:
    def test_normal_calculation(self):
        ratio = telemetry.cache_ratio(42, 50, 8)
        assert ratio == pytest.approx(0.42)

    def test_zero_division(self):
        assert telemetry.cache_ratio(0, 0, 0) == 0.0

    def test_all_cache_read(self):
        assert telemetry.cache_ratio(100, 0, 0) == pytest.approx(1.0)

    def test_no_cache_read(self):
        assert telemetry.cache_ratio(0, 50, 50) == 0.0


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

class TestEmit:
    def test_creates_file(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'test'})
        path = tmp_path / 'telemetry.jsonl'
        assert path.exists()
        entry = json.loads(path.read_text().strip())
        assert entry['event'] == 'test'
        assert 'ts' in entry

    def test_appends_not_overwrites(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'first'})
        telemetry.emit(str(tmp_path), {'event': 'second'})
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        assert len(lines) == 2
        assert json.loads(lines[0])['event'] == 'first'
        assert json.loads(lines[1])['event'] == 'second'

    def test_auto_timestamps(self, tmp_path):
        telemetry.emit(str(tmp_path), {'event': 'check_ts'})
        entry = json.loads(
            (tmp_path / 'telemetry.jsonl').read_text().strip())
        ts = entry['ts']
        # Should be valid ISO 8601 — parse it
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # timezone-aware

    def test_fail_silent(self, tmp_path):
        """Unwritable path doesn't raise."""
        bad_dir = str(tmp_path / 'nonexistent' / 'deep' / 'path')
        # Should not raise
        telemetry.emit(bad_dir, {'event': 'should_not_crash'})


# ---------------------------------------------------------------------------
# Once-per-crossing logic (tested as tier transitions)
# ---------------------------------------------------------------------------

class TestOncePerCrossing:
    """Tests for the tier-crossing detection pattern used by sigma_hook.

    The actual 'last tier' tracking lives in sigma_hook, but we test the
    tier_from_percentage function's role in the pattern here.
    """

    def test_same_tier_twice(self):
        """Same percentage range should produce same tier (caller deduplicates)."""
        assert telemetry.tier_from_percentage(72) == telemetry.tier_from_percentage(78)

    def test_tier_upgrade_different(self):
        """Crossing from watch to warn produces different tier values."""
        tier_a = telemetry.tier_from_percentage(80)
        tier_b = telemetry.tier_from_percentage(90)
        assert tier_a != tier_b
        assert tier_a == 'watch'
        assert tier_b == 'warn'


# ---------------------------------------------------------------------------
# cmd_session_end
# ---------------------------------------------------------------------------

class TestSessionEnd:
    def test_session_end_with_events(self, tmp_path):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        # Write some telemetry entries
        telemetry.emit(str(tmp_path), {
            'event': 'compact', 'context_pct': 93})
        telemetry.emit(str(tmp_path), {
            'event': 'headroom_warning', 'context_pct': 87, 'tier': 'warn'})
        telemetry.emit(str(tmp_path), {
            'event': 'headroom_warning', 'context_pct': 72, 'tier': 'watch'})
        telemetry.emit(str(tmp_path), {
            'event': 'compact', 'context_pct': 95})

        # Write .session_active
        sa_path = tmp_path / '.session_active'
        sa_path.write_text(json.dumps({'date': today, 'off_count': 2}))

        # Run session-end
        telemetry.cmd_session_end(str(tmp_path))

        # Read last line (the session_end event)
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        end_event = json.loads(lines[-1])
        assert end_event['event'] == 'session_end'
        assert end_event['compactions'] == 2
        assert end_event['warnings_emitted'] == 2
        assert end_event['peak_context_pct'] == 95
        assert end_event['off_count'] == 2

    def test_session_end_no_prior_events(self, tmp_path):
        """Session end with no prior telemetry emits zeros."""
        telemetry.cmd_session_end(str(tmp_path))
        lines = (tmp_path / 'telemetry.jsonl').read_text().strip().split('\n')
        end_event = json.loads(lines[-1])
        assert end_event['event'] == 'session_end'
        assert end_event['compactions'] == 0
        assert end_event['warnings_emitted'] == 0
        assert end_event['peak_context_pct'] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd session-buffer && python -m pytest tests/test_telemetry.py -v`
Expected: ImportError or ModuleNotFoundError (telemetry.py doesn't exist yet)

- [ ] **Step 3: Create `plugin/scripts/telemetry.py`**

Write the complete `telemetry.py` file as shown in the "Core functions to implement" section above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_telemetry.py -v`
Expected: All 17 tests PASS

- [ ] **Step 5: Commit**

```bash
cd session-buffer
git add plugin/scripts/telemetry.py tests/test_telemetry.py
git commit -m "feat(telemetry): add telemetry utility with emit, tiers, cache ratio, session-end"
```

---

## Chunk 2: Sigma Hook Headroom Check + Statusline

### Task 2: Add headroom check to `sigma_hook.py`

**Files:**
- Modify: `plugin/scripts/sigma_hook.py:1362-1410` (main function, after gates, before cascade)

The headroom check runs on every `UserPromptSubmit` firing, after the cooldown gate and before the cascade. It:
1. Reads `used_percentage` from hook input session JSON
2. Computes tier via `tier_from_percentage()`
3. Compares to last emitted tier (stored in `.sigma_headroom_tier`)
4. If tier changed: injects warning message AND emits `headroom_warning` telemetry event
5. Does NOT exit — the normal sigma cascade continues after injection

**Key design point:** The headroom injection uses `systemMessage` (not `additionalContext`) and does NOT call `emit()` to exit. It appends to a list of system messages that get combined at the end. However, looking at the current code, `emit()` calls `sys.exit(0)`. So the headroom check must be structured as a **pre-cascade injection** that adds to the output dict before the cascade runs, not a separate emit.

**Implementation approach:** Add a `headroom_injection` variable that gets populated early. At each `emit()` call site later in the cascade, if `headroom_injection` is set, prepend it to the systemMessage.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_telemetry.py` (or a new test, but these are really telemetry tests):

The headroom logic in sigma_hook is hard to unit test in isolation since `main()` reads stdin and calls `sys.exit`. Instead, we test the building blocks (`tier_from_percentage` is already tested in Task 1) and do a lightweight integration test of the tier-tracking file.

Create `tests/test_headroom.py`:

```python
# tests/test_headroom.py
"""Tests for headroom tier tracking (sigma_hook integration)."""

import json
import os

import pytest


class TestHeadroomTierFile:
    """Test the .sigma_headroom_tier file read/write pattern."""

    def test_no_file_returns_none(self, tmp_path):
        tier_path = tmp_path / '.sigma_headroom_tier'
        # No file → last tier is None (first time)
        assert not tier_path.exists()

    def test_write_and_read_tier(self, tmp_path):
        tier_path = tmp_path / '.sigma_headroom_tier'
        tier_path.write_text('watch')
        assert tier_path.read_text() == 'watch'

    def test_tier_crossing_detection(self, tmp_path):
        """Simulate the once-per-crossing pattern."""
        import importlib.util
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugin', 'scripts')
        _spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(scripts_dir, 'telemetry.py'))
        telemetry = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(telemetry)

        tier_path = tmp_path / '.sigma_headroom_tier'

        # Simulate sequence: 60% → 72% → 78% → 88% → 90% → 95%
        percentages = [60, 72, 78, 88, 90, 95]
        expected_emissions = []  # (pct, tier) for each crossing

        last_tier = None
        for pct in percentages:
            current_tier = telemetry.tier_from_percentage(pct)
            if current_tier != last_tier and current_tier is not None:
                expected_emissions.append((pct, current_tier))
                last_tier = current_tier

        # Should emit: (72, watch), (88, warn), (95, critical)
        assert len(expected_emissions) == 3
        assert expected_emissions[0] == (72, 'watch')
        assert expected_emissions[1] == (88, 'warn')
        assert expected_emissions[2] == (95, 'critical')

    def test_no_emission_within_same_tier(self, tmp_path):
        """72% and 78% are both 'watch' — only one emission."""
        import importlib.util
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugin', 'scripts')
        _spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(scripts_dir, 'telemetry.py'))
        telemetry = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(telemetry)

        emissions = []
        last_tier = 'watch'  # Already emitted watch
        for pct in [72, 75, 78, 80, 84]:
            tier = telemetry.tier_from_percentage(pct)
            if tier != last_tier and tier is not None:
                emissions.append(tier)
                last_tier = tier
        assert emissions == []  # No new crossings
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd session-buffer && python -m pytest tests/test_headroom.py -v`
Expected: All 4 tests PASS (these test the pattern, not the sigma_hook code yet)

- [ ] **Step 3: Prerequisite — capture session JSON fields**

Before modifying sigma_hook.py, verify what fields are available in the hook input. Run a quick check:

```bash
cd session-buffer
python -c "
import json
# The hook input schema from Claude Code docs
# Expected fields in UserPromptSubmit hook input:
expected = ['user_prompt', 'cwd', 'session_id',
            'used_percentage', 'remaining_percentage',
            'cache_read_input_tokens', 'cache_creation_input_tokens',
            'input_tokens']
print('Expected session JSON fields for headroom:')
for f in expected:
    print(f'  {f}')
print()
print('Fallback: if used_percentage is absent, headroom check is skipped.')
print('Cache ratio fields are supplementary — omit from telemetry if absent.')
"
```

**Note for implementer:** The spec says to verify these fields are present in actual hook stdin. If `used_percentage` is not in the hook input, the headroom check should silently skip (no error). Cache ratio fields are supplementary — compute if available, omit if not.

- [ ] **Step 4: Modify `sigma_hook.py` — add headroom check**

In `plugin/scripts/sigma_hook.py`, make these changes:

**4a. Add import for telemetry at the top of `main()` (lazy import via importlib):**

After line 1369 (`cwd = hook_input.get('cwd', os.getcwd())`), add a helper to load telemetry:

```python
    # Load telemetry module (lazy, fail-silent)
    _telemetry_mod = None
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        _tel_spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(script_dir, 'telemetry.py'))
        _telemetry_mod = importlib.util.module_from_spec(_tel_spec)
        _tel_spec.loader.exec_module(_telemetry_mod)
    except Exception:
        pass
```

**4b. Add headroom check after GATE 0b (distill-active), before keyword extraction.**

Insert after line 1402 (`emit_empty()` for distill gate), before line 1404 (`# Extract keywords`):

```python
    # -----------------------------------------------------------------------
    # HEADROOM CHECK — context pressure awareness (Layer 2)
    # Runs on every firing. Injects warning on tier crossing only.
    # -----------------------------------------------------------------------
    headroom_injection = None
    used_pct = hook_input.get('used_percentage')
    if used_pct is not None and _telemetry_mod is not None:
        try:
            used_pct = float(used_pct)
            current_tier = _telemetry_mod.tier_from_percentage(used_pct)

            if current_tier is not None:
                # Read last emitted tier
                tier_path = os.path.join(buffer_dir, '.sigma_headroom_tier')
                last_tier = None
                try:
                    with open(tier_path, 'r', encoding='utf-8') as f:
                        last_tier = f.read().strip() or None
                except (FileNotFoundError, OSError):
                    pass

                # Only inject on tier crossing
                if current_tier != last_tier:
                    # Write new tier
                    try:
                        with open(tier_path, 'w', encoding='utf-8') as f:
                            f.write(current_tier)
                    except OSError:
                        pass

                    # Compute cache ratio (supplementary)
                    cr = None
                    cache_read = hook_input.get('cache_read_input_tokens')
                    cache_creation = hook_input.get('cache_creation_input_tokens')
                    input_tok = hook_input.get('input_tokens')
                    if cache_read is not None and cache_creation is not None and input_tok is not None:
                        cr = _telemetry_mod.cache_ratio(
                            float(cache_read), float(cache_creation), float(input_tok))

                    # Emit telemetry event
                    telemetry_event = {
                        'event': 'headroom_warning',
                        'context_pct': int(used_pct),
                        'tier': current_tier,
                    }
                    if cr is not None:
                        telemetry_event['cache_ratio'] = round(cr, 2)
                    _telemetry_mod.emit(buffer_dir, telemetry_event)

                    # Build injection message
                    pct_int = int(used_pct)
                    if current_tier == 'watch':
                        headroom_injection = f"Context at {pct_int}%."
                    elif current_tier == 'warn':
                        headroom_injection = (
                            f"Context at {pct_int}%. Consider compacting before "
                            "starting heavy work. Directives are ready."
                        )
                    elif current_tier == 'critical':
                        headroom_injection = (
                            f"Context at {pct_int}% \u2014 compaction imminent. "
                            "Run /compact now; directives will preserve active "
                            "threads and vocabulary."
                        )
        except (ValueError, TypeError):
            pass  # used_pct not a valid number — skip

```

**4c. Modify all `emit()` call sites to prepend headroom injection.**

Create a helper function near the top of `main()` (after the headroom check block):

```python
    def _emit_with_headroom(output):
        """Prepend headroom warning to systemMessage if present."""
        if headroom_injection and isinstance(output, dict):
            existing = output.get('systemMessage', '')
            if existing:
                output['systemMessage'] = headroom_injection + '\n\n' + existing
            else:
                output['systemMessage'] = headroom_injection
                output['suppressOutput'] = True
        return output
```

Then at each `emit()` call site in `main()` that runs **after** the headroom check block, wrap the output dict with `_emit_with_headroom()`. There are exactly 7 such sites. Find them by searching for `emit(` and `emit_empty()` within `main()`:

1. **No-keywords exit** (~line 1407): `emit(_with_resolution({}, resolution_due))` → `emit(_with_resolution(_emit_with_headroom({}), resolution_due))`
2. **Grid hit** (~line 1424): the `{"suppressOutput": True, "systemMessage": injection}` dict → wrap with `_emit_with_headroom()`
3. **Hot hits** (~line 1482): the `{"suppressOutput": True, "systemMessage": injection}` dict → wrap with `_emit_with_headroom()`
4. **Lite/no-concept exit** (~line 1493): `emit(_with_resolution({}, resolution_due))` → wrap `{}` with `_emit_with_headroom()`
5. **Ambiguity signal** (~line 1549): the `{"suppressOutput": True, "systemMessage": ambiguity}` dict → wrap with `_emit_with_headroom()`
6. **Empty ambiguity exit** (~line 1552): `emit(_with_resolution({}, resolution_due))` → wrap `{}` with `_emit_with_headroom()`
7. **Final alpha hit** (~line 1566): the `{"suppressOutput": True, "systemMessage": injection}` dict → wrap with `_emit_with_headroom()`

**Verification:** After editing, search `main()` for all `emit(` calls. You should find:
- 2 `emit_empty()` calls at the top (quick exits, lines ~1373-1375) — these do NOT get headroom wrapping (fire before buffer_dir is found)
- 1 `check_compact_relay()` call (line ~1398) — does NOT get headroom wrapping (relay has its own output)
- 7 `emit(` calls that DO get headroom wrapping (listed above)
- Total: 10 emit-family calls in main()

- [ ] **Step 5: Run all tests**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: All tests pass (existing + new)

- [ ] **Step 6: Commit**

```bash
cd session-buffer
git add plugin/scripts/sigma_hook.py tests/test_headroom.py
git commit -m "feat(headroom): add context pressure tier detection to sigma hook with telemetry"
```

### Task 3: Add `ctx:XX%` segment to statusline

**Files:**
- Modify: `plugin/scripts/statusline.py:47-110`

- [ ] **Step 1: Modify `statusline.py`**

In the `main()` function, after line 52 (`data = {}`) where session JSON is parsed, extract `used_percentage`:

```python
    # Context pressure (headroom check)
    used_pct = data.get('used_percentage')
```

Then after line 108 (`parts.append(branch)`), before line 110 (`print(" | ".join(parts))`), add the context pressure segment:

```python
    # Context pressure indicator (after all other segments)
    if used_pct is not None:
        try:
            pct = float(used_pct)
            pct_int = int(pct)
            if pct >= 93:
                parts.append(f"ctx:{pct_int}%!!")
            elif pct >= 85:
                parts.append(f"ctx:{pct_int}%!")
            elif pct >= 70:
                parts.append(f"ctx:{pct_int}%")
        except (ValueError, TypeError):
            pass
```

- [ ] **Step 2: Run existing statusline tests (if any) + manual verification**

Run: `cd session-buffer && python -m pytest tests/ -k statusline -v`
If no statusline tests exist, verify manually:

```bash
cd session-buffer
echo '{"cwd": ".", "used_percentage": 87}' | python plugin/scripts/statusline.py
# Expected output should contain: ctx:87%!
echo '{"cwd": ".", "used_percentage": 50}' | python plugin/scripts/statusline.py
# Expected output should NOT contain ctx:
echo '{"cwd": ".", "used_percentage": 95}' | python plugin/scripts/statusline.py
# Expected output should contain: ctx:95%!!
```

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/scripts/statusline.py
git commit -m "feat(statusline): add ctx:XX% context pressure indicator"
```

---

## Chunk 3: Compact Hook Telemetry + Off Skill + Version Bump

### Task 4: Add telemetry emit to `compact_hook.py`

**Files:**
- Modify: `plugin/scripts/compact_hook.py:230-285` (`cmd_pre_compact` function)

- [ ] **Step 1: Add telemetry import and emit in `cmd_pre_compact`**

In `cmd_pre_compact()`, after line 284 (`write_json(hot_path, hot)`) and before line 285 (`sys.exit(0)`), add:

```python
    # Emit telemetry event (Layer 3 — fail-silent)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        _tel_spec = importlib.util.spec_from_file_location(
            'telemetry', os.path.join(script_dir, 'telemetry.py'))
        _tel_mod = importlib.util.module_from_spec(_tel_spec)
        _tel_spec.loader.exec_module(_tel_mod)

        # Read context pressure from hook input
        used_pct = hook_input.get('used_percentage')
        context_pct = int(float(used_pct)) if used_pct is not None else None

        # Compute cache ratio
        cr = None
        cache_read = hook_input.get('cache_read_input_tokens')
        cache_creation = hook_input.get('cache_creation_input_tokens')
        input_tok = hook_input.get('input_tokens')
        if cache_read is not None and cache_creation is not None and input_tok is not None:
            cr = round(_tel_mod.cache_ratio(
                float(cache_read), float(cache_creation), float(input_tok)), 2)

        # Read session depth
        off_count = 0
        session_active_path = os.path.join(buffer_dir, '.session_active')
        try:
            with open(session_active_path, 'r', encoding='utf-8') as f:
                sa = json.load(f)
                off_count = int(sa.get('off_count', 0))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            pass

        # Count open threads
        threads = hot.get('open_threads', [])
        thread_count = len(threads) if isinstance(threads, list) else 0

        # Read headroom tier
        headroom_tier = None
        tier_path = os.path.join(buffer_dir, '.sigma_headroom_tier')
        try:
            with open(tier_path, 'r', encoding='utf-8') as f:
                headroom_tier = f.read().strip() or None
        except (FileNotFoundError, OSError):
            pass

        event = {
            'event': 'compact',
            'threads': thread_count,
            'off_count': off_count,
            'headroom_tier': headroom_tier,
        }
        if context_pct is not None:
            event['context_pct'] = context_pct
        if cr is not None:
            event['cache_ratio'] = cr

        _tel_mod.emit(buffer_dir, event)
    except Exception:
        pass  # Fail-silent: telemetry must never block compaction
```

- [ ] **Step 2: Run all tests**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd session-buffer
git add plugin/scripts/compact_hook.py
git commit -m "feat(telemetry): emit compact event in pre-compact hook"
```

### Task 5: Add telemetry session-end call to `/buffer:off`

**Files:**
- Modify: `plugin/skills/off/SKILL.md:381-392`

- [ ] **Step 1: Add telemetry session-end call after Step 13**

In `plugin/skills/off/SKILL.md`, within Step 13 — after the `.session_active` paragraph (line 392) and before Step 14, add:

```markdown

Emit session-end telemetry summary:
```bash
python plugin/scripts/telemetry.py session-end --buffer-dir .claude/buffer/
```
This logs a session summary (compaction count, warnings, peak context %) to `telemetry.jsonl`. Fail-silent — if it errors, proceed to Step 14.
```

- [ ] **Step 2: Commit**

```bash
cd session-buffer
git add plugin/skills/off/SKILL.md
git commit -m "feat(telemetry): add session-end emit to /buffer:off Step 13"
```

### Task 6: Version bump and changelog

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json:3`
- Modify: `plugin/skills/on/SKILL.md:419`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump version in `plugin.json`**

In `plugin/.claude-plugin/plugin.json`, change line 3:
```
  "version": "3.2.0",
```
→
```
  "version": "3.3.0",
```

- [ ] **Step 2: Update version string in `on/SKILL.md`**

In `plugin/skills/on/SKILL.md`, change line 419:
```
buffer v3.2.0 | [scope] mode | Alpha: N referents (if present) | W: [ratio]
```
→
```
buffer v3.3.0 | [scope] mode | Alpha: N referents (if present) | W: [ratio]
```

- [ ] **Step 3: Add CHANGELOG entry**

At the top of `CHANGELOG.md`, after line 3 (the `# Changelog` header and blank line), add:

```markdown
## [buffer 3.3.0] - 2026-03-14

### Added
- **Headroom check (Layer 2):** Context pressure tier detection (watch/warn/critical at 70/85/93%) with universal sigma hook injection on tier crossing
- **Statusline `ctx:XX%`:** Passive context pressure indicator for CLI users
- **Telemetry (Layer 3):** Append-only `telemetry.jsonl` with compact events, headroom warnings, and session-end summaries
- **`telemetry.py`:** Shared utility with `emit()`, `tier_from_percentage()`, `cache_ratio()`, and `session-end` CLI subcommand

```

- [ ] **Step 4: Commit**

```bash
cd session-buffer
git add plugin/.claude-plugin/plugin.json plugin/skills/on/SKILL.md CHANGELOG.md
git commit -m "chore: bump buffer to v3.3.0 — headroom check + telemetry"
```

- [ ] **Step 5: Run full test suite**

Run: `cd session-buffer && python -m pytest tests/ -v`
Expected: All tests pass (existing + new telemetry + headroom tests)
