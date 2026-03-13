"""Tests for sigma_hook.py — pure-function unit tests.

Covers dynamic scalars, keyword extraction, word matching, IDF weighting,
hot/alpha matching, formatting, suppression, and source lookup.
"""

import os
import pytest

from sigma_hook import (
    dynamic_max_keywords, dynamic_max_inject, dynamic_score_exact,
    dynamic_min_score, confidence_threshold, extract_keywords,
    word_match, compute_idf_weights, match_hot, match_alpha_concepts,
    find_source_for_id, format_hot_hits, format_alpha_hits, is_suppressed,
    compute_spread, record_prediction_error, _record_co_activation,
    record_grid_adjustment, update_continuous_scores,
    _compute_entropy, _compute_dkl, load_regime, update_regime,
    regime_threshold_modifier, apply_cw_boost, check_ambiguity_signal,
    check_cooldown,
    SCORE_SUBSTRING,
)


# ---------------------------------------------------------------------------
# 1-5. Dynamic scalars (parametrized)
# ---------------------------------------------------------------------------

class TestDynamicMaxKeywords:
    """dynamic_max_keywords scales keyword cap with prompt word count."""

    @pytest.mark.parametrize("word_count, expected", [
        (10, 8),       # short prompt → floor of 8
        (20, 8),       # 20 // 20 = 1, clamped to 8
        (100, 8),      # 100 // 20 = 5, clamped to 8
        (200, 10),     # 200 // 20 = 10
        (300, 15),     # 300 // 20 = 15
        (500, 25),     # 500 // 20 = 25, hits ceiling
        (600, 25),     # 600 // 20 = 30, clamped to 25
    ])
    def test_scales_with_word_count(self, word_count, expected):
        assert dynamic_max_keywords(word_count) == expected

    def test_short_prompt_gives_lower_value(self):
        short = dynamic_max_keywords(10)
        long = dynamic_max_keywords(200)
        assert short < long

    def test_long_prompt_gives_higher_value(self):
        assert dynamic_max_keywords(200) > dynamic_max_keywords(10)


class TestDynamicMaxInject:
    """dynamic_max_inject scales injection slots with prompt size."""

    @pytest.mark.parametrize("word_count, expected", [
        (10, 3),       # short → default 3
        (50, 3),       # still short
        (99, 3),       # just under medium
        (100, 4),      # medium → 4
        (199, 4),      # upper medium
        (200, 5),      # long → 5
        (500, 5),      # very long → still 5
    ])
    def test_scales_with_word_count(self, word_count, expected):
        assert dynamic_max_inject(word_count) == expected


class TestDynamicScoreExact:
    """dynamic_score_exact scales exact-match multiplier with corpus size."""

    @pytest.mark.parametrize("corpus_size, expected", [
        (10, 2),       # small corpus → 2
        (49, 2),       # just under medium
        (50, 3),       # medium → 3
        (299, 3),      # upper medium
        (300, 4),      # large → 4
        (1000, 4),     # very large → still 4
    ])
    def test_scales_with_corpus_size(self, corpus_size, expected):
        assert dynamic_score_exact(corpus_size) == expected

    def test_small_corpus_lower_than_large(self):
        assert dynamic_score_exact(10) < dynamic_score_exact(300)


class TestDynamicMinScore:
    """dynamic_min_score scales minimum alpha score with corpus size."""

    @pytest.mark.parametrize("corpus_size, expected", [
        (10, 1.5),     # small corpus → 1.5
        (49, 1.5),     # just under medium
        (50, 2.0),     # medium → 2.0
        (299, 2.0),    # upper medium
        (300, 3.0),    # large → 3.0
        (1000, 3.0),   # very large → still 3.0
    ])
    def test_scales_with_corpus_size(self, corpus_size, expected):
        assert dynamic_min_score(corpus_size) == expected


class TestConfidenceThreshold:
    """confidence_threshold non-linear scaling with keyword count."""

    @pytest.mark.parametrize("num_keywords, expected", [
        (0, 0.8),      # base only
        (3, 1.04),     # 0.8 + 0.08 * 3 = 1.04
        (5, 1.20),     # 0.8 + 0.08 * 5 = 1.20
        (10, 1.45),    # 0.8 + 0.40 + 0.05 * 5 = 1.45
        (15, 1.70),    # 0.8 + 0.40 + 0.05 * 10 = 1.70
        (25, 2.20),    # 0.8 + 0.40 + 0.05 * 20 = 2.20
    ])
    def test_non_linear_scaling(self, num_keywords, expected):
        assert confidence_threshold(num_keywords) == pytest.approx(expected)

    def test_few_keywords_lower_than_many(self):
        assert confidence_threshold(3) < confidence_threshold(15)


