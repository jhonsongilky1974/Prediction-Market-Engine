"""Rate limiting de transporte -- Tramo 5B. Protege `POST
/advisory/positions/evaluate` (2 evaluaciones/segundo, burst 5) -- un
429 aquí es una decisión de TRANSPORTE, nunca una decisión de dominio
(nunca se traduce a `NO_TRADE`/`NO_NEW_ENTRY`/ningún campo de
`src.advisory`).

Identidad de la clave: la IP observada por el servidor
(`Request.client.host`) es la dimensión de CONFIANZA y PRIMARIA -- no
hay autenticación/sesión en este proyecto (herramienta local de un solo
usuario), así que es lo único que el servidor puede verificar por sí
mismo. El bucket de IP se aplica SIEMPRE, sin importar qué header mande
el cliente -- rotar `X-Advisory-Client-Id` nunca puede aumentar el
presupuesto total de esa IP (si la clave fuera `(ip, header)`, un
cliente podría evadir el límite mandando un header distinto en cada
request; por eso el bucket de IP existe de forma INDEPENDIENTE del
header, no compuesto con él).

El header, cuando el cliente lo manda, es una dimensión SECUNDARIA
adicional: exige un segundo bucket propio de esa combinación
(ip, client_id) con los mismos parámetros -- distingue pestañas/sesiones
del mismo origen sin nunca poder conceder MÁS presupuesto que el que ya
permite el bucket de IP (ambos deben aprobar la request).

Reloj inyectable (`clock: Callable[[], float]`, mismo patrón que
`src.payoff.payoff_model`/`src.calibration.calibration_layer`) --
permite tests deterministas sin `time.sleep` real.

LIMITACIÓN DOCUMENTADA (Tramo 5B): `RateLimiter`/`TokenBucket` viven
ÚNICAMENTE en memoria de proceso, sin locks -- adecuado para uvicorn en
un solo worker/proceso (el despliegue real de este proyecto, herramienta
local de un solo usuario), pero NO es seguro para múltiples workers o
procesos (cada uno tendría su propio conteo independiente, multiplicando
el límite efectivo) ni estrictamente thread-safe bajo escritura
concurrente real dentro del mismo proceso (no hay lock alrededor de
`TokenBucket.allow()`). Ambas limitaciones quedan fuera de alcance de
Tramo 5B -- requerirían un backend compartido (p.ej. Redis) para un
despliegue multi-proceso real.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from fastapi import Depends, Header, HTTPException, Request

DEFAULT_RATE_PER_SECOND = 2.0
DEFAULT_BURST = 5

_BucketKey = Tuple[str, ...]


@dataclass
class TokenBucket:
    rate_per_second: float
    capacity: float
    clock: Callable[[], float]
    tokens: float = field(init=False)
    last_check: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity
        self.last_check = self.clock()

    def allow(self) -> bool:
        now = self.clock()
        elapsed = max(0.0, now - self.last_check)
        self.last_check = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    """Bucket PRIMARIO por `source_ip` (siempre aplicado, nunca evadible
    rotando el header) + bucket SECUNDARIO opcional por
    `(source_ip, client_id)` (más granular, nunca más permisivo -- ambos
    deben aprobar). Ver docstring del módulo."""

    def __init__(
        self,
        rate_per_second: float = DEFAULT_RATE_PER_SECOND,
        burst: int = DEFAULT_BURST,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.rate_per_second = rate_per_second
        self.burst = burst
        self.clock = clock
        self._buckets: Dict[_BucketKey, TokenBucket] = {}

    def _get_bucket(self, key: _BucketKey) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(rate_per_second=self.rate_per_second, capacity=float(self.burst), clock=self.clock)
            self._buckets[key] = bucket
        return bucket

    def check(self, source_ip: str, client_id: Optional[str] = None) -> bool:
        ip_bucket = self._get_bucket(("ip", source_ip))
        if not ip_bucket.allow():
            return False
        if client_id is not None:
            sub_bucket = self._get_bucket(("ip+client", source_ip, client_id))
            if not sub_bucket.allow():
                return False
        return True


_default_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Dependencia inyectable -- los tests la sobreescriben vía
    `app.dependency_overrides` con un `RateLimiter(clock=fake_clock)`
    determinista, mismo principio que `get_positions_repository`."""
    return _default_rate_limiter


def enforce_rate_limit(
    request: Request,
    x_advisory_client_id: Optional[str] = Header(default=None, alias="X-Advisory-Client-Id"),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    source_ip = request.client.host if request.client is not None else "unknown"
    if not limiter.check(source_ip, x_advisory_client_id):
        raise HTTPException(
            status_code=429,
            detail=(
                f"rate limit excedido para {source_ip!r}: máximo "
                f"{limiter.rate_per_second}/s, burst {limiter.burst}"
            ),
            headers={"Retry-After": "1"},
        )
