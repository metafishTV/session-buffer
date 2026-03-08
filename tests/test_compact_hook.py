"""Tests for compact_hook.py — layer-limit detection, compact summary builder, and pre-compact marker logic."""

import json
import os

import pytest

from compact_hook import (
    build_compact_summary,
    detect_layer_limits,
    find_buffer_dir,
    read_json,
    write_json,
)


# ---------------------------------------------------------------------------
# detect_layer_limits
# ---------------------------------------------------------------------------

class TestDetectLayerLimits:
    """Tests for detect_layer_limits()."""

    def test_defaults_when_no_config_files(self, tmp_path):
        """No config files at all -> returns hardcoded defaults (200, 500, 500)."""
        hot, warm, cold = detect_layer_limits(str(tmp_path))
        assert (hot, warm, cold) == (200, 500, 500)

    def test_skill_config_overrides_hot(self, tmp_path):
        """Skill config .claude/skills/buffer/on.md sets hot_max -> picked up."""
        skill_dir = tmp_path / '.claude' / 'skills' / 'buffer'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'on.md').write_text(
            "# Buffer Skill\nhot_max: 300\n", encoding='utf-8')

        hot, warm, cold = detect_layer_limits(str(tmp_path))
        assert hot == 300
        assert warm == 500  # unchanged
        assert cold == 500  # unchanged

    def test_local_md_overrides_skill_config(self, tmp_path):
        """buffer.local.md is read after skill config, so its values win."""
        # Skill config sets hot_max: 300
        skill_dir = tmp_path / '.claude' / 'skills' / 'buffer'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'on.md').write_text(
            "# Buffer Skill\nhot_max: 300\n", encoding='utf-8')

        # Local override sets hot_max: 400
        claude_dir = tmp_path / '.claude'
        (claude_dir / 'buffer.local.md').write_text(
            "# Local Config\nhot_max: 400\n", encoding='utf-8')

        hot, warm, cold = detect_layer_limits(str(tmp_path))
        assert hot == 400  # local wins over skill config

    def test_partial_override_leaves_other_defaults(self, tmp_path):
        """Only warm_max in local.md -> hot and cold stay at defaults."""
        claude_dir = tmp_path / '.claude'
        claude_dir.mkdir(parents=True)
        (claude_dir / 'buffer.local.md').write_text(
            "warm_max: 800\n", encoding='utf-8')

        hot, warm, cold = detect_layer_limits(str(tmp_path))
        assert hot == 200   # default
        assert warm == 800  # overridden
        assert cold == 500  # default

    def test_various_key_formats(self, tmp_path):
        """hot-max, hot_max, HOT_MAX all parse correctly via the regex."""
        claude_dir = tmp_path / '.claude'
        claude_dir.mkdir(parents=True)

        # Test hyphen form
        (claude_dir / 'buffer.local.md').write_text(
            "hot-max: 250\n", encoding='utf-8')
        hot, _, _ = detect_layer_limits(str(tmp_path))
        assert hot == 250

        # Test underscore form
        (claude_dir / 'buffer.local.md').write_text(
            "hot_max: 260\n", encoding='utf-8')
        hot, _, _ = detect_layer_limits(str(tmp_path))
        assert hot == 260

        # Test uppercase form
        (claude_dir / 'buffer.local.md').write_text(
            "HOT_MAX: 270\n", encoding='utf-8')
        hot, _, _ = detect_layer_limits(str(tmp_path))
        assert hot == 270

        # Test mixed-case with space separator
        (claude_dir / 'buffer.local.md').write_text(
            "Hot Max: 280\n", encoding='utf-8')
        hot, _, _ = detect_layer_limits(str(tmp_path))
        assert hot == 280


# ---------------------------------------------------------------------------
# build_compact_summary
# ---------------------------------------------------------------------------

class TestBuildCompactSummary:
    """Tests for build_compact_summary()."""

    def test_minimal_hot_contains_phase_and_summary(self, buffer_dir, hot_minimal):
        """Hot layer with natural_summary and active_work -> output has phase and summary."""
        result = build_compact_summary(hot_minimal, str(buffer_dir), 200, 500, 500)

        assert 'POST-COMPACTION SIGMA TRUNK RECOVERY' in result
        assert 'Testing phase' in result  # current_phase
        assert 'Setting up pytest suite' in result  # natural_summary
        assert 'lite' in result  # buffer_mode

    def test_with_alpha_bin(self, full_buffer_dir, hot_full):
        """buffer_dir containing alpha/index.json -> output mentions alpha refs."""
        result = build_compact_summary(hot_full, str(full_buffer_dir), 200, 500, 500)

        # Alpha index has 2 cross_source + 1 convergence_web + 0 framework = 3 refs, 1 source
        assert 'Alpha' in result
        assert '3 refs' in result
        assert '1 sources' in result

    def test_empty_hot_graceful(self, buffer_dir):
        """Empty dict for hot layer -> does not crash, produces valid output."""
        result = build_compact_summary({}, str(buffer_dir), 200, 500, 500)

        assert 'POST-COMPACTION SIGMA TRUNK RECOVERY' in result
        # Should still have layer sizes and consistency-check sections
        assert 'Layer Sizes' in result
        assert 'REQUIRED: Post-Compaction Consistency Check' in result

    def test_orientation_section(self, buffer_dir, hot_full):
        """Full hot layer with orientation -> output includes core_insight and warning."""
        result = build_compact_summary(hot_full, str(buffer_dir), 200, 500, 500)

        assert 'Orientation' in result
        assert 'Session memory plugin for Claude Code.' in result
        assert 'WARNING: Do NOT delete tower files without asking.' in result

    def test_layer_sizes_reflect_limits(self, buffer_dir, hot_minimal):
        """Layer sizes line uses the passed max values."""
        result = build_compact_summary(hot_minimal, str(buffer_dir), 350, 700, 900)

        assert '350' in result
        assert '700' in result
        assert '900' in result


# ---------------------------------------------------------------------------
# Pre-compact marker tests
# ---------------------------------------------------------------------------

class TestPreCompactMarker:
    """Integration tests for the pre-compact marker file written by cmd_pre_compact."""

    def test_pre_compact_saves_marker(self, buffer_dir, hot_minimal):
        """Calling cmd_pre_compact creates .compact_marker in buffer_dir."""
        from compact_hook import cmd_pre_compact

        hook_input = {'cwd': str(buffer_dir.parent.parent)}  # tmp_path

        # cmd_pre_compact calls sys.exit(0), so catch SystemExit
        with pytest.raises(SystemExit) as exc_info:
            cmd_pre_compact(hook_input)
        assert exc_info.value.code == 0

        marker = buffer_dir / '.compact_marker'
        assert marker.exists()

    def test_marker_contains_date_string(self, buffer_dir, hot_minimal):
        """The .compact_marker file content is today's date in ISO format."""
        from datetime import date as dt_date

        from compact_hook import cmd_pre_compact

        hook_input = {'cwd': str(buffer_dir.parent.parent)}

        with pytest.raises(SystemExit):
            cmd_pre_compact(hook_input)

        marker = buffer_dir / '.compact_marker'
        content = marker.read_text().strip()
        # Verify it is a valid ISO date string matching today
        assert content == dt_date.today().isoformat()
