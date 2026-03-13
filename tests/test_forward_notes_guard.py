"""Tests for forward_notes_guard.py PreToolUse hook."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

GUARD_SCRIPT = Path(__file__).parent.parent / 'distill' / 'scripts' / 'forward_notes_guard.py'
PYTHON = sys.executable


def run_guard(tool_name: str, file_path: str, cwd: str = '') -> dict:
    """Run the guard script with simulated hook input, return parsed output."""
    stdin_data = json.dumps({
        'hook_event_name': 'PreToolUse',
        'tool_name': tool_name,
        'tool_params': {'file_path': file_path},
        'cwd': cwd,
    })
    result = subprocess.run(
        [PYTHON, str(GUARD_SCRIPT)],
        input=stdin_data, capture_output=True, text=True, timeout=10,
    )
    return json.loads(result.stdout.strip()) if result.stdout.strip() else {}


def test_allows_non_forward_notes():
    result = run_guard('Write', '/some/path/foo.md')
    assert result == {}


def test_allows_non_write_tool():
    result = run_guard('Bash', '/some/forward_notes.json')
    assert result == {}


def test_blocks_without_marker(tmp_path):
    fn = tmp_path / 'forward_notes.json'
    fn.write_text('{}', encoding='utf-8')
    result = run_guard('Write', str(fn))
    assert result.get('decision') == 'block'
    assert 'scan existing' in result.get('reason', '')


def test_allows_with_valid_marker(tmp_path):
    fn = tmp_path / 'forward_notes.json'
    fn.write_text('{}', encoding='utf-8')
    marker = tmp_path / '.fn_queried'
    marker.write_text(str(time.time()), encoding='utf-8')
    result = run_guard('Write', str(fn))
    assert result == {}


def test_blocks_stale_marker(tmp_path):
    fn = tmp_path / 'forward_notes.json'
    fn.write_text('{}', encoding='utf-8')
    marker = tmp_path / '.fn_queried'
    marker.write_text(str(time.time() - 10800), encoding='utf-8')  # 3 hours ago
    result = run_guard('Write', str(fn))
    assert result.get('decision') == 'block'


def test_allows_edit_tool_with_marker(tmp_path):
    fn = tmp_path / 'forward_notes.json'
    fn.write_text('{}', encoding='utf-8')
    marker = tmp_path / '.fn_queried'
    marker.write_text(str(time.time()), encoding='utf-8')
    result = run_guard('Edit', str(fn))
    assert result == {}


def test_fails_open_on_bad_json():
    """Malformed stdin should allow (fail open)."""
    result = subprocess.run(
        [PYTHON, str(GUARD_SCRIPT)],
        input='not json at all', capture_output=True, text=True, timeout=10,
    )
    output = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
    assert output == {}
