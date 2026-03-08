"""Tests for plugin/scripts/migrate_to_alpha.py — pure-function unit tests."""

import pytest

from migrate_to_alpha import (
    kebab,
    parse_source_prefix,
    prefix_to_folder,
    id_num,
    pad_id,
    normalize_cross_source,
    normalize_convergence_web,
    make_framework_md,
    make_cross_source_md,
    make_convergence_web_md,
    group_cross_source_by_source,
    group_convergence_web_by_thesis,
    build_index,
)


# ── String utilities ────────────────────────────────────────────────────────


class TestKebab:
    @pytest.mark.parametrize("input_str, expected", [
        ("Cross Source", "cross-source"),
        ("already-kebab", "already-kebab"),
        ("Under_Score", "under-score"),
        ("  spaced  out  ", "spaced-out"),
        ("MixedCase", "mixedcase"),
        ("D&G", "dg"),
        ("special!@#chars", "specialchars"),
        ("multi___under", "multi-under"),
    ])
    def test_kebab(self, input_str, expected):
        assert kebab(input_str) == expected


class TestParseSourcePrefix:
    @pytest.mark.parametrize("key, expected", [
        ("Sartre:totalization", "Sartre"),
        ("D&G:rhizome", "D&G"),
        ("Levinas:face", "Levinas"),
        ("bare_concept", None),
        ("", None),
        (None, None),
        ("Emery:sociotechnical:extra", "Emery"),
    ])
    def test_parse_source_prefix(self, key, expected):
        assert parse_source_prefix(key) == expected


class TestPrefixToFolder:
    @pytest.mark.parametrize("prefix, expected", [
        ("Sartre", "sartre-early"),
        ("Levinas", "levinas-early"),
        ("D&G", "dg-early"),
        ("DG", "dg-early"),
        ("Lizier", "lizier-early"),
        ("Turchin", "turchin-early"),
        ("R&B", "ruesch-bateson-early"),
        ("RB", "ruesch-bateson-early"),
        ("_forward_note", "_forward-notes"),
        ("Unificity", "unificity"),
        (None, "_mixed-early"),
        ("", "_mixed-early"),
    ])
    def test_known_prefixes(self, prefix, expected):
        assert prefix_to_folder(prefix) == expected

    def test_unknown_prefix_derives_kebab(self):
        result = prefix_to_folder("SomeNewSource")
        assert result == "somenewsource-early"


class TestIdNum:
    @pytest.mark.parametrize("entry_id, expected", [
        ("w:65", 65),
        ("cw:7", 7),
        ("w:0", 0),
        ("w:1234", 1234),
        ("bad", 0),
        ("w:abc", 0),
    ])
    def test_id_num(self, entry_id, expected):
        assert id_num(entry_id) == expected


class TestPadId:
    @pytest.mark.parametrize("entry_id, expected", [
        ("w:65", "w065"),
        ("cw:7", "cw007"),
        ("w:1234", "w1234"),
        ("w:1", "w001"),
        ("cw:99", "cw099"),
        ("w:abc", "wabc"),
    ])
    def test_pad_id(self, entry_id, expected):
        assert pad_id(entry_id) == expected


# ── Schema normalization ────────────────────────────────────────────────────


