"""Tests del Tramo 1 del resolver estructural de pares de tenis
(`src/matching/tennis_pair_matcher.py`, 2026-08-15).

Cubre: `resolve_tennis_pair_by_structure` (función pura), el gate
`_tennis_uses_structural_pair_resolver` (`tennis_pipeline.py`), el
wiring end-to-end vía `run_tennis_pipeline`, y el aislamiento de MLB
(estructural: el módulo entero nunca se importa desde el camino MLB).

El caso Faria vs Wu es real, reconstruido en vivo el 2026-08-15 contra las
APIs reales de ESPN/Kalshi (ver informe de la sesión): ESPN
`round.id="14"`/`displayName="Qualifying Final"`, Kalshi
`event_ticker=KXATPMATCH-26AUG12FARYIB`, `product_metadata.competition=
"ATP Cincinnati"`. La captura histórica local no tiene snapshots de
2026-08-11/12 (gap real verificado), así que los valores aquí vienen
directamente de la reconstrucción en vivo documentada en esa sesión, no de
`data/engine.db`.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.kalshi import KalshiConnector
from src.connectors.base_client import FetchResult
from src.matching.event_matcher import MatchResult, _CONFIDENT_METHODS
from src.matching.tennis_pair_matcher import (
    TENNIS_PAIR_MATCH_MIN_CONFIDENCE,
    resolve_tennis_pair_by_structure,
)
from src.models.schemas import MatchMethod
from src.pipelines.tennis_pipeline import _tennis_uses_structural_pair_resolver, run_tennis_pipeline


def _kalshi_event(event_ticker, title, yes_sub_title_a, yes_sub_title_b):
    """Mismo shape real que `kalshi_atp_events_sample.json` (título "A vs
    B", dos mercados con yes_sub_title por lado)."""
    return {
        "event_ticker": event_ticker,
        "series_ticker": "KXATPMATCH",
        "title": title,
        "markets": [
            {"ticker": f"{event_ticker}-A", "event_ticker": event_ticker,
             "yes_sub_title": yes_sub_title_a, "no_sub_title": yes_sub_title_b},
            {"ticker": f"{event_ticker}-B", "event_ticker": event_ticker,
             "yes_sub_title": yes_sub_title_b, "no_sub_title": yes_sub_title_a},
        ],
    }


# ---------------------------------------------------------------------
# 1. Faria vs Wu -- caso real reconstruido
# ---------------------------------------------------------------------

def test_faria_vs_wu_real_case_resolves_unique():
    """Reconstrucción real (2026-08-15, ver informe de sesión): ESPN
    'Jaime Faria'/'Wu Yibing' (orden apellido-primero), Kalshi event_ticker
    KXATPMATCH-26AUG12FARYIB con mercados -FAR ('Jaime Faria')/-YIB
    ('Yibing Wu', orden nombre-primero, invertido). Antes de este Tramo,
    match_event() con tolerancia=330 (Qualifying) daba NEEDS_REVIEW porque
    el delta real era 390min. Este resolver nunca usa tiempo: debe resolver
    RESOLVED por candidato único."""
    events = [_kalshi_event("KXATPMATCH-26AUG12FARYIB", "Faria vs Wu", "Jaime Faria", "Yibing Wu")]

    match, diagnostics = resolve_tennis_pair_by_structure("Jaime Faria", "Wu Yibing", events)

    assert match.match_result.method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert match.match_result.is_confident
    assert not match.match_result.needs_review
    assert match.match_result.confidence == pytest.approx(1.0)
    assert diagnostics.outcome == "UNIQUE"
    assert diagnostics.candidates_examined == 1
    assert diagnostics.candidates_passed_pair_match == 1
    # orientación: selected_market debe ser el lado -FAR (yes_sub_title == participant_a)
    assert match.selected_market["ticker"] == "KXATPMATCH-26AUG12FARYIB-A"
    assert match.selected_market["yes_sub_title"] == "Jaime Faria"


# ---------------------------------------------------------------------
# 2-3. Candidato único A-B / B-A
# ---------------------------------------------------------------------

def test_single_candidate_direct_order_resolves():
    events = [_kalshi_event("KXATPMATCH-26AUG20ONETWO", "Player One vs Player Two", "Player One", "Player Two")]
    match, diagnostics = resolve_tennis_pair_by_structure("Player One", "Player Two", events)
    assert match.match_result.method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert diagnostics.outcome == "UNIQUE"
    assert not match.match_result.swapped


def test_single_candidate_swapped_order_still_identifies_same_match():
    """Kalshi lista el par como 'Player Two vs Player One' (orden
    invertido respecto a la fuente) -- debe seguir identificando el mismo
    encuentro (swapped=True), nunca fallar por el orden."""
    events = [_kalshi_event("KXATPMATCH-26AUG20TWOONE", "Player Two vs Player One", "Player Two", "Player One")]
    match, diagnostics = resolve_tennis_pair_by_structure("Player One", "Player Two", events)
    assert match.match_result.method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert match.match_result.swapped is True
    assert diagnostics.outcome == "UNIQUE"


def test_orientation_preserved_after_swapped_order():
    """Preservación de side: aunque Kalshi liste el par invertido, el
    mercado seleccionado debe seguir siendo el que corresponde a
    participant_a por NOMBRE, nunca por posición."""
    events = [_kalshi_event("KXATPMATCH-26AUG20TWOONE", "Player Two vs Player One", "Player Two", "Player One")]
    match, _ = resolve_tennis_pair_by_structure("Player One", "Player Two", events)
    assert match.selected_market["yes_sub_title"] == "Player One"


# ---------------------------------------------------------------------
# 4. Cero candidatos conjuntos -> NOT_FOUND
# ---------------------------------------------------------------------

def test_zero_candidates_not_found():
    match, diagnostics = resolve_tennis_pair_by_structure("Player One", "Player Two", [])
    assert match.match_result.method == MatchMethod.NO_MATCH
    assert match.match_result.needs_review
    assert match.kalshi_event is None
    assert match.selected_market is None
    assert diagnostics.outcome == "NOT_FOUND"
    assert diagnostics.candidates_passed_pair_match == 0


def test_no_candidate_matches_pair_not_found():
    events = [_kalshi_event("KXATPMATCH-26AUG20XXXYYY", "Player Xxx vs Player Yyy", "Player Xxx", "Player Yyy")]
    match, diagnostics = resolve_tennis_pair_by_structure("Player One", "Player Two", events)
    assert match.match_result.method == MatchMethod.NO_MATCH
    assert diagnostics.outcome == "NOT_FOUND"
    assert diagnostics.candidates_examined == 1
    assert diagnostics.candidates_passed_pair_match == 0


# ---------------------------------------------------------------------
# 5. Dos candidatos con el par completo -> NEEDS_REVIEW, sin desempate
# ---------------------------------------------------------------------

def test_two_candidates_with_full_pair_needs_review():
    """Mismo par en dos eventos Kalshi distintos (ej. round-robin
    rematch) -- ninguna señal secundaria (fecha, torneo, orden) debe
    desempatar en este Tramo."""
    events = [
        _kalshi_event("KXATPMATCH-26AUG10ONETWO", "Player One vs Player Two", "Player One", "Player Two"),
        _kalshi_event("KXATPMATCH-26AUG20ONETWO", "Player One vs Player Two", "Player One", "Player Two"),
    ]
    match, diagnostics = resolve_tennis_pair_by_structure("Player One", "Player Two", events)
    assert match.match_result.method == MatchMethod.NEEDS_REVIEW
    assert match.match_result.needs_review
    assert match.kalshi_event is None
    assert match.selected_market is None
    assert diagnostics.outcome == "NEEDS_REVIEW"
    assert diagnostics.candidates_passed_pair_match == 2


# ---------------------------------------------------------------------
# 6. A coincide con X, B coincide con Y, X != Y -> nunca RESOLVED
# ---------------------------------------------------------------------

def test_a_matches_one_candidate_b_matches_another_never_resolved():
    """Invariante central: nunca se combina el nombre de A de un
    candidato con el nombre de B de OTRO candidato distinto."""
    events = [
        _kalshi_event("KXATPMATCH-26AUG20ALPGAM", "Player Alpha vs Player Gamma", "Player Alpha", "Player Gamma"),
        _kalshi_event("KXATPMATCH-26AUG20DELBET", "Player Delta vs Player Beta", "Player Delta", "Player Beta"),
    ]
    match, diagnostics = resolve_tennis_pair_by_structure("Player Alpha", "Player Beta", events)
    assert match.match_result.method != MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert diagnostics.outcome in ("NOT_FOUND", "NEEDS_REVIEW")
    assert diagnostics.candidates_passed_pair_match == 0


# ---------------------------------------------------------------------
# 7. Apellido/nombre compartido tipo "Daniel" -> no fuerza resolución
# ---------------------------------------------------------------------

def test_shared_first_name_does_not_force_resolution():
    """'Daniel Merida' (fuente) vs 'Daniel Smith' (candidato, comparte
    solo el nombre de pila) -- ya probado a nivel de name_similarity
    (test_event_matcher.py); aquí se prueba que el resolver completo
    tampoco lo fuerza."""
    events = [_kalshi_event("KXATPMATCH-26AUG20DANTIE", "Daniel Smith vs Learner Tien", "Daniel Smith", "Learner Tien")]
    match, diagnostics = resolve_tennis_pair_by_structure("Daniel Merida", "Learner Tien", events)
    assert match.match_result.method != MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert diagnostics.candidates_passed_pair_match == 0


# ---------------------------------------------------------------------
# 8. Nombres normalizados / abreviaciones / acentos
# ---------------------------------------------------------------------

def test_unicode_accented_name_normalizes_and_resolves():
    events = [_kalshi_event("KXATPMATCH-26AUG20LUKNAD", "Lukasz Kubot vs Rafael Nadal", "Lukasz Kubot", "Rafael Nadal")]
    match, diagnostics = resolve_tennis_pair_by_structure("Łukasz Kubot", "Rafael Nadal", events)
    assert match.match_result.method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert diagnostics.outcome == "UNIQUE"


def test_min_confidence_threshold_is_isolated_constant():
    """Confirma que el umbral es una constante nueva y aislada, no una
    reutilización/mutación de un threshold global existente."""
    from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE

    assert TENNIS_PAIR_MATCH_MIN_CONFIDENCE == 0.97
    assert TENNIS_PAIR_MATCH_MIN_CONFIDENCE != EVENT_NAME_MATCH_MIN_CONFIDENCE


# ---------------------------------------------------------------------
# 9. Participantes de origen ausentes
# ---------------------------------------------------------------------

def test_missing_source_participant_never_forces_match():
    match, diagnostics = resolve_tennis_pair_by_structure(None, "Player Two", [])
    assert match.match_result.method == MatchMethod.NO_MATCH
    assert match.match_result.needs_review
    assert diagnostics.outcome == "NOT_FOUND"


# ---------------------------------------------------------------------
# 10-12. Gate determinístico por ronda
# ---------------------------------------------------------------------

def _espn_match(round_id=None, round_name=None):
    return {"round": {"id": round_id, "displayName": round_name}} if (round_id or round_name) else {"round": {}}


@pytest.mark.parametrize("round_name", ["Qualifying 1st Round", "Qualifying Final", "Qualifying 2nd Round"])
def test_qualifying_enters_structural_pair_resolver(round_name):
    assert _tennis_uses_structural_pair_resolver(_espn_match(None, round_name)) is True


@pytest.mark.parametrize("round_id,round_name", [("15", "Group Stage"), (None, "Group Stage"), (None, "GROUP STAGE")])
def test_group_stage_enters_structural_pair_resolver(round_id, round_name):
    """Verificado en vivo contra la API real de ESPN (2026-08-15, dos
    torneos reales distintos: Nitto ATP Finals y WTA Finals, ambos
    formato round-robin) -- round.id='15'/displayName='Group Stage' es el
    ÚNICO valor real observado para este formato. 'Round Robin' (texto)
    NUNCA aparece en datos reales -- ver test siguiente."""
    assert _tennis_uses_structural_pair_resolver(_espn_match(round_id, round_name)) is True


def test_literal_round_robin_text_never_seen_in_real_data_does_not_enter():
    """'Round Robin' era la suposición inicial (sin verificar) -- la
    verificación real (2026-08-15) confirmó que ESPN nunca usa ese texto;
    el valor real es 'Group Stage' (id=15, ver test anterior). Este test
    documenta explícitamente que la cadena no verificada NO activa el
    gate -- fail-closed, ninguna variante inventada."""
    assert _tennis_uses_structural_pair_resolver(_espn_match(None, "Round Robin")) is False


@pytest.mark.parametrize(
    "round_id,round_name",
    [
        ("1", "Round 1"), ("2", "Round 2"), ("3", "Round 3"), ("4", "Round 4"),
        ("5", "Quarterfinal"), ("6", "Semifinal"), ("7", "Final"),
    ],
)
def test_unauthorized_round_does_not_enter_structural_pair_resolver(round_id, round_name):
    assert _tennis_uses_structural_pair_resolver(_espn_match(round_id, round_name)) is False


def test_unknown_or_missing_round_does_not_enter_structural_pair_resolver():
    assert _tennis_uses_structural_pair_resolver({}) is False
    assert _tennis_uses_structural_pair_resolver({"round": None}) is False


# ---------------------------------------------------------------------
# 13. Wiring end-to-end vía run_tennis_pipeline -- Qualifying entra,
#     QF/SF/Final no (regresión del camino existente, sin tocarlo)
# ---------------------------------------------------------------------

def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


def _espn_scoreboard_payload(match_id, participant_a, participant_b, iso_date, round_id, round_name, tournament_name="Test Open"):
    return {
        "events": [{
            "name": tournament_name,
            "groupings": [{
                "grouping": {"displayName": "Men's Singles"},
                "competitions": [{
                    "id": match_id,
                    "date": iso_date,
                    "status": {"type": {"state": "pre"}},
                    "round": {"id": round_id, "displayName": round_name},
                    "competitors": [
                        {"homeAway": "home", "id": "espn_id_a", "athlete": {"displayName": participant_a}},
                        {"homeAway": "away", "id": "espn_id_b", "athlete": {"displayName": participant_b}},
                    ],
                }],
            }],
        }]
    }


def test_pipeline_wiring_qualifying_uses_structural_pair_resolver(monkeypatch):
    monkeypatch.setattr(
        EspnTennisConnector, "get_scoreboard",
        lambda self, tour, date: _ok(_espn_scoreboard_payload(
            "999001", "Player One", "Player Two", "2026-08-12T19:20:00Z", "14", "Qualifying Final",
        )),
    )
    kalshi_events_payload = {"events": [_kalshi_event("KXATPMATCH-26AUG12ONETWO", "Player One vs Player Two", "Player One", "Player Two")]}
    monkeypatch.setattr(
        KalshiConnector, "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok(kalshi_events_payload),
    )

    result = run_tennis_pipeline("ATP", "20260812", fetch_features=False, enrich_sofascore=False)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.data_quality.match_method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert not record.data_quality.needs_review
    assert record.market_id == "KXATPMATCH-26AUG12ONETWO-A"


def test_pipeline_wiring_quarterfinal_still_uses_existing_path(monkeypatch):
    """Regresión: QF debe seguir usando find_best_kalshi_event (tolerancia
    330), no el resolver nuevo -- si el delta excede 330min, debe caer a
    NEEDS_REVIEW igual que antes de este Tramo."""
    monkeypatch.setattr(
        EspnTennisConnector, "get_scoreboard",
        lambda self, tour, date: _ok(_espn_scoreboard_payload(
            "999002", "Player Three", "Player Four", "2026-08-12T19:20:00Z", "5", "Quarterfinal",
        )),
    )
    far_future_occurrence = "2026-08-11T00:00:00Z"  # delta > 330min respecto al start real
    kalshi_events_payload = {"events": [
        {
            "event_ticker": "KXATPMATCH-26AUG11THRFOU",
            "series_ticker": "KXATPMATCH",
            "title": "Player Three vs Player Four",
            "markets": [
                {"ticker": "KXATPMATCH-26AUG11THRFOU-A", "event_ticker": "KXATPMATCH-26AUG11THRFOU",
                 "yes_sub_title": "Player Three", "no_sub_title": "Player Four", "occurrence_datetime": far_future_occurrence},
                {"ticker": "KXATPMATCH-26AUG11THRFOU-B", "event_ticker": "KXATPMATCH-26AUG11THRFOU",
                 "yes_sub_title": "Player Four", "no_sub_title": "Player Three", "occurrence_datetime": far_future_occurrence},
            ],
        }
    ]}
    monkeypatch.setattr(
        KalshiConnector, "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok(kalshi_events_payload),
    )

    result = run_tennis_pipeline("ATP", "20260812", fetch_features=False, enrich_sofascore=False)

    record = result.records[0]
    assert record.data_quality.match_method != MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert record.data_quality.needs_review


# ---------------------------------------------------------------------
# 14. Aislamiento MLB
# ---------------------------------------------------------------------

def test_mlb_pipeline_never_references_tennis_pair_matcher():
    import src.pipelines.mlb_pipeline as mlb_pipeline_module
    import src.matching.market_matcher as market_matcher_module

    for module in (mlb_pipeline_module, market_matcher_module):
        source = inspect.getsource(module)
        assert "tennis_pair_matcher" not in source
        assert "resolve_tennis_pair_by_structure" not in source
        assert "TENNIS_STRUCTURAL_PAIR_UNIQUE" not in source


def test_mlb_pipeline_wiring_never_produces_new_method(monkeypatch):
    """Regresión funcional (no solo estructural): un partido MLB real
    resuelto vía find_best_kalshi_event/apply_kalshi_match (camino sin
    cambios) nunca puede producir TENNIS_STRUCTURAL_PAIR_UNIQUE."""
    from src.pipelines.mlb_pipeline import run_mlb_pipeline
    from src.connectors.mlb import MlbConnector

    monkeypatch.setattr(
        KalshiConnector, "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({
            "events": [{
                "event_ticker": "KXMLBGAME-26AUG12AAABBB",
                "title": "Team AAA vs Team BBB",
                "markets": [
                    {"ticker": "KXMLBGAME-26AUG12AAABBB-AAA", "event_ticker": "KXMLBGAME-26AUG12AAABBB",
                     "yes_sub_title": "Team AAA", "occurrence_datetime": "2026-08-12T19:00:00Z"},
                    {"ticker": "KXMLBGAME-26AUG12AAABBB-BBB", "event_ticker": "KXMLBGAME-26AUG12AAABBB",
                     "yes_sub_title": "Team BBB", "occurrence_datetime": "2026-08-12T19:00:00Z"},
                ],
            }]
        }),
    )
    monkeypatch.setattr(
        MlbConnector, "get_schedule",
        lambda self, date: _ok({"dates": [{"games": [{
            "gamePk": 1,
            "gameDate": "2026-08-12T19:00:00Z",
            "status": {"detailedState": "Scheduled"},
            "teams": {
                "home": {"team": {"id": 1, "name": "Team AAA"}},
                "away": {"team": {"id": 2, "name": "Team BBB"}},
            },
        }]}]}),
    )

    result = run_mlb_pipeline("2026-08-12", fetch_features=False, fetch_boxscore=False, fetch_pitcher_stats=False)
    for record in result.records:
        assert record.data_quality.match_method != MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE


def test_confident_methods_includes_new_tennis_method():
    assert MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE in _CONFIDENT_METHODS


def test_new_method_is_confident_when_not_needs_review():
    result = MatchResult(confidence=1.0, method=MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE, needs_review=False)
    assert result.is_confident is True
