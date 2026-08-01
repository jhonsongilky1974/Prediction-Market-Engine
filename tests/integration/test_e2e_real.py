"""Versión pytest (pass/fail) del test end-to-end real. Para el reporte
legible por humanos usar `python scripts/run_e2e.py` (ver README).
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from src.connectors.espn_tennis import EspnTennisConnector
from src.connectors.mlb import MlbConnector
from src.pipelines.mlb_pipeline import run_mlb_pipeline
from src.pipelines.tennis_pipeline import run_tennis_pipeline

pytestmark = pytest.mark.integration


def _next_mlb_date_with_games():
    mlb = MlbConnector()
    for i in range(10):
        d = (date.today() + timedelta(days=i)).isoformat()
        result = mlb.get_schedule(d)
        if result.ok and MlbConnector.extract_games(result.data):
            return d
    return None


def _next_tennis_date_with_matches(tour="atp"):
    espn = EspnTennisConnector()
    for i in range(10):
        d = (date.today() + timedelta(days=i)).strftime("%Y%m%d")
        result = espn.get_scoreboard(tour, d)
        if result.ok and EspnTennisConnector.extract_matches(result.data):
            return d
    return None


def test_mlb_pipeline_end_to_end_real(tmp_repository):
    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.sport.value == "MLB"
    assert record.participant_a is not None
    assert record.participant_b is not None
    # nunca se inventan campos: missing_fields siempre debe ser una lista (posiblemente no vacía)
    assert isinstance(record.data_quality.missing_fields, list)
    assert record.data_quality.data_completeness_score is not None


def test_tennis_pipeline_end_to_end_real(tmp_repository):
    tennis_date = _next_tennis_date_with_matches("atp")
    if tennis_date is None:
        pytest.skip("no hay partidos ATP próximos disponibles vía ESPN")
    result = run_tennis_pipeline("ATP", tennis_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.sport.value == "TENNIS"
    assert record.tennis_variables is not None
    assert isinstance(record.data_quality.missing_fields, list)


def test_mlb_pipeline_history_wiring_reaches_history_repository_real(tmp_repository, tmp_history_repository):
    """Paso 0c, prueba controlada real (E): confirma que el wiring del
    pipeline MLB alcanza `HistoryRepository` de verdad, contra la API real,
    escribiendo únicamente en bases temporales (`tmp_path`) -- nunca en
    `data/engine.db`. No fabrica histórico pasado: `captured_at` es el
    instante real de esta ejecución.

    Paso 5b, Bloque 2: además confirma que el wiring de `feature_snapshots`
    (fetch_features=True por defecto cuando hay history_repository) también
    alcanza la API real -- sin exigir valores no-None (el próximo juego
    puede no tener probable pitcher confirmado todavía), solo que el
    snapshot de features se haya creado."""
    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1
    record = result.records[0]
    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    captured_at = datetime.fromisoformat(snapshots[0]["captured_at"])
    assert captured_at.tzinfo is not None

    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    assert len(feature_snapshots) == 1


def test_tennis_pipeline_history_wiring_reaches_history_repository_real(tmp_repository, tmp_history_repository):
    """Paso 0c, prueba controlada real (E), equivalente para tenis. Ver
    docstring de la prueba MLB hermana arriba."""
    tennis_date = _next_tennis_date_with_matches("atp")
    if tennis_date is None:
        pytest.skip("no hay partidos ATP próximos disponibles vía ESPN")
    result = run_tennis_pipeline(
        "ATP", tennis_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1
    record = result.records[0]
    snapshots = tmp_history_repository.get_snapshots_for_event(record.event_id)
    assert len(snapshots) == 1
    captured_at = datetime.fromisoformat(snapshots[0]["captured_at"])
    assert captured_at.tzinfo is not None


def test_tennis_pipeline_persists_feature_snapshot_and_predicts_honestly_on_real_data(
    tmp_repository, tmp_history_repository
):
    """Paso 11, prueba controlada real (E): confirma que
    `run_tennis_pipeline` persiste un `feature_snapshot` real
    (rest_days/tournament_round_context, calculados contra la API real de
    ESPN) y que `predict_tennis_baseline` reporta honestamente
    `MODEL_NOT_TRAINED` sin ningún artefacto entrenado en este entorno --
    esperado dado el doble bloqueo (SofaScore + histórico propio bajo,
    PLAN_PHASE2.md §6)."""
    from src.features.tennis_features import TennisFeatureInputs
    from src.models.base import ModelStatus
    from src.models.tennis_baseline import predict_tennis_baseline

    tennis_date = _next_tennis_date_with_matches("atp")
    if tennis_date is None:
        pytest.skip("no hay partidos ATP próximos disponibles vía ESPN")
    result = run_tennis_pipeline(
        "ATP", tennis_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1
    record = result.records[0]

    feature_snapshots = tmp_history_repository.get_feature_snapshots_for_event(record.event_id)
    assert len(feature_snapshots) == 1

    output = predict_tennis_baseline(
        record, TennisFeatureInputs(), datetime.now(timezone.utc), loaded_artifact=None
    )
    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None


def test_quality_score_computes_on_real_mlb_pipeline_output(tmp_repository):
    """Paso 7, prueba controlada real (E): confirma que
    `compute_quality_score` no falla y produce una salida válida sobre un
    `NormalizedRecord` real de la API (sin `consensus`, ya que
    `ODDS_API_KEY` no está configurada en este entorno -- ver Paso 4)."""
    from src.uncertainty.quality_score import compute_quality_score

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    score = compute_quality_score(record, consensus=None)

    assert score.confidence_method == "HEURISTIC_V1"
    assert score.components["missing_critical"] is not None  # siempre calculable
    if score.confidence is not None:
        assert 0.0 <= score.confidence <= 1.0


def test_mlb_elo_inference_works_on_real_pipeline_output(tmp_repository):
    """Paso 6, prueba controlada real (E): confirma que `predict_mlb_elo`
    no falla sobre un `NormalizedRecord` real de la API. Sin artefacto
    entrenado todavía en este entorno (`loaded_artifact=None`) ->
    `MODEL_NOT_TRAINED` honesto, nunca una probabilidad fabricada."""
    from src.models.base import ModelStatus
    from src.models.mlb_elo import predict_mlb_elo

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    output = predict_mlb_elo(record, loaded_artifact=None)

    assert output.model_status == ModelStatus.MODEL_NOT_TRAINED
    assert output.p_model_yes is None


def test_backtest_dataset_builds_honestly_on_real_mlb_pipeline_output_without_results(
    tmp_repository, tmp_history_repository
):
    """Paso 9, prueba controlada real (E): confirma que
    `build_backtest_dataset` no falla contra un `HistoryRepository`
    alimentado por una corrida real del pipeline MLB. Sin `event_results`
    reales sincronizados en este entorno, el dataset debe reportar
    honestamente 0 filas (excluidas por "sin event_result todavía"), nunca
    fabricar una etiqueta."""
    from src.backtesting.dataset import build_backtest_dataset

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1

    dataset = build_backtest_dataset(tmp_history_repository)

    assert dataset.size == 0
    assert any("sin event_result" in w for w in dataset.warnings)


def test_compare_baselines_builds_honestly_on_real_mlb_pipeline_output_without_results(
    tmp_repository, tmp_history_repository
):
    """Paso 10, prueba controlada real (E): confirma que
    `compare_baselines` no falla contra un `HistoryRepository` alimentado
    por una corrida real del pipeline MLB. Sin `event_results` reales
    sincronizados en este entorno, `walk_forward_splits` no produce
    ningún fold (volumen insuficiente para los defaults documentados) --
    los tres baselines deben reportar 0 predicciones honestamente, nunca
    fabricar un resultado ni fallar."""
    from src.backtesting.dataset import build_backtest_dataset
    from src.evaluation.reports import compare_baselines
    from src.models.mlb_baseline import predict_mlb_baseline_from_features, train_mlb_baseline_model
    from src.models.mlb_elo import predict_mlb_elo, train_mlb_elo_model

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1

    dataset = build_backtest_dataset(tmp_history_repository)
    assert dataset.size == 0  # sin event_results reales sincronizados en este entorno

    def fit_fn_1(history_repository, models_dir):
        return train_mlb_baseline_model(history_repository, models_dir=models_dir)

    def predict_fn_1(row, artifact):
        return predict_mlb_baseline_from_features(row.features, artifact)

    def fit_fn_2(history_repository, models_dir):
        return train_mlb_elo_model(history_repository, models_dir=models_dir)

    def predict_fn_2(row, artifact):
        return predict_mlb_elo(row.record, artifact).p_model_yes

    report = compare_baselines(tmp_history_repository, dataset, fit_fn_1, predict_fn_1, fit_fn_2, predict_fn_2)

    for name in ("baseline_0_market", "baseline_1_logreg", "baseline_2_elo"):
        assert report.baseline_reports[name].n_predictions == 0
    assert any("0 predicciones" in w for w in report.warnings)


def test_gate_report_builds_honestly_on_real_mlb_pipeline_output_without_results(
    tmp_repository, tmp_history_repository
):
    """Fase 4, Paso 4.2, prueba controlada real (E): confirma que
    `build_sport_gate_report` no falla contra un `HistoryRepository`
    alimentado por una corrida real del pipeline MLB. Sin `event_results`
    reales sincronizados en este entorno (tmp_path, nunca data/engine.db),
    GATE-0 debe reportar honestamente "no cumplido" y el Coverage Gate
    0 etiquetados utilizables -- nunca fabricar una etiqueta ni un
    cumplimiento de gate."""
    from src.evaluation.gate_report import build_sport_gate_report
    from src.features.registry import CURRENT_FEATURE_SET_VERSION
    from src.models.mlb_baseline import DEFAULT_MIN_TRAINING_SAMPLES, build_mlb_training_dataset
    from src.models.schemas import Sport

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1

    report = build_sport_gate_report(
        tmp_history_repository,
        Sport.MLB,
        event_id_prefix="mlb_",
        thresholds={"mlb_classifier": DEFAULT_MIN_TRAINING_SAMPLES},
        build_dataset_fn=build_mlb_training_dataset,
        feature_set_version=CURRENT_FEATURE_SET_VERSION,
    )

    assert report.event_results_total == 0
    assert report.gate_0_met["mlb_classifier"] is False
    assert report.coverage_labeled_count == 0
    if report.feature_snapshots_total > 0:
        assert report.coverage_ratio == 0.0
        assert report.exclusions["no_result"] >= 1


def test_orchestrator_end_to_end_real(tmp_repository, tmp_history_repository, tmp_path):
    """Fase 4, Paso 4.1, prueba controlada real (E): confirma que el
    orquestador completo (captura real -> Policy Engine ->
    OpportunityRepository) funciona end-to-end contra un
    NormalizedRecord real de la API, con el PolicyManifest real
    aprobado (config/policy/mlb_v1.json) -- escribiendo únicamente en
    tmp_path, nunca en data/engine.db. Sin modelo entrenado en este
    entorno -> MODEL_NOT_TRAINED en cascada, ENTER nunca aparece
    (ORCHESTRATOR_SPEC.md §1.7), honesto, nunca fabricado."""
    from config.settings import PROJECT_ROOT
    from src.models.registry import load_latest_mlb_artifact
    from src.models.mlb_baseline import predict_mlb_baseline
    from src.models.schemas import Sport
    from src.opportunity.opportunity_repository import OpportunityRepository
    from src.orchestration.decision_pipeline import run_decision_pipeline
    from src.orchestration.sport_adapter import SportAdapter
    from src.policy.manifest import load_policy_manifest

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(
        mlb_date, repository=tmp_repository, history_repository=tmp_history_repository, limit=1
    )
    assert len(result.records) == 1

    opp_repository = OpportunityRepository(db_path=tmp_path / "opportunities.db")
    manifest = load_policy_manifest(PROJECT_ROOT / "config" / "policy" / "mlb_v1.json")
    adapter = SportAdapter(Sport.MLB, predict_mlb_baseline, load_latest_mlb_artifact)

    summary = run_decision_pipeline(
        records=result.records,
        feature_inputs_list=result.feature_inputs_list,
        feature_cutoffs=result.feature_cutoffs,
        sport=Sport.MLB,
        adapter=adapter,
        history_repository=tmp_history_repository,
        opportunity_repository=opp_repository,
        policy_manifest=manifest,
    )

    assert summary.skipped_errors == []
    record = result.records[0]
    if record.market_id is None:
        # matching de Kalshi no resuelto para este evento -- honesto,
        # nada que evaluar, no se fabrica una oportunidad (§4.2).
        assert summary.opportunities_created == 0
        assert summary.skipped_no_market_id == 1
    else:
        assert summary.opportunities_created == 2  # YES + NO
        assert summary.evaluations_created == 2
        assert "ENTER" not in summary.signal_type_counts
        evaluation = opp_repository.get_latest_evaluation(
            f"opp:{record.event_id}:{record.market_id}:YES"
        )
        assert evaluation is not None
        assert evaluation.signal_inputs.model_status.value == "MODEL_NOT_TRAINED"
        assert evaluation.model_version is None


def test_edge_and_ev_compute_honestly_on_real_mlb_pipeline_output(tmp_repository):
    """Paso 8, prueba controlada real (E): confirma que
    `compute_edge_yes`/`compute_edge_no`/`compute_ev_yes_bruto`/
    `compute_ev_no_bruto` no fallan sobre un `NormalizedRecord` real de la
    API. Sin modelo entrenado en este entorno -> EDGE/EV = None en
    cascada, honesto, nunca fabricado."""
    from src.models.mlb_elo import predict_mlb_elo
    from src.signals.edge import compute_edge_no, compute_edge_yes
    from src.signals.expected_value import compute_ev_no_bruto, compute_ev_yes_bruto

    mlb_date = _next_mlb_date_with_games()
    if mlb_date is None:
        pytest.skip("no hay juegos MLB próximos disponibles vía la API")
    result = run_mlb_pipeline(mlb_date, repository=tmp_repository, limit=1)
    assert len(result.records) == 1
    record = result.records[0]

    model_output = predict_mlb_elo(record, loaded_artifact=None)

    assert compute_edge_yes(model_output, record) is None
    assert compute_edge_no(model_output, record) is None
    assert compute_ev_yes_bruto(model_output, record) is None
    assert compute_ev_no_bruto(model_output, record) is None
