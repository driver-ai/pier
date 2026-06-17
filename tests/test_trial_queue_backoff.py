from pier.models.job.config import RetryConfig
from pier.trial.queue import TrialQueue


def _queue() -> TrialQueue:
    return TrialQueue(
        n_concurrent=1,
        retry_config=RetryConfig(
            max_retries=4, wait_multiplier=2.0, min_wait_sec=5.0, max_wait_sec=120.0
        ),
    )


def test_backoff_base_is_capped_exponential():
    q = _queue()
    assert q._backoff_base(0) == 5.0
    assert q._backoff_base(1) == 10.0
    assert q._backoff_base(2) == 20.0
    assert q._backoff_base(10) == 120.0  # capped at max_wait_sec


def test_jitter_within_bounds():
    q = _queue()
    for attempt in range(6):
        base = q._backoff_base(attempt)
        for _ in range(100):
            d = q._calculate_backoff_delay(attempt)
            assert 0.0 <= d <= base


def test_jitter_desynchronizes():
    """Two draws at the same attempt should (almost surely) differ — proves jitter."""
    q = _queue()
    draws = {q._calculate_backoff_delay(3) for _ in range(20)}
    assert len(draws) > 1
