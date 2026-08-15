"""Resolver estructural de pares para tenis -- Tramo 1 (2026-08-15).

SOLO Qualifying y Round Robin -- ver
`src/pipelines/tennis_pipeline.py::_tennis_uses_structural_pair_resolver`.
Nunca importado por `mlb_pipeline.py`/`market_matcher.py`/`event_matcher.py`:
aislamiento tennis-only por construcción (un módulo entero que MLB nunca
importa), no una rama condicional dentro de un módulo compartido.

Motivación (ver CONTINUITY.md, investigación real de Faria vs Wu,
2026-08-12 -- reconstruida en vivo el 2026-08-15 contra las APIs reales de
ESPN/Kalshi porque la captura histórica local no tiene snapshots de esos
dos días): el caso real tenía identidad de par perfecta
(`participants_similarity` = 1.0 para "Jaime Faria"/"Wu Yibing" contra
"Jaime Faria"/"Yibing Wu") pero fallaba solo porque el delta real
(occurrence_datetime de Kalshi vs start_time real de ESPN) era 390min,
60min por encima de la tolerancia de Qualifying (330min,
`TENNIS_LATE_ROUND_TOLERANCE_MINUTES`). Este módulo ignora deliberadamente
el tiempo (y cualquier otra señal secundaria: torneo/competition, orden de
listado, heurística de score) como filtro o criterio de decisión -- exige
en su lugar que AMBOS participantes coincidan conjuntamente dentro del
MISMO candidato Kalshi, nunca mezclando un nombre de un candidato con el
otro nombre de un candidato distinto.

Alcance de este Tramo (aprobado explícitamente, ver Design Proposal): solo
resuelve cuando existe EXACTAMENTE un candidato que supera el pair-match.
0 candidatos -> NOT_FOUND (`MatchMethod.NO_MATCH`). 2+ candidatos ->
`MatchMethod.NEEDS_REVIEW`, SIN NINGÚN DESEMPATE -- ninguna señal
secundaria (torneo/competition, fecha exacta del ticker, proximidad
temporal, inferencia de round-robin, orden de listado, primer candidato,
score heurístico) puede transformar 2+ candidatos en RESOLVED en esta
iteración. Esa lógica de desempate es el Tramo 2, explícitamente NO
implementado aquí -- pendiente de su propia auditoría empírica.

Duplicación deliberada, documentada como deuda técnica (aprobada
explícitamente en vez de modificar/refactorizar `market_matcher.py`,
compartido con MLB): `_pair_candidate_participants` y
`_select_market_for_participant_a` duplican la lógica exacta de
`src/matching/market_matcher.py::_kalshi_event_participants` y
`::_select_market` respectivamente (ambas privadas, no importadas a
propósito). Si esa lógica cambia en `market_matcher.py`, este archivo
puede divergir silenciosamente -- revisar ambos si se toca cualquiera de
los dos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.matching.event_matcher import MatchResult, name_similarity, participants_similarity
from src.matching.market_matcher import KalshiEventMatch
from src.models.schemas import MatchMethod

TENNIS_PAIR_MATCH_MIN_CONFIDENCE = 0.97
"""Umbral de par completo del Tramo 1 -- deliberadamente estricto: mismo
valor que `match_event()` ya usa para `EXACT_NAME_TIME`
(`src/matching/event_matcher.py`), NO el umbral fuzzy general (0.72,
`EVENT_NAME_MATCH_MIN_CONFIDENCE`). Esta rama nunca tiene la confirmación
de tiempo como respaldo, así que exige el nivel de nombre más alto que ya
existe en el sistema en vez de inventar un número nuevo sin evidencia
propia (pendiente de calibración con muestra real, ver Design Proposal).
Constante AISLADA -- nunca sustituye ni modifica
`EVENT_NAME_MATCH_MIN_CONFIDENCE`/`EVENT_TIME_MATCH_TOLERANCE_MINUTES`/
`TENNIS_LATE_ROUND_TOLERANCE_MINUTES`."""


def _pair_candidate_participants(kalshi_event: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """DUPLICADO deliberado de
    `market_matcher._kalshi_event_participants` (privada, no importada --
    ver docstring de módulo). Misma lógica exacta: título "A vs B" si
    existe, si no los dos primeros mercados."""
    title = kalshi_event.get("title") or ""
    if " vs " in title:
        a, b = title.split(" vs ", 1)
        return a.strip(), b.strip()
    markets = kalshi_event.get("markets") or []
    if len(markets) >= 2:
        return markets[0].get("yes_sub_title"), markets[1].get("yes_sub_title")
    if len(markets) == 1:
        return markets[0].get("yes_sub_title"), markets[0].get("no_sub_title")
    return None, None


def _select_market_for_participant_a(
    kalshi_event: Dict[str, Any], participant_a: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[float]]:
    """DUPLICADO deliberado de `market_matcher._select_market` (privada, no
    importada -- ver docstring de módulo). Misma lógica exacta: mejor
    `yes_sub_title` contra `participant_a` vía `name_similarity` -- nunca
    por posición/orden en `markets`, así que preserva orientación correcta
    incluso si Kalshi listó el par invertido respecto a la fuente."""
    markets = kalshi_event.get("markets") or []
    if not markets:
        return None, "el evento de Kalshi no tiene mercados anidados", None
    if not participant_a:
        return markets[0], "participant_a ausente; se tomó el primer mercado por defecto", None

    best_market = None
    best_score = -1.0
    for market in markets:
        score = name_similarity(participant_a, market.get("yes_sub_title"))
        if score > best_score:
            best_score = score
            best_market = market

    warning = None
    if best_score < 0.72:
        warning = f"selección de mercado por lado YES incierta (similitud {best_score:.2f})"
    return best_market, warning, best_score


@dataclass
class TennisPairResolverDiagnostics:
    """Resumen conciso para observabilidad (ver Design Proposal §8) -- el
    detalle candidato-por-candidato vive solo en logs
    (`run_tennis_pipeline`, `log_step`/`logger.info`), nunca aquí ni en
    `match_warnings` (que sí recibe este resumen agregado)."""

    candidates_examined: int
    candidates_passed_pair_match: int
    outcome: str  # "UNIQUE" | "NEEDS_REVIEW" | "NOT_FOUND"


def resolve_tennis_pair_by_structure(
    source_participant_a: Optional[str],
    source_participant_b: Optional[str],
    kalshi_events: List[Dict[str, Any]],
) -> Tuple[KalshiEventMatch, TennisPairResolverDiagnostics]:
    """Tramo 1 del resolver estructural de pares (tenis, Qualifying/Round
    Robin únicamente -- gate en `tennis_pipeline.py`).

    Evalúa CADA `kalshi_event` de `kalshi_events` (la misma lista ya
    obtenida por `run_tennis_pipeline` vía `kalshi.get_all_events_for_sport`,
    sin fetch nuevo) como candidato independiente, exigiendo que AMBOS
    `source_participant_a`/`source_participant_b` coincidan conjuntamente
    dentro del MISMO candidato (`participants_similarity`, que ya aplica
    `min()` de los dos lados -- nunca se compara `source_a` contra un
    candidato y `source_b` contra otro candidato distinto: es
    estructuralmente imposible que ese escenario produzca RESOLVED). Nunca
    usa tiempo, torneo/competition, orden de listado, ni ninguna otra señal
    secundaria para decidir -- ver docstring de módulo.

    Devuelve `(KalshiEventMatch, TennisPairResolverDiagnostics)`:
      - `source_participant_a`/`b` ausentes -> `NO_MATCH` (mismo criterio
        que `match_event()` para participantes de origen incompletos).
      - 0 candidatos pasan el pair-match -> `NO_MATCH`, `needs_review=True`,
        `selected_market=None`.
      - exactamente 1 -> `TENNIS_STRUCTURAL_PAIR_UNIQUE`,
        `confidence=pair_score`, `needs_review=False`, `selected_market`
        fijado por comparación directa de nombre contra CADA mercado del
        candidato (nunca por orden/posición).
      - 2+ -> `NEEDS_REVIEW` (mismo `MatchMethod.NEEDS_REVIEW` ya
        existente, nunca se fuerza), `selected_market=None` -- ningún
        candidato se privilegia sobre otro, sin desempate (Tramo 2, no
        implementado).
    """
    if not source_participant_a or not source_participant_b:
        result = MatchResult(
            confidence=0.0,
            method=MatchMethod.NO_MATCH,
            warnings=["tennis_structural_pair_resolver: participantes de origen incompletos"],
            needs_review=True,
        )
        return (
            KalshiEventMatch(kalshi_event=None, match_result=result),
            TennisPairResolverDiagnostics(0, 0, "NOT_FOUND"),
        )

    candidates_examined = 0
    passed: List[Tuple[Dict[str, Any], float, bool]] = []

    for kalshi_event in kalshi_events:
        candidates_examined += 1
        try:
            target_a, target_b = _pair_candidate_participants(kalshi_event)
        except (AttributeError, TypeError, KeyError):
            continue
        if not target_a or not target_b:
            continue
        pair_score, swapped = participants_similarity(
            source_participant_a, source_participant_b, target_a, target_b
        )
        if pair_score >= TENNIS_PAIR_MATCH_MIN_CONFIDENCE:
            passed.append((kalshi_event, pair_score, swapped))

    if not passed:
        result = MatchResult(
            confidence=0.0,
            method=MatchMethod.NO_MATCH,
            warnings=[
                "tennis_structural_pair_resolver: 0 candidatos superaron el pair-match "
                f"(examinados={candidates_examined})"
            ],
            needs_review=True,
        )
        return (
            KalshiEventMatch(kalshi_event=None, match_result=result),
            TennisPairResolverDiagnostics(candidates_examined, 0, "NOT_FOUND"),
        )

    if len(passed) > 1:
        result = MatchResult(
            confidence=max(p[1] for p in passed),
            method=MatchMethod.NEEDS_REVIEW,
            warnings=[
                f"tennis_structural_pair_resolver: {len(passed)} candidatos superaron el "
                f"pair-match, sin desempate en Tramo 1 (examinados={candidates_examined})"
            ],
            needs_review=True,
        )
        return (
            KalshiEventMatch(kalshi_event=None, match_result=result),
            TennisPairResolverDiagnostics(candidates_examined, len(passed), "NEEDS_REVIEW"),
        )

    kalshi_event, pair_score, swapped = passed[0]
    selected_market, market_warning, market_selection_confidence = _select_market_for_participant_a(
        kalshi_event, source_participant_a
    )
    warnings = [
        "tennis_structural_pair_resolver: candidato único por par completo "
        f"(examinados={candidates_examined}, pair_score={pair_score:.4f})"
    ]
    if swapped:
        warnings.append("orden de participantes invertido respecto al candidato Kalshi")

    result = MatchResult(
        confidence=pair_score,
        method=MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE,
        warnings=warnings,
        needs_review=False,
        swapped=swapped,
    )
    match = KalshiEventMatch(
        kalshi_event=kalshi_event,
        match_result=result,
        selected_market=selected_market,
        market_selection_warning=market_warning,
        market_selection_confidence=market_selection_confidence,
    )
    return match, TennisPairResolverDiagnostics(candidates_examined, 1, "UNIQUE")
