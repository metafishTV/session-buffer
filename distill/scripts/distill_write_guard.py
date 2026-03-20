#!/usr/bin/env python3
"""distill_write_guard.py — PreToolUse hook for Write and Edit tools.

Blocks writes/edits to distilled/*.md and interpretations/*.md files
unless a valid .distill_active marker exists with SKILL_INVOKED: prefix.

The marker is created by distill_skill_gate.py when the Skill tool is
invoked with a distill:* skill.

Input (stdin):  {"tool_name": "Write"|"Edit", "tool_params": {"file_path": "..."}, "cwd": "..."}
Output (stdout): {} to allow, {"decision": "block", "reason": "..."} to block
"""

import sys
import io
import json
import os

if sys.platform == 'win32' and __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ALLOW = '{}'


def find_project_root(cwd: str):
    current = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(current, '.git')):
            return current
        if os.path.isdir(os.path.join(current, '.claude')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def is_guarded_path(file_path: str) -> bool:
    fp = file_path.replace('\\', '/')
    is_distill = 'distilled/' in fp and fp.endswith('.md') and '/raw/' not in fp
    is_interp = 'interpretations/' in fp and fp.endswith('.md')
    return is_distill or is_interp


def marker_is_valid(root: str) -> bool:
    paths = [
        os.path.join(root, '.claude', 'buffer', '.distill_active'),
        os.path.join(root, '.distill_active'),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content.startswith('SKILL_INVOKED:'):
                    return True
            except Exception:
                pass
    return False


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(ALLOW)
            return
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        print(ALLOW)
        return

    params = data.get('tool_params', data.get('tool_input', {}))
    file_path = params.get('file_path', '')

    if not file_path or not is_guarded_path(file_path):
        print(ALLOW)
        return

    cwd = data.get('cwd', os.getcwd())
    root = find_project_root(cwd)
    if not root:
        print(ALLOW)
        return

    if marker_is_valid(root):
        print(ALLOW)
        return

    reason = (
        "STOP: Writing distillation or interpretation files requires "
        "Skill tool invocation. Use /distill to start the pipeline.\n\n"
        "The .distill_active marker must contain SKILL_INVOKED: prefix, "
        "which is written automatically by the PreToolUse:Skill hook "
        "when any distill:* skill is invoked via the Skill tool."
    )
    print(json.dumps({'decision': 'block', 'reason': reason}))


if __name__ == '__main__':
    main()
