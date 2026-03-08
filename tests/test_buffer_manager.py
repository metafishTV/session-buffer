"""Comprehensive pytest suite for buffer_manager.py.

Covers:
  Tier 1 — Pure function unit tests (no filesystem)
  Tier 2 — Filesystem integration tests (tmp_path / fixtures)
  Tier 3 — End-to-end pipeline tests
"""

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from buffer_manager import (
    is_full_mode, is_active_mode, resolve_scope, count_json_lines,
    next_id_in_entries, collect_all_entries, resolve_see_refs,
    _parse_concept_key, pad_id, format_section, _parse_limits_from_file,
    detect_layer_limits, resolve_limits, read_json, write_json,
    cmd_read, cmd_update, cmd_migrate, cmd_validate, cmd_next_id,
    cmd_alpha_read, cmd_alpha_query, cmd_alpha_write, cmd_alpha_delete,
    cmd_alpha_validate, cmd_handoff, cmd_archive, cmd_sync,
    alpha_update_index, alpha_remove_from_index, alpha_max_id,
    make_cross_source_md, make_convergence_web_md,
    HOT_MAX_LINES, WARM_MAX_LINES_DEFAULT, COLD_MAX_LINES,
)


# =========================================================================
# Tier 1: Pure function unit tests
# =========================================================================

class TestIsFullMode:
    """is_full_mode: only 'project' and 'full' return True."""

    @pytest.mark.parametrize("mode,expected", [
        ("project", True),
        ("full", True),
        ("memory", False),
        ("lite", False),
        ("minimal", False),
        ("unknown", False),
    ])
    def test_modes(self, mode, expected):
        assert is_full_mode(mode) is expected


class TestIsActiveMode:
    """is_active_mode: everything except 'minimal' returns True."""

    @pytest.mark.parametrize("mode,expected", [
        ("project", True),
        ("memory", True),
        ("full", True),
        ("lite", True),
        ("unknown", True),
        ("minimal", False),
    ])
    def test_modes(self, mode, expected):
        assert is_active_mode(mode) is expected


class TestResolveScope:
    """resolve_scope: maps legacy buffer_mode to 'full' or 'lite'."""

    @pytest.mark.parametrize("mode,expected", [
        ("project", "full"),
        ("memory", "lite"),
        ("minimal", "lite"),
        ("full", "full"),
        ("lite", "lite"),
        ("garbage", "lite"),
    ])
    def test_scope(self, mode, expected):
        assert resolve_scope(mode) == expected


class TestCountJsonLines:
    """count_json_lines: counts lines in JSON serialization."""

    def test_empty_dict(self):
        assert count_json_lines({}) == 1

    def test_simple_dict(self):
        data = {"a": 1, "b": 2}
        expected = len(json.dumps(data, indent=2).split("\n"))
        assert count_json_lines(data) == expected

    def test_nested_dict(self):
        data = {"top": {"nested": [1, 2, 3]}}
        expected = len(json.dumps(data, indent=2).split("\n"))
        assert count_json_lines(data) == expected


class TestNextIdInEntries:
    """next_id_in_entries: finds the next sequential ID for a prefix."""

    def test_empty_list(self):
        assert next_id_in_entries([], "w:") == "w:1"

    def test_with_existing_ids(self):
        entries = [
            {"id": "w:3", "key": "a"},
            {"id": "w:7", "key": "b"},
        ]
        assert next_id_in_entries(entries, "w:") == "w:8"

    def test_non_dict_entries_ignored(self):
        entries = ["garbage", 42, {"id": "w:5"}]
        assert next_id_in_entries(entries, "w:") == "w:6"

    def test_cw_prefix(self):
        entries = [{"id": "cw:1"}, {"id": "cw:2"}]
        assert next_id_in_entries(entries, "cw:") == "cw:3"

    def test_no_matching_prefix(self):
        entries = [{"id": "c:10"}, {"id": "c:20"}]
        assert next_id_in_entries(entries, "w:") == "w:1"


