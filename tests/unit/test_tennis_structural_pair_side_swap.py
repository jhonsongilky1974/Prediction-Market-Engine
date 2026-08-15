"""Tests de integración entre el Tramo 1 del resolver estructural de pares
(`MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE`) y `_resolve_other_side_tennis`
(`src/api/event_resolver.py`, 2026-08-15).

Auditoría previa al cambio (documentada aquí, no solo en el mensaje de la
sesión): `_resolve_other_side_tennis` filtraba "hermanos confidentes" solo
por `(EXACT_NAME_TIME, FUZZY_NAME_TIME)` -- un registro resuelto por el
nuevo resolver nunca calificaba, así que pedir el ticker del lado NO
adjunto volvía a producir 404, reproduciendo el bug que el fix del
2026-08-10 ya había cerrado para los demás métodos. Cambio mínimo aplicado:
se añadió `MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE` al mismo tuple
(`event_resolver.py`). El resto de la función es idéntico -- ningún cambio
de arquitectura: `match_result.method` se sigue copiando tal cual del
hermano, y `apply_kalshi_match` sigue seleccionando el mercado del lado
nuevo por comparación de NOMBRE contra `participant_a` (nunca por
posición/orden), mismo invariante que ya protegía EXACT_NAME_TIME/
FUZZY_NAME_TIME.

Estos tests usan el caso real Faria vs Wu (reconstrucción 2026-08-15, ver
informe de sesión) para los escenarios 1-4/8, y un escenario sintético
"Player One vs Player Two" con el ORDEN INVERTIDO en el título de Kalshi
para el detector de doble inversión (escenarios 6-7) -- combina las DOS
únicas fuentes posibles de "swap" en todo el sistema (la selección por
nombre del resolver estructural + la inversión de perspectiva de
`_resolve_other_side_tennis`) para demostrar que el resultado final nunca
queda doblemente invertido.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.api import event_resolver as resolver_module
from src.api.event_resolver import resolve_ticker
from src.connectors.base_client import FetchResult
from src.connectors.kalshi import KalshiConnector
from src.features.tennis_features import TennisFeatureInputs
from src.matching.tennis_pair_matcher import resolve_tennis_pair_by_structure
from src.models.schemas import MatchMethod, NormalizedRecord, Sport, TennisVariables


def _ok(data):
    return FetchResult(ok=True, status_code=200, data=data, error=None, url="x", capture_ts=datetime.now(timezone.utc))


class _FakeTennisPipelineResult:
    def __init__(self, records, feature_inputs_list=None, feature_cutoffs=None, steps=None):
        self.records = records
        self.feature_inputs_list = feature_inputs_list or [None] * len(records)
        self.feature_cutoffs = feature_cutoffs or [None] * len(records)
        self.steps = steps or []


def _patch_kalshi(monkeypatch, event):
    monkeypatch.setattr(
        KalshiConnector,
        "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({"events": [event]}),
    )


def _patch_pipeline(monkeypatch, records):
    monkeypatch.setattr(
        resolver_module, "run_tennis_pipeline",
        lambda tour, date, **kw: _FakeTennisPipelineResult(records),
    )


# ---------------------------------------------------------------------
# Caso real: Faria vs Wu (reconstrucción 2026-08-15, ver informe de sesión)
# ---------------------------------------------------------------------

_FARYIB_EVENT_TICKER = "KXATPMATCH-26AUG12FARYIB"

_FARYIB_EVENT = {
    "event_ticker": _FARYIB_EVENT_TICKER,
    "title": "Faria vs Wu",
    "product_metadata": {"competition": "ATP Cincinnati"},
    "markets": [
        {
            "ticker": f"{_FARYIB_EVENT_TICKER}-FAR",
            "event_ticker": _FARYIB_EVENT_TICKER,
            "yes_sub_title": "Jaime Faria",
            "no_sub_title": "Jaime Faria",
            "yes_bid_dollars": "0.9800",
            "yes_ask_dollars": "0.9900",
            "no_bid_dollars": "0.0100",
            "no_ask_dollars": "0.0200",
            "occurrence_datetime": "2026-08-12T19:20:00Z",
            "close_time": "2026-08-13T03:15:27Z",
            "expected_expiration_time": "2026-08-12T19:20:00Z",
        },
        {
            # Precios deliberadamente NO complementarios de los de FAR
            # (0.03 != 1-0.99) -- si el swap copiara/invirtiera el precio
            # del otro lado en vez de leer el propio, este test lo detecta.
            "ticker": f"{_FARYIB_EVENT_TICKER}-YIB",
            "event_ticker": _FARYIB_EVENT_TICKER,
            "yes_sub_title": "Yibing Wu",
            "no_sub_title": "Yibing Wu",
            "yes_bid_dollars": "0.0200",
            "yes_ask_dollars": "0.0300",
            "no_bid_dollars": "0.9700",
            "no_ask_dollars": "0.9800",
            "occurrence_datetime": "2026-08-12T19:20:00Z",
            "close_time": "2026-08-13T03:15:27Z",
            "expected_expiration_time": "2026-08-12T19:20:00Z",
        },
    ],
}


def _faria_wu_sibling():
    """Registro tal como lo dejaría `run_tennis_pipeline` real hoy: resuelto
    vía TENNIS_STRUCTURAL_PAIR_UNIQUE, market_id en el lado -FAR (el que
    matchea participant_a)."""
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_184431",
        source_event_ids={"kalshi": _FARYIB_EVENT_TICKER, "espn_tennis": "184431"},
        market_id=f"{_FARYIB_EVENT_TICKER}-FAR",
        source_market_id=f"{_FARYIB_EVENT_TICKER}-FAR",
        participant_a="Jaime Faria",
        participant_b="Wu Yibing",
        tennis_variables=TennisVariables(),
    )
    record.market.yes_bid = 0.98
    record.market.yes_ask = 0.99
    record.data_quality.match_confidence = 1.0
    record.data_quality.match_method = MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    record.data_quality.needs_review = False
    record.data_quality.missing_fields = []
    record.model_inputs.context = {
        "tournament_name": "Cincinnati Open",
        "tour": "atp",
        "participant_a_espn_id": "10219",
        "participant_b_espn_id": "2875",
        "tournament_round": "Qualifying Final",
    }
    return record, TennisFeatureInputs(prior_match_start_times={"participant_a": [], "participant_b": []})


# 1. Faria-Wu ticker del primer participante -> resultado correcto
def test_faria_wu_first_participant_ticker_resolves_correctly(monkeypatch):
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, feature_inputs = _faria_wu_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-FAR")

    assert resolved.record is sibling
    assert resolved.record.market_id == f"{_FARYIB_EVENT_TICKER}-FAR"
    assert resolved.record.participant_a == "Jaime Faria"
    assert resolved.record.data_quality.match_method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE


# 2. Faria-Wu ticker del segundo participante -> resultado correcto
def test_faria_wu_second_participant_ticker_resolves_correctly(monkeypatch):
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, feature_inputs = _faria_wu_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-YIB")

    assert resolved.record.market_id == f"{_FARYIB_EVENT_TICKER}-YIB"
    assert resolved.record.participant_a == "Wu Yibing"
    assert resolved.record.participant_b == "Jaime Faria"
    assert resolved.record.data_quality.match_method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert not resolved.record.data_quality.needs_review


# 3. Ambos tickers identifican el MISMO encuentro
def test_both_faria_wu_tickers_identify_same_event(monkeypatch):
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, _ = _faria_wu_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved_far = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-FAR")
    resolved_yib = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-YIB")

    assert resolved_far.record.source_event_ids["kalshi"] == resolved_yib.record.source_event_ids["kalshi"]
    assert resolved_far.record.source_event_ids["kalshi"] == _FARYIB_EVENT_TICKER
    assert resolved_far.record.model_inputs.context["tournament_name"] == \
        resolved_yib.record.model_inputs.context["tournament_name"]


# 4. Cada ticker conserva el participante correcto asociado a su mercado
def test_each_ticker_keeps_correct_participant_for_its_market(monkeypatch):
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, _ = _faria_wu_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved_far = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-FAR")
    resolved_yib = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-YIB")

    assert resolved_far.record.market_id.endswith("-FAR")
    assert resolved_far.record.participant_a == "Jaime Faria"
    assert resolved_yib.record.market_id.endswith("-YIB")
    assert resolved_yib.record.participant_a == "Wu Yibing"


# 8. YES/NO (precio) no queda invertido -- cada lado conserva su propio precio
def test_side_price_not_inverted_between_faria_and_wu(monkeypatch):
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, _ = _faria_wu_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved_yib = resolve_ticker(f"{_FARYIB_EVENT_TICKER}-YIB")

    # precio propio del lado YIB (0.02/0.03), no el complementario/copiado
    # del lado FAR (0.98/0.99)
    assert resolved_yib.record.market.yes_bid == pytest.approx(0.02)
    assert resolved_yib.record.market.yes_ask == pytest.approx(0.03)


# ---------------------------------------------------------------------
# 6-7. Detector de doble inversión: Kalshi lista el par en orden B-A
# (dispara `swapped=True` DENTRO del resolver estructural, por selección
# de nombre, no de posición) + _resolve_other_side_tennis invierte
# perspectiva otra vez al pedir el otro lado -- el resultado final debe
# seguir siendo correcto, nunca volver a caer en el jugador equivocado.
# ---------------------------------------------------------------------

_TWOONE_EVENT_TICKER = "KXATPMATCH-26AUG20TWOONE"

_TWOONE_EVENT = {
    "event_ticker": _TWOONE_EVENT_TICKER,
    # Orden INVERTIDO respecto a la fuente (ESPN: "Player One"/"Player Two")
    "title": "Player Two vs Player One",
    "markets": [
        {
            "ticker": f"{_TWOONE_EVENT_TICKER}-TWO", "event_ticker": _TWOONE_EVENT_TICKER,
            "yes_sub_title": "Player Two", "no_sub_title": "Player One",
            "yes_bid_dollars": "0.7000", "yes_ask_dollars": "0.7100",
            "no_bid_dollars": "0.2900", "no_ask_dollars": "0.3000",
            "occurrence_datetime": "2026-08-20T19:00:00Z", "close_time": "2026-09-03T19:00:00Z",
            "expected_expiration_time": "2026-08-20T19:00:00Z",
        },
        {
            "ticker": f"{_TWOONE_EVENT_TICKER}-ONE", "event_ticker": _TWOONE_EVENT_TICKER,
            "yes_sub_title": "Player One", "no_sub_title": "Player Two",
            "yes_bid_dollars": "0.2500", "yes_ask_dollars": "0.2600",
            "no_bid_dollars": "0.7400", "no_ask_dollars": "0.7500",
            "occurrence_datetime": "2026-08-20T19:00:00Z", "close_time": "2026-09-03T19:00:00Z",
            "expected_expiration_time": "2026-08-20T19:00:00Z",
        },
    ],
}


def test_resolver_internal_swap_confirmed_before_side_swap_test():
    """Precondición del test de doble inversión: confirma con el propio
    resolver que este evento SÍ dispara `swapped=True` (orden Kalshi B-A)
    y que `selected_market` queda correctamente pinned a 'Player One' por
    nombre, no por posición -- si esto no fuera cierto, el escenario de
    abajo no probaría nada."""
    match, _ = resolve_tennis_pair_by_structure("Player One", "Player Two", [_TWOONE_EVENT])
    assert match.match_result.swapped is True
    assert match.match_result.method == MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    assert match.selected_market["ticker"] == f"{_TWOONE_EVENT_TICKER}-ONE"
    assert match.selected_market["yes_sub_title"] == "Player One"


def _two_one_sibling():
    record = NormalizedRecord(
        sport=Sport.TENNIS,
        event_id="espn_tennis_atp_888888",
        source_event_ids={"kalshi": _TWOONE_EVENT_TICKER, "espn_tennis": "888888"},
        market_id=f"{_TWOONE_EVENT_TICKER}-ONE",
        source_market_id=f"{_TWOONE_EVENT_TICKER}-ONE",
        participant_a="Player One",
        participant_b="Player Two",
    )
    record.market.yes_bid = 0.25
    record.market.yes_ask = 0.26
    record.data_quality.match_confidence = 1.0
    record.data_quality.match_method = MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    record.data_quality.needs_review = False
    record.data_quality.missing_fields = []
    record.model_inputs.context = {"tournament_name": "Test Open", "tour": "atp"}
    return record


def test_no_double_inversion_after_kalshi_listed_pair_reversed(monkeypatch):
    """El escenario más adverso posible para detectar doble inversión: el
    evento Kalshi YA estaba en orden B-A (el resolver estructural lo
    corrigió por nombre, no por posición -- ver test anterior) y ahora se
    pide el lado NO adjunto, forzando la SEGUNDA inversión
    (`_resolve_other_side_tennis`). El resultado final debe aterrizar
    exactamente en 'Player Two' <-> mercado '-TWO', nunca de vuelta en
    'Player One' ni en una combinación mezclada."""
    _patch_kalshi(monkeypatch, _TWOONE_EVENT)
    sibling = _two_one_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved = resolve_ticker(f"{_TWOONE_EVENT_TICKER}-TWO")

    assert resolved.record.market_id == f"{_TWOONE_EVENT_TICKER}-TWO"
    assert resolved.record.participant_a == "Player Two"
    assert resolved.record.participant_b == "Player One"
    # precio propio del lado TWO (0.70/0.71) -- nunca el de ONE (0.25/0.26)
    # ni su complementario (1-0.25=0.75)
    assert resolved.record.market.yes_bid == pytest.approx(0.70)
    assert resolved.record.market.yes_ask == pytest.approx(0.71)


def test_original_side_unaffected_by_double_inversion_scenario(monkeypatch):
    """El lado ya resuelto (ONE) sigue devolviendo el registro original sin
    pasar por ningún swap -- confirma que la rama de doble inversión nunca
    se ejecuta para el ticker que ya tenía market_id propio."""
    _patch_kalshi(monkeypatch, _TWOONE_EVENT)
    sibling = _two_one_sibling()
    _patch_pipeline(monkeypatch, [sibling])

    resolved = resolve_ticker(f"{_TWOONE_EVENT_TICKER}-ONE")
    assert resolved.record is sibling
    assert resolved.record.participant_a == "Player One"


# ---------------------------------------------------------------------
# 9. NEEDS_REVIEW nunca habilita side swap
# ---------------------------------------------------------------------

def test_needs_review_structural_result_never_enables_side_swap(monkeypatch):
    """Un registro cuyo match_method es NEEDS_REVIEW (2+ candidatos del
    Tramo 1, sin desempate) nunca queda con market_id -- nunca puede
    calificar como hermano confidente, así que el ticker del otro lado
    sigue en 404, no se adivina."""
    _patch_kalshi(monkeypatch, _FARYIB_EVENT)
    sibling, _ = _faria_wu_sibling()
    sibling.data_quality.match_method = MatchMethod.NEEDS_REVIEW
    sibling.data_quality.needs_review = True
    sibling.market_id = None
    _patch_pipeline(monkeypatch, [sibling])

    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker(f"{_FARYIB_EVENT_TICKER}-YIB")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------
# 10. MLB nunca usa este mecanismo, incluso si (adversarialmente) un
# registro MLB tuviera el nuevo match_method
# ---------------------------------------------------------------------

def test_mlb_gate_blocks_side_swap_even_with_new_method_defensively(monkeypatch):
    """Defensivo: aunque un registro MLB tuviera (por error) match_method
    == TENNIS_STRUCTURAL_PAIR_UNIQUE, `resolve_ticker` nunca llama a
    `_resolve_other_side_tennis` para sport=MLB -- el gate es
    `sport == Sport.TENNIS` (event_resolver.py), independiente del método."""
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("_resolve_other_side_tennis no debe llamarse nunca para MLB")

    monkeypatch.setattr(resolver_module, "_resolve_other_side_tennis", _fail_if_called)
    monkeypatch.setattr(
        KalshiConnector, "get_all_events_for_sport",
        lambda self, sport_key, status="open", max_pages=10: _ok({
            "events": [{
                "event_ticker": "KXMLBGAME-26AUG20AAABBB",
                "title": "Team AAA vs Team BBB",
                "markets": [
                    {"ticker": "KXMLBGAME-26AUG20AAABBB-AAA", "event_ticker": "KXMLBGAME-26AUG20AAABBB",
                     "yes_sub_title": "Team AAA", "occurrence_datetime": "2026-08-20T19:00:00Z"},
                    {"ticker": "KXMLBGAME-26AUG20AAABBB-BBB", "event_ticker": "KXMLBGAME-26AUG20AAABBB",
                     "yes_sub_title": "Team BBB", "occurrence_datetime": "2026-08-20T19:00:00Z"},
                ],
            }]
        }),
    )
    mlb_record = NormalizedRecord(
        sport=Sport.MLB, event_id="mlb_999", market_id="KXMLBGAME-26AUG20AAABBB-AAA",
        participant_a="Team AAA", participant_b="Team BBB",
    )
    # forzado adversarialmente -- nunca ocurriría en producción real (ver
    # tests/unit/test_tennis_pair_matcher.py, aislamiento estructural)
    mlb_record.data_quality.match_method = MatchMethod.TENNIS_STRUCTURAL_PAIR_UNIQUE
    mlb_record.data_quality.needs_review = False
    monkeypatch.setattr(
        resolver_module, "run_mlb_pipeline",
        lambda date, **kw: _FakeTennisPipelineResult([mlb_record]),
    )

    with pytest.raises(resolver_module.ResolverError) as exc_info:
        resolve_ticker("KXMLBGAME-26AUG20AAABBB-BBB")
    assert exc_info.value.status_code == 404
