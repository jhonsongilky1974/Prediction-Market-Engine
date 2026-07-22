"""Cliente HTTP compartido por todos los conectores.

Nota de arquitectura (desviación menor de la estructura sugerida): el árbol
de archivos pedido no incluye este módulo. Se añade porque los 5 conectores
(mlb, sofascore, espn_tennis, kalshi, odds_api) necesitan la misma lógica de
timeout/retry/backoff/rate-limit/captura-RAW; sin este módulo esa lógica se
duplicaría 5 veces. Cada conector sigue siendo el único que conoce sus
endpoints y su forma de payload.

Comportamiento:
- Timeout corto por request.
- Reintentos limitados (nunca loops agresivos) con backoff exponencial y jitter.
- Rate limiting conservador: espaciado mínimo entre requests por instancia de cliente.
- Nunca lanza excepciones al pipeline: devuelve un `FetchResult` con
  `ok=False` y el error, para que el pipeline decida el fallback.
- Guarda automáticamente la respuesta (o el error) como captura RAW si se
  provee un `Repository`.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from config.settings import HttpPolicy

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    ok: bool
    status_code: Optional[int]
    data: Optional[Any]
    error: Optional[str]
    url: str
    capture_ts: datetime
    headers: Dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}


class BaseHttpClient:
    def __init__(self, source_name: str, policy: HttpPolicy, repository: Optional[Any] = None):
        self.source_name = source_name
        self.policy = policy
        self.repository = repository
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": policy.user_agent, "Accept": "application/json"})
        self._last_request_ts: float = 0.0

    def _respect_rate_limit(self) -> None:
        min_gap = self.policy.min_seconds_between_requests
        if min_gap <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        remaining = min_gap - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        endpoint_label: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        endpoint_label = endpoint_label or url
        attempt = 0
        last_error: Optional[str] = None
        last_status: Optional[int] = None

        while attempt <= self.policy.max_retries:
            self._respect_rate_limit()
            self._last_request_ts = time.monotonic()
            capture_ts = datetime.now(timezone.utc)
            try:
                resp = self._session.get(
                    url,
                    params=params,
                    timeout=self.policy.timeout_seconds,
                    headers=extra_headers,
                )
                last_status = resp.status_code
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        last_error = f"invalid_json: {exc}"
                        data = None
                        self._save_raw(endpoint_label, None, False, last_error, capture_ts)
                        return FetchResult(False, resp.status_code, None, last_error, url, capture_ts)
                    self._save_raw(endpoint_label, data, True, None, capture_ts)
                    return FetchResult(True, resp.status_code, data, None, url, capture_ts, dict(resp.headers))

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"http_{resp.status_code}"
                    attempt += 1
                    if attempt <= self.policy.max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    self._save_raw(endpoint_label, None, False, last_error, capture_ts)
                    return FetchResult(False, resp.status_code, None, last_error, url, capture_ts)

                # Errores 4xx no reintentables (404, 400, etc.)
                last_error = f"http_{resp.status_code}"
                self._save_raw(endpoint_label, None, False, last_error, capture_ts)
                return FetchResult(False, resp.status_code, None, last_error, url, capture_ts)

            except requests.exceptions.Timeout:
                last_error = "timeout"
            except requests.exceptions.RequestException as exc:
                last_error = f"request_exception: {exc}"

            attempt += 1
            if attempt <= self.policy.max_retries:
                self._sleep_backoff(attempt)

        capture_ts = datetime.now(timezone.utc)
        self._save_raw(endpoint_label, None, False, last_error, capture_ts)
        logger.warning("%s: fetch failed for %s after retries: %s", self.source_name, endpoint_label, last_error)
        return FetchResult(False, last_status, None, last_error, url, capture_ts)

    def _sleep_backoff(self, attempt: int) -> None:
        base = self.policy.backoff_base_seconds * (2 ** (attempt - 1))
        capped = min(base, self.policy.backoff_max_seconds)
        jitter = random.uniform(0, capped * 0.25)
        time.sleep(capped + jitter)

    def _save_raw(
        self,
        endpoint_label: str,
        data: Optional[Any],
        ok: bool,
        error: Optional[str],
        capture_ts: datetime,
    ) -> None:
        if self.repository is None:
            return
        self.repository.save_raw_capture(
            source=self.source_name,
            endpoint=endpoint_label,
            payload=data,
            ok=ok,
            error=error,
            capture_ts=capture_ts,
        )
