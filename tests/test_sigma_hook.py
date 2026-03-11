"""Tests for sigma_hook.py — pure-function unit tests.

Covers dynamic scalars, keyword extraction, word matching, IDF weighting,
hot/alpha matching, formatting, suppression, and source lookup.
"""

import pytest

from sigma_hook import (
    dynamic_max_keywords, dynamic_max_inject, dynamic_score_exact,
    dynamic_min_score, confidence_threshold, extract_keywords,
    word_match, compute_idf_weights, match_hot, match_alpha_concepts,
    find_source_for_id, format_hot_hits, format_alpha_hits, is_suppressed,
    compute_spread, record_prediction_error, _record_co_activation,
    record_grid_adjustment, update_continuous_scores,
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
