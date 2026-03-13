"""Tests for distill_forward_notes.py template command."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add distill scripts to path
DISTILL_SCRIPTS = Path(__file__).parent.parent / 'distill' / 'scripts'
if str(DISTILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DISTILL_SCRIPTS))

from distill_forward_notes import cmd_template, touch_marker, marker_is_valid, MARKER_TTL_SECONDS


@pytest.fixture
def registry(tmp_path):
    """Create a minimal forward_notes.json."""
    notes_file = tmp_path / 'forward_notes.json'
    data = {
        "next_number": 85,
        "notes": {
            "5.70": {"source": "TestSource", "description": "First note", "status": "candidate", "date": "2026-03-01"},
            "5.71": {"source": "TestSource", "description": "Second note", "status": "accepted", "date": "2026-03-02"},
            "5.72": {"source": "OtherSource", "description": "Merged note", "status": "merged_into", "date": "2026-03-03"},
        }
    }
    notes_file.write_text(json.dumps(data), encoding='utf-8')
    return notes_file


def run_template(notes_path, capsys):
    args = SimpleNamespace(notes=str(notes_path))
    cmd_template(args)
    return capsys.readouterr().out


def test_template_next_number(registry, capsys):
    out = run_template(registry, capsys)
    assert 'next_number: 85' in out


def test_template_required_fields(registry, capsys):
    out = run_template(registry, capsys)
    # Parse the JSON template from output
    lines = out.split('\n')
    json_start = next(i for i, l in enumerate(lines) if l.strip().startswith('{'))
    json_end = next(i for i in range(len(lines) - 1, -1, -1) if lines[i].strip().startswith('}'))
    template = json.loads('\n'.join(lines[json_start:json_end + 1]))
    entry = template['5.85']
    assert 'source' in entry
    assert 'description' in entry
    assert 'status' in entry
    assert 'date' in entry


def test_template_status_candidate(registry, capsys):
    out = run_template(registry, capsys)
    lines = out.split('\n')
    json_start = next(i for i, l in enumerate(lines) if l.strip().startswith('{'))
    json_end = next(i for i in range(len(lines) - 1, -1, -1) if lines[i].strip().startswith('}'))
    template = json.loads('\n'.join(lines[json_start:json_end + 1]))
    assert template['5.85']['status'] == 'candidate'


def test_template_creates_marker(registry):
    args = SimpleNamespace(notes=str(registry))
    cmd_template(args)
    marker = registry.parent / '.fn_queried'
    assert marker.exists()


def test_template_reminder(registry, capsys):
    out = run_template(registry, capsys)
    assert 'check-new' in out


def test_marker_ttl_valid(tmp_path):
    notes_path = tmp_path / 'forward_notes.json'
    notes_path.write_text('{}', encoding='utf-8')
    touch_marker(notes_path)
    assert marker_is_valid(notes_path)


def test_marker_ttl_expired(tmp_path):
    notes_path = tmp_path / 'forward_notes.json'
    notes_path.write_text('{}', encoding='utf-8')
    marker = tmp_path / '.fn_queried'
    # Write a timestamp from 3 hours ago
    marker.write_text(str(time.time() - 10800), encoding='utf-8')
    assert not marker_is_valid(notes_path)


def test_marker_missing(tmp_path):
    notes_path = tmp_path / 'forward_notes.json'
    notes_path.write_text('{}', encoding='utf-8')
    assert not marker_is_valid(notes_path)
