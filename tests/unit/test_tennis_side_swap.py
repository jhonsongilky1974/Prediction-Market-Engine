"""Tests de la corrección de orientación de lado de mercado en tenis
(Fase de recalibración 2026-08-10, ver CONTINUITY.md).

`run_tennis_pipeline` produce un solo `NormalizedRecord` por partido real,
con un solo lado del mercado de Kalshi (2 lados) adjunto -- el ticker del
lado NO adjunto nunca encontraba coincidencia en `resolve_ticker`, aunque
el evento ya estuviera confidentemente resuelto (bug real reproducido con
Jodar/Fils lado FIL y Merida/Tien lado TIE, sin relación con la tolerancia
por ronda). `_resolve_other_side_tennis` (`src/api/event_resolver.py`)
construye la perspectiva invertida reutilizando `apply_kalshi_match` tal
cual -- estos tests usan nombres genéricos ("Player One"/"Player Two"),
nunca un ticker real, para probar que la solución generaliza.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.api import event_resolver as resolver_module
from src.api.event_resolver import resolve_ticker
from src.connectors.base_client import FetchResult
from src.connectors.kalshi import KalshiConnector
from src.features.tennis_features import TennisFeatureInputs
from src.models.schemas import MatchMethod, NormalizedRecord, Sport, TennisVariables


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


_EVENT_TICKER = "KXATPMATCH-26AUG10ONETWO"

_TENNIS_EVENT = {
    "event_ticker": _EVENT_TICKER,
    "title": "Player One vs Player Two",
    "product_metadata": {"competition": "Test Open"},
    "markets": [
        {
            "ticker": f"{_EVENT_TICKER}-ONE",
            "event_ticker": _EVENT_TICKER,
            "yes_sub_title": "Player One",
            "no_sub_title": "Player Two",
            "yes_bid_dollars": "0.6000",
            "yes_ask_dollars": "0.6200",
            "no_bid_dollars": "0.3800",
            "no_ask_dollars": "0.4000",
            "occurrence_datetime": "2026-08-10T19:30:00Z",
            "close_time": "2026-08-24T19:30:00Z",
            "expected_expiration_time": "2026-08-10T19:30:00Z",
        },
        {
            # Precios deliberadamente NO complementarios de los de ONE
            # (0.39 != 1-0.62) -- si el swap estuviera copiando/invirtiendo
            # el precio del otro lado en vez de leer el propio, este test
            # lo detectaria.
            "ticker": f"{_EVENT_TICKER}-TWO",
            "event_ticker": _EVENT_TICKER,
            "yes_sub_title": "Player Two",
            "no_sub_title": "Player One",
            "yes_bid_dollars": "0.3900",
            "yes_ask_dollars": "0.4100",
            "no_bid_dollars": "0.5900",
            "no_ask_dollars": "0.6100",
            "occurrence_datetime": "2026-08-10T19:30:00Z",
            "close_time": "2026-08-24T19:30:00Z",
            "expected_expiration_time": "2026-08-10T19:30:00Z",
        },
    ],
}


def _sibling_record(prior_a=None, prior_b=None, ranking_a=None, ranking_b=None):
    """Registro confidentemente resuelto al lado ONE (participant_a =
    "Player One"), tal como lo dejaria `run_tennis_pipeline` hoy."""
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_999999",
        source_event_ids={"kalshi": _EVENT_TICKER, "espn_tennis": "999999"},
        market_id=f"{_EVENT_TICKER}-ONE",
        source_market_id=f"{_EVENT_TICKER}-ONE",
        participant_a="Player One",
        participant_b="Player Two",
        tennis_variables=TennisVariables(ranking_a=ranking_a, ranking_b=ranking_b),
    )
    record.market.yes_bid = 0.60
    record.market.yes_ask = 0.62
    record.data_quality.match_confidence = 1.0
    record.data_quality.match_method = MatchMethod.EXACT_NAME_TIME
    record.data_quality.needs_review = False
    record.data_quality.missing_fields = []
    record.model_inputs.context = {
        "tournament_name": "Test Open",
        "tour": "atp",
        "participant_a_espn_id": "espn_id_one",
        "participant_b_espn_id": "espn_id_two",
        "tournament_round": "Quarterfinal",
    }
    feature_inputs = TennisFeatureInputs(
        prior_match_start_times={"participant_a": prior_a or [], "participant_b": prior_b or []}
    )
    return record, feature_inputs


class _FakeTennisPipelineResult:
    def __init__(self, records, feature_inputs_list=None, feature_cutoffs=None, steps=None):
        self.records = records
        self.feature_inputs_list = feature_inputs_list or [None] * len(records)
        self.feature_cutoffs = feature_cutoffs or [None] * len(records)
        self.steps = steps or []


def _patch_kalshi(monkeypatch, event=_TENNIS_EVENT):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({"events": [event]}),
    )


# ---------------------------------------------------------------------
# 1. Swap correcto: participante, mercado y precios del lado propio
# ---------------------------------------------------------------------

def test_resolves_other_side_with_correct_participant_and_own_market_price(monkeypatch):
    _patch_kalshi(monkeypatch)
    sibling, feature_inputs = _sibling_record()
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )

    resolved = resolve_ticker(f"{_EVENT_TICKER}-TWO")

    assert resolved.record.market_id == f"{_EVENT_TICKER}-TWO"
    assert resolved.record.participant_a == "Player Two"
    assert resolved.record.participant_b == "Player One"
    # precio propio del lado TWO, no el complementario/copiado de ONE
    assert resolved.record.market.yes_ask == pytest.approx(0.41)
    assert resolved.record.market.yes_bid == pytest.approx(0.39)


def test_original_side_still_resolves_unaffected(monkeypatch):
    """El lado que ya funcionaba (ONE) sigue funcionando exactamente
    igual -- la nueva rama nunca se ejecuta para el caso ya cubierto."""
    _patch_kalshi(monkeypatch)
    sibling, feature_inputs = _sibling_record()
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )

    resolved = resolve_ticker(f"{_EVENT_TICKER}-ONE")
    assert resolved.record is sibling
    assert resolved.record.participant_a == "Player One"


# ---------------------------------------------------------------------
# 2. Orientación consistente: contexto (espn ids) y ranking swap
# ---------------------------------------------------------------------

def test_participant_espn_ids_swapped(monkeypatch):
    _patch_kalshi(monkeypatch)
    sibling, feature_inputs = _sibling_record()
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )

    resolved = resolve_ticker(f"{_EVENT_TICKER}-TWO")
    ctx = resolved.record.model_inputs.context
    assert ctx["participant_a_espn_id"] == "espn_id_two"
    assert ctx["participant_b_espn_id"] == "espn_id_one"
    # campos NO indexados por participante -- sin cambios
    assert ctx["tournament_name"] == "Test Open"
    assert ctx["tournament_round"] == "Quarterfinal"


def test_ranking_a_b_swapped(monkeypatch):
    _patch_kalshi(monkeypatch)
    sibling, feature_inputs = _sibling_record(ranking_a=12, ranking_b=45)
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )

    resolved = resolve_ticker(f"{_EVENT_TICKER}-TWO")
    assert resolved.record.tennis_variables.ranking_a == 45
    assert resolved.record.tennis_variables.ranking_b == 12


# ---------------------------------------------------------------------
# 3. prior_match_start_times (TennisFeatureInputs, vive en ResolvedEvent
#    -- no en el record) queda orientado al participante correcto
# ---------------------------------------------------------------------

def test_prior_match_start_times_swapped(monkeypatch):
    _patch_kalshi(monkeypatch)
    t_one = datetime(2026, 7, 1, tzinfo=timezone.utc)
    t_two = datetime(2026, 7, 15, tzinfo=timezone.utc)
    sibling, feature_inputs = _sibling_record(prior_a=[t_one], prior_b=[t_two])
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )

    resolved = resolve_ticker(f"{_EVENT_TICKER}-TWO")
    # participant_a ahora es "Player Two" -> su historial (antes en "b") debe quedar en "a"
    assert resolved.feature_inputs.prior_match_start_times["participant_a"] == [t_two]
    assert resolved.feature_inputs.prior_match_start_times["participant_b"] == [t_one]


# ---------------------------------------------------------------------
# 4. Casos negativos: nunca se adivina
# ---------------------------------------------------------------------

def test_no_sibling_at_all_still_raises_404(monkeypatch):
    _patch_kalshi(monkeypatch)
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([]),
    )
    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker(f"{_EVENT_TICKER}-TWO")
    assert exc_info.value.status_code == 404


def test_sibling_needs_review_does_not_swap_stays_404(monkeypatch):
    """El evento nunca se resolvió confidentemente -- construir el lado
    "otro" sobre una base no confirmada seria fabricar un match."""
    _patch_kalshi(monkeypatch)
    sibling, feature_inputs = _sibling_record()
    sibling.data_quality.match_method = MatchMethod.NEEDS_REVIEW
    sibling.data_quality.needs_review = True
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling], [feature_inputs], [None]),
    )
    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker(f"{_EVENT_TICKER}-TWO")
    assert exc_info.value.status_code == 404


def test_ambiguous_multiple_siblings_does_not_guess_stays_404(monkeypatch):
    """Anomalía de datos: dos registros reclamando el mismo event_ticker
    de Kalshi -- no se adivina cuál es el correcto, se cae al 404."""
    _patch_kalshi(monkeypatch)
    sibling_1, fi_1 = _sibling_record()
    sibling_2, fi_2 = _sibling_record()
    sibling_2.event_id = "espn_tennis_atp_other_duplicate"
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult([sibling_1, sibling_2], [fi_1, fi_2], [None, None]),
    )
    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker(f"{_EVENT_TICKER}-TWO")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------
# 5. Regresión MLB: la rama nueva nunca se ejecuta
# ---------------------------------------------------------------------

def test_mlb_never_attempts_side_swap(monkeypatch):
    """Si `_resolve_other_side_tennis` llegara a invocarse para un ticker
    MLB, este test fallaria -- confirma que el gate `sport == Sport.TENNIS`
    aísla por completo la rama nueva del camino de MLB."""
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("_resolve_other_side_tennis no debe llamarse nunca para MLB")

    monkeypatch.setattr(resolver_module, "_resolve_other_side_tennis", _fail_if_called)
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({
            "events": [{
                "event_ticker": "KXMLBGAME-26AUG10AAABBB",
                "title": "Team AAA vs Team BBB",
                "markets": [
                    {"ticker": "KXMLBGAME-26AUG10AAABBB-AAA", "event_ticker": "KXMLBGAME-26AUG10AAABBB",
                     "yes_sub_title": "Team AAA", "occurrence_datetime": "2026-08-10T19:00:00Z"},
                    {"ticker": "KXMLBGAME-26AUG10AAABBB-BBB", "event_ticker": "KXMLBGAME-26AUG10AAABBB",
                     "yes_sub_title": "Team BBB", "occurrence_datetime": "2026-08-10T19:00:00Z"},
                ],
            }]
        }),
    )
    mlb_record = NormalizedRecord(
        sport=Sport.MLB, event_id="mlb_999", market_id="KXMLBGAME-26AUG10AAABBB-AAA",
        participant_a="Team AAA", participant_b="Team BBB",
    )
    monkeypatch.setattr(
        resolver_module, "run_mlb_pipeline",
        lambda date, **kw: _FakeTennisPipelineResult([mlb_record]),
    )

    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker("KXMLBGAME-26AUG10AAABBB-BBB")
    assert exc_info.value.status_code == 404
