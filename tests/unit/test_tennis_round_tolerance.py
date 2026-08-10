"""Tests de la politica de tolerancia de tenis por ronda (Fase de
recalibracion 2026-08-10, ver CONTINUITY.md). Cubre:

  1. `_tennis_round_tolerance_minutes` -- seleccion 240/330 a partir del
     campo ESTRUCTURADO de ESPN (`match["round"]`), nunca texto de Kalshi.
  2. Casos reales capturados en la auditoria (Merida vs Tien, Shapovalov
     vs Svrcina, limite exacto de 330min, Round Of 128 con delta grande)
     via `find_best_kalshi_event`, para probar el camino completo de
     matching con la tolerancia ya seleccionada -- no solo la funcion
     aislada.
  3. Regresion: mismo par de jugadores con eventos Kalshi en semanas
     distintas (hallazgo real de la auditoria, 35/39 casos) sigue
     resolviendose al candidato temporalmente correcto bajo la tolerancia
     ampliada, sin confundirse con el de la semana equivocada.
  4. Regresion: MLB no se ve afectado (no importa esta constante, y su
     tolerancia sigue en 90min).

No se modifica `match_event()` ni su firma -- estos tests llaman a
`find_best_kalshi_event`/`match_event` exactamente como ya lo hacian,
solo variando el `tolerance_minutes` que se les pasa, igual que hace
`run_tennis_pipeline` en produccion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT, TENNIS_LATE_ROUND_TOLERANCE_MINUTES
from src.connectors.kalshi import KalshiConnector
from src.matching.event_matcher import match_event
from src.matching.market_matcher import find_best_kalshi_event
from src.models.schemas import MatchMethod
from src.pipelines.tennis_pipeline import _tennis_round_tolerance_minutes


# ---------------------------------------------------------------------
# 1. Seleccion de tolerancia por ronda (funcion aislada)
# ---------------------------------------------------------------------

def _espn_match(round_id=None, round_name=None):
    return {"round": {"id": round_id, "displayName": round_name}} if (round_id or round_name) else {"round": {}}


@pytest.mark.parametrize(
    "round_id,round_name",
    [
        ("5", "Quarterfinal"),
        ("6", "Semifinal"),
        ("7", "Final"),
    ],
)
def test_late_stage_round_id_gets_330(round_id, round_name):
    assert _tennis_round_tolerance_minutes(_espn_match(round_id, round_name)) == TENNIS_LATE_ROUND_TOLERANCE_MINUTES


def test_late_stage_round_detected_by_displayname_even_without_id():
    # "y/o displayName segun corresponda" -- no depende exclusivamente del id.
    assert _tennis_round_tolerance_minutes(_espn_match(None, "Quarterfinal")) == 330


@pytest.mark.parametrize(
    "round_name",
    ["Qualifying 1st Round", "Qualifying Final", "Qualifying 2nd Round"],
)
def test_qualifying_rounds_get_330(round_name):
    # Detectado por displayName ("qualif...") -- no se asume una lista de
    # ids no verificada contra datos reales (solo 11 y 14 se observaron).
    assert _tennis_round_tolerance_minutes(_espn_match(None, round_name)) == 330


@pytest.mark.parametrize("round_id,round_name", [("1", "Round 1"), ("2", "Round 2"), ("3", "Round 3"), ("4", "Round 4")])
def test_early_rounds_keep_240(round_id, round_name):
    """Round Of 128/64/32/16 (Round 1-4 en la numeracion de ESPN) NUNCA
    reciben 330 -- verificado (auditoria): ampliar la tolerancia ahi no
    ayuda (<76% de cobertura incluso a 480min) y solo aumentaria riesgo."""
    tol = _tennis_round_tolerance_minutes(_espn_match(round_id, round_name))
    assert tol == EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["TENNIS"] == 240


def test_unknown_or_missing_round_falls_back_to_240():
    assert _tennis_round_tolerance_minutes({}) == 240
    assert _tennis_round_tolerance_minutes({"round": None}) == 240
    assert _tennis_round_tolerance_minutes(_espn_match("99", "Round Robin")) == 240


# ---------------------------------------------------------------------
# Helpers para construir eventos Kalshi sinteticos (misma forma que el
# fixture real kalshi_atp_events_sample.json)
# ---------------------------------------------------------------------

def _kalshi_event(event_ticker, participant_a, participant_b, occurrence_iso):
    side_a = participant_a.split()[-1][:3].upper()
    side_b = participant_b.split()[-1][:3].upper()
    return {
        "event_ticker": event_ticker,
        "series_ticker": "KXATPMATCH",
        "title": f"{participant_a} vs {participant_b}",
        "markets": [
            {
                "ticker": f"{event_ticker}-{side_a}",
                "event_ticker": event_ticker,
                "yes_sub_title": participant_a,
                "no_sub_title": participant_b,
                "occurrence_datetime": occurrence_iso,
            },
            {
                "ticker": f"{event_ticker}-{side_b}",
                "event_ticker": event_ticker,
                "yes_sub_title": participant_b,
                "no_sub_title": participant_a,
                "occurrence_datetime": occurrence_iso,
            },
        ],
    }


# ---------------------------------------------------------------------
# 2. Casos reales capturados en la auditoria (via find_best_kalshi_event)
# ---------------------------------------------------------------------

def test_merida_vs_tien_real_case_becomes_confident_with_330():
    """Caso real 2026-08-10: KXATPMATCH-26AUG10MERTIE-TIE, Cuartos de
    Final, delta real=300min. Con tolerancia=240 (la de antes) fallaba
    (NEEDS_REVIEW); con 330 (la nueva, para Cuartos+) debe confirmarse."""
    kalshi_dt = datetime(2026, 8, 10, 23, 0, tzinfo=timezone.utc)
    espn_dt = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)  # delta real = -300min
    events = [_kalshi_event("KXATPMATCH-26AUG10MERTIE", "Daniel Merida", "Learner Tien", kalshi_dt.isoformat())]

    espn_match = _espn_match("5", "Quarterfinal")
    tolerance = _tennis_round_tolerance_minutes(espn_match)
    assert tolerance == 330

    result = find_best_kalshi_event("Daniel Merida", "Learner Tien", espn_dt, events, tolerance_minutes=tolerance)
    assert result.match_result.is_confident
    assert result.match_result.method == MatchMethod.EXACT_NAME_TIME


def test_merida_vs_tien_real_case_still_failed_with_old_240_tolerance():
    """Confirma que el bug reportado era real: con la tolerancia vieja
    (240, la que Round Of 128/64/32/16 sigue usando) este mismo caso NO
    se confirmaba -- documenta el "antes" exacto del fix."""
    kalshi_dt = datetime(2026, 8, 10, 23, 0, tzinfo=timezone.utc)
    espn_dt = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)
    events = [_kalshi_event("KXATPMATCH-26AUG10MERTIE", "Daniel Merida", "Learner Tien", kalshi_dt.isoformat())]

    result = find_best_kalshi_event("Daniel Merida", "Learner Tien", espn_dt, events, tolerance_minutes=240)
    assert not result.match_result.is_confident


def test_exact_330_minute_boundary_is_confident():
    """Limite exacto: delta=330min con tolerancia=330 debe confirmar
    (match_event usa <=, inclusivo)."""
    kalshi_dt = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    espn_dt = kalshi_dt + timedelta(minutes=330)
    events = [_kalshi_event("KXATPMATCH-26AUG10AAABBB", "Player Aaa", "Player Bbb", kalshi_dt.isoformat())]

    result = find_best_kalshi_event("Player Aaa", "Player Bbb", espn_dt, events, tolerance_minutes=330)
    assert result.match_result.is_confident
    assert result.match_result.method == MatchMethod.EXACT_NAME_TIME


def test_shapovalov_vs_svrcina_real_case_stays_needs_review():
    """Caso real 2026-07-30 (ATP Los Cabos, Cuartos de Final): delta real
    de -490min, el unico de los 77 casos auditados que queda FUERA de
    330min. Debe seguir en NEEDS_REVIEW -- el sistema es honesto sobre su
    limite real, no se fabrica un match."""
    kalshi_dt = datetime(2026, 7, 30, 19, 30, tzinfo=timezone.utc)
    espn_dt = kalshi_dt + timedelta(minutes=490)
    events = [_kalshi_event("KXATPMATCH-26JUL30SHASVR", "Denis Shapovalov", "Dalibor Svrcina", kalshi_dt.isoformat())]

    espn_match = _espn_match("5", "Quarterfinal")
    tolerance = _tennis_round_tolerance_minutes(espn_match)
    result = find_best_kalshi_event("Denis Shapovalov", "Dalibor Svrcina", espn_dt, events, tolerance_minutes=tolerance)
    assert not result.match_result.is_confident
    assert result.match_result.method == MatchMethod.NEEDS_REVIEW


def test_round_of_128_large_delta_still_needs_review_under_new_policy():
    """Caso real observado (Round Of 128, delta mediano ~1395min/23h):
    con la politica nueva esta ronda sigue en 240 (no 330) -- confirma
    que 330 NO se filtra por accidente a rondas tempranas."""
    kalshi_dt = datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc)
    espn_dt = kalshi_dt + timedelta(minutes=1395)  # delta mediano real observado para Round Of 128
    events = [_kalshi_event("KXATPMATCH-26AUG01SONGRI", "Lorenzo Sonego", "Tallon Griekspoor", kalshi_dt.isoformat())]

    espn_match = _espn_match("1", "Round 1")  # Round Of 128 en la numeracion de Kalshi
    tolerance = _tennis_round_tolerance_minutes(espn_match)
    assert tolerance == 240  # nunca 330

    result = find_best_kalshi_event("Lorenzo Sonego", "Tallon Griekspoor", espn_dt, events, tolerance_minutes=tolerance)
    assert not result.match_result.is_confident


# ---------------------------------------------------------------------
# 3. Guardrails de la auditoria: mismo jugador/mismo dia, mismo par en
#    multiples eventos -- deben seguir sin forzar un match equivocado
#    bajo la tolerancia ampliada.
# ---------------------------------------------------------------------

def test_same_pair_multiple_weeks_selects_temporally_correct_event():
    """Hallazgo real de la auditoria (35/39 casos ambiguos): el mismo par
    de jugadores aparece en dos eventos Kalshi de semanas distintas (ej.
    Ruud vs Cerundolo en Gstaad y luego en Montreal). Con tolerancia
    ampliada a 330min, el candidato de la semana equivocada (dias de
    diferencia) sigue sin calificar -- su confidence queda penalizada
    (name_score*0.5) frente al candidato correcto (confidence=1.0)."""
    wrong_week_dt = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)  # Gstaad, semana equivocada
    correct_week_dt = datetime(2026, 8, 5, 19, 30, tzinfo=timezone.utc)  # Montreal, semana correcta
    source_start = correct_week_dt + timedelta(minutes=120)  # ESPN real, cerca solo del evento correcto

    events = [
        _kalshi_event("KXATPMATCH-26JUL17CERRUU", "Casper Ruud", "Francisco Cerundolo", wrong_week_dt.isoformat()),
        _kalshi_event("KXATPMATCH-26AUG05RUUCER", "Casper Ruud", "Francisco Cerundolo", correct_week_dt.isoformat()),
    ]

    result = find_best_kalshi_event("Casper Ruud", "Francisco Cerundolo", source_start, events, tolerance_minutes=330)
    assert result.match_result.is_confident
    assert result.kalshi_event["event_ticker"] == "KXATPMATCH-26AUG05RUUCER"

    # El candidato de la semana equivocada, evaluado aislado, nunca
    # califica como confidente aunque el nombre sea perfecto -- confirma
    # que el filtro de tiempo (no solo la eleccion del "mejor") lo protege.
    wrong_week_result = match_event(
        "Casper Ruud", "Francisco Cerundolo", source_start,
        "Casper Ruud", "Francisco Cerundolo", wrong_week_dt,
        tolerance_minutes=330,
    )
    assert not wrong_week_result.is_confident


def test_same_player_same_day_different_opponent_not_confused():
    """Guardrail: dos eventos Kalshi el mismo dia comparten un jugador
    pero con RIVALES distintos -- `participants_similarity` exige que
    AMBOS nombres alineen (minimo de los dos scores), asi que el evento
    con el rival equivocado nunca puede ganarle al correcto solo por
    compartir un jugador."""
    same_day = datetime(2026, 8, 10, 19, 0, tzinfo=timezone.utc)
    events = [
        _kalshi_event("KXATPMATCH-26AUG10XXXYYY", "Player Xxx", "Player Yyy", same_day.isoformat()),
        _kalshi_event("KXATPMATCH-26AUG10XXXZZZ", "Player Xxx", "Player Zzz", (same_day + timedelta(minutes=30)).isoformat()),
    ]

    # La fuente real es Xxx vs Yyy -- el evento con Zzz no debe ganar.
    result = find_best_kalshi_event("Player Xxx", "Player Yyy", same_day, events, tolerance_minutes=330)
    assert result.match_result.is_confident
    assert result.kalshi_event["event_ticker"] == "KXATPMATCH-26AUG10XXXYYY"


# ---------------------------------------------------------------------
# 4. Regresion MLB
# ---------------------------------------------------------------------

def test_mlb_tolerance_untouched():
    assert EVENT_TIME_MATCH_TOLERANCE_MINUTES_BY_SPORT["MLB"] == 90


def test_mlb_pipeline_does_not_reference_tennis_round_tolerance():
    """MLB nunca debe importar ni usar la constante nueva -- confirma que
    el cambio esta genuinamente acotado a tenis."""
    import inspect

    import src.pipelines.mlb_pipeline as mlb_pipeline_module

    source = inspect.getsource(mlb_pipeline_module)
    assert "TENNIS_LATE_ROUND_TOLERANCE_MINUTES" not in source
    assert "_tennis_round_tolerance_minutes" not in source
