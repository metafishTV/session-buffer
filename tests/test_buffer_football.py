"""Tests for buffer_football.py — football lifecycle management."""
import json
import importlib.util
import os
import pytest
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# Load module via importlib (same pattern as test_buffer_utils.py)
_spec = importlib.util.spec_from_file_location(
    'buffer_football',
    os.path.join(os.path.dirname(__file__), '..', 'plugin', 'scripts', 'buffer_football.py'))
buffer_football = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buffer_football)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _args(**kwargs):
    """Build argparse Namespace with safe defaults."""
    defaults = dict(cwd=None, football=None, side=None, type=None,
                    thread=None, alpha_refs=None, completed=None,
                    changes=None, next_action=None,
                    type_flag=None, content=None, rationale=None)
    defaults.update(kwargs)
    return Namespace(**defaults)


@pytest.fixture
def buffer_dir(tmp_path):
    """Buffer dir with .git marker required by buffer_utils git guard."""
    d = tmp_path / ".claude" / "buffer"
    d.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    return d


@pytest.fixture
def planner_buffer_dir(buffer_dir):
    """Planner session: trunk hot layer present, no micro-hot-layer."""
    (buffer_dir / "handoff.json").write_text(json.dumps({
        "schema_version": 2, "layer": "hot",
        "orientation": {
            "core_insight": "sigma-TAP models PRAXIS via the L-matrix.",
            "practical_warning": "Do not impose ABM assumptions."
        },
        "instance_notes": {
            "from": "inst-1", "to": "inst-2",
            "dialogue_style": "Casual and collaborative.",
            "remarks": [], "open_questions": []
        },
        "recent_decisions": [],
        "active_work": {"current_phase": "planning", "completed_this_session": [],
                        "in_progress": None, "blocked_by": None,
                        "next_action": "Design football"},
        "open_threads": [], "natural_summary": "Planning session."
    }))
    return buffer_dir


@pytest.fixture
def worker_buffer_dir(buffer_dir):
    """Worker session: micro-hot-layer present, no trunk."""
    (buffer_dir / "football-micro.json").write_text(json.dumps({
        "session_date": "2026-03-14", "catch_count": 1, "throw_count": 1,
        "active_task": "Implement foo",
        "completed_tasks": ["Wrote tests"],
        "decisions_made": [], "flagged_for_trunk": []
    }))
    return buffer_dir


@pytest.fixture
def valid_football(buffer_dir):
    """A valid in_flight heavy football on disk."""
    data = {
        "schema_version": 1, "mode": "football", "state": "in_flight",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 1,
        "thrown_at": "2026-03-14",
        "planner_payload": {
            "thread": {
                "description": "Implement the buffer football script",
                "current_task": "Write status subcommand",
                "files_to_touch": ["plugin/scripts/buffer_football.py"],
                "next_action": "Run pytest tests/test_buffer_football.py"
            },
            "context": {
                "relevant_decisions": [], "alpha_refs": ["w:152"],
                "orientation_fragment": "sigma-TAP models PRAXIS via the L-matrix.",
                "dialogue_style": "Casual and collaborative."
            }
        },
        "worker_output": {}
    }
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps(data))
    return fp


# ── status tests ──────────────────────────────────────────────────────────────

def test_status_detects_planner(planner_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "planner"


def test_status_detects_worker(worker_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "worker"


def test_status_ambiguous(buffer_dir, capsys):
    (buffer_dir / "handoff.json").write_text("{}")
    (buffer_dir / "football-micro.json").write_text("{}")
    with patch.object(buffer_football, 'find_buffer_dir', return_value=buffer_dir):
        buffer_football.cmd_status(_args())
    assert json.loads(capsys.readouterr().out)["session_type"] == "ambiguous"


def test_status_includes_football_state(planner_buffer_dir, valid_football, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_status(_args())
    out = json.loads(capsys.readouterr().out)
    assert out["football_state"] == "in_flight"
    assert out["throw_type"] == "heavy"


# ── validate tests ────────────────────────────────────────────────────────────

def test_validate_passes_valid(valid_football, capsys):
    buffer_football.cmd_validate(_args(football=str(valid_football)))
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_validate_fails_missing_fields(buffer_dir, capsys):
    bad = buffer_dir / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "mode": "football"}))
    with pytest.raises(SystemExit):
        buffer_football.cmd_validate(_args(football=str(bad)))
    assert json.loads(capsys.readouterr().out)["valid"] is False


# ── archive tests ─────────────────────────────────────────────────────────────

def test_archive_names_correctly(valid_football, capsys):
    buffer_football.cmd_archive(_args(football=str(valid_football)))
    out = json.loads(capsys.readouterr().out)
    dest = Path(out["archived_to"])
    assert dest.exists()
    assert dest.name == "2026-03-14-implement-the-buffer-football-script.json"
    assert not valid_football.exists()


def test_archive_short_description(buffer_dir, capsys):
    """Fewer than 5 words: use all available words."""
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps({
        "schema_version": 1, "mode": "football", "state": "absorbed",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 2,
        "thrown_at": "2026-03-14",
        "planner_payload": {"thread": {"description": "Fix bug", "current_task": "x", "next_action": "y"}},
        "worker_output": {}
    }))
    buffer_football.cmd_archive(_args(football=str(fp)))
    dest = Path(json.loads(capsys.readouterr().out)["archived_to"])
    assert "fix-bug" in dest.name