class TestNormalizeCrossSource:
    def test_standard_key_field(self):
        entry = {"id": "w:1", "key": "Sartre:totalization", "maps_to": "T", "ref": "CDR1 p.45"}
        norm = normalize_cross_source(entry)
        assert norm["key"] == "Sartre:totalization"
        assert norm["_origin"] == "key_field"
        assert norm["id"] == "w:1"
        assert norm["maps_to"] == "T"
        assert norm["ref"] == "CDR1 p.45"

    def test_source_field_variant(self):
        entry = {"id": "w:80", "source": "Easwaran:dharma", "maps_to": "A", "ref": "Gita ch.3"}
        norm = normalize_cross_source(entry)
        assert norm["key"] == "Easwaran:dharma"
        assert norm["_origin"] == "source_field"

    def test_forward_note_from_ref(self):
        entry = {"id": "w:100", "maps_to": "sigma_hook", "ref": "§5.12"}
        norm = normalize_cross_source(entry)
        assert norm["key"].startswith("_forward_note:")
        assert norm["_origin"] == "forward_note"

    def test_unattributed_fallback(self):
        entry = {"id": "w:200", "maps_to": "something", "ref": ""}
        norm = normalize_cross_source(entry)
        assert norm["key"] == "_forward_note:something"
        assert norm["_origin"] == "unattributed"

    def test_sartre_cdr2_ref_inferred(self):
        entry = {"id": "w:55", "maps_to": "envelopment", "ref": "Sartre_CritiqueDR2_1991_Envelopment p.10"}
        norm = normalize_cross_source(entry)
        assert norm["key"].startswith("Sartre_CDR2_Envelopment:")
        assert norm["_origin"] == "ref_inferred:sartre_CDR2"

    def test_suggest_field_preserved(self):
        entry = {"id": "w:3", "key": "D&G:rhizome", "maps_to": "S", "suggest": {"note": "check"}}
        norm = normalize_cross_source(entry)
        assert norm["suggest"] == {"note": "check"}

    def test_missing_suggest_is_none(self):
        entry = {"id": "w:4", "key": "Levinas:face", "maps_to": "A"}
        norm = normalize_cross_source(entry)
        assert norm["suggest"] is None


class TestNormalizeConvergenceWeb:
    def test_full_entry(self):
        entry = {
            "id": "cw:1",
            "thesis": {"ref": "CDR1", "label": "Sartre:totalization"},
            "athesis": {"ref": "Gita", "label": "Easwaran:dharma"},
            "synthesis": "[bridge] TAP links",
            "metathesis": "dialectic unfolding",
        }
        norm = normalize_convergence_web(entry)
        assert norm["id"] == "cw:1"
        assert norm["thesis"]["ref"] == "CDR1"
        assert norm["athesis"]["label"] == "Easwaran:dharma"
        assert norm["synthesis"] == "[bridge] TAP links"
        assert norm["metathesis"] == "dialectic unfolding"

    def test_missing_fields_get_defaults(self):
        entry = {"id": "cw:2"}
        norm = normalize_convergence_web(entry)
        assert norm["thesis"]["ref"] == "?"
        assert norm["thesis"]["label"] == "?"
        assert norm["athesis"]["ref"] == "?"
        assert norm["athesis"]["label"] == "?"
        assert norm["synthesis"] == ""
        assert norm["metathesis"] == ""

    def test_partial_thesis_fills_missing(self):
        entry = {"id": "cw:3", "thesis": {"label": "Levinas:face"}}
        norm = normalize_convergence_web(entry)
        assert norm["thesis"]["label"] == "Levinas:face"
        assert norm["thesis"]["ref"] == "?"


# ── Markdown generators ─────────────────────────────────────────────────────


class TestMakeFrameworkMd:
    def test_basic_output(self):
        entries = [
            {"id": "f:1", "term": "TAPS", "base": "The core framework."},
            {"id": "f:2", "term": "RIP", "base": "Resonance-inhibition-praxis."},
        ]
        md = make_framework_md("foundational_triad", entries)
        assert "# Foundational Triad" in md
        assert "**Framework group**: foundational_triad" in md
        assert "## f:1 -- TAPS" in md
        assert "The core framework." in md
        assert "## f:2 -- RIP" in md

    def test_meta_entry(self):
        entries = [{"id": "m:1", "_meta": "Overview of the group."}]
        md = make_framework_md("dialectic", entries)
        assert "## m:1 -- [meta]" in md
        assert "Overview of the group." in md