class TestCollectAllEntries:
    """collect_all_entries: gathers entries from warm/cold by prefix."""

    def test_warm_prefix(self, warm_full):
        entries = collect_all_entries(warm_full, "w:")
        ids = {e.get("id") for e in entries}
        # concept_map core + cross_source + convergence_web entries + decisions_archive + validation_log
        assert "w:1" in ids
        assert "w:10" in ids
        assert "w:20" in ids
        assert "w:30" in ids

    def test_cold_prefix(self, cold_full):
        entries = collect_all_entries(cold_full, "c:")
        ids = {e.get("id") for e in entries}
        assert "c:1" in ids
        assert "c:2" in ids
        assert "c:10" in ids
        assert "c:20" in ids

    def test_cw_prefix(self, warm_full):
        entries = collect_all_entries(warm_full, "cw:")
        ids = {e.get("id") for e in entries}
        assert "cw:1" in ids
        assert "cw:2" in ids

    def test_empty_layer(self):
        assert collect_all_entries({}, "w:") == []


class TestResolveSeeRefs:
    """resolve_see_refs: resolve hot-layer 'see' pointers to warm/cold entries."""

    def test_basic_warm_resolution(self, hot_full, warm_full, cold_full):
        resolved = resolve_see_refs(hot_full, warm_full, cold_full)
        ids_resolved = {r["ref"] for r in resolved}
        assert "w:10" in ids_resolved
        # w:10 should resolve to warm
        for r in resolved:
            if r["ref"] == "w:10":
                assert r["source"] == "warm"
                assert r["entry"]["id"] == "w:10"

    def test_redirect_handling(self, hot_full, warm_full, cold_full):
        """When warm entry has migrated_to, follow redirect to cold."""
        warm = dict(warm_full)
        warm["concept_map"] = {
            "cross_source": [
                {"id": "w:10", "migrated_to": "c:1", "key": "old-entry"}
            ]
        }
        resolved = resolve_see_refs(hot_full, warm, cold_full)
        for r in resolved:
            if r["ref"] == "w:10":
                assert "cold (via redirect" in r["source"]
                assert r["entry"]["id"] == "c:1"

    def test_archived_to_detection(self):
        hot = {"recent_decisions": [{"see": ["c:99"]}]}
        warm = {}
        cold = {
            "archived_decisions": [
                {"id": "c:99", "archived_to": "tower-001", "was": "old decision"}
            ]
        }
        resolved = resolve_see_refs(hot, warm, cold)
        assert len(resolved) == 1
        assert "archived to tower-tower-001" in resolved[0]["source"]

    def test_not_found(self):
        hot = {"recent_decisions": [{"see": ["w:999"]}]}
        resolved = resolve_see_refs(hot, {}, {})
        assert len(resolved) == 1
        assert resolved[0]["source"] == "NOT FOUND"
        assert resolved[0]["entry"] is None


class TestParseConceptKey:
    """_parse_concept_key: splits 'Source:concept' into (concept, source)."""

    def test_sourced_concept(self):
        assert _parse_concept_key("Sartre:totalization") == ("totalization", "Sartre")

    def test_bare_concept(self):
        assert _parse_concept_key("bare_concept") == ("bare_concept", None)

    def test_question_mark(self):
        assert _parse_concept_key("?") == (None, None)

    def test_empty_string(self):
        assert _parse_concept_key("") == (None, None)

    def test_internal_prefix(self):
        name, source = _parse_concept_key("_internal:x")
        assert name == "x"
        assert source is None

    def test_none_input(self):
        assert _parse_concept_key(None) == (None, None)


class TestPadId:
    """pad_id: pads numeric part of IDs to 3 digits for filenames."""

    def test_w_prefix(self):
        assert pad_id("w:65") == "w065"

    def test_cw_prefix(self):
        assert pad_id("cw:7") == "cw007"

    def test_four_digits(self):
        assert pad_id("w:1234") == "w1234"

    def test_single_digit(self):
        assert pad_id("c:1") == "c001"


class TestFormatSection:
    """format_section: wraps content with section title."""

    def test_basic(self):
        result = format_section("Title", "body text")
        assert "--- Title ---" in result
        assert "body text" in result

    def test_multiline_content(self):
        result = format_section("Multi", "line1\nline2")
        assert "line1\nline2" in result


