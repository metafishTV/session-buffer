#!/usr/bin/env python3
"""distill_skill_gate.py — PreToolUse hook for Skill tool.

Writes a content-validated .distill_active marker when any distill:* skill
is invoked via the Skill tool. The marker contains SKILL_INVOKED:{timestamp}
which downstream Write/Edit hooks validate before allowing writes to
distilled/*.md or interpretations/*.md.

This hook NEVER blocks — it only writes the marker as a side effect.
If the project is not initialized (no SKILL.md), no marker is written
(first_run_gate.py handles blocking).

Input (stdin):  {"tool_name": "Skill", "tool_params": {"skill": "..."}, "cwd": "..."}
Output (stdout): {} (always allow)
"""

import sys
import io
import json
import os
from datetime import datetime, timezone

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


def project_configured(root: str) -> bool:
    skill_path = os.path.join(root, '.claude', 'skills', 'distill', 'SKILL.md')
    config_path = os.path.join(root, '.claude', 'distill.config.yaml')
    return os.path.isfile(skill_path) or os.path.isfile(config_path)


def write_marker(path: str, content: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f"distill_skill_gate: marker write failed: {e}", file=sys.stderr)


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

    tool_name = data.get('tool_name', '')
    if tool_name != 'Skill':
        print(ALLOW)
        return

    skill = data.get('tool_params', {}).get('skill', '')

    if not skill.startswith('distill:') and skill != 'distill':
        print(ALLOW)
        return

    cwd = data.get('cwd', os.getcwd())
    root = find_project_root(cwd)
    if not root or not project_configured(root):
        print(ALLOW)
        return

    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    content = f'SKILL_INVOKED:{timestamp}'

    buffer_path = os.path.join(root, '.claude', 'buffer', '.distill_active')
    root_path = os.path.join(root, '.distill_active')

    if os.path.isdir(os.path.join(root, '.claude', 'buffer')):
        write_marker(buffer_path, content)
    write_marker(root_path, content)

    print(ALLOW)


if __name__ == '__main__':
    main()
