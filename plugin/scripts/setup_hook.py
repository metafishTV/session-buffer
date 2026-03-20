#!/usr/bin/env python3
"""
Session Buffer — Setup Hook (SessionStart)

Lightweight health check at session start. Non-blocking — reports
findings via stderr so they appear in the terminal regardless of
whether SessionStart honors systemMessage.

Checks:
  1. Stale handoff detection (>7 days since last session_meta.date)
  2. Orphaned .distill_active marker (>4 hours old, with grace window)
  3. Alpha index consistency (max ID in index vs max ID on disk, sampled)
  4. Managed rules deployment (.claude/rules/buffer-compact-protocol.md)

Timeout: 5 seconds (must be fast — blocks session start).
"""

import sys
import os
import io
import json
import time
from datetime import datetime

# Force UTF-8 on Windows
if sys.platform == 'win32' and __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except AttributeError:
        pass


def find_buffer_dir(start_path):
    """Find buffer dir via buffer_utils, with walk-up fallback."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'buffer_utils', os.path.join(script_dir, 'buffer_utils.py'))
        utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(utils)
        return utils.find_buffer_dir(start_path)
    except Exception:
        # Fallback: walk up looking for .claude/buffer/handoff.json
        current = os.path.abspath(start_path)
        while True:
            candidate = os.path.join(current, '.claude', 'buffer', 'handoff.json')
            if os.path.exists(candidate):
                return os.path.join(current, '.claude', 'buffer')
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent


def check_stale_handoff(buffer_dir):
    """Check if handoff.json is >7 days old."""
    hot_path = os.path.join(buffer_dir, 'handoff.json')
    try:
        with open(hot_path, 'r', encoding='utf-8-sig') as f:
            hot = json.load(f)
        last_date = hot.get('session_meta', {}).get('date', '')
        if not last_date:
            return None
        last = datetime.strptime(last_date, '%Y-%m-%d')
        age_seconds = (datetime.now() - last).total_seconds()
        age_days = age_seconds / 86400
        if age_days >= 7:
            return f"Handoff is {int(age_days)} days old (last: {last_date}). Consider running /buffer:on to refresh."
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def check_orphaned_distill_marker(buffer_dir):
    """Check for .distill_active marker >4 hours old.

    Uses a 10-minute grace window: markers younger than 10 minutes are
    never deleted, even if mtime appears stale (guards against race
    with a parallel session that just created the marker).
    """
    marker = os.path.join(buffer_dir, '.distill_active')
    try:
        if not os.path.exists(marker):
            return None
        mtime = os.path.getmtime(marker)
        age_hours = (time.time() - mtime) / 3600
        # Grace window: never delete markers younger than 10 minutes
        if age_hours < (10.0 / 60):
            return None
        if age_hours > 4:
            # Re-check mtime immediately before delete (narrow race window)
            current_mtime = os.path.getmtime(marker)
            if current_mtime == mtime:
                os.remove(marker)
                return f"Cleaned up orphaned .distill_active marker ({age_hours:.1f}h old). Distillation likely crashed."
    except OSError:
        pass
    return None


def check_alpha_consistency(buffer_dir):
    """Quick check: max alpha ID in index vs max ID on disk (sampled)."""
    alpha_dir = os.path.join(buffer_dir, 'alpha')
    if not os.path.isdir(alpha_dir):
        return None

    index_path = os.path.join(alpha_dir, 'index.json')
    try:
        with open(index_path, 'r', encoding='utf-8-sig') as f:
            index = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    # Max ID from entries dict
    entries = index.get('entries', {})
    max_index_id = 0
    for key in entries:
        try:
            if key.startswith('w:'):
                max_index_id = max(max_index_id, int(key[2:]))
        except (ValueError, IndexError):
            pass

    # Max ID from disk — sample last 20 by sorted filename, not full scan
    max_disk_id = 0
    try:
        w_files = [f for f in os.listdir(alpha_dir)
                   if f.startswith('w') and f.endswith('.md')]
        # Sort lexicographically and check only the tail (highest IDs)
        for fname in sorted(w_files)[-20:]:
            try:
                num = int(fname[1:].split('_')[0].split('.')[0])
                max_disk_id = max(max_disk_id, num)
            except (ValueError, IndexError):
                pass
    except OSError:
        return None

    if max_disk_id > max_index_id and (max_disk_id - max_index_id) > 5:
        return (f"Alpha index may be stale: disk has w:{max_disk_id} but "
                f"index max is w:{max_index_id}. Consider running alpha-reinforce.")

    return None


BUFFER_RULES_VERSION = "3.8.2"

BUFFER_RULES_CONTENT = """\
<!-- managed by buffer plugin v{version} — do not edit manually -->
# Buffer Plugin Rules