class TestMakeCrossSourceMd:
    def test_with_source_label(self):
        entry = {"id": "w:44", "key": "Sartre:totalization", "maps_to": "T", "ref": "CDR1 p.45"}
        md = make_cross_source_md(entry, source_label="sartre-early")
        assert "# w:44 -- Sartre:totalization" in md
        assert "**Source**: sartre-early" in md
        assert "**Key**: Sartre:totalization" in md
        assert "**Maps to**: T" in md
        assert "**Ref**: CDR1 p.45" in md

    def test_without_source_label(self):
        entry = {"id": "w:10", "key": "Levinas:face", "maps_to": "A"}
        md = make_cross_source_md(entry)
        assert "**Source**:" not in md
        assert "**ID**: w:10 | **Type**: cross_source" in md

    def test_suggest_included_when_present(self):
        entry = {"id": "w:11", "key": "D&G:rhizome", "maps_to": "S", "suggest": "check mapping"}
        md = make_cross_source_md(entry)
        assert '**Suggest**: "check mapping"' in md

    def test_suggest_omitted_when_none(self):
        entry = {"id": "w:12", "key": "D&G:rhizome", "maps_to": "S", "suggest": None}
        md = make_cross_source_md(entry)
        assert "Suggest" not in md


class TestMakeConvergenceWebMd:
    def test_tetradic_structure(self):
        entry = {
            "id": "cw:1",
            "thesis": {"ref": "CDR1", "label": "Sartre:totalization"},
            "athesis": {"ref": "Gita", "label": "Easwaran:dharma"},
            "synthesis": "[bridge] TAP links",
            "metathesis": "dialectic unfolding",
        }
        md = make_convergence_web_md(entry)
        assert "# cw:1 -- Sartre:totalization x Easwaran:dharma" in md
        assert "**Type**: convergence_web" in md
        assert "## Tetradic Structure" in md
        assert "**Thesis**: CDR1 (Sartre:totalization)" in md
        assert "**Athesis**: Gita (Easwaran:dharma)" in md
        assert "**Synthesis**: [bridge] TAP links" in md
        assert "**Metathesis**: dialectic unfolding" in md

    def test_missing_labels_use_question_mark(self):
        entry = {"id": "cw:2", "thesis": {}, "athesis": {}}
        md = make_convergence_web_md(entry)
        assert "# cw:2 -- ? x ?" in md
        assert "**Thesis**: ? (?)" in md


# ── Grouping ────────────────────────────────────────────────────────────────


class TestGroupCrossSourceBySource:
    def test_groups_by_prefix(self):
        entries = [
            {"id": "w:1", "key": "Sartre:totalization", "maps_to": "T"},
            {"id": "w:2", "key": "Sartre:praxis", "maps_to": "P"},
            {"id": "w:3", "key": "Levinas:face", "maps_to": "A"},
        ]
        groups = group_cross_source_by_source(entries)
        assert "sartre-early" in groups
        assert "levinas-early" in groups
        assert len(groups["sartre-early"]) == 2
        assert len(groups["levinas-early"]) == 1

    def test_unkeyed_entries_go_to_forward_notes(self):
        entries = [
            {"id": "w:99", "maps_to": "sigma_hook", "ref": ""},
        ]
        groups = group_cross_source_by_source(entries)
        assert "_forward-notes" in groups


class TestGroupConvergenceWebByThesis:
    def test_groups_by_thesis_prefix(self):
        entries = [
            {"id": "cw:1", "thesis": {"label": "Sartre:tot", "ref": "CDR1"}, "athesis": {"label": "x", "ref": "y"}},
            {"id": "cw:2", "thesis": {"label": "Levinas:f", "ref": "TI"}, "athesis": {"label": "x", "ref": "y"}},
        ]
        groups = group_convergence_web_by_thesis(entries)
        assert "sartre-early" in groups
        assert "levinas-early" in groups

    def test_no_label_goes_to_mixed(self):
        entries = [
            {"id": "cw:5", "thesis": {"ref": "??"}, "athesis": {"ref": "??"}}
        ]
        groups = group_convergence_web_by_thesis(entries)
        assert "_mixed-early" in groups


