"""Cálculo del baseline v1 de features MLB (Fase 2, Paso 2).

Implementa una función `compute_*` por cada feature `FULLY_SPECIFIED` de
MLB en el Feature Registry (`src.features.registry`, Paso 1) — los nombres
coinciden exactamente con `FeatureDefinition.compute_function_name`. Ver
`test_all_computable_mlb_features_have_a_matching_function` para la
verificación cruzada automática contra el registry.

DECISIÓN DE DISEÑO (documentada, no inventada en silencio): este módulo
**nunca hace llamadas de red**. Cada función recibe los payloads crudos ya
obtenidos como `RawDataPoint` (payload + su propio timestamp de captura).
Motivo: tres de las doce features necesitan capacidades que el
`MlbConnector` de Fase 1 no expone hoy (`sitCodes` en
`get_person_stats`, `rosterType` en `get_roster`, y no existe ningún
método para stats de equipo) — extenderlo no es una corrección de un
defecto de Fase 1, es una capacidad nueva, y el alcance textual de
PLAN_PHASE2.md §12 Paso 2 es "cálculo", no "conectores". Diseñar el
cómputo como funciones puras evita inventar esa extensión sin aprobación
explícita y mantiene cada función determinista y testeable con fixtures
reales. Ver el informe de entrega del Paso 2 para el detalle completo de
esta limitación.

Control anti-leakage uniforme:
  - Endpoints "snapshot" (stats de temporada, splits, roster): el payload
    completo se descarta si `captured_at` del propio payload no es
    estrictamente anterior a `data_cutoff_timestamp` -- no hay forma de
    filtrar "parte" de un acumulado de temporada, así que la única defensa
    posible es la fecha de captura del payload en sí.
  - Endpoints de serie temporal (gameLog): cada entrada individual se
    filtra por su propio campo `date` < `data_cutoff_timestamp`, además
    del filtro de captured_at del payload completo.

Ningún campo se convierte a 0 cuando falta: falta de dato -> `None`,
siempre, salvo que 0 sea el valor real reportado por la fuente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.features.registry import ExpectedImportance, get_feature, list_computable_features
from src.models.schemas import NormalizedRecord, Sport
from src.storage.history_repository import HistoryRepository

CURRENT_FEATURE_SET_VERSION = "phase2_registry_v1"
"""Debe coincidir con src.features.registry.CURRENT_FEATURE_SET_VERSION --
verificado por test, no importado directamente para no acoplar el valor
por accidente a un futuro refactor silencioso del registry."""


# =========================================================================
# Entrada cruda con control de temporalidad
# =========================================================================

@dataclass(frozen=True)
class RawDataPoint:
    """Un payload crudo ya obtenido, junto con el instante en que se
    obtuvo. Es el único mecanismo de anti-leakage para datos "snapshot"
    (acumulados de temporada): si `captured_at` no es estrictamente
    anterior al cutoff, el payload se trata como no utilizable, sin
    importar su contenido."""

    payload: Optional[Any]
    captured_at: Optional[datetime]

    def usable(self, data_cutoff_timestamp: datetime) -> bool:
        if self.payload is None or self.captured_at is None:
            return False
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError(
                f"RawDataPoint.captured_at debe ser tz-aware (UTC), recibido naive: {self.captured_at!r}"
            )
        if data_cutoff_timestamp.tzinfo is None or data_cutoff_timestamp.utcoffset() is None:
            raise ValueError(
                f"data_cutoff_timestamp debe ser tz-aware (UTC), recibido naive: {data_cutoff_timestamp!r}"
            )
        return self.captured_at < data_cutoff_timestamp


# =========================================================================
# Parsers defensivos (la MLB Stats API usa formatos no triviales)
# =========================================================================

def _parse_stat_float(value: Any) -> Optional[float]:
    """era/whip/avg/obp/slg/ops/pct llegan como strings (ej. '.750',
    '12.00'). None/vacío/no parseable -> None, nunca 0."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_innings_pitched(stat: Dict[str, Any]) -> Optional[float]:
    """`outs` (entero, sin ambigüedad) es preferido si está presente.
    Si no, se parsea la notación MLB 'X.Y' donde Y son TERCIOS de inning
    (0, 1 o 2) -- NUNCA decimal. Verificado contra la API real:
    inningsPitched='11.1' con outs=34 corresponde a 11 + 1/3 innings
    (11*3=33, +1=34), no a 11.1 innings decimales. Un fraccionario fuera
    de {0,1,2} indica un cambio de formato inesperado -> None, no se
    inventa una interpretación."""
    outs = stat.get("outs")
    if isinstance(outs, (int, float)) and not isinstance(outs, bool):
        return outs / 3.0

    raw = stat.get("inningsPitched")
    if raw is None:
        return None
    text = str(raw)
    if "." in text:
        whole_str, _, frac_str = text.partition(".")
        try:
            whole = int(whole_str)
            frac = int(frac_str)
        except ValueError:
            return None
        if frac not in (0, 1, 2):
            return None
        return whole + frac / 3.0
    try:
        return float(text)
    except ValueError:
        return None