## Post-Compaction Protocol

After context compaction, the buffer plugin injects recovery context via the PostCompact hook.

1. The PostCompact hook output contains session state, active threads, and orientation. Trust it.
2. If a football is mentioned as in-flight, check `.claude/buffer/footballs/` for its payload.
3. If distillation was interrupted, the injection will say so. Resume from where indicated — do NOT re-extract.
4. Run `/buffer:on` only if the user requests it. Never autonomously.
5. Compaction directives at `.claude/buffer/compact-directives.md` list on-disk resources. Read specific files as needed — do not dump everything into context.

## User Interaction Gates

- Any step requiring user input MUST use `AskUserQuestion`. Do NOT substitute plain text questions, infer the answer from context, or skip the question because it seems obvious. Wait for the response before continuing.
- After calling `AskUserQuestion`, your turn ENDS. Do not continue, prefetch, or write "while we wait." The next step begins ONLY after the user responds.
- Do NOT infer user intent for mode selection. The user chooses — present the options and wait.

## Autonomy Boundaries

- NEVER invoke `/buffer:on` or `/buffer:off` autonomously. Only when the user types the slash command.
- Do NOT bypass buffer skill routing. The dispatcher skill loads the operational skill — do not read handoff files, search for buffer files, or use MEMORY.md to locate projects until the operational skill tells you to.
- Do NOT auto-load trunk data before user intent is established.
- Do NOT auto-resolve concepts. Surface the count; the user decides whether to resolve now or defer.
- Do NOT auto-modify inherited entries during consolidation. Present proposals via `AskUserQuestion` and wait. Never auto-modify framework entries without `NEEDS_USER_INPUT`.

## Data Integrity

- NEVER silently drop content during compression. If a field exceeds its limit, compress in place.
- Autosave can update the hot layer. Autosave CANNOT overflow it. Overflow = user decision.
- NEVER silently read tower files. If an entry resolves to a tombstone with `archived_to`, ask the user before retrieving. Tower files are sealed with user consent.
- Session handoff files are structured state — read with tools, do not guess their contents.
- Alpha bin entries are source-indexed. Use `alpha/index.json` to find entries by source, not by scanning filenames.

## Worker Sessions (Footballs)

- Standing orders from the planner are non-negotiable constraints, not suggestions. Internalize them before starting work.
- Use the full field proactively — every available skill, agent, and tool. Do not wait for the user to ask.
- Adopt `dialogue_style` silently. Match the conversational register without announcing it.

## Epistemic Conduct

- Be honest in instance notes. If something confused you, say so. If a mapping felt forced, flag it. The next instance benefits more from candor than from false confidence.
""".format(version=BUFFER_RULES_VERSION)


def ensure_managed_rules(project_root):
    """Deploy managed rules file to .claude/rules/ if needed.

    Idempotent: only writes if content changed or file missing.
    Fail-safe: skips silently on any error.
    """
    try:
        rules_dir = os.path.join(project_root, '.claude', 'rules')
        rules_path = os.path.join(rules_dir, 'buffer-compact-protocol.md')

        # Check if current content matches — skip if unchanged
        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                existing = f.read()
            if existing == BUFFER_RULES_CONTENT:
                return None
        except (FileNotFoundError, OSError):
            pass

        os.makedirs(rules_dir, exist_ok=True)
        with open(rules_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(BUFFER_RULES_CONTENT)
        return f"Deployed buffer rules to .claude/rules/buffer-compact-protocol.md (v{BUFFER_RULES_VERSION})"
    except OSError:
        return None


def main():
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    cwd = hook_input.get('cwd', os.getcwd())
    buffer_dir = find_buffer_dir(cwd)

    if not buffer_dir:
        print('{}')
        return

    # Derive project root from buffer_dir ({root}/.claude/buffer)
    project_root = os.path.dirname(os.path.dirname(buffer_dir))

    warnings = []

    # Deploy managed rules (before health checks — rules are more important)
    try:
        result = ensure_managed_rules(project_root)
        if result:
            print(result, file=sys.stderr)
    except Exception:
        pass

    for check in [check_stale_handoff, check_orphaned_distill_marker, check_alpha_consistency]:
        try:
            result = check(buffer_dir)
            if result:
                warnings.append(result)
        except Exception:
            pass  # Individual check failure is non-fatal

    if warnings:
        # Write to stderr (always visible in terminal) rather than
        # systemMessage (may not be honored at SessionStart)
        message = "Buffer health check:\n" + "\n".join(f"  - {w}" for w in warnings)
        print(message, file=sys.stderr)

    # Always output empty JSON — don't block session start
    print('{}')


if __name__ == '__main__':
    main()
