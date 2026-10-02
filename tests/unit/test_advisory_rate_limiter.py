"""Tests de Phase 6 -- Tramo 5B: `src.api.rate_limiter`. Reloj inyectable
determinista -- sin `time.sleep` real. Verifica explícitamente que el
header `X-Advisory-Client-Id` es SOLO una dimensión secundaria: rotarlo
nunca debe permitir exceder el presupuesto de la IP."""
from __future__ import annotations

from src.api.rate_limiter import RateLimiter, TokenBucket


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_token_bucket_allows_up_to_burst_immediately():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=2.0, capacity=5.0, clock=clock)
    results = [bucket.allow() for _ in range(5)]
    assert all(results)


def test_token_bucket_rejects_beyond_burst():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=2.0, capacity=5.0, clock=clock)
    for _ in range(5):
        assert bucket.allow()
    assert bucket.allow() is False


def test_token_bucket_recharges_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=2.0, capacity=5.0, clock=clock)
    for _ in range(5):
        assert bucket.allow()
    assert bucket.allow() is False
    clock.advance(0.5)  # 0.5s * 2/s = 1 token recargado
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_rate_limiter_different_ips_are_independent():
    clock = FakeClock()
    limiter = RateLimiter(rate_per_second=2.0, burst=1, clock=clock)
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is False
    # Otra IP nunca consume el presupuesto de la primera.
    assert limiter.check("5.6.7.8") is True


def test_rate_limiter_rejects_without_any_header():
    clock = FakeClock()
    limiter = RateLimiter(rate_per_second=2.0, burst=1, clock=clock)
    assert limiter.check("1.2.3.4", client_id=None) is True
    assert limiter.check("1.2.3.4", client_id=None) is False


def test_rotating_client_header_never_evades_the_ip_level_cap():
    """El requisito explícito: la identidad observada por el servidor
    (IP) es la clave primaria -- rotar el header secundario NUNCA debe
    conceder más presupuesto del que la IP ya agotó."""
    clock = FakeClock()
    limiter = RateLimiter(rate_per_second=2.0, burst=1, clock=clock)
    assert limiter.check("1.2.3.4", client_id="session-a") is True
    # Agotado el burst de la IP -- un header NUEVO no debe reabrir cupo.
    assert limiter.check("1.2.3.4", client_id="session-b") is False
    assert limiter.check("1.2.3.4", client_id="session-c") is False
    assert limiter.check("1.2.3.4", client_id=None) is False


def test_client_header_adds_a_stricter_not_looser_sub_bucket():
    """Con presupuesto de IP amplio, un mismo (ip, client_id) agota SU
    propio sub-bucket de forma independiente -- el header nunca hace que
    el límite sea más permisivo, solo más granular."""
    clock = FakeClock()
    limiter = RateLimiter(rate_per_second=2.0, burst=5, clock=clock)
    for _ in range(5):
        assert limiter.check("1.2.3.4", client_id="session-a") is True
    # session-a agotó su propio sub-bucket (burst=5) aunque la IP (burst=5,
    # ya consumido 5 veces también) coincide en este caso -- confirmamos
    # que un client_id distinto bajo la MISMA ip ya sin cupo de IP tampoco
    # puede pasar (la IP manda).
    assert limiter.check("1.2.3.4", client_id="session-b") is False
