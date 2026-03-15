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


# ── pack — planner heavy ──────────────────────────────────────────────────────

def test_pack_heavy_planner_creates_football(planner_buffer_dir, capsys):
    thread = {"description": "Build foo", "current_task": "Write tests", "next_action": "Run pytest"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="heavy",
                                       thread=json.dumps(thread), alpha_refs='["w:152"]'))
    fp = planner_buffer_dir / "football.json"
    assert fp.exists()
    data = json.loads(fp.read_text())
    assert data["mode"] == "football"
    assert data["throw_count"] == 1
    assert data["thrown_by"] == "planner"
    assert data["state"] == "in_flight"
    assert data["planner_payload"]["context"]["dialogue_style"] == "Casual and collaborative."
    assert data["planner_payload"]["context"]["alpha_refs"] == ["w:152"]


def test_pack_lite_planner_omits_context(planner_buffer_dir, valid_football, capsys):
    thread = {"description": "Fix bug", "current_task": "Patch line 42", "next_action": "Run tests"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="lite", thread=json.dumps(thread)))
    data = json.loads(valid_football.read_text())
    assert "context" not in data["planner_payload"]
    assert data["state"] == "in_flight"
    assert data["throw_count"] == 2   # incremented from existing 1


def test_pack_increments_throw_count(planner_buffer_dir, valid_football, capsys):
    thread = {"description": "Next task", "current_task": "Do it", "next_action": "Done"}
    with patch.object(buffer_football, 'find_buffer_dir', return_value=planner_buffer_dir):
        buffer_football.cmd_pack(_args(side="planner", type="lite", thread=json.dumps(thread)))
    assert json.loads(valid_football.read_text())["throw_count"] == 2


# ── pack — worker ─────────────────────────────────────────────────────────────

def test_pack_heavy_worker_uses_micro(worker_buffer_dir, valid_football, capsys):
    # Both fixtures chain from buffer_dir (same tmp_path) — worker has micro, valid_football has football.json
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_pack(_args(side="worker", type="heavy"))
    data = json.loads(valid_football.read_text())
    assert data["thrown_by"] == "worker"
    assert data["state"] == "returned"
    assert data["worker_output"]["completed"] == ["Wrote tests"]


def test_pack_lite_worker_takes_args(worker_buffer_dir, valid_football, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_pack(_args(side="worker", type="lite",
                                       completed='["Wrote foo.py"]',
                                       changes='["Added cmd_foo"]',
                                       next_action="Run full suite"))
    data = json.loads(valid_football.read_text())
    assert data["worker_output"]["completed"] == ["Wrote foo.py"]
    assert data["worker_output"]["next_action"] == "Run full suite"


# ── unpack ────────────────────────────────────────────────────────────────────

def test_unpack_returns_football(valid_football, capsys):
    buffer_football.cmd_unpack(_args(football=str(valid_football)))
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "football"
    assert out["planner_payload"]["thread"]["description"] == "Implement the buffer football script"


# ── flag ──────────────────────────────────────────────────────────────────────

def test_flag_appends_to_micro(worker_buffer_dir, capsys):
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        buffer_football.cmd_flag(_args(
            type_flag="decision",
            content='{"what": "use digest", "chose": "digest", "why": "keeps trunk voice clean"}',
            rationale="Emerged during implementation"))
    micro = json.loads((worker_buffer_dir / "football-micro.json").read_text())
    assert len(micro["flagged_for_trunk"]) == 1
    assert micro["flagged_for_trunk"][0]["type"] == "decision"


def test_flag_accumulates_across_calls(worker_buffer_dir, capsys):
    """Flag called twice produces two entries — async mid-session use."""
    with patch.object(buffer_football, 'find_buffer_dir', return_value=worker_buffer_dir):
        for i in range(2):
            buffer_football.cmd_flag(_args(
                type_flag="alpha_entry",
                content=f'{{"key": "term_{i}", "definition": "def {i}"}}',
                rationale=f"Term {i} coined during work"))
    micro = json.loads((worker_buffer_dir / "football-micro.json").read_text())
    assert len(micro["flagged_for_trunk"]) == 2


# ── stale football detection ─────────────────────────────────────────────────

def test_stale_football_detection(buffer_dir, capsys):
    """Caught + 3 days old → stale flag in status output."""
    stale_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps({
        "schema_version": 1, "mode": "football", "state": "caught",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 1,
        "thrown_at": stale_date,
        "planner_payload": {"thread": {"description": "Old task", "current_task": "x", "next_action": "y"}},
        "worker_output": {}
    }))
    (buffer_dir / "handoff.json").write_text("{}")  # planner marker
    with patch.object(buffer_football, 'find_buffer_dir', return_value=buffer_dir):
        buffer_football.cmd_status(_args())
    out = json.loads(capsys.readouterr().out)
    assert out["football_state"] == "caught"
    assert out.get("stale") is True


def test_stale_football_fresh(buffer_dir, capsys):
    """Caught + <3 days → no stale flag."""
    fp = buffer_dir / "football.json"
    fp.write_text(json.dumps({
        "schema_version": 1, "mode": "football", "state": "caught",
        "throw_type": "heavy", "thrown_by": "planner", "throw_count": 1,
        "thrown_at": datetime.now().strftime("%Y-%m-%d"),
        "planner_payload": {"thread": {"description": "Fresh task", "current_task": "x", "next_action": "y"}},
        "worker_output": {}
    }))
    (buffer_dir / "handoff.json").write_text("{}")
    with patch.object(buffer_football, 'find_buffer_dir', return_value=buffer_dir):
        buffer_football.cmd_status(_args())
    out = json.loads(capsys.readouterr().out)
    assert out.get("stale", False) is False
