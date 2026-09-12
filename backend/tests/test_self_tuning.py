"""Self-tuning unit tests."""
import pytest
from app.services.pm.self_tuning import BetaSuccessRate


class TestBetaSuccessRate:
    def test_initial_state(self):
        beta = BetaSuccessRate()
        assert beta.alpha == 1.0
        assert beta.beta == 1.0

    def test_update_success(self):
        beta = BetaSuccessRate()
        beta.update(True)
        assert beta.alpha == 2.0
        assert beta.beta == 1.0

    def test_update_failure(self):
        beta = BetaSuccessRate()
        beta.update(False)
        assert beta.alpha == 1.0
        assert beta.beta == 2.0

    def test_prob_below_high_success(self):
        # All successes -> prob below 0.5 should be very low
        beta = BetaSuccessRate()
        for _ in range(20):
            beta.update(True)
        prob = beta.prob_below(0.5)
        assert prob < 0.05  # Very unlikely that true rate < 0.5

    def test_prob_below_low_success(self):
        # All failures -> prob below 0.5 should be high
        beta = BetaSuccessRate()
        for _ in range(20):
            beta.update(False)
        prob = beta.prob_below(0.5)
        assert prob > 0.95

    def test_prob_below_mixed(self):
        # 50% success rate
        beta = BetaSuccessRate()
        for _ in range(10):
            beta.update(True)
        for _ in range(10):
            beta.update(False)
        prob = beta.prob_below(0.5)
        # With 50% success, prob that rate < 0.5 should be around 0.5
        assert 0.3 < prob < 0.7

    def test_prob_below_handles_exception(self):
        beta = BetaSuccessRate(alpha=0.0001, beta=0.0001)
        prob = beta.prob_below(0.5)
        assert isinstance(prob, float)