# =========================================================================
# Extracción defensiva de la forma real de cada endpoint
# =========================================================================

def _extract_season_pitching_stat(
    raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime
) -> Optional[Dict[str, Any]]:
    """`people/{id}/stats?stats=season&group=pitching` ->
    stats[0].splits[0].stat. None si el payload no es usable, no tiene la
    forma esperada, o el pitcher no tiene starts en la temporada (rookie)."""
    if raw is None or not raw.usable(data_cutoff_timestamp):
        return None
    try:
        splits = raw.payload["stats"][0]["splits"]
    except (KeyError, IndexError, TypeError):
        return None
    if not splits:
        return None
    stat = splits[0].get("stat")
    if not isinstance(stat, dict):
        return None
    if not stat.get("gamesStarted"):
        return None  # sin starts esta temporada -> NULL, nunca 0
    return stat


def _extract_handedness_splits(
    raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime
) -> Dict[str, Dict[str, Any]]:
    """`people/{id}/stats?stats=statSplits&sitCodes=vr,vl` ->
    {'vl': stat_dict, 'vr': stat_dict}. Dict vacío si no usable/malformado."""
    if raw is None or not raw.usable(data_cutoff_timestamp):
        return {}
    try:
        splits = raw.payload["stats"][0]["splits"]
    except (KeyError, IndexError, TypeError):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for entry in splits or []:
        if not isinstance(entry, dict):
            continue
        code = (entry.get("split") or {}).get("code")
        stat = entry.get("stat")
        if code in ("vl", "vr") and isinstance(stat, dict):
            result[code] = stat
    return result


def _extract_game_log_entries(
    raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime
) -> List[Dict[str, Any]]:
    """`people/{id}/stats?stats=gameLog&group=pitching` -> lista de
    entradas con `date`/`stat`, filtradas a fecha < data_cutoff_timestamp
    (control de leakage a nivel de ENTRADA individual, no solo del
    payload completo -- el game log trae TODOS los starts de la
    temporada). Entradas sin `date` parseable se excluyen (no se asume
    que están "antes" por defecto).

    IMPORTANTE (bug de leakage encontrado y corregido en la auditoría del
    Paso 2): `date` solo tiene granularidad de DÍA, sin hora. Comparar
    "medianoche de ese día" contra un `data_cutoff_timestamp` con hora
    (ej. 22:40) trataba incorrectamente un start del MISMO día calendario
    del cutoff -- potencialmente el propio partido a predecir -- como
    "seguro en el pasado", porque medianoche es numéricamente anterior a
    22:40 del mismo día. La comparación correcta es por FECHA calendario:
    se excluye cualquier entrada cuya fecha sea >= la fecha calendario del
    cutoff, sin importar la hora de ninguno de los dos."""
    if raw is None or not raw.usable(data_cutoff_timestamp):
        return []
    try:
        splits = raw.payload["stats"][0]["splits"]
    except (KeyError, IndexError, TypeError):
        return []

    cutoff_date = data_cutoff_timestamp.date()
    valid: List[Dict[str, Any]] = []
    for entry in splits or []:
        if not isinstance(entry, dict):
            continue
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if entry_date >= cutoff_date:
            continue  # leakage: este start es en la fecha del cutoff o después
        stat = entry.get("stat")
        if isinstance(stat, dict):
            valid.append(entry)
    valid.sort(key=lambda e: e["date"])
    return valid


# =========================================================================
# Features de pitcher — stats de temporada (5 features, mismo payload)
# =========================================================================

