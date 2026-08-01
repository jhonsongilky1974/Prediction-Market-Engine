"""Tests de `run_decision_pipeline`/`evaluate_opportunity` (Fase 4, Paso
4.1). Ver `ORCHESTRATOR_SPEC.md` §11. Todo contra `tmp_path` -- nunca
`data/engine.db`. No re-testea `decide()`/Policy Engine (Fase 3, ya
cubierto en `test_policy_decision.py`) -- solo que el orquestador los
invoca correctamente, persiste, y aísla fallos por evento/lado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from config.settings import PROJECT_ROOT
from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import MarketData, NormalizedRecord, Sport
from src.opportunity.opportunity_repository import OpportunityRepository
from src.orchestration.decision_pipeline import run_decision_pipeline
from src.orchestration.sport_adapter import SportAdapter
from src.policy.manifest import load_policy_manifest
from src.storage.history_repository import HistoryRepository
from tests.unit.fase3_factories import make_policy_manifest

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
REAL_MLB_MANIFEST_PATH = PROJECT_ROOT / "config" / "policy" / "mlb_v1.json"


def _record(event_id="mlb_1", market_id="KXMLBGAME-TEST", **overrides) -> NormalizedRecord:
    base = dict(
        sport=Sport.MLB,
        event_id=event_id,
        market_id=market_id,
        participant_a="A",
        participant_b="B",
        market=MarketData(yes_bid=0.40, yes_ask=0.45, no_bid=0.55, no_ask=0.60),
    )
    base.update(overrides)
    return NormalizedRecord(**base)


def _not_trained_predict(record, inputs, data_cutoff_timestamp, loaded_artifact):
    return PModelOutput(
        p_model_yes=None,
        model_version=None,
        model_status=ModelStatus.MODEL_NOT_TRAINED,
        feature_set_version="phase2_registry_v1",
        prediction_timestamp=NOW,
        data_cutoff_timestamp=data_cutoff_timestamp or NOW,
    )


def _adapter(predict_fn=_not_trained_predict) -> SportAdapter:
    return SportAdapter(sport=Sport.MLB, predict_fn=predict_fn, load_artifact_fn=lambda: None)


def _repos(tmp_path):
    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    opp = OpportunityRepository(db_path=tmp_path / "hist.db")
    return hist, opp


def _lenient_manifest(**overrides):
    return make_policy_manifest(hard_block_rules=[], hard_hold_rules=[], **overrides)


def test_happy_path_creates_both_sides_at_state_version_one(tmp_path):
    hist, opp = _repos(tmp_path)
    record = _record()

    summary = run_decision_pipeline(
        records=[record],
        feature_inputs_list=[None],
        feature_cutoffs=[NOW],
        sport=Sport.MLB,
        adapter=_adapter(),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )

    assert summary.records_evaluated == 1
    assert summary.skipped_no_market_id == 0
    assert summary.opportunities_created == 2  # YES + NO
    assert summary.evaluations_created == 2
    assert summary.skipped_errors == []

    yes_opp = opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:YES")
    no_opp = opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:NO")
    assert yes_opp is not None and yes_opp.state_version == 1
    assert no_opp is not None and no_opp.state_version == 1
    assert yes_opp.previous_signal_id is None

    yes_eval = opp.get_latest_evaluation("opp:mlb_1:KXMLBGAME-TEST:YES")
    assert yes_eval is not None and yes_eval.state_version == 1
    assert yes_eval.model_version is None  # MODEL_NOT_TRAINED, honesto


def test_second_run_increments_state_version_and_chains_previous_signal_id(tmp_path):
    hist, opp = _repos(tmp_path)
    record = _record()
    kwargs = dict(
        records=[record],
        feature_inputs_list=[None],
        feature_cutoffs=[NOW],
        sport=Sport.MLB,
        adapter=_adapter(),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )

    run_decision_pipeline(**kwargs)
    later = NOW.replace(hour=13)
    kwargs["now"] = later
    run_decision_pipeline(**kwargs)

    yes_opp = opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:YES")
    yes_eval = opp.get_latest_evaluation("opp:mlb_1:KXMLBGAME-TEST:YES")
    assert yes_opp.state_version == 2
    assert yes_eval.state_version == 2
    assert yes_opp.previous_signal_id == "eval:opp:mlb_1:KXMLBGAME-TEST:YES:1"
    assert yes_opp.first_seen_at == NOW  # preservado de la primera versión
    assert yes_opp.last_evaluated_at == later


def test_record_without_market_id_is_skipped_not_evaluated(tmp_path):
    hist, opp = _repos(tmp_path)
    record = _record(market_id=None)

    summary = run_decision_pipeline(
        records=[record],
        feature_inputs_list=[None],
        feature_cutoffs=[NOW],
        sport=Sport.MLB,
        adapter=_adapter(),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )

    assert summary.skipped_no_market_id == 1
    assert summary.opportunities_created == 0
    assert opp.get_latest_opportunity("opp:mlb_1:None:YES") is None


def test_failure_in_one_record_does_not_abort_the_rest_of_the_batch(tmp_path):
    """Garantía central del orquestador (ORCHESTRATOR_SPEC.md §5) --
    a diferencia de mlb_pipeline.py/tennis_pipeline.py, un registro
    problemático no aborta el lote completo."""
    hist, opp = _repos(tmp_path)
    records = [_record(event_id="mlb_1"), _record(event_id="mlb_BROKEN"), _record(event_id="mlb_3")]

    def flaky_predict(record, inputs, data_cutoff_timestamp, loaded_artifact):
        if record.event_id == "mlb_BROKEN":
            raise RuntimeError("fallo simulado de predict_fn")
        return _not_trained_predict(record, inputs, data_cutoff_timestamp, loaded_artifact)

    summary = run_decision_pipeline(
        records=records,
        feature_inputs_list=[None, None, None],
        feature_cutoffs=[NOW, NOW, NOW],
        sport=Sport.MLB,
        adapter=_adapter(predict_fn=flaky_predict),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )

    assert summary.records_evaluated == 3
    assert summary.opportunities_created == 4  # mlb_1 y mlb_3, YES+NO cada uno
    assert len(summary.skipped_errors) == 1
    assert summary.skipped_errors[0][0] == "mlb_BROKEN"
    assert summary.skipped_errors[0][1] == "pre-side"
    assert opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:YES") is not None
    assert opp.get_latest_opportunity("opp:mlb_3:KXMLBGAME-TEST:YES") is not None
    assert opp.get_latest_opportunity("opp:mlb_BROKEN:KXMLBGAME-TEST:YES") is None


def test_failure_in_one_side_does_not_block_the_other_side(tmp_path, monkeypatch):
    """Aísla el fallo al nivel de `evaluate_opportunity` (pasos 5-19,
    per-side) -- distinto del test "pre-side" de arriba. Se fuerza un
    fallo únicamente para Side.NO parcheando `build_signal_inputs` tal
    como lo importa `decision_pipeline.py`."""
    import src.orchestration.decision_pipeline as decision_pipeline_module
    from src.signals.signal_schema import Side

    hist, opp = _repos(tmp_path)
    record = _record()
    real_build_signal_inputs = decision_pipeline_module.build_signal_inputs

    def flaky_build_signal_inputs(record, model_output, quality_score_output, side, now):
        if side == Side.NO:
            raise RuntimeError("fallo simulado, solo lado NO")
        return real_build_signal_inputs(record, model_output, quality_score_output, side, now)

    monkeypatch.setattr(decision_pipeline_module, "build_signal_inputs", flaky_build_signal_inputs)

    summary = run_decision_pipeline(
        records=[record],
        feature_inputs_list=[None],
        feature_cutoffs=[NOW],
        sport=Sport.MLB,
        adapter=_adapter(),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )

    assert summary.opportunities_created == 1  # solo YES
    assert len(summary.skipped_errors) == 1
    assert summary.skipped_errors[0] == ("mlb_1", "NO", "RuntimeError('fallo simulado, solo lado NO')")
    assert opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:YES") is not None
    assert opp.get_latest_opportunity("opp:mlb_1:KXMLBGAME-TEST:NO") is None


def test_never_produces_enter_with_the_real_approved_manifest(tmp_path):
    """Fija como regresión el hallazgo central de ORCHESTRATOR_SPEC.md
    §1.7: con el PolicyManifest real aprobado (config/policy/mlb_v1.json,
    catálogo completo de reglas, enter_global_threshold=100.0), ENTER
    permanece estructuralmente inalcanzable mientras D-3 no se resuelva
    -- ev_neto_strength es siempre None (componente crítico, no
    compensable)."""
    hist, opp = _repos(tmp_path)
    manifest = load_policy_manifest(REAL_MLB_MANIFEST_PATH)
    record = _record()

    summary = run_decision_pipeline(
        records=[record],
        feature_inputs_list=[None],
        feature_cutoffs=[NOW],
        sport=Sport.MLB,
        adapter=_adapter(),
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=manifest,
        now=NOW,
    )

    assert summary.opportunities_created == 2
    assert "ENTER" not in summary.signal_type_counts


def test_naive_now_raises():
    with pytest.raises(ValueError, match="tz-aware"):
        run_decision_pipeline(
            records=[],
            feature_inputs_list=[],
            feature_cutoffs=[],
            sport=Sport.MLB,
            adapter=_adapter(),
            history_repository=HistoryRepository(db_path=Path("/tmp/unused.db")),
            opportunity_repository=OpportunityRepository(db_path=Path("/tmp/unused.db")),
            policy_manifest=_lenient_manifest(),
            now=datetime(2026, 8, 1, 12, 0, 0),
        )


# ---------------------------------------------------------------------
# Arquitectura -- src/orchestration/ es la única capa que conoce todo,
# nada de src/policy|opportunity|evidence|health|calibration|payoff la
# conoce a ella (ORCHESTRATOR_SPEC.md §2.4).
# ---------------------------------------------------------------------


def test_no_fase3_package_imports_orchestration():
    import ast

    root = PROJECT_ROOT / "src"
    fase3_dirs = ["policy", "opportunity", "evidence", "health", "calibration", "payoff", "signals", "pricing", "uncertainty"]
    offenders = []
    for dirname in fase3_dirs:
        for path in (root / dirname).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "orchestration" in node.module:
                    offenders.append(str(path))
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "orchestration" in alias.name:
                            offenders.append(str(path))
    assert offenders == []
