"""
Tests for backend/app.py pure-function utilities:
    - normalize_state
    - jitter
    - composite_from_scores

These functions are the deterministic core of the risk pipeline and have
no external dependencies — fastest tests in the suite.
"""
from __future__ import annotations

import app as gad_app

# ═══════════════ normalize_state ═════════════════════════════════════════════


class TestNormalizeState:
    def test_two_letter_code_passthrough(self):
        assert gad_app.normalize_state("TX") == "TX"

    def test_two_letter_code_lowercase_uppercased(self):
        assert gad_app.normalize_state("tx") == "TX"

    def test_full_state_name_resolves_to_code(self):
        assert gad_app.normalize_state("Texas") == "TX"
        assert gad_app.normalize_state("California") == "CA"
        assert gad_app.normalize_state("New York") == "NY"

    def test_empty_string_returns_empty(self):
        assert gad_app.normalize_state("") == ""

    def test_none_returns_empty(self):
        assert gad_app.normalize_state(None) == ""

    def test_unknown_returns_empty(self):
        assert gad_app.normalize_state("Atlantis") == ""

    def test_whitespace_is_stripped(self):
        assert gad_app.normalize_state("  Texas  ") == "TX"


# ═══════════════ jitter ═════════════════════════════════════════════════════


class TestJitter:
    def test_output_bounded_to_zero_ten(self):
        # Sweep a grid of lat/lon and scores; output must always stay in [0, 10].
        for lat in (-90, -33, 0, 27.95, 61.22, 90):
            for lon in (-180, -149.9, -82.45, 0, 100, 180):
                for score in (0, 1, 5, 9, 10):
                    out = gad_app.jitter(score, lat, lon)
                    assert 0 <= out <= 10, (lat, lon, score, out)

    def test_deterministic(self):
        # Same inputs → same output (reproducibility for caching).
        a = gad_app.jitter(7, 27.9506, -82.4572)
        b = gad_app.jitter(7, 27.9506, -82.4572)
        assert a == b

    def test_clamps_negative_inputs(self):
        # If a profile somehow had a -1, output should still be ≥ 0.
        out = gad_app.jitter(-5, 27.95, -82.45)
        assert out >= 0

    def test_clamps_above_ten_inputs(self):
        # Profile of 15 should still produce ≤ 10.
        out = gad_app.jitter(15, 27.95, -82.45)
        assert out <= 10


# ═══════════════ composite_from_scores ══════════════════════════════════════


class TestCompositeFromScores:
    def test_all_zeros_yields_zero(self):
        scores = {k: 0 for k in gad_app.RISK_CATEGORIES}
        assert gad_app.composite_from_scores(scores) == 0

    def test_all_tens_yields_one_hundred(self):
        scores = {k: 10 for k in gad_app.RISK_CATEGORIES}
        assert gad_app.composite_from_scores(scores) == 100

    def test_known_florida_profile(self):
        # FL profile: hurricane=9, tornado=4, flood=7, winter=0, heat=7,
        # seismic=0, wildfire=4. Weighted sum = 1.8+0.72+1.05+0+0.7+0+0.4 = 4.67.
        # composite = round(4.67 / 10 * 100) = 47.
        scores = {
            "hurricane": 9, "tornado": 4, "flood": 7, "winter": 0,
            "heat": 7, "seismic": 0, "wildfire": 4,
        }
        assert gad_app.composite_from_scores(scores) == 47

    def test_missing_keys_default_to_zero(self):
        # If the dict is missing a hazard, treat it as 0 (don't raise).
        scores = {"hurricane": 10}
        out = gad_app.composite_from_scores(scores)
        # Only hurricane (weight 0.20) contributes: 10*0.20/10 = 0.20 → 20.
        assert out == 20

    def test_output_always_in_range(self):
        # Even with an all-10s dict plus an extra unknown key, stay 0-100.
        scores = {k: 10 for k in gad_app.RISK_CATEGORIES}
        scores["meteor"] = 10  # ignored by the function
        out = gad_app.composite_from_scores(scores)
        assert 0 <= out <= 100


# ═══════════════ RISK_CATEGORIES sanity check ═══════════════════════════════


def test_risk_category_weights_sum_to_one():
    """Composite formula assumes weights sum to 1.0 (max possible = 10).
    If anyone edits weights, this guards the invariant."""
    total = sum(c["weight"] for c in gad_app.RISK_CATEGORIES.values())
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}, expected 1.0"