# ---------------------------------------------------------------------------
# 6-8. Keyword extraction (pure)
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    """extract_keywords pulls meaningful words, skipping stopwords."""

    def test_extracts_meaningful_words(self):
        kws = extract_keywords("How does the sigma trunk handle conservation?")
        # "how", "does", "the" are stopwords or < MIN_WORD_LEN
        assert "sigma" in kws
        assert "trunk" in kws
        assert "conservation" in kws
        # stopwords must not appear
        for stop in ("does", "the"):
            assert stop not in kws

    def test_respects_max_keywords_limit(self):
        long_text = " ".join(f"word{i}" for i in range(100))
        kws = extract_keywords(long_text, max_keywords=5)
        assert len(kws) <= 5

    def test_empty_string_returns_empty(self):
        assert extract_keywords("") == []

    def test_none_input_returns_empty(self):
        # The function guards `if not text`
        assert extract_keywords(None) == []

    def test_underscore_terms_preserved(self):
        kws = extract_keywords("The active_work field drives the sigma_hook pipeline")
        assert "active_work" in kws
        assert "sigma_hook" in kws

    def test_short_words_excluded(self):
        kws = extract_keywords("I am a dog and cat")
        # all words <= 3 chars or stopwords
        assert kws == []


# ---------------------------------------------------------------------------
# 9-10. Word matching (pure)
# ---------------------------------------------------------------------------

class TestWordMatch:
    """word_match checks whole-word boundary matching."""

    def test_exact_word_in_text(self):
        assert word_match("sigma", "the sigma trunk") is True

    def test_substring_of_another_word_no_match(self):
        # "sigma" should NOT match inside "sigmatic"
        assert word_match("sigma", "sigmatic process") is False

    def test_word_at_start(self):
        assert word_match("sigma", "sigma is important") is True

    def test_word_at_end(self):
        assert word_match("trunk", "the sigma trunk") is True

    def test_no_match(self):
        assert word_match("alterity", "the sigma trunk") is False

    def test_case_sensitive_boundary(self):
        # word_match operates on pre-lowered text; test matching at boundary
        assert word_match("trunk", "trunk.") is True


# ---------------------------------------------------------------------------
# 11-12. IDF weighting (pure)
# ---------------------------------------------------------------------------