# ── Index builder ────────────────────────────────────────────────────────────


class TestBuildIndex:
    def test_structure_and_counts(self, tmp_path):
        alpha_dir = str(tmp_path / "alpha")

        framework_entries = {
            "foundational_triad": [
                {"id": "f:1", "term": "TAPS"},
                {"id": "f:2", "term": "RIP"},
            ],
        }
        cs_groups = {
            "sartre-early": [
                {"id": "w:1", "key": "Sartre:totalization", "maps_to": "T"},
                {"id": "w:2", "key": "Sartre:praxis", "maps_to": "P"},
            ],
            "levinas-early": [
                {"id": "w:3", "key": "Levinas:face", "maps_to": "A"},
            ],
        }
        cw_groups = {
            "sartre-early": [
                {
                    "id": "cw:1",
                    "thesis": {"ref": "CDR1", "label": "Sartre:totalization"},
                    "athesis": {"ref": "Gita", "label": "Easwaran:dharma"},
                    "synthesis": "[bridge]",
                    "metathesis": "unfold",
                },
            ],
        }

        index = build_index(alpha_dir, framework_entries, cs_groups, cw_groups)

        # Top-level keys
        assert "schema_version" in index
        assert "summary" in index
        assert "sources" in index
        assert "entries" in index
        assert "concept_index" in index
        assert "source_index" in index

        # Summary counts
        assert index["summary"]["total_framework"] == 2
        assert index["summary"]["total_cross_source"] == 3
        assert index["summary"]["total_convergence_web"] == 1
        assert index["summary"]["total_sources"] == 2  # sartre-early, levinas-early

        # Framework entries in index
        assert "f:1" in index["entries"]
        assert index["entries"]["f:1"]["source"] == "_framework"
        assert index["entries"]["f:1"]["group"] == "foundational_triad"

        # Cross-source entries in index
        assert "w:1" in index["entries"]
        assert index["entries"]["w:1"]["source"] == "sartre-early"
        assert "w065" not in index["entries"]["w:1"]["file"]  # w:1 -> w001
        assert "w001.md" in index["entries"]["w:1"]["file"]

        # Convergence web entries in index
        assert "cw:1" in index["entries"]
        assert index["entries"]["cw:1"]["type"] == "convergence_web"
        assert "Sartre:totalization x Easwaran:dharma" in index["entries"]["cw:1"]["concept"]

        # concept_index populated
        assert "totalization" in index["concept_index"]
        assert "w:1" in index["concept_index"]["totalization"]

        # source_index populated
        assert "Sartre" in index["source_index"]
        assert "w:1" in index["source_index"]["Sartre"]
        assert "Levinas" in index["source_index"]

    def test_empty_inputs(self, tmp_path):
        alpha_dir = str(tmp_path / "alpha")
        index = build_index(alpha_dir, {}, {}, {})
        assert index["summary"]["total_framework"] == 0
        assert index["summary"]["total_cross_source"] == 0
        assert index["summary"]["total_convergence_web"] == 0
        assert index["summary"]["total_sources"] == 0
        assert index["entries"] == {}

    def test_source_with_both_cs_and_cw(self, tmp_path):
        """When a source folder has both cross_source and convergence_web entries."""
        alpha_dir = str(tmp_path / "alpha")
        cs_groups = {
            "sartre-early": [
                {"id": "w:10", "key": "Sartre:totalization", "maps_to": "T"},
            ],
        }
        cw_groups = {
            "sartre-early": [
                {
                    "id": "cw:5",
                    "thesis": {"ref": "CDR1", "label": "Sartre:t"},
                    "athesis": {"ref": "TI", "label": "Levinas:f"},
                },
            ],
        }
        index = build_index(alpha_dir, {}, cs_groups, cw_groups)
        src = index["sources"]["sartre-early"]
        assert "w:10" in src["cross_source_ids"]
        assert "cw:5" in src["convergence_web_ids"]
        assert src["entry_count"] == 2
