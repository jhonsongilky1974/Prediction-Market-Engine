"""Conector Live Tennis API (livetennisapi.com).

Fuente de **estado de partido en vivo** para tenis: marcador (sets/games/
points), servidor actual (1|2|null), estado de retiro/walkover/finalizado, y
metadatos de jugadores (ranking + Elo) y fixtures. Complementa a
`espn_tennis` (calendario/evento base) y `sofascore` (ranking/forma/stats de
saque-resto) con el detalle punto-a-punto que ninguno de los otros expone de
forma estable.

Regla de seguridad (idéntica a `odds_api.py`): la API key se lee EXCLUSIVAMENTE
desde la variable de entorno `LIVE_TENNIS_API_KEY`
(ver `config.settings.get_live_tennis_api_key`). Nunca se hardcodea, nunca se
inventa. Si no está configurada, `is_configured() == False` y cualquier llamada
devuelve un `FetchResult` con `error="NOT_CONFIGURED"` sin tocar la red, para
que el pipeline continúe sin romperse.

Contrato de la API (tier gratuito, verificado contra la documentación pública):
  - Base:     https://api.livetennisapi.com/api/public/v1
  - Auth:     header `X-API-Key: <key>`
  - Respuesta: `{"data": [ ... ]}`
  - Cuota tier gratuito: 30 req/min, 100 req/día (sin tarjeta). Por eso la
    política de red (`LIVE_TENNIS_API_POLICY`) espacia las requests de forma
    conservadora. La key gratuita se obtiene en
    https://livetennisapi.com/subscribe/free .
  - El feed en tiempo real por WebSocket y la probabilidad de modelo son del
    tier ULTRA (de pago); este conector usa únicamente los endpoints REST del
    tier gratuito.

Campos por partido usados aquí (todos opcionales; extracción defensiva que
nunca asume que una clave anidada existe):
  id, status, players.p1.name, players.p2.name,
  score.sets / score.games / score.points / score.server
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config.settings import (
    LIVE_TENNIS_API_BASE_URL,
    LIVE_TENNIS_API_POLICY,
    get_live_tennis_api_key,
)
from src.connectors.base_client import BaseHttpClient, FetchResult

# Valores de "point" del tenis en scoring estándar. Un valor fuera de este
# conjunto (p.ej. "6", "7") indica que el juego actual es un tiebreak.
_STANDARD_POINTS = frozenset({"0", "15", "30", "40", "AD", "A"})
_ADVANTAGE_POINTS = frozenset({"AD", "A"})
_SERVER_ON_DEFENSIVE = frozenset({"0", "15", "30"})

# Estado del flag de break point (tri-valuado). Se expone como constantes para
# que los consumidores no dependan de literales sueltos.
BREAK_POINT_YES = "Yes"
BREAK_POINT_NO = "No"
BREAK_POINT_UNDEF = "UNDEF"


class LiveTennisApiConnector:
    def __init__(self, repository: Optional[Any] = None, base_url: str = LIVE_TENNIS_API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client = BaseHttpClient("live_tennis_api", LIVE_TENNIS_API_POLICY, repository)
        self._api_key = get_live_tennis_api_key()

    def is_configured(self) -> bool:
        return self._api_key is not None

    def _auth_headers(self) -> Dict[str, str]:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    def _not_configured(self, url: str) -> FetchResult:
        return FetchResult(
            ok=False,
            status_code=None,
            data=None,
            error="NOT_CONFIGURED",
            url=url,
            capture_ts=datetime.now(timezone.utc),
        )

    def get_live_matches(self) -> FetchResult:
        """Estado de partido en vivo de todos los partidos en curso.

        Si la key no está configurada devuelve `NOT_CONFIGURED` sin tocar la
        red (mismo patrón que `OddsApiConnector.get_odds`)."""
        url = f"{self.base_url}/live"
        if not self.is_configured():
            return self._not_configured(url)
        return self._client.get_json(
            url,
            endpoint_label="live_matches",
            extra_headers=self._auth_headers(),
        )

    # -----------------------------------------------------------------
    # Extracción defensiva (tolerante a cambios de schema).
    # -----------------------------------------------------------------
    @staticmethod
    def extract_matches(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Devuelve la lista `data` de partidos; [] si el schema no coincide."""
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        return data if isinstance(data, list) else []

    @staticmethod
    def extract_participant_names(match: Dict[str, Any]) -> List[Optional[str]]:
        """[p1.name, p2.name]; None por cada nombre ausente."""
        players = match.get("players") if isinstance(match, dict) else None
        players = players if isinstance(players, dict) else {}
        names: List[Optional[str]] = []
        for slot in ("p1", "p2"):
            player = players.get(slot)
            player = player if isinstance(player, dict) else {}
            names.append(player.get("name"))
        return names

    @staticmethod
    def extract_status(match: Dict[str, Any]) -> Optional[str]:
        """Estado crudo tal cual lo reporta la fuente (p.ej. "live",
        "completed", "retired", "walkover"). El mapeo al `EventStatus` del
        esquema único es responsabilidad del normalizer, no del conector."""
        if not isinstance(match, dict):
            return None
        return match.get("status")

    @staticmethod
    def extract_server(match: Dict[str, Any]) -> Optional[int]:
        """Jugador al saque: 1, 2 o None si es desconocido/no aplica."""
        score = match.get("score") if isinstance(match, dict) else None
        score = score if isinstance(score, dict) else {}
        server = score.get("server")
        return server if server in (1, 2) else None

    @staticmethod
    def break_point_flag(score: Optional[Dict[str, Any]]) -> str:
        """Flag de break point TRI-VALUADO calculado desde el objeto `score`.

        Un break point existe cuando el jugador al RESTO está a un punto de
        ganar el juego al saque del rival:
          - resto con ventaja ("AD"), o
          - resto en "40" mientras el sacador está en {"0","15","30"}.

        Devuelve:
          - ``BREAK_POINT_YES``   si hay break point confirmado,
          - ``BREAK_POINT_NO``    si NO hay (incluye deuce, sacador con ventaja,
                                  o dentro de un tiebreak — donde el concepto se
                                  suprime), o si los points no se pueden leer,
          - ``BREAK_POINT_UNDEF`` únicamente cuando el servidor es desconocido
                                  (no se puede saber quién resta).

        Función pura sobre el objeto `score`; no toca la red. Nunca inventa: si
        falta el dato de points, devuelve ``BREAK_POINT_NO`` (no un break point
        confirmado), nunca ``BREAK_POINT_YES``.
        """
        if not isinstance(score, dict):
            return BREAK_POINT_UNDEF

        server = score.get("server")
        if server not in (1, 2):
            return BREAK_POINT_UNDEF

        points = score.get("points")
        if not isinstance(points, dict):
            return BREAK_POINT_NO

        server_key = "p1" if server == 1 else "p2"
        returner_key = "p2" if server == 1 else "p1"
        server_point = _normalize_point(points.get(server_key))
        returner_point = _normalize_point(points.get(returner_key))

        # Tiebreak: los points dejan de ser 0/15/30/40/AD -> se suprime el flag.
        if score.get("tiebreak") is True:
            return BREAK_POINT_NO
        if server_point not in _STANDARD_POINTS or returner_point not in _STANDARD_POINTS:
            return BREAK_POINT_NO

        if returner_point in _ADVANTAGE_POINTS:
            return BREAK_POINT_YES
        if returner_point == "40" and server_point in _SERVER_ON_DEFENSIVE:
            return BREAK_POINT_YES
        return BREAK_POINT_NO

    @classmethod
    def match_state(cls, match: Dict[str, Any]) -> Dict[str, Any]:
        """Vista compacta y agnóstica-de-consumidor del estado en vivo de un
        partido, lista para que el normalizer/feature-layer la use:

          {id, status, participant_a, participant_b, server, break_point,
           sets, games, points}

        Todo campo ausente queda en None / con el flag correspondiente; nunca
        se inventan valores."""
        match = match if isinstance(match, dict) else {}
        score = match.get("score")
        score = score if isinstance(score, dict) else {}
        name_a, name_b = cls.extract_participant_names(match)
        return {
            "id": match.get("id"),
            "status": cls.extract_status(match),
            "participant_a": name_a,
            "participant_b": name_b,
            "server": cls.extract_server(match),
            "break_point": cls.break_point_flag(score),
            "sets": score.get("sets"),
            "games": score.get("games"),
            "points": score.get("points"),
        }


def _normalize_point(value: Any) -> Optional[str]:
    """Normaliza un valor de point a string canónico ("A" -> "AD"). Devuelve
    None si no es un escalar representable."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text == "A":
        return "AD"
    return text
