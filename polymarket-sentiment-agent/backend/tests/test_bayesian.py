"""Math tests for the deterministic Bayesian log-odds update."""
from __future__ import annotations

import math

import pytest

from app.modules.intelligence import bayesian_update


def _expected(prior: float, lr: float) -> float:
    log_odds = math.log(prior / (1 - prior)) + math.log(lr)
    return 1 / (1 + math.exp(-log_odds))


def test_neutral_sentiment_is_identity():
    posterior, lr = bayesian_update(0.4, "neutral", 0.9)
    assert lr == 1.0
    assert posterior == pytest.approx(0.4, abs=1e-4)


def test_bullish_raises_posterior():
    posterior, _ = bayesian_update(0.5, "bullish", 0.7)
    assert posterior > 0.5


def test_bearish_lowers_posterior():
    posterior, _ = bayesian_update(0.5, "bearish", 0.7)
    assert posterior < 0.5


def test_bullish_lr_formula_and_cap():
    _, lr = bayesian_update(0.5, "bullish", 1.0)
    assert lr == pytest.approx(5.0)  # 1 + 4*conf caps at 5
    _, lr_half = bayesian_update(0.5, "bullish", 0.5)
    assert lr_half == pytest.approx(3.0)


def test_bearish_lr_is_reciprocal():
    _, lr = bayesian_update(0.5, "bearish", 1.0)
    assert lr == pytest.approx(1.0 / 5.0, abs=1e-4)


def test_exact_posterior_value_matches_log_odds_math():
    prior, conf = 0.62, 0.78
    posterior, lr = bayesian_update(prior, "bullish", conf)
    assert lr == pytest.approx(1.0 + 4.0 * conf, abs=1e-4)
    assert posterior == pytest.approx(_expected(prior, 1.0 + 4.0 * conf), abs=1e-4)


def test_extreme_priors_are_clamped_and_stay_in_bounds():
    for prior in (0.0, 1.0, -3.0, 42.0):
        posterior, _ = bayesian_update(prior, "bullish", 1.0)
        assert 0.0 < posterior < 1.0


def test_confidence_is_clamped():
    p_hi, lr_hi = bayesian_update(0.5, "bullish", 5.0)
    p_capped, lr_capped = bayesian_update(0.5, "bullish", 1.0)
    assert lr_hi == lr_capped
    assert p_hi == p_capped
    _, lr_neg = bayesian_update(0.5, "bullish", -1.0)
    assert lr_neg == pytest.approx(1.0)


def test_bull_bear_symmetry_in_odds_space():
    """A bullish update then an equal-confidence bearish update round-trips."""
    prior = 0.37
    up, _ = bayesian_update(prior, "bullish", 0.8)
    back, _ = bayesian_update(up, "bearish", 0.8)
    assert back == pytest.approx(prior, abs=1e-3)


def test_monotone_in_confidence():
    posteriors = [bayesian_update(0.5, "bullish", c)[0] for c in (0.1, 0.4, 0.7, 1.0)]
    assert posteriors == sorted(posteriors)