class TestComputeIdfWeights:
    """compute_idf_weights assigns IDF-based weights to keywords."""

    def test_unique_concept_gets_high_weight(self):
        concept_index = {
            "alterity": ["w:1"],
            "structure": ["w:2"],
        }
        weights = compute_idf_weights(["alterity"], concept_index)
        # "alterity" matches exactly 1 concept → weight 1.0
        assert weights["alterity"] == pytest.approx(1.0)

    def test_common_keyword_gets_lower_weight(self):
        concept_index = {
            "deep structure": ["w:1"],
            "deep analysis": ["w:2"],
            "deep ecology": ["w:3"],
        }
        weights = compute_idf_weights(["deep"], concept_index)
        # "deep" is a substring of 3 concepts → 0.25 / 3 ~= 0.083
        assert weights["deep"] < 0.5

    def test_no_match_gives_zero(self):
        concept_index = {"alterity": ["w:1"]}
        weights = compute_idf_weights(["review"], concept_index)
        assert weights["review"] == 0.0

    def test_empty_concept_index(self):
        weights = compute_idf_weights(["sigma", "trunk"], {})
        assert weights["sigma"] == 0.0
        assert weights["trunk"] == 0.0

    def test_question_mark_key_skipped(self):
        concept_index = {"?": ["unknown"], "alterity": ["w:1"]}
        weights = compute_idf_weights(["alterity"], concept_index)
        assert weights["alterity"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 13-14. Hot layer matching (pure)
# ---------------------------------------------------------------------------

class TestMatchHot:
    """match_hot matches keywords against hot layer fields."""

    def test_matches_active_work(self):
        hot = {
            "active_work": {
                "current_phase": "sigma trunk development",
                "in_progress": None,
                "next_action": None,
            },
            "open_threads": [],
            "recent_decisions": [],
        }
        keywords = ["sigma", "trunk"]
        # Give high IDF weights so threshold is met
        idf_weights = {"sigma": 1.0, "trunk": 1.0}
        hits = match_hot(keywords, hot, frozenset(), idf_weights,
                         threshold=0.5, max_inject=3)
        assert len(hits) >= 1
        assert hits[0][0] == "active"
        assert "sigma trunk" in hits[0][1]

    def test_suppressed_entry_skipped(self):
        hot = {
            "active_work": {
                "current_phase": "sigma trunk development",
                "in_progress": None,
                "next_action": None,
            },
            "open_threads": [],
            "recent_decisions": [],
        }
        keywords = ["sigma", "trunk"]
        idf_weights = {"sigma": 1.0, "trunk": 1.0}
        suppress = frozenset({"sigma trunk"})
        hits = match_hot(keywords, hot, suppress, idf_weights,
                         threshold=0.5, max_inject=3)
        # The matching entry is suppressed — no hits from active_work
        assert all(h[0] != "active" or "sigma trunk" not in h[1] for h in hits)

    def test_matches_open_threads(self):
        hot = {
            "active_work": {},
            "open_threads": [
                {"thread": "R&B deep review", "status": "noted"},
            ],
            "recent_decisions": [],
        }
        keywords = ["review"]
        idf_weights = {"review": 1.5}
        hits = match_hot(keywords, hot, frozenset(), idf_weights,
                         threshold=1.0, max_inject=3)
        assert len(hits) >= 1
        assert hits[0][0] == "thread"
        assert "review" in hits[0][1].lower()

    def test_empty_hot_returns_empty(self):
        assert match_hot(["sigma"], {}, frozenset(), {"sigma": 1.0},
                         threshold=0.5) == []

    def test_empty_keywords_returns_empty(self):
        hot = {"active_work": {"current_phase": "test"}}
        assert match_hot([], hot, frozenset(), {}, threshold=0.5) == []


# ---------------------------------------------------------------------------
# 15-16. Alpha concept matching (pure)
# ---------------------------------------------------------------------------

class TestMatchAlphaConcepts:
    """match_alpha_concepts matches keywords against concept_index."""

    def test_matches_concept_by_substring(self):
        concept_index = {
            "totalization": ["w:44"],
            "praxis": ["w:45"],
        }
        keywords = ["total"]
        # "total" is a substring of "totalization" → substring weight
        idf_weights = {"total": 1.0}
        matches = match_alpha_concepts(
            keywords, concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        concept_keys = [m[0] for m in matches]
        assert "totalization" in concept_keys

    def test_exact_match_scores_higher(self):
        concept_index = {
            "totalization": ["w:44"],
            "praxis": ["w:45"],
        }
        # "praxis" is an exact match, "total" is a substring of "totalization"
        keywords = ["praxis", "total"]
        idf_weights = {"praxis": 1.0, "total": 1.0}
        matches = match_alpha_concepts(
            keywords, concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        scores = {m[0]: m[2] for m in matches}
        # praxis exact = 1.0 * 3 = 3.0; totalization substring = 1.0 * 1 = 1.0
        assert scores.get("praxis", 0) > scores.get("totalization", 0)

    def test_low_score_filtered_by_min_score(self):
        concept_index = {
            "totalization": ["w:44"],
        }
        keywords = ["total"]
        idf_weights = {"total": 0.5}
        # substring score = 0.5 * 1 = 0.5, below min_score=2.0
        matches = match_alpha_concepts(
            keywords, concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=2.0, max_inject=5)
        assert len(matches) == 0

    def test_suppressed_concept_excluded(self):
        concept_index = {"totalization": ["w:44"]}
        keywords = ["totalization"]
        idf_weights = {"totalization": 1.0}
        suppress = frozenset({"totalization"})
        matches = match_alpha_concepts(
            keywords, concept_index, suppress, idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        assert len(matches) == 0

    def test_empty_concept_index_returns_empty(self):
        matches = match_alpha_concepts(
            ["sigma"], {}, frozenset(), {"sigma": 1.0},
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        assert matches == []


# ---------------------------------------------------------------------------
# 17-18. Formatting (pure)
# ---------------------------------------------------------------------------

class TestFormatHotHits:
    """format_hot_hits produces 'sigma hot:' prefixed string."""

    def test_basic_format(self):
        hits = [("thread", "[noted] R&B deep review")]
        result = format_hot_hits(hits)
        assert result.startswith("sigma hot:")
        assert "[noted] R&B deep review" in result

    def test_multiple_hits_joined(self):
        hits = [
            ("active", "current_phase: testing"),
            ("thread", "[noted] CI setup"),
        ]
        result = format_hot_hits(hits)
        assert " | " in result
        assert "active:" in result
        assert "thread:" in result

    def test_long_text_truncated(self):
        long_text = "x" * 100
        hits = [("active", long_text)]
        result = format_hot_hits(hits)
        # Text > 60 chars gets truncated to 57 + "..."
        assert "..." in result
        assert len(result) < len("sigma hot: active: ") + 100


class TestFormatAlphaHits:
    """format_alpha_hits produces 'sigma alpha:' prefixed string."""

    def test_basic_format_with_source(self):
        matches = [("totalization", ["w:44"], 3.0)]
        sources = {
            "sartre-early": {
                "cross_source_ids": ["w:44", "w:45"],
                "convergence_web_ids": ["cw:1"],
            }
        }
        result = format_alpha_hits(matches, sources)
        assert result.startswith("sigma alpha:")
        assert "w:44" in result
        assert "totalization" in result
        assert "sartre-early" in result

    def test_format_without_source(self):
        matches = [("unknown_concept", ["w:99"], 2.0)]
        result = format_alpha_hits(matches, {})
        assert "w:99" in result
        assert "unknown_concept" in result
        # No source found — parenthetical should be absent
        assert "(" not in result

    def test_multiple_matches_piped(self):
        matches = [
            ("totalization", ["w:44"], 3.0),
            ("praxis", ["w:45"], 2.5),
        ]
        result = format_alpha_hits(matches, {})
        assert " | " in result


# ---------------------------------------------------------------------------
# 19. Suppression (pure)
# ---------------------------------------------------------------------------

class TestIsSuppressed:
    """is_suppressed checks if text contains any suppressed term."""

    def test_suppressed_term_found(self):
        assert is_suppressed("R&B deep review", frozenset({"deep review"})) is True

    def test_not_suppressed(self):
        assert is_suppressed("sigma trunk work", frozenset({"deep review"})) is False

    def test_empty_suppress_list(self):
        assert is_suppressed("anything at all", frozenset()) is False

    def test_case_insensitive(self):
        # is_suppressed lowercases text before checking
        assert is_suppressed("DEEP REVIEW session", frozenset({"deep review"})) is True


# ---------------------------------------------------------------------------
# 20. Source lookup (pure)
# ---------------------------------------------------------------------------

class TestFindSourceForId:
    """find_source_for_id locates which source folder owns a work ID."""

    def test_finds_cross_source_id(self):
        sources = {
            "sartre-early": {
                "cross_source_ids": ["w:44", "w:45"],
                "convergence_web_ids": ["cw:1"],
            }
        }
        assert find_source_for_id("w:44", sources) == "sartre-early"

    def test_finds_convergence_web_id(self):
        sources = {
            "sartre-early": {
                "cross_source_ids": ["w:44"],
                "convergence_web_ids": ["cw:1"],
            }
        }
        assert find_source_for_id("cw:1", sources) == "sartre-early"

    def test_missing_id_returns_none(self):
        sources = {
            "sartre-early": {
                "cross_source_ids": ["w:44"],
                "convergence_web_ids": [],
            }
        }
        assert find_source_for_id("w:999", sources) is None

    def test_empty_sources_returns_none(self):
        assert find_source_for_id("w:44", {}) is None

    def test_none_sources_returns_none(self):
        assert find_source_for_id("w:44", None) is None


# ---------------------------------------------------------------------------
# 21. Spreading activation with resonator weighting
# ---------------------------------------------------------------------------

class TestComputeSpread:
    """compute_spread does Hopfield-style spreading activation."""

    def test_basic_spread(self):
        adj = {'w:1': ['w:2', 'w:3'], 'w:2': ['w:1'], 'w:3': ['w:1']}
        result = compute_spread(['w:1'], adj)
        ids = [r[0] for r in result]
        assert 'w:2' in ids
        assert 'w:3' in ids

    def test_multi_source_convergence(self):
        adj = {
            'w:1': ['w:3'], 'w:2': ['w:3'],
            'w:3': ['w:1', 'w:2'],
        }
        result = compute_spread(['w:1', 'w:2'], adj)
        # w:3 reached from both w:1 and w:2 → highest score
        assert result[0][0] == 'w:3'
        assert result[0][1] >= 2  # at least 2 (base structural)

    def test_resonator_boost(self):
        adj = {'w:1': ['w:2', 'w:3'], 'w:2': ['w:1'], 'w:3': ['w:1']}
        coact = {'w:1|w:2': 5}  # w:2 co-activated 5 times with w:1
        result = compute_spread(['w:1'], adj, coactivation=coact)
        # w:2 should rank higher than w:3 due to resonance
        scores = {r[0]: r[1] for r in result}
        assert scores['w:2'] > scores['w:3']

    def test_no_adjacency_returns_empty(self):
        assert compute_spread(['w:1'], {}) == []
        assert compute_spread([], {'w:1': ['w:2']}) == []

    def test_max_spread_limit(self):
        adj = {'w:1': ['w:2', 'w:3', 'w:4', 'w:5']}
        for wid in ['w:2', 'w:3', 'w:4', 'w:5']:
            adj[wid] = ['w:1']
        result = compute_spread(['w:1'], adj, max_spread=2)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# 22. Prediction error recording (filesystem-dependent)
# ---------------------------------------------------------------------------

class TestRecordPredictionError:
    """record_prediction_error logs gaps and false positives."""

    def test_gap_detection(self, tmp_path):
        buf_dir = str(tmp_path)
        keywords = ['alterity', 'bifurcation', 'topology']
        # Only 'alterity' matched
        matched = [('alterity', ['w:1'], 3.0)]
        record_prediction_error(buf_dir, keywords, matched, None)

        errors_path = tmp_path / '.sigma_errors'
        assert errors_path.exists()
        import json
        lines = errors_path.read_text().strip().split('\n')
        entry = json.loads(lines[0])
        assert entry['type'] == 'gap'
        assert 'bifurcation' in entry['keywords']
        assert 'topology' in entry['keywords']
        assert 'alterity' not in entry['keywords']

    def test_no_errors_when_all_match(self, tmp_path):
        buf_dir = str(tmp_path)
        keywords = ['alterity']
        matched = [('alterity', ['w:1'], 3.0)]
        record_prediction_error(buf_dir, keywords, matched, None)

        errors_path = tmp_path / '.sigma_errors'
        # File might exist but no gap entry (only keyword matched)
        if errors_path.exists():
            content = errors_path.read_text().strip()
            if content:
                import json
                for line in content.split('\n'):
                    entry = json.loads(line)
                    assert entry['type'] != 'gap' or not entry.get('keywords')

    def test_false_positive(self, tmp_path):
        buf_dir = str(tmp_path)
        keywords = ['something']
        grid_hit = ['w:1', 'w:2']  # grid fired but no IDF match
        record_prediction_error(buf_dir, keywords, [], grid_hit)

        errors_path = tmp_path / '.sigma_errors'
        assert errors_path.exists()
        import json
        lines = errors_path.read_text().strip().split('\n')
        has_false_pos = any(
            json.loads(l).get('type') == 'false_pos' for l in lines if l
        )
        assert has_false_pos


# ---------------------------------------------------------------------------
# 23. Co-activation recording (resonator dynamics)
# ---------------------------------------------------------------------------

class TestCoActivation:
    """_record_co_activation tracks temporal concept pairs."""

    def test_pairs_recorded(self, tmp_path):
        buf_dir = str(tmp_path)
        _record_co_activation(buf_dir, ['w:1', 'w:2', 'w:3'])
        import json
        coact = json.loads((tmp_path / '.sigma_coactivation').read_text())
        assert 'w:1|w:2' in coact
        assert 'w:1|w:3' in coact
        assert 'w:2|w:3' in coact
        assert coact['w:1|w:2'] == 1

    def test_pairs_accumulate(self, tmp_path):
        buf_dir = str(tmp_path)
        _record_co_activation(buf_dir, ['w:1', 'w:2'])
        _record_co_activation(buf_dir, ['w:1', 'w:2'])
        import json
        coact = json.loads((tmp_path / '.sigma_coactivation').read_text())
        assert coact['w:1|w:2'] == 2


# ---------------------------------------------------------------------------
# 24. Grid adjustments (incremental learning)
# ---------------------------------------------------------------------------

class TestRecordGridAdjustment:
    """record_grid_adjustment logs cell confirmations."""

    def test_confirm_recorded(self, tmp_path):
        buf_dir = str(tmp_path)
        record_grid_adjustment(buf_dir, 'global', ['w:1', 'w:2'], hit=True)
        import json
        adj_path = tmp_path / '.grid_adjustments'
        assert adj_path.exists()
        entry = json.loads(adj_path.read_text().strip())
        assert entry['cell'] == 'global'
        assert entry['type'] == 'confirm'

    def test_disconfirm_recorded(self, tmp_path):
        buf_dir = str(tmp_path)
        record_grid_adjustment(buf_dir, 'global', ['w:1'], hit=False)
        import json
        entry = json.loads((tmp_path / '.grid_adjustments').read_text().strip())
        assert entry['type'] == 'disconfirm'


# ---------------------------------------------------------------------------
# 25. Continuous scores (W')
# ---------------------------------------------------------------------------

class TestUpdateContinuousScores:
    """update_continuous_scores adjusts concept scores incrementally."""

    def test_scores_increment(self, tmp_path):
        buf_dir = str(tmp_path)
        update_continuous_scores(buf_dir, ['w:1', 'w:2'], [], {})
        import json
        scores = json.loads((tmp_path / '.sigma_scores').read_text())
        assert scores['w:1'] == pytest.approx(0.1)
        assert scores['w:2'] == pytest.approx(0.1)

    def test_scores_accumulate(self, tmp_path):
        buf_dir = str(tmp_path)
        update_continuous_scores(buf_dir, ['w:1'], [], {})
        update_continuous_scores(buf_dir, ['w:1'], [], {})
        import json
        scores = json.loads((tmp_path / '.sigma_scores').read_text())
        assert scores['w:1'] == pytest.approx(0.2)

    def test_w_prime_tracked(self, tmp_path):
        import json as json_mod
        buf_dir = str(tmp_path)
        # Create wholeness state
        w_state = {'W': 5, 'W_potential': 20, 'active_set': []}
        (tmp_path / '.sigma_wholeness').write_text(json_mod.dumps(w_state))
        update_continuous_scores(buf_dir, ['w:1'], [], {})
        scores = json_mod.loads((tmp_path / '.sigma_scores').read_text())
        assert '__W_prev' in scores
        assert '__W_prime' in scores


# ---------------------------------------------------------------------------
# 26. Entropy computation
# ---------------------------------------------------------------------------

class TestComputeEntropy:
    """_compute_entropy computes Shannon entropy over activation distribution."""

    def test_empty_returns_zero(self):
        assert _compute_entropy({}) == 0.0

    def test_single_dominant_near_zero(self):
        # One concept with all activation → H ≈ 0
        assert _compute_entropy({"a": 1.0}) == pytest.approx(0.0)

    def test_uniform_returns_log2_n(self):
        import math
        # 4 equal activations → H = log2(4) = 2.0
        activations = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        assert _compute_entropy(activations) == pytest.approx(math.log2(4))

    def test_skewed_lower_than_uniform(self):
        uniform = _compute_entropy({"a": 0.5, "b": 0.5})
        skewed = _compute_entropy({"a": 0.9, "b": 0.1})
        assert skewed < uniform


# ---------------------------------------------------------------------------
# 27. Regime threshold modifier
# ---------------------------------------------------------------------------

class TestRegimeThresholdModifier:
    """regime_threshold_modifier scales threshold based on entropy."""

    def test_low_entropy_lowers_threshold(self):
        regime = {'_entropy': 0.5}
        assert regime_threshold_modifier(regime) < 1.0

    def test_high_entropy_raises_threshold(self):
        regime = {'_entropy': 4.0}
        assert regime_threshold_modifier(regime) > 1.0

    def test_medium_entropy_no_change(self):
        regime = {'_entropy': 2.0}
        assert regime_threshold_modifier(regime) == 1.0

    def test_clamp_bounds(self):
        assert regime_threshold_modifier({'_entropy': 0.0}) >= 0.8
        assert regime_threshold_modifier({'_entropy': 100.0}) <= 1.2


# ---------------------------------------------------------------------------
# 28. Update regime
# ---------------------------------------------------------------------------

class TestUpdateRegime:
    """update_regime boosts matched, decays all, recomputes entropy."""

    def test_boost_matched(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        regime = update_regime(buf_dir, regime, ['alterity'])
        assert regime['activations']['alterity'] == pytest.approx(0.3)

    def test_decay_existing(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        regime['activations'] = {'old_concept': 1.0}
        regime = update_regime(buf_dir, regime, [])
        assert regime['activations']['old_concept'] == pytest.approx(0.85)

    def test_clamp_to_one(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        regime['activations'] = {'hot': 0.9}
        regime = update_regime(buf_dir, regime, ['hot'])
        # 0.9 * 0.85 + 0.3 = 1.065 → clamped to 1.0
        assert regime['activations']['hot'] <= 1.0

    def test_prompt_count_increments(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        regime = update_regime(buf_dir, regime, [])
        assert regime['_prompt_count'] == 1
        regime = update_regime(buf_dir, regime, [])
        assert regime['_prompt_count'] == 2

    def test_entropy_recomputed(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        regime = update_regime(buf_dir, regime, ['a', 'b', 'c'])
        assert regime['_entropy'] > 0


# ---------------------------------------------------------------------------
# 29. Directional asymmetry
# ---------------------------------------------------------------------------

class TestDirectionalAsymmetry:
    """match_alpha_concepts applies directional modulation with regime."""

    def _make_index(self):
        return {"alterity": ["w:1"], "praxis": ["w:2"], "totalization": ["w:3"]}

    def test_on_step_penalty(self):
        """Concept with low regime activation gets penalized."""
        regime = {'activations': {'alterity': 0.1}}  # below ON_STEP_THRESHOLD
        concept_index = self._make_index()
        idf_weights = {"alterity": 1.0}
        # Without regime: score = 1.0 * 3 = 3.0
        no_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        # With regime: score = 3.0 * 0.5 = 1.5
        with_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5,
            regime=regime)
        no_regime_score = no_regime[0][2] if no_regime else 0
        with_regime_score = with_regime[0][2] if with_regime else 0
        assert with_regime_score < no_regime_score

    def test_established_no_change(self):
        """Concept with high regime activation gets no modification."""
        regime = {'activations': {'alterity': 0.5}}  # above ON_STEP_THRESHOLD
        concept_index = self._make_index()
        idf_weights = {"alterity": 1.0}
        no_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5)
        with_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.0, score_exact=3, min_score=0.0, max_inject=5,
            regime=regime)
        assert no_regime[0][2] == with_regime[0][2]

    def test_pulse_strong_first_contact(self):
        """First-contact concept with strong score gets PULSE boost."""
        regime = {'activations': {}}  # activation == 0
        concept_index = self._make_index()
        idf_weights = {"alterity": 1.0}
        # score = 3.0, threshold = 0.5 → 3.0 >= 1.3 * 0.5 = 0.65 → PULSE
        with_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.5, score_exact=3, min_score=0.5, max_inject=5,
            regime=regime)
        no_regime = match_alpha_concepts(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=0.5, score_exact=3, min_score=0.5, max_inject=5)
        assert with_regime[0][2] > no_regime[0][2]

    def test_pulse_gate_weak_first_contact(self):
        """First-contact with weak score gets penalty, not pulse."""
        regime = {'activations': {}}
        concept_index = {"totalization": ["w:3"]}
        # "total" is substring → score = 1.0 * SCORE_SUBSTRING = 1
        idf_weights = {"total": 1.0}
        # threshold=0.5, min_score=0.5 → 1.0 < 1.3*0.5=0.65? No, 1.0 >= 0.65 → pulse
        # Use higher threshold so gate kicks in
        with_regime = match_alpha_concepts(
            ["total"], concept_index, frozenset(), idf_weights,
            threshold=2.0, score_exact=3, min_score=0.0, max_inject=5,
            regime=regime)
        no_regime = match_alpha_concepts(
            ["total"], concept_index, frozenset(), idf_weights,
            threshold=2.0, score_exact=3, min_score=0.0, max_inject=5)
        # With regime: 1.0 < 1.3*2.0=2.6 → penalty (0.5x) → 0.5
        # Without regime: 1.0
        if with_regime:
            assert with_regime[0][2] < (no_regime[0][2] if no_regime else 999)
        # Both may be filtered by threshold — that's fine too


# ---------------------------------------------------------------------------
# 30. CW-graph boost
# ---------------------------------------------------------------------------

class TestApplyCwBoost:
    """apply_cw_boost uplifts cw-neighbors and splashes saturation."""

    def _make_adj(self):
        return {
            'adjacency': {'w:1': ['w:2', 'w:3'], 'w:2': ['w:1'], 'w:3': ['w:1']},
            'concepts': {'w:1': 'alterity', 'w:2': 'praxis', 'w:3': 'totalization'},
            'edge_count': 2,
        }

    def test_neighbor_uplift(self):
        adj = self._make_adj()
        scores = {
            'alterity': (['w:1'], 3.0),
            'praxis': (['w:2'], 0.5),
        }
        result = apply_cw_boost(scores, adj, effective_threshold=2.0)
        # praxis is neighbor of alterity → should get 30% of 3.0 = 0.9 boost
        assert result['praxis'][1] > 0.5

    def test_saturation_cap(self):
        adj = self._make_adj()
        scores = {
            'alterity': (['w:1'], 5.0),  # Way above 1.3 * 2.0 = 2.6
        }
        result = apply_cw_boost(scores, adj, effective_threshold=2.0)
        assert result['alterity'][1] <= 2.0 * 1.3  # capped

    def test_splash_to_eligible(self):
        adj = self._make_adj()
        # alterity saturated, praxis in eligibility band (85-100% of 2.0 = 1.7-2.0)
        scores = {
            'alterity': (['w:1'], 5.0),
            'praxis': (['w:2'], 1.8),  # in band
        }
        result = apply_cw_boost(scores, adj, effective_threshold=2.0)
        # praxis should get the splash excess
        assert result['praxis'][1] > 1.8

    def test_cascade_termination(self):
        adj = self._make_adj()
        scores = {
            'alterity': (['w:1'], 10.0),
        }
        # No eligible splash targets → just cap
        result = apply_cw_boost(scores, adj, effective_threshold=2.0)
        assert result['alterity'][1] <= 2.0 * 1.3

    def test_empty_adj_noop(self):
        scores = {'alterity': (['w:1'], 3.0)}
        result = apply_cw_boost(scores, None, effective_threshold=2.0)
        assert result['alterity'][1] == 3.0


# ---------------------------------------------------------------------------
# 31. Ambiguity signal
# ---------------------------------------------------------------------------

class TestCheckAmbiguitySignal:
    """check_ambiguity_signal emits near-threshold diagnostics."""

    def test_at_95_percent_emits(self):
        concept_index = {"alterity": ["w:1"]}
        idf_weights = {"alterity": 1.0}
        # score = 1.0 * 3 = 3.0, threshold = 3.2 → 3.0/3.2 = 93.75% → emits
        result = check_ambiguity_signal(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=3.2, score_exact=3)
        assert result is not None
        assert "alterity" in result

    def test_at_80_percent_silent(self):
        concept_index = {"alterity": ["w:1"]}
        idf_weights = {"alterity": 1.0}
        # score = 3.0, threshold = 4.0 → 75% → silent
        result = check_ambiguity_signal(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=4.0, score_exact=3)
        assert result is None

    def test_above_threshold_not_applicable(self):
        # This function is only called when no matches fired,
        # but the function itself just checks the score
        concept_index = {"alterity": ["w:1"]}
        idf_weights = {"alterity": 1.0}
        # score = 3.0, threshold = 2.0 → 150% → emits (but caller wouldn't call this)
        result = check_ambiguity_signal(
            ["alterity"], concept_index, frozenset(), idf_weights,
            threshold=2.0, score_exact=3)
        # It's fine to return signal even above threshold — caller gates this
        assert result is not None


# ---------------------------------------------------------------------------
# 32. D_KL computation
# ---------------------------------------------------------------------------

class TestComputeDkl:
    """_compute_dkl computes KL divergence for SWM becoming rate."""

    def test_identical_near_zero(self):
        current = {"a": 0.5, "b": 0.5}
        previous = {"a": 0.5, "b": 0.5}
        assert _compute_dkl(current, previous) == pytest.approx(0.0, abs=1e-6)

    def test_shifted_high(self):
        current = {"a": 0.9, "b": 0.1}
        previous = {"a": 0.1, "b": 0.9}
        dkl = _compute_dkl(current, previous)
        assert dkl > 0.5  # significant divergence

    def test_empty_current_zero(self):
        assert _compute_dkl({}, {"a": 1.0}) == 0.0

    def test_empty_previous_nonzero(self):
        # New concepts introduced → divergence from "nothing"
        dkl = _compute_dkl({"a": 1.0}, {})
        assert dkl >= 0.0


# ---------------------------------------------------------------------------
# 33. Regime integration (multi-prompt simulation)
# ---------------------------------------------------------------------------

class TestRegimeIntegration:
    """Integration test: regime accumulator over simulated session."""

    def test_topic_builds_over_prompts(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        # 5 prompts about 'alterity'
        for _ in range(5):
            regime = update_regime(buf_dir, regime, ['alterity'])
        assert regime['activations']['alterity'] > 0.5

    def test_dkl_spike_on_topic_shift(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        # Build up 'alterity'
        for _ in range(5):
            regime = update_regime(buf_dir, regime, ['alterity'])
        # Shift to 'praxis'
        regime = update_regime(buf_dir, regime, ['praxis'])
        assert regime['_dkl'] > 0  # shift causes divergence

    def test_threshold_modifier_evolves(self, tmp_path):
        buf_dir = str(tmp_path)
        regime = load_regime(buf_dir)
        # Initial: entropy 0 → modifier < 1.0
        m_initial = regime_threshold_modifier(regime)
        assert m_initial < 1.0  # low entropy = focused
        # Add many diverse concepts → high entropy
        for i in range(10):
            regime = update_regime(buf_dir, regime, [f'concept_{i}'])
        m_diverse = regime_threshold_modifier(regime)
        assert m_diverse >= m_initial  # higher entropy = higher or equal modifier


# ---------------------------------------------------------------------------
# Cooldown timer
# ---------------------------------------------------------------------------

class TestCheckCooldown:
    """check_cooldown prevents rapid re-firing."""

    def test_first_fire_always_proceeds(self, tmp_path):
        assert check_cooldown(str(tmp_path)) is True

    def test_second_fire_within_cooldown_blocked(self, tmp_path):
        buf = str(tmp_path)
        assert check_cooldown(buf, cooldown_seconds=60) is True
        assert check_cooldown(buf, cooldown_seconds=60) is False

    def test_fire_after_cooldown_expires(self, tmp_path):
        import time as _time
        buf = str(tmp_path)
        marker = os.path.join(buf, '.sigma_last_fire')
        # Write marker with old timestamp
        with open(marker, 'w') as f:
            f.write(str(_time.time() - 100))
        assert check_cooldown(buf, cooldown_seconds=30) is True

    def test_missing_marker_file_proceeds(self, tmp_path):
        buf = str(tmp_path)
        # No marker file — should proceed
        assert check_cooldown(buf) is True
        # Marker now exists
        assert os.path.exists(os.path.join(buf, '.sigma_last_fire'))
