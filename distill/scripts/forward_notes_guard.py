#!/usr/bin/env python3
"""forward_notes_guard.py — PreToolUse hook for Write/Edit.

Blocks writes to forward_notes.json unless the LLM has first consulted
the registry via `distill_forward_notes.py template` (which creates a
.fn_queried marker with a 2-hour TTL).

Input (stdin):  {"tool_name": "Write"|"Edit", "tool_params": {"file_path": "..."}, ...}
Output (stdout): {} to allow, {"decision": "block", "reason": "..."} to block
"""

import sys
import io
import json
import os
import time

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

MARKER_TTL = 7200  # 2 hours, matches distill_forward_notes.py


def is_forward_notes(file_path: str) -> bool:
    return file_path.rstrip('/\\').endswith('forward_notes.json')


def marker_valid(file_path: str) -> bool:
    """Check .fn_queried marker next to the target forward_notes.json."""
    marker = os.path.join(os.path.dirname(file_path), '.fn_queried')
    if not os.path.exists(marker):
        return False
    try:
        with open(marker, 'r', encoding='utf-8') as f:
            ts = float(f.read().strip())
        return (time.time() - ts) < MARKER_TTL
    except (ValueError, OSError):
        return False


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print('{}')
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        print('{}')
        return

    tool_name = data.get('tool_name', '')
    if tool_name not in ('Write', 'Edit'):
        print('{}')
        return

    file_path = data.get('tool_params', {}).get('file_path', '')
    if not is_forward_notes(file_path):
        print('{}')
        return

    if marker_valid(file_path):
        print('{}')
        return

    reason = (
        "STOP \u2014 scan existing forward notes before writing.\n\n"
        "Run: python distill_forward_notes.py template --notes <path-to-forward_notes.json>\n\n"
        "This shows the current next_number and existing entries. "
        "The guard will allow your write after you've consulted the registry."
    )
    print(json.dumps({'decision': 'block', 'reason': reason}))


if __name__ == '__main__':
    main()
