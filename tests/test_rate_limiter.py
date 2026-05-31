import time
from src.middleware.rate_limiter import RateLimiter


def _limiter(cooldown: float = 60.0) -> RateLimiter:
    return RateLimiter(cooldown_seconds=cooldown)


# ── is_allowed ────────────────────────────────────────────────────────────────

def test_allowed_before_any_trade():
    rl = _limiter()
    assert rl.is_allowed("C:EURUSD") is True


def test_blocked_immediately_after_trade():
    rl = _limiter(cooldown=60.0)
    rl.record_trade("C:EURUSD")
    assert rl.is_allowed("C:EURUSD") is False


def test_allowed_after_cooldown_expires():
    rl = _limiter(cooldown=0.1)    # 100 ms
    rl.record_trade("C:EURUSD")
    assert rl.is_allowed("C:EURUSD") is False
    time.sleep(0.2)                # 2× headroom for loaded CI
    assert rl.is_allowed("C:EURUSD") is True


def test_symbols_are_independent():
    rl = _limiter()
    rl.record_trade("C:EURUSD")
    # different symbol must not be affected
    assert rl.is_allowed("C:USDJPY") is True


# ── record_trade ──────────────────────────────────────────────────────────────

def test_record_trade_resets_cooldown():
    rl = _limiter(cooldown=0.05)
    rl.record_trade("C:EURUSD")
    time.sleep(0.06)           # cooldown expires
    rl.record_trade("C:EURUSD")  # record again — new cooldown starts
    assert rl.is_allowed("C:EURUSD") is False


# ── remaining_cooldown ────────────────────────────────────────────────────────

def test_remaining_cooldown_zero_before_any_trade():
    rl = _limiter()
    assert rl.remaining_cooldown("C:EURUSD") == 0.0


def test_remaining_cooldown_positive_right_after_trade():
    rl = _limiter(cooldown=60.0)
    rl.record_trade("C:EURUSD")
    remaining = rl.remaining_cooldown("C:EURUSD")
    assert 0.0 < remaining <= 60.0


def test_remaining_cooldown_approaches_zero():
    rl = _limiter(cooldown=0.1)
    rl.record_trade("C:EURUSD")
    time.sleep(0.05)
    remaining = rl.remaining_cooldown("C:EURUSD")
    assert 0.0 < remaining < 0.1


def test_remaining_cooldown_zero_after_expiry():
    rl = _limiter(cooldown=0.05)
    rl.record_trade("C:EURUSD")
    time.sleep(0.06)
    assert rl.remaining_cooldown("C:EURUSD") == 0.0