class TestParseLimitsFromFile:
    """_parse_limits_from_file: extracts hot/warm/cold limits from config."""

    def test_parse_limits(self, tmp_path):
        cfg = tmp_path / "config.md"
        cfg.write_text("hot_max: 250\nwarm_max: 800\ncold_max: 750\n",
                       encoding="utf-8")
        limits = {"hot": 200, "warm": 500, "cold": 500}
        _parse_limits_from_file(str(cfg), limits)
        assert limits["hot"] == 250
        assert limits["warm"] == 800
        assert limits["cold"] == 750

    def test_nonexistent_file(self, tmp_path):
        limits = {"hot": 200, "warm": 500, "cold": 500}
        _parse_limits_from_file(str(tmp_path / "nope.md"), limits)
        assert limits == {"hot": 200, "warm": 500, "cold": 500}

    def test_partial_limits(self, tmp_path):
        cfg = tmp_path / "partial.md"
        cfg.write_text("warm-max: 600\n", encoding="utf-8")
        limits = {"hot": 200, "warm": 500, "cold": 500}
        _parse_limits_from_file(str(cfg), limits)
        assert limits["warm"] == 600
        assert limits["hot"] == 200  # unchanged


class TestMakeCrossSourceMd:
    """make_cross_source_md: verify output contains key, maps_to, source label."""

    def test_basic_output(self):
        entry = {"id": "w:100", "key": "Sartre:totalization", "maps_to": "dialectical totality"}
        md = make_cross_source_md(entry, source_label="sartre-early")
        assert "w:100" in md
        assert "Sartre:totalization" in md
        assert "dialectical totality" in md
        assert "sartre-early" in md
        assert "cross_source" in md

    def test_without_source_label(self):
        entry = {"id": "w:50", "key": "test", "maps_to": "mapped"}
        md = make_cross_source_md(entry)
        assert "**Source**" not in md
        assert "**ID**: w:50 | **Type**: cross_source" in md


class TestMakeConvergenceWebMd:
    """make_convergence_web_md: verify output contains thesis/athesis/synthesis/metathesis."""

    def test_basic_output(self):
        entry = {
            "id": "cw:5",
            "thesis": {"ref": "w:1", "label": "sigma trunk"},
            "athesis": {"ref": "w:2", "label": "alpha bin"},
            "synthesis": "Working and reference memory cooperate",
            "metathesis": "Dual-process cognition",
        }
        md = make_convergence_web_md(entry)
        assert "cw:5" in md
        assert "sigma trunk" in md
        assert "alpha bin" in md
        assert "Working and reference memory cooperate" in md
        assert "Dual-process cognition" in md
        assert "convergence_web" in md


class TestAlphaUpdateAndRemoveIndex:
    """alpha_update_index / alpha_remove_from_index: add and remove from index."""

    def test_add_entry_to_empty_index(self):
        index = {}
        alpha_update_index(index, "w:100", "cross_source", "test-src",
                           "Sartre:praxis", "test-src/w100.md")
        assert "w:100" in index["entries"]
        assert index["entries"]["w:100"]["source"] == "test-src"
        assert "test-src" in index["sources"]
        assert "w:100" in index["sources"]["test-src"]["cross_source_ids"]
        assert "praxis" in index["concept_index"]
        assert "Sartre" in index["source_index"]
        assert index["summary"]["total_cross_source"] == 1

    def test_add_convergence_web_entry(self):
        index = {}
        alpha_update_index(index, "cw:10", "convergence_web", "test-src",
                           "thesis x athesis", "test-src/cw010.md")
        assert "cw:10" in index["entries"]
        assert "cw:10" in index["sources"]["test-src"]["convergence_web_ids"]
        assert index["summary"]["total_convergence_web"] == 1

    def test_remove_entry(self):
        index = {}
        alpha_update_index(index, "w:50", "cross_source", "src",
                           "Hegel:dialectic", "src/w050.md")
        removed = alpha_remove_from_index(index, "w:50")
        assert removed is not None
        assert "w:50" not in index.get("entries", {})
        # source folder should be removed if empty
        assert "src" not in index.get("sources", {})
        assert index["summary"]["total_cross_source"] == 0

    def test_remove_nonexistent_entry(self):
        index = {"entries": {}}
        removed = alpha_remove_from_index(index, "w:999")
        assert removed is None


