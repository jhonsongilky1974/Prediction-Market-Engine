"""Tests de collect_evidence() (Fase 3, Paso 3.3). Ver
FASE3_EXECUTION_PLAN.md, Paso 3.3, y EVIDENCE_EXPLAINABILITY_SPEC.md §1.1
-- las 4 plantillas, cada una probada en su caso "dispara" y su caso
"campo ausente -> ningún item", más una combinatoria completa (16
combinaciones, supera el mínimo de 8 pedido) que confirma la regla de
no-fabricación en conjunto.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE
from src.evidence.evidence_engine import collect_evidence
from src.evidence.schemas import EvidenceDirection
from src.models.schemas import (
    BookmakerConsensus,
    DataQuality,
    ModelInputs,
    NormalizedRecord,
    Sport,
)
from tests.unit.fase3_factories import NOW, make_calibration_output, make_confidence_profile

_PITCHER_SOURCE = "model_inputs.lineup_or_pitcher"
_MATCH_CONFIDENCE_SOURCE = "data_quality.match_confidence"
_MODEL_RELIABILITY_SOURCE = "confidence_profile.model_reliability"
_DIVERGENCE_SOURCE = "bookmaker_consensus.consensus_probability_no_vig"


def _record(**overrides) -> NormalizedRecord:
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        **overrides,
    )


def _source_fields(items) -> set:
    return {item.source_field for item in items}


# ---------------------------------------------------------------------
# Plantilla 1: pitcher probable confirmado -- FOR
# ---------------------------------------------------------------------


def test_pitcher_confirmed_generates_for_evidence():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    matches = [i for i in items if i.source_field == _PITCHER_SOURCE]
    assert len(matches) == 1
    assert matches[0].direction == EvidenceDirection.FOR
    assert matches[0].fact == "Pitcher probable confirmado"


def test_pitcher_absent_generates_no_evidence():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher=None))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    assert _PITCHER_SOURCE not in _source_fields(items)


# ---------------------------------------------------------------------
# Plantilla 2: confianza de emparejamiento marginal -- AGAINST
# ---------------------------------------------------------------------


def test_match_confidence_marginal_generates_against_evidence():
    marginal_value = EVENT_NAME_MATCH_MIN_CONFIDENCE + 0.05
    record = _record(data_quality=DataQuality(match_confidence=marginal_value))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    matches = [i for i in items if i.source_field == _MATCH_CONFIDENCE_SOURCE]
    assert len(matches) == 1
    assert matches[0].direction == EvidenceDirection.AGAINST
    assert f"{marginal_value:.2f}" in matches[0].fact


def test_match_confidence_none_generates_no_evidence():
    record = _record(data_quality=DataQuality(match_confidence=None))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    assert _MATCH_CONFIDENCE_SOURCE not in _source_fields(items)


def test_match_confidence_below_minimum_generates_no_evidence():
    """Por debajo del mínimo de matching no es 'marginal' -- ese caso lo
    cubre el Hard Block unsafe_matching (Paso 3.4.2), no el Evidence
    Engine."""
    record = _record(data_quality=DataQuality(match_confidence=EVENT_NAME_MATCH_MIN_CONFIDENCE - 0.05))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    assert _MATCH_CONFIDENCE_SOURCE not in _source_fields(items)


def test_match_confidence_well_above_band_generates_no_evidence():
    record = _record(data_quality=DataQuality(match_confidence=0.99))
    items = collect_evidence(
        "opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW
    )
    assert _MATCH_CONFIDENCE_SOURCE not in _source_fields(items)


# ---------------------------------------------------------------------
# Plantilla 3: modelo con historial de performance evaluado -- FOR
# ---------------------------------------------------------------------


def test_model_reliability_above_threshold_generates_for_evidence():
    confidence_profile = make_confidence_profile(model_reliability=75.0)
    items = collect_evidence(
        "opp-1", _record(), make_calibration_output(), confidence_profile, now=NOW
    )
    matches = [i for i in items if i.source_field == _MODEL_RELIABILITY_SOURCE]
    assert len(matches) == 1
    assert matches[0].direction == EvidenceDirection.FOR


def test_model_reliability_at_threshold_generates_no_evidence():
    confidence_profile = make_confidence_profile(model_reliability=50.0)
    items = collect_evidence(
        "opp-1", _record(), make_calibration_output(), confidence_profile, now=NOW
    )
    assert _MODEL_RELIABILITY_SOURCE not in _source_fields(items)


def test_model_reliability_none_generates_no_evidence():
    confidence_profile = make_confidence_profile(model_reliability=None)
    items = collect_evidence(
        "opp-1", _record(), make_calibration_output(), confidence_profile, now=NOW
    )
    assert _MODEL_RELIABILITY_SOURCE not in _source_fields(items)


# ---------------------------------------------------------------------
# Plantilla 4: divergencia significativa modelo/consenso -- AGAINST
# ---------------------------------------------------------------------


def test_divergence_above_threshold_generates_against_evidence():
    calibration_output = make_calibration_output(p_model_calibrated=0.70, calibration_version="V1")
    record = _record(bookmaker_consensus=BookmakerConsensus(consensus_probability_no_vig=0.50))
    items = collect_evidence(
        "opp-1", record, calibration_output, make_confidence_profile(), now=NOW
    )
    matches = [i for i in items if i.source_field == _DIVERGENCE_SOURCE]
    assert len(matches) == 1
    assert matches[0].direction == EvidenceDirection.AGAINST


def test_divergence_at_threshold_generates_no_evidence():
    calibration_output = make_calibration_output(p_model_calibrated=0.60, calibration_version="V1")
    record = _record(bookmaker_consensus=BookmakerConsensus(consensus_probability_no_vig=0.50))
    items = collect_evidence(
        "opp-1", record, calibration_output, make_confidence_profile(), now=NOW
    )
    assert _DIVERGENCE_SOURCE not in _source_fields(items)


def test_divergence_missing_p_model_calibrated_generates_no_evidence():
    calibration_output = make_calibration_output(p_model_calibrated=None)
    record = _record(bookmaker_consensus=BookmakerConsensus(consensus_probability_no_vig=0.50))
    items = collect_evidence(
        "opp-1", record, calibration_output, make_confidence_profile(), now=NOW
    )
    assert _DIVERGENCE_SOURCE not in _source_fields(items)


def test_divergence_missing_consensus_generates_no_evidence():
    calibration_output = make_calibration_output(p_model_calibrated=0.70, calibration_version="V1")
    record = _record(bookmaker_consensus=BookmakerConsensus(consensus_probability_no_vig=None))
    items = collect_evidence(
        "opp-1", record, calibration_output, make_confidence_profile(), now=NOW
    )
    assert _DIVERGENCE_SOURCE not in _source_fields(items)


# ---------------------------------------------------------------------
# Combinatoria completa (16 = 2^4, supera el mínimo de 8 exigido):
# confirma la regla de no-fabricación sobre el conjunto completo
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "pitcher_on,match_marginal_on,reliability_on,divergence_on",
    list(itertools.product([False, True], repeat=4)),
)
def test_no_fabrication_across_all_field_combinations(
    pitcher_on, match_marginal_on, reliability_on, divergence_on
):
    record = _record(
        model_inputs=ModelInputs(
            lineup_or_pitcher={"name": "Jane Doe"} if pitcher_on else None
        ),
        data_quality=DataQuality(
            match_confidence=(EVENT_NAME_MATCH_MIN_CONFIDENCE + 0.05) if match_marginal_on else None
        ),
        bookmaker_consensus=BookmakerConsensus(
            consensus_probability_no_vig=0.50 if divergence_on else None
        ),
    )
    calibration_output = make_calibration_output(
        p_model_calibrated=0.70 if divergence_on else None,
        calibration_version="V1" if divergence_on else None,
    )
    confidence_profile = make_confidence_profile(
        model_reliability=75.0 if reliability_on else None
    )

    items = collect_evidence("opp-1", record, calibration_output, confidence_profile, now=NOW)
    fields = _source_fields(items)

    assert (_PITCHER_SOURCE in fields) == pitcher_on
    assert (_MATCH_CONFIDENCE_SOURCE in fields) == match_marginal_on
    assert (_MODEL_RELIABILITY_SOURCE in fields) == reliability_on
    assert (_DIVERGENCE_SOURCE in fields) == divergence_on
    assert len(items) == sum([pitcher_on, match_marginal_on, reliability_on, divergence_on])


def test_all_fields_none_returns_empty_list():
    items = collect_evidence(
        "opp-1", _record(), make_calibration_output(p_model_calibrated=None), make_confidence_profile(model_reliability=None), now=NOW
    )
    assert items == []


# ---------------------------------------------------------------------
# opportunity_id se propaga; ningún item referencia un campo None;
# pureza; now naive; no mutación
# ---------------------------------------------------------------------


def test_opportunity_id_propagated_to_every_item():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}))
    confidence_profile = make_confidence_profile(model_reliability=75.0)
    items = collect_evidence("opp-42", record, make_calibration_output(), confidence_profile, now=NOW)
    assert items
    assert all(item.opportunity_id == "opp-42" for item in items)


def test_same_input_produces_same_output():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}))
    calibration_output = make_calibration_output()
    confidence_profile = make_confidence_profile()
    items_a = collect_evidence("opp-1", record, calibration_output, confidence_profile, now=NOW)
    items_b = collect_evidence("opp-1", record, calibration_output, confidence_profile, now=NOW)
    assert items_a == items_b


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        collect_evidence(
            "opp-1",
            _record(),
            make_calibration_output(),
            make_confidence_profile(),
            now=datetime(2026, 7, 30, 12, 0, 0),
        )


def test_function_does_not_mutate_input_record():
    record = _record(model_inputs=ModelInputs(lineup_or_pitcher={"name": "Jane Doe"}))
    collect_evidence("opp-1", record, make_calibration_output(), make_confidence_profile(), now=NOW)
    assert record.model_inputs.lineup_or_pitcher == {"name": "Jane Doe"}


def test_does_not_import_policy_business_logic_modules():
    """Regla de dependencia (ARCHITECTURE_FASE3.md §4): evidence/ puede
    depender de policy/schemas.py (contratos de datos), pero nunca de
    policy/hard_rules.py, soft_score.py, decision.py, manifest.py,
    validation.py (lógica de negocio) ni de explainability/."""
    import src.evidence.evidence_engine as module

    source = open(module.__file__, encoding="utf-8").read()
    forbidden = [
        "policy.hard_rules",
        "policy.soft_score",
        "policy.decision",
        "policy.manifest",
        "policy.validation",
        "explainability",
    ]
    for token in forbidden:
        assert token not in source, f"evidence_engine.py no debe importar {token}"