def compute_pitcher_era_season(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    stat = _extract_season_pitching_stat(raw, data_cutoff_timestamp)
    if stat is None:
        return None
    return _parse_stat_float(stat.get("era"))


def compute_pitcher_whip_season(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    stat = _extract_season_pitching_stat(raw, data_cutoff_timestamp)
    if stat is None:
        return None
    return _parse_stat_float(stat.get("whip"))


def compute_pitcher_k_pct(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    stat = _extract_season_pitching_stat(raw, data_cutoff_timestamp)
    if stat is None:
        return None
    k = stat.get("strikeOuts")
    bf = stat.get("battersFaced")
    if not isinstance(k, (int, float)) or not isinstance(bf, (int, float)) or bf == 0:
        return None
    return k / bf


def compute_pitcher_bb_pct(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    stat = _extract_season_pitching_stat(raw, data_cutoff_timestamp)
    if stat is None:
        return None
    bb = stat.get("baseOnBalls")
    bf = stat.get("battersFaced")
    if not isinstance(bb, (int, float)) or not isinstance(bf, (int, float)) or bf == 0:
        return None
    return bb / bf


def compute_pitcher_ip_season(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    stat = _extract_season_pitching_stat(raw, data_cutoff_timestamp)
    if stat is None:
        return None
    return _parse_innings_pitched(stat)


# =========================================================================
# pitcher_form_last5 — ERA/WHIP sobre los últimos <=5 starts pre-cutoff
# =========================================================================

MIN_STARTS_FOR_FORM = 3


def compute_pitcher_form_last5(
    raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime
) -> Optional[Dict[str, Any]]:
    entries = _extract_game_log_entries(raw, data_cutoff_timestamp)
    if not entries:
        return None
    last5 = entries[-5:]

    total_outs = 0.0
    total_er = 0.0
    total_bb_h = 0.0
    used = 0
    has_whip_component = True

    for entry in last5:
        stat = entry["stat"]
        er = stat.get("earnedRuns")
        innings = _parse_innings_pitched(stat)
        if not isinstance(er, (int, float)) or innings is None:
            continue  # entrada incompleta: se excluye, no se imputa 0
        total_er += er
        total_outs += innings * 3
        used += 1

        bb = stat.get("baseOnBalls")
        hits = stat.get("hits")
        if isinstance(bb, (int, float)) and isinstance(hits, (int, float)):
            total_bb_h += bb + hits
        else:
            has_whip_component = False

    if used < MIN_STARTS_FOR_FORM:
        return None  # muestra insuficiente -> NULL, nunca calcular con <3

    innings_total = total_outs / 3.0
    if innings_total <= 0:
        return None

    era = (total_er * 9.0) / innings_total
    whip = (total_bb_h / innings_total) if has_whip_component else None

    return {"era": round(era, 4), "whip": round(whip, 4) if whip is not None else None, "starts_used": used}


# =========================================================================
# pitcher_vs_opponent_handedness_ops
# =========================================================================

def compute_pitcher_vs_opponent_handedness_ops(
    raw: Optional[RawDataPoint],
    opponent_dominant_hand: Optional[str],
    data_cutoff_timestamp: datetime,
) -> Optional[float]:
    """`opponent_dominant_hand` debe ser 'L' o 'R' (lado dominante del
    lineup RIVAL confirmado). None si el lineup rival no está confirmado
    todavía -- coincide exactamente con el missing_treatment del registry."""
    if opponent_dominant_hand not in ("L", "R"):
        return None
    splits = _extract_handedness_splits(raw, data_cutoff_timestamp)
    code = "vl" if opponent_dominant_hand == "L" else "vr"
    stat = splits.get(code)
    if stat is None:
        return None
    return _parse_stat_float(stat.get("ops"))


# =========================================================================
# bullpen_era_recent
# =========================================================================

BULLPEN_LOOKBACK_APPEARANCES = 15
"""Alcance deliberado (documentado en el informe de entrega): esta función
recibe los game logs de relevistas YA IDENTIFICADOS por el llamador
(`reliever_game_logs`), no decide por sí misma "quién es relevista" a
partir del roster -- esa clasificación es un problema aparte (requeriría
cruzar roster + gamesStarted de cada jugador) fuera del alcance textual
de "cálculo de features" de este módulo."""


def compute_bullpen_era_recent(
    reliever_game_logs: Dict[int, RawDataPoint],
    data_cutoff_timestamp: datetime,
) -> Optional[float]:
    if not reliever_game_logs:
        return None

    total_er = 0.0
    total_outs = 0.0
    any_usable = False

    for _, raw in reliever_game_logs.items():
        entries = _extract_game_log_entries(raw, data_cutoff_timestamp)
        if not entries:
            continue
        recent = entries[-BULLPEN_LOOKBACK_APPEARANCES:]
        for entry in recent:
            stat = entry["stat"]
            er = stat.get("earnedRuns")
            innings = _parse_innings_pitched(stat)
            if not isinstance(er, (int, float)) or innings is None:
                continue
            total_er += er
            total_outs += innings * 3
            any_usable = True

    if not any_usable or total_outs <= 0:
        return None

    innings_total = total_outs / 3.0
    return round((total_er * 9.0) / innings_total, 4)


# =========================================================================
# Features de equipo
# =========================================================================

def compute_team_record_pct(league_record: Optional[Dict[str, Any]]) -> Optional[float]:
    """Fuente: `model_inputs.context.{away,home}_league_record`, ya
    presente en el NormalizedRecord (Fase 1) -- no requiere un payload
    crudo/nuevo ni control de cutoff propio: hereda el instante de
    captura del propio NormalizedRecord del que proviene.

    Prefiere el campo `pct` directo del payload (ej. '.485') sobre
    recalcular wins/(wins+losses); ambos deberían coincidir salvo
    redondeo, y usar el campo directo evita un caso especial de
    división por cero al inicio de temporada."""
    if not isinstance(league_record, dict):
        return None
    pct = _parse_stat_float(league_record.get("pct"))
    if pct is not None:
        return pct
    wins = league_record.get("wins")
    losses = league_record.get("losses")
    if not isinstance(wins, (int, float)) or not isinstance(losses, (int, float)):
        return None
    total = wins + losses
    if total <= 0:
        return None
    return wins / total


def compute_team_ops_season(raw: Optional[RawDataPoint], data_cutoff_timestamp: datetime) -> Optional[float]:
    if raw is None or not raw.usable(data_cutoff_timestamp):
        return None
    try:
        splits = raw.payload["stats"][0]["splits"]
    except (KeyError, IndexError, TypeError):
        return None
    if not splits:
        return None
    stat = splits[0].get("stat")
    if not isinstance(stat, dict):
        return None
    return _parse_stat_float(stat.get("ops"))


def compute_home_away(record: NormalizedRecord, participant: str) -> Optional[str]:
    """`participant` en {"participant_a", "participant_b"}. Hecho
    estructural del calendario -- sin control de cutoff (no se acumula,
    no cambia retroactivamente)."""
    if participant not in ("participant_a", "participant_b"):
        raise ValueError(f"participant debe ser 'participant_a' o 'participant_b', recibido: {participant!r}")
    context = record.model_inputs.context or {}
    home_id = context.get("home_team_id")
    away_id = context.get("away_team_id")
    if home_id is None or away_id is None:
        return None
    # mlb_normalizer.py (Fase 1) asigna participant_a=away, participant_b=home
    is_participant_a = participant == "participant_a"
    return "AWAY" if is_participant_a else "HOME"


def compute_il_flag_key_players(
    il_roster: Optional[RawDataPoint],
    key_player_ids: List[int],
    data_cutoff_timestamp: datetime,
) -> Optional[bool]:
    """True/False solo si el roster de IL fue consultado con éxito Y hay al
    menos un jugador clave que verificar; None (no False) si no se pudo
    consultar, o si `key_player_ids` está vacío -- un False fabricado
    implicaría "confirmado sano", que no es lo mismo que "no verificado"
    (ver missing_treatment del registry, Paso 1). Hallazgo de auditoría
    del Paso 2: antes, `key_player_ids=[]` devolvía `False` (vía
    `any([])`) sin haber verificado a NADIE -- exactamente el mismo error
    conceptual que la propia función ya prevenía para el roster ausente."""
    if not key_player_ids:
        return None
    if il_roster is None or not il_roster.usable(data_cutoff_timestamp):
        return None
    if not isinstance(il_roster.payload, dict):
        return None
    roster = il_roster.payload.get("roster")
    if not isinstance(roster, list):
        return None
    il_ids = set()
    for entry in roster:
        if not isinstance(entry, dict):
            continue
        person_id = (entry.get("person") or {}).get("id")
        if person_id is not None:
            il_ids.add(person_id)
    return any(pid in il_ids for pid in key_player_ids)


# =========================================================================
# Orquestador: calcula TODAS las features del baseline v1 MLB para un
# NormalizedRecord dado, sin persistir (la persistencia es un paso
# explícito separado, ver `persist_mlb_feature_snapshot`).
# =========================================================================

_VALIDATION_RANGES: Dict[str, Tuple[float, float]] = {
    "pitcher_era_season": (0.0, 15.0),
    "pitcher_whip_season": (0.0, 5.0),
    "pitcher_k_pct": (0.0, 0.6),
    "pitcher_bb_pct": (0.0, 0.3),
    "pitcher_ip_season": (0.0, 250.0),
    "pitcher_vs_opponent_handedness_ops": (0.300, 1.200),
    "bullpen_era_recent": (0.0, 12.0),
    "team_ops_season": (0.500, 1.000),
    "team_record_pct": (0.0, 1.0),
}


@dataclass
class MlbFeatureInputs:
    """Bundle de payloads YA OBTENIDOS (con su propio timestamp de
    captura) necesarios para el baseline v1 MLB, por lado
    (participant_a=away, participant_b=home, consistente con
    mlb_normalizer.py de Fase 1). Este módulo no fetch-ea nada: es
    responsabilidad del llamador construir este bundle."""

    pitcher_season_stat: Dict[str, Optional[RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    pitcher_game_log: Dict[str, Optional[RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    pitcher_handedness_splits: Dict[str, Optional[RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    opponent_dominant_hand: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    reliever_game_logs: Dict[str, Dict[int, RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": {}, "participant_b": {}}
    )
    team_hitting_stat: Dict[str, Optional[RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    il_roster: Dict[str, Optional[RawDataPoint]] = field(
        default_factory=lambda: {"participant_a": None, "participant_b": None}
    )
    key_player_ids: Dict[str, List[int]] = field(
        default_factory=lambda: {"participant_a": [], "participant_b": []}
    )


def compute_mlb_features(
    record: NormalizedRecord,
    inputs: MlbFeatureInputs,
    data_cutoff_timestamp: datetime,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Calcula las 12 features FULLY_SPECIFIED de MLB para un
    NormalizedRecord. Devuelve (features, missing_features, warnings).

    `features[name]` es `{"participant_a": valor|None, "participant_b": valor|None}`
    para las features por-lado, o un valor único para `home_away`.
    Ningún valor faltante se convierte en 0/False -- queda `None` y su
    nombre se añade a `missing_features`."""
    if record.sport != Sport.MLB:
        raise ValueError(f"compute_mlb_features solo aplica a NormalizedRecord de MLB, recibido: {record.sport}")
    if data_cutoff_timestamp.tzinfo is None or data_cutoff_timestamp.utcoffset() is None:
        raise ValueError(f"data_cutoff_timestamp debe ser tz-aware (UTC), recibido naive: {data_cutoff_timestamp!r}")

    features: Dict[str, Any] = {}
    missing: List[str] = []
    warnings: List[str] = []

    def _per_side(name: str, compute_fn) -> None:
        value = {
            "participant_a": compute_fn("participant_a"),
            "participant_b": compute_fn("participant_b"),
        }
        features[name] = value
        if value["participant_a"] is None:
            missing.append(f"{name}.participant_a")
        if value["participant_b"] is None:
            missing.append(f"{name}.participant_b")

    _per_side(
        "pitcher_era_season",
        lambda side: compute_pitcher_era_season(inputs.pitcher_season_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_whip_season",
        lambda side: compute_pitcher_whip_season(inputs.pitcher_season_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_k_pct",
        lambda side: compute_pitcher_k_pct(inputs.pitcher_season_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_bb_pct",
        lambda side: compute_pitcher_bb_pct(inputs.pitcher_season_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_ip_season",
        lambda side: compute_pitcher_ip_season(inputs.pitcher_season_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_form_last5",
        lambda side: compute_pitcher_form_last5(inputs.pitcher_game_log.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "pitcher_vs_opponent_handedness_ops",
        lambda side: compute_pitcher_vs_opponent_handedness_ops(
            inputs.pitcher_handedness_splits.get(side),
            inputs.opponent_dominant_hand.get(side),
            data_cutoff_timestamp,
        ),
    )
    _per_side(
        "bullpen_era_recent",
        lambda side: compute_bullpen_era_recent(inputs.reliever_game_logs.get(side, {}), data_cutoff_timestamp),
    )
    _per_side(
        "team_ops_season",
        lambda side: compute_team_ops_season(inputs.team_hitting_stat.get(side), data_cutoff_timestamp),
    )
    _per_side(
        "il_flag_key_players",
        lambda side: compute_il_flag_key_players(
            inputs.il_roster.get(side), inputs.key_player_ids.get(side, []), data_cutoff_timestamp
        ),
    )

    context = record.model_inputs.context or {}
    _per_side(
        "team_record_pct",
        lambda side: compute_team_record_pct(
            context.get("away_league_record" if side == "participant_a" else "home_league_record")
        ),
    )

    home_away_a = compute_home_away(record, "participant_a")
    home_away_b = compute_home_away(record, "participant_b")
    features["home_away"] = {"participant_a": home_away_a, "participant_b": home_away_b}
    if home_away_a is None:
        missing.append("home_away.participant_a")
    if home_away_b is None:
        missing.append("home_away.participant_b")

    for name, (lo, hi) in _VALIDATION_RANGES.items():
        for side in ("participant_a", "participant_b"):
            value = features.get(name, {}).get(side) if isinstance(features.get(name), dict) else None
            if isinstance(value, (int, float)) and not (lo <= value <= hi):
                warnings.append(f"{name}.{side}={value} fuera de rango plausible [{lo},{hi}]")

    # pitcher_form_last5 devuelve un dict anidado {"era":..., "whip":...},
    # así que no encaja en el bucle escalar de arriba -- se valida aparte,
    # con el mismo rango que ERA/WHIP de temporada (validation_rule del
    # registry: "Igual rango que ERA/WHIP de temporada"). Hallazgo de
    # auditoría del Paso 2: esta feature nunca se validaba (un ERA de 450
    # no generaba ningún warning).
    era_lo, era_hi = _VALIDATION_RANGES["pitcher_era_season"]
    whip_lo, whip_hi = _VALIDATION_RANGES["pitcher_whip_season"]
    for side in ("participant_a", "participant_b"):
        form = features.get("pitcher_form_last5", {}).get(side)
        if not isinstance(form, dict):
            continue
        era = form.get("era")
        whip = form.get("whip")
        if isinstance(era, (int, float)) and not (era_lo <= era <= era_hi):
            warnings.append(f"pitcher_form_last5.{side}.era={era} fuera de rango plausible [{era_lo},{era_hi}]")
        if isinstance(whip, (int, float)) and not (whip_lo <= whip <= whip_hi):
            warnings.append(f"pitcher_form_last5.{side}.whip={whip} fuera de rango plausible [{whip_lo},{whip_hi}]")

    return features, missing, warnings


def persist_mlb_feature_snapshot(
    history_repository: HistoryRepository,
    record: NormalizedRecord,
    event_snapshot_id: int,
    inputs: MlbFeatureInputs,
    data_cutoff_timestamp: datetime,
    computed_at: Optional[datetime] = None,
) -> Tuple[int, Dict[str, Any], List[str], List[str]]:
    """Calcula las features (`compute_mlb_features`) y las persiste en
    `feature_snapshots` (Paso 0, INSERT-only) en un solo paso -- "extiende
    Paso 0" tal como pide PLAN_PHASE2.md §12 Paso 2. `event_snapshot_id`
    debe ser el id devuelto por un `HistoryRepository.save_event_snapshot`
    previo del MISMO evento/instante (la FK se aplica: un id inexistente
    hace fallar el INSERT, ver auditoría del Paso 1).

    Devuelve (feature_snapshot_id, features, missing_features, warnings).
    `warnings` NO se persiste todavía (feature_snapshots no tiene columna
    para ello, ver §11 del plan) -- se devuelve para que el llamador
    decida qué hacer (loggear, etc), consistente con cómo Fase 1 maneja
    warnings de pipeline sin bloquear la persistencia del dato real."""
    features, missing, warnings = compute_mlb_features(record, inputs, data_cutoff_timestamp)
    feature_snapshot_id = history_repository.save_feature_snapshot(
        event_id=record.event_id,
        event_snapshot_id=event_snapshot_id,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
        data_cutoff_timestamp=data_cutoff_timestamp,
        features=features,
        missing_features=missing,
        computed_at=computed_at,
    )
    return feature_snapshot_id, features, missing, warnings