class TestAlphaMaxId:
    """alpha_max_id: find max numeric ID in alpha index for a prefix."""

    def test_with_entries(self, alpha_index):
        assert alpha_max_id(alpha_index, "w:") == 45

    def test_cw_prefix(self, alpha_index):
        assert alpha_max_id(alpha_index, "cw:") == 1

    def test_empty_index(self):
        assert alpha_max_id({}, "w:") == 0
        assert alpha_max_id({"entries": {}}, "w:") == 0


# =========================================================================
# Tier 2: Filesystem integration tests
# =========================================================================

class TestReadWriteJson:
    """read_json / write_json: round-trip JSON through the filesystem."""

    def test_round_trip(self, tmp_path):
        p = tmp_path / "test.json"
        data = {"key": "value", "nested": [1, 2, 3]}
        write_json(str(p), data)
        loaded = read_json(str(p))
        assert loaded == data

    def test_read_nonexistent(self, tmp_path):
        result = read_json(str(tmp_path / "no_such_file.json"))
        assert result == {}

    def test_write_creates_parents(self, tmp_path):
        p = tmp_path / "a" / "b" / "c.json"
        write_json(str(p), {"x": 1})
        assert p.exists()
        assert read_json(str(p)) == {"x": 1}


class TestDetectLayerLimits:
    """detect_layer_limits: project-level config, local.md overrides skill config."""

    def test_defaults_when_no_config(self, tmp_path):
        limits = detect_layer_limits(str(tmp_path))
        assert limits["hot"] == HOT_MAX_LINES
        assert limits["warm"] == WARM_MAX_LINES_DEFAULT
        assert limits["cold"] == COLD_MAX_LINES

    def test_skill_config_applies(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "buffer"
        skill_dir.mkdir(parents=True)
        (skill_dir / "on.md").write_text(
            "hot_max: 300\nwarm_max: 700\n", encoding="utf-8")
        limits = detect_layer_limits(str(tmp_path))
        assert limits["hot"] == 300
        assert limits["warm"] == 700
        assert limits["cold"] == COLD_MAX_LINES  # not overridden

    def test_local_md_overrides_skill(self, tmp_path):
        # Set up skill config
        skill_dir = tmp_path / ".claude" / "skills" / "buffer"
        skill_dir.mkdir(parents=True)
        (skill_dir / "on.md").write_text(
            "hot_max: 300\nwarm_max: 700\n", encoding="utf-8")
        # Set up local override
        claude_dir = tmp_path / ".claude"
        (claude_dir / "buffer.local.md").write_text(
            "hot_max: 150\n", encoding="utf-8")
        limits = detect_layer_limits(str(tmp_path))
        assert limits["hot"] == 150     # local wins
        assert limits["warm"] == 700    # skill config still applies
        assert limits["cold"] == COLD_MAX_LINES


class TestResolveLimits:
    """resolve_limits: CLI flag > project config > defaults."""

    def test_defaults_only(self, tmp_path):
        buf = tmp_path / ".claude" / "buffer"
        buf.mkdir(parents=True)
        args = SimpleNamespace(buffer_dir=str(buf),
                               hot_max=None, warm_max=None, cold_max=None)
        h, w, c = resolve_limits(args)
        assert h == HOT_MAX_LINES
        assert w == WARM_MAX_LINES_DEFAULT
        assert c == COLD_MAX_LINES

    def test_cli_flags_override(self, tmp_path):
        buf = tmp_path / ".claude" / "buffer"
        buf.mkdir(parents=True)
        args = SimpleNamespace(buffer_dir=str(buf),
                               hot_max=100, warm_max=200, cold_max=300)
        h, w, c = resolve_limits(args)
        assert h == 100
        assert w == 200
        assert c == 300


class TestCmdRead:
    """cmd_read: parse layers, produce reconstruction on stdout."""

    def test_read_full_buffer(self, full_args, capsys):
        cmd_read(full_args)
        captured = capsys.readouterr()
        assert "BUFFER RECONSTRUCTION" in captured.out
        assert "Hot:" in captured.out
        assert "Warm:" in captured.out

    def test_read_empty_buffer_exits(self, tmp_path):
        buf = tmp_path / ".claude" / "buffer"
        buf.mkdir(parents=True)
        # handoff.json intentionally not created
        args = SimpleNamespace(buffer_dir=str(buf),
                               hot_max=None, warm_max=None, cold_max=None)
        with pytest.raises(SystemExit):
            cmd_read(args)


class TestCmdUpdate:
    """cmd_update: merge alpha stash into hot+warm layers."""

    def test_update_via_file_input(self, full_buffer_dir, capsys):
        stash = {
            "session_meta": {"date": "2026-03-09", "commit": "aaa1111", "branch": "main"},
            "natural_summary": "Test update via file input.",
        }
        stash_path = full_buffer_dir / "stash.json"
        stash_path.write_text(json.dumps(stash), encoding="utf-8")

        args = SimpleNamespace(buffer_dir=str(full_buffer_dir), input=str(stash_path))
        cmd_update(args)

        hot = read_json(str(full_buffer_dir / "handoff.json"))
        assert hot["session_meta"]["commit"] == "aaa1111"
        assert hot["natural_summary"] == "Test update via file input."

    def test_update_empty_input_exits(self, full_buffer_dir, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(buffer_dir=str(full_buffer_dir), input=str(empty))
        with pytest.raises(SystemExit):
            cmd_update(args)


class TestCmdMigrate:
    """cmd_migrate: conservation enforcement — move decisions when oversized."""

    def test_oversized_hot_triggers_migration(self, full_buffer_dir, capsys):
        hot_path = full_buffer_dir / "handoff.json"
        hot = read_json(str(hot_path))
        # Pad hot layer with many decisions to exceed HOT_MAX_LINES
        hot["recent_decisions"] = [
            {"what": f"decision-{i}", "chose": "x", "why": "test", "session": "2026-03-08"}
            for i in range(30)
        ]
        write_json(str(hot_path), hot)

        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            hot_max=10, warm_max=None, cold_max=None, dry_run=False)
        cmd_migrate(args)

        hot_after = read_json(str(hot_path))
        # Should keep only last 2
        assert len(hot_after.get("recent_decisions", [])) == 2

        warm_after = read_json(str(full_buffer_dir / "handoff-warm.json"))
        # Migrated 28 decisions to warm archive
        assert len(warm_after.get("decisions_archive", [])) >= 28

    def test_within_bounds_no_migration(self, full_buffer_dir, capsys):
        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            hot_max=9999, warm_max=9999, cold_max=9999, dry_run=False)
        cmd_migrate(args)
        captured = capsys.readouterr()
        assert "No migration needed" in captured.err


class TestCmdValidate:
    """cmd_validate: check layer sizes, schema, required fields."""

    def test_full_buffer_validates(self, full_args, capsys):
        cmd_validate(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        # Full buffer fixture should pass basic validation
        assert result["status"] in ("ok", "issues_found")

    def test_missing_hot_exits(self, tmp_path):
        buf = tmp_path / ".claude" / "buffer"
        buf.mkdir(parents=True)
        args = SimpleNamespace(buffer_dir=str(buf),
                               hot_max=None, warm_max=None, cold_max=None)
        with pytest.raises(SystemExit):
            cmd_validate(args)

    def test_missing_required_fields(self, buffer_dir, capsys):
        """Minimal fixture missing 'project' mode required fields."""
        hot_path = buffer_dir / "handoff.json"
        hot = read_json(str(hot_path))
        # Switch to project mode to trigger project-specific required fields
        hot["buffer_mode"] = "project"
        hot.pop("concept_map_digest", None)
        hot.pop("convergence_web_digest", None)
        write_json(str(hot_path), hot)

        args = SimpleNamespace(buffer_dir=str(buffer_dir),
                               hot_max=None, warm_max=None, cold_max=None)
        cmd_validate(args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "issues_found"
        assert any("concept_map_digest" in i for i in result["issues"])


class TestCmdNextId:
    """cmd_next_id: get next sequential ID for warm, cold, convergence."""

    def test_warm_next_id(self, full_args, capsys):
        full_args.layer = "warm"
        cmd_next_id(full_args)
        captured = capsys.readouterr()
        # warm entries go up to w:30 in fixture, alpha has w:45
        output = captured.out.strip()
        assert output.startswith("w:")
        num = int(output.split(":")[1])
        assert num > 30

    def test_cold_next_id(self, full_args, capsys):
        full_args.layer = "cold"
        cmd_next_id(full_args)
        captured = capsys.readouterr()
        output = captured.out.strip()
        assert output.startswith("c:")

    def test_convergence_next_id(self, full_args, capsys):
        full_args.layer = "convergence"
        cmd_next_id(full_args)
        captured = capsys.readouterr()
        output = captured.out.strip()
        assert output.startswith("cw:")


class TestCmdAlphaRead:
    """cmd_alpha_read: JSON output with summary stats."""

    def test_with_alpha(self, full_args, capsys):
        cmd_alpha_read(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"
        assert "summary" in result
        assert result["summary"]["total_cross_source"] == 2

    def test_without_alpha(self, minimal_args, capsys):
        cmd_alpha_read(minimal_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "absent"


class TestCmdAlphaQuery:
    """cmd_alpha_query: test --id, --source, --concept queries."""

    def test_query_by_id(self, full_args, capsys):
        full_args.id = ["w:44"]
        full_args.source = None
        full_args.concept = None
        cmd_alpha_query(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["count"] == 1
        assert result["results"][0]["id"] == "w:44"
        assert result["results"][0]["content"]  # file exists in fixture

    def test_query_by_source(self, full_args, capsys):
        full_args.id = None
        full_args.source = "sartre"
        full_args.concept = None
        cmd_alpha_query(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["count"] >= 2  # w:44, w:45 at minimum

    def test_query_by_concept(self, full_args, capsys):
        full_args.id = None
        full_args.source = None
        full_args.concept = "totalization"
        cmd_alpha_query(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["count"] >= 1
        ids = [r["id"] for r in result["results"]]
        assert "w:44" in ids

    def test_query_id_not_found(self, full_args, capsys):
        full_args.id = ["w:9999"]
        full_args.source = None
        full_args.concept = None
        cmd_alpha_query(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["results"][0]["status"] == "not_found"

    def test_no_alpha_bin(self, minimal_args, capsys):
        minimal_args.id = None
        minimal_args.source = None
        minimal_args.concept = None
        cmd_alpha_query(minimal_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "absent"


class TestCmdAlphaWrite:
    """cmd_alpha_write: pipe JSON to stdin, verify file created + index updated."""

    def test_write_cross_source(self, full_buffer_dir, capsys, monkeypatch):
        entry = {
            "type": "cross_source",
            "source_folder": "test-write",
            "key": "Test:write_entry",
            "maps_to": "pytest verification",
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(entry)))

        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            dry_run=False, id_override=None)
        cmd_alpha_write(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"
        assert len(result["entries_written"]) == 1

        written = result["entries_written"][0]
        assert written["type"] == "cross_source"
        # Verify file on disk
        md_path = full_buffer_dir / "alpha" / written["file"]
        assert md_path.exists()

        # Verify index updated
        idx = read_json(str(full_buffer_dir / "alpha" / "index.json"))
        assert written["id"] in idx["entries"]

    def test_write_convergence_web(self, full_buffer_dir, capsys, monkeypatch):
        entry = {
            "type": "convergence_web",
            "source_folder": "test-write",
            "thesis": {"ref": "w:44", "label": "totalization"},
            "athesis": {"ref": "w:45", "label": "praxis"},
            "synthesis": "unified action",
            "metathesis": "practical ontology",
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(entry)))

        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            dry_run=False, id_override=None)
        cmd_alpha_write(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"
        written = result["entries_written"][0]
        assert written["type"] == "convergence_web"
        assert written["id"].startswith("cw:")

    def test_write_no_alpha_exits(self, buffer_dir, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"type":"cross_source"}'))
        args = SimpleNamespace(
            buffer_dir=str(buffer_dir),
            dry_run=False, id_override=None)
        with pytest.raises(SystemExit):
            cmd_alpha_write(args)


class TestCmdAlphaDelete:
    """cmd_alpha_delete: remove entry, verify file removed + index cleaned."""

    def test_delete_existing_entry(self, full_buffer_dir, capsys):
        args = SimpleNamespace(buffer_dir=str(full_buffer_dir), id=["w:44"])
        cmd_alpha_delete(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "w:44" in result["deleted"]

        # Verify file removed
        assert not (full_buffer_dir / "alpha" / "sartre-early" / "w044.md").exists()

        # Verify index updated
        idx = read_json(str(full_buffer_dir / "alpha" / "index.json"))
        assert "w:44" not in idx.get("entries", {})

    def test_delete_nonexistent_entry(self, full_buffer_dir, capsys):
        args = SimpleNamespace(buffer_dir=str(full_buffer_dir), id=["w:9999"])
        cmd_alpha_delete(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "w:9999" in result["not_found"]
        assert result["deleted"] == []


class TestCmdAlphaValidate:
    """cmd_alpha_validate: integrity check on alpha bin."""

    def test_valid_alpha(self, full_args, capsys):
        cmd_alpha_validate(full_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "ok"

    def test_missing_file_detected(self, full_buffer_dir, capsys):
        # Remove a file that the index references
        (full_buffer_dir / "alpha" / "sartre-early" / "w044.md").unlink()

        args = SimpleNamespace(buffer_dir=str(full_buffer_dir))
        cmd_alpha_validate(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "issues_found"
        assert any("missing" in i.lower() or "Missing" in i for i in result["issues"])

    def test_no_alpha_returns_absent(self, minimal_args, capsys):
        cmd_alpha_validate(minimal_args)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["status"] == "absent"


class TestCmdArchive:
    """cmd_archive: cold->tower archival with --entry-ids."""

    def test_archive_specific_entries(self, full_buffer_dir, capsys):
        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            hot_max=None, warm_max=None, cold_max=None,
            force=True, entry_ids=["c:1", "c:2"])
        cmd_archive(args)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "archived" in result
        assert result["archived"]["entries_archived"] == 2

        # Verify tower file exists
        tower_files = list(full_buffer_dir.glob("handoff-tower-*.json"))
        assert len(tower_files) == 1
        tower = read_json(str(tower_files[0]))
        assert len(tower["entries"]) == 2

        # Verify tombstones in cold
        cold = read_json(str(full_buffer_dir / "handoff-cold.json"))
        for d in cold["archived_decisions"]:
            if d["id"] in ("c:1", "c:2"):
                assert "archived_to" in d

    def test_under_limit_exits(self, full_buffer_dir, capsys):
        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            hot_max=None, warm_max=None, cold_max=9999,
            force=False, entry_ids=None)
        with pytest.raises(SystemExit) as exc_info:
            cmd_archive(args)
        assert exc_info.value.code == 0


# =========================================================================
# Tier 3: End-to-end pipeline tests
# =========================================================================

class TestCmdHandoff:
    """cmd_handoff: full pipeline — update + migrate + sync."""

    def test_full_pipeline(self, full_buffer_dir, capsys):
        stash = {
            "session_meta": {
                "date": "2026-03-09",
                "commit": "e2e1234",
                "branch": "main",
                "files_modified": ["test_buffer_manager.py"],
                "tests": "50 passed, 0 failed",
            },
            "active_work": {
                "current_phase": "E2E pipeline test",
                "completed_this_session": ["wrote pipeline test"],
                "in_progress": None,
                "blocked_by": None,
                "next_action": "Review results",
            },
            "natural_summary": "End-to-end pipeline test for cmd_handoff.",
        }
        stash_path = full_buffer_dir / "pipeline_stash.json"
        stash_path.write_text(json.dumps(stash), encoding="utf-8")

        registry_path = full_buffer_dir.parent / "projects.json"
        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            input=str(stash_path),
            hot_max=None, warm_max=None, cold_max=None,
            memory_path=None,
            registry_path=str(registry_path),
            project_name="test-e2e",
        )
        cmd_handoff(args)

        # Verify hot updated
        hot = read_json(str(full_buffer_dir / "handoff.json"))
        assert hot["session_meta"]["commit"] == "e2e1234"
        assert hot["natural_summary"] == "End-to-end pipeline test for cmd_handoff."

        # Verify registry written
        reg = read_json(str(registry_path))
        assert "test-e2e" in reg["projects"]


class TestCmdSync:
    """cmd_sync: MEMORY.md + project registry."""

    def test_registry_updated(self, full_buffer_dir, capsys):
        registry_path = str(full_buffer_dir.parent / "test_registry.json")
        args = SimpleNamespace(
            buffer_dir=str(full_buffer_dir),
            memory_path=None,
            registry_path=registry_path,
            project_name="sync-test",
        )
        cmd_sync(args)

        reg = read_json(registry_path)
        assert "sync-test" in reg["projects"]
        assert reg["projects"]["sync-test"]["scope"] == "full"
