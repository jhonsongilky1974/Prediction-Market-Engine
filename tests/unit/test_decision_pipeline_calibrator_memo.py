"""Memoización del calibrador POR CORRIDA en `run_decision_pipeline`.

`load_calibrator_fn` se invoca como máximo una vez por `model_version` base
durante UNA invocación (se reutiliza tanto un calibrador válido como `None`);
una excepción nunca se memoiza (comportamiento fail-closed previo intacto);
no existe estado entre corridas. No cambia selección, validación ni hashes
del calibrador: solo cuántas veces se invoca el cargador."""
from __future__ import annotations

import pytest

from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import Sport
from src.orchestration.decision_pipeline import _build_record_context, run_decision_pipeline
from src.orchestration.sport_adapter import SportAdapter
from tests.unit.test_decision_pipeline import (
    NOW,
    _FakeCalibrator,
    _lenient_manifest,
    _not_trained_predict,
    _record,
    _repos,
    _trained_predict,
)

VERSION_A = "tennis_baseline_logreg_v1_A"
VERSION_B = "tennis_baseline_logreg_v1_B"


def _records(n):
    return [_record(event_id=f"mlb_{i}", market_id=f"KXMLBGAME-T{i}") for i in range(n)]


def _run(tmp_path, records, adapter, hist_opp=None):
    hist, opp = hist_opp or _repos(tmp_path)
    summary = run_decision_pipeline(
        records=records,
        feature_inputs_list=[None] * len(records),
        feature_cutoffs=[NOW] * len(records),
        sport=Sport.MLB,
        adapter=adapter,
        history_repository=hist,
        opportunity_repository=opp,
        policy_manifest=_lenient_manifest(),
        now=NOW,
    )
    return summary, opp


def _calibration_version(opp, record):
    evaluation = opp.get_latest_evaluation(f"opp:{record.event_id}:{record.market_id}:YES")
    return evaluation.calibration_output.calibration_version, evaluation


def _predict_by_event(versions):
    """`predict_fn` que asigna a cada registro la `model_version` base de `versions[event_id]`."""

    def predict(record, inputs, data_cutoff_timestamp, loaded_artifact):
        return PModelOutput(
            p_model_yes=0.60,
            model_version=versions[record.event_id],
            model_status=ModelStatus.TRAINED,
            feature_set_version="phase2_registry_v1",
            prediction_timestamp=NOW,
            data_cutoff_timestamp=data_cutoff_timestamp or NOW,
        )

    return predict


def _adapter(load_calibrator_fn, predict_fn=_trained_predict):
    return SportAdapter(
        sport=Sport.MLB, predict_fn=predict_fn, load_artifact_fn=lambda: None, load_calibrator_fn=load_calibrator_fn
    )


def test_many_records_with_the_same_model_version_call_the_loader_exactly_once(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return _FakeCalibrator()

    records = _records(5)
    summary, opp = _run(tmp_path, records, _adapter(loader))

    assert calls == ["tennis_baseline_logreg_v1_test"]  # 5 registros, 1 sola invocación
    assert summary.skipped_errors == []
    for record in records:
        assert _calibration_version(opp, record)[0] == "FAKE_V1"  # todos calibrados


def test_a_valid_calibrator_instance_is_reused_for_every_record(tmp_path):
    used = []

    class CountingCalibrator(_FakeCalibrator):
        def calibrate(self, p_raw):
            used.append(id(self))
            return super().calibrate(p_raw)

    created = []

    def loader(model_version):
        created.append(CountingCalibrator())
        return created[-1]

    records = _records(4)
    _run(tmp_path, records, _adapter(loader))

    assert len(created) == 1
    assert used == [id(created[0])] * 4  # la misma instancia calibró los 4 registros


def test_a_none_result_is_memoized_too_fail_closed_without_retrying_per_record(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return None  # el guardián rechazó: fail-closed

    records = _records(4)
    summary, opp = _run(tmp_path, records, _adapter(loader))

    assert calls == ["tennis_baseline_logreg_v1_test"]  # el rechazo no se reintenta por registro
    assert summary.skipped_errors == []
    for record in records:
        version, evaluation = _calibration_version(opp, record)
        assert version is None
        assert evaluation.calibration_output.p_model_calibrated is None
        assert evaluation.signal_inputs.p_model == 0.60  # probabilidad cruda intacta


def test_different_base_model_versions_are_loaded_independently(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return _FakeCalibrator() if model_version == VERSION_A else None  # B es rechazado

    records = _records(6)
    versions = {r.event_id: (VERSION_A if i % 2 == 0 else VERSION_B) for i, r in enumerate(records)}
    _, opp = _run(tmp_path, records, _adapter(loader, _predict_by_event(versions)))

    assert sorted(calls) == [VERSION_A, VERSION_B]  # cada versión se evalúa una vez, por separado
    for i, record in enumerate(records):
        version, _ = _calibration_version(opp, record)
        assert version == ("FAKE_V1" if i % 2 == 0 else None)  # el resultado de A no contamina a B


def test_an_exception_is_never_memoized_and_stays_fail_closed_per_record(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        raise RuntimeError("guardián no disponible")

    records = _records(3)
    summary, opp = _run(tmp_path, records, _adapter(loader))

    assert len(calls) == 3  # la excepción NO se guarda: cada registro vuelve a intentarlo, como sin memo
    assert [(e, side) for e, side, _ in summary.skipped_errors] == [(r.event_id, "pre-side") for r in records]
    assert all("guardián no disponible" in err for _, _, err in summary.skipped_errors)
    for record in records:  # ningún registro se evalúa sin calibrador resuelto
        assert opp.get_latest_evaluation(f"opp:{record.event_id}:{record.market_id}:YES") is None


def test_after_an_exception_a_later_success_is_memoized_from_then_on(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        if len(calls) == 1:
            raise RuntimeError("fallo transitorio")
        return _FakeCalibrator()

    records = _records(4)
    summary, opp = _run(tmp_path, records, _adapter(loader))

    assert len(calls) == 2  # fallo (no memoizado) + 1 éxito reutilizado por los 2 registros restantes
    assert [e for e, _, _ in summary.skipped_errors] == [records[0].event_id]
    assert opp.get_latest_evaluation(f"opp:{records[0].event_id}:{records[0].market_id}:YES") is None
    for record in records[1:]:
        assert _calibration_version(opp, record)[0] == "FAKE_V1"


def test_the_memo_does_not_survive_between_runs_no_stale_state(tmp_path):
    """Cada invocación relee: el estado del registro cambia entre corridas y la
    segunda corrida usa el nuevo calibrador (sin caché global, de módulo ni entre corridas)."""
    state = {"calibrator": _FakeCalibrator()}
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return state["calibrator"]

    adapter = _adapter(loader)
    repos = _repos(tmp_path)
    first = _records(3)
    _run(tmp_path, first, adapter, repos)
    assert len(calls) == 1

    state["calibrator"] = None  # p. ej. el calibrador pasó a INVALID en el registro
    second = [_record(event_id=f"mlb_second_{i}", market_id=f"KXMLBGAME-S{i}") for i in range(3)]
    _, opp = _run(tmp_path, second, adapter, repos)

    assert len(calls) == 2  # una invocación por corrida
    for record in second:
        assert _calibration_version(opp, record)[0] is None  # no se reutilizó el calibrador viejo


def test_the_loader_is_never_called_without_a_model_version_or_a_market_id(tmp_path):
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return _FakeCalibrator()

    _run(tmp_path, _records(3), _adapter(loader, _not_trained_predict))  # sin model_version
    assert calls == []

    no_market = [_record(event_id="mlb_x", market_id=None)]
    _run(tmp_path, no_market, _adapter(loader))  # sin market_id: el registro se omite antes
    assert calls == []


def test_without_a_memo_direct_calls_keep_the_previous_behavior_of_loading_every_time():
    calls = []

    def loader(model_version):
        calls.append(model_version)
        return _FakeCalibrator()

    adapter = _adapter(loader)
    record = _record()
    _build_record_context(record, None, NOW, adapter, None, NOW)
    _build_record_context(record, None, NOW, adapter, None, NOW)
    assert len(calls) == 2  # sin `calibrator_memo` no hay memoización alguna

    memo = {}
    _build_record_context(record, None, NOW, adapter, None, NOW, memo)
    _build_record_context(record, None, NOW, adapter, None, NOW, memo)
    assert len(calls) == 3
    assert list(memo) == ["tennis_baseline_logreg_v1_test"]


def test_no_module_level_cache_exists_in_decision_pipeline():
    import src.orchestration.decision_pipeline as module

    mutable_module_state = [
        name for name, value in vars(module).items()
        if not name.startswith("__") and isinstance(value, (dict, list, set))
    ]
    assert mutable_module_state == []


def _predict_with_version(model_version):
    """`predict_fn` entrenado (p=0.60) cuyo `model_version` es el dado (`""` o `None`)."""

    def predict(record, inputs, data_cutoff_timestamp, loaded_artifact):
        return PModelOutput(
            p_model_yes=0.60,
            model_version=model_version,
            model_status=ModelStatus.TRAINED,
            feature_set_version="phase2_registry_v1",
            prediction_timestamp=NOW,
            data_cutoff_timestamp=data_cutoff_timestamp or NOW,
        )

    return predict


def test_empty_model_version_is_treated_exactly_like_an_absent_model_version(tmp_path):
    """`model_version == ""` equivale a versión ausente: el cargador no se invoca, la cadena
    vacía no se guarda como clave del memo, no se aplica ningún calibrador, los campos de
    calibración quedan en None y la probabilidad cruda se conserva; idéntico a `None`."""
    outcomes = {}
    for label, version in (("empty", ""), ("absent", None)):
        calls = []

        def loader(model_version, _calls=calls):
            _calls.append(model_version)
            return _FakeCalibrator()  # si se invocara, SÍ calibraría: el test lo detectaría

        adapter = _adapter(loader, _predict_with_version(version))

        # 1) a través de run_decision_pipeline (5 registros)
        records = _records(5)
        (tmp_path / label).mkdir()
        summary, opp = _run(tmp_path / label, records, adapter)
        assert calls == []  # el cargador no se invoca (ni siquiera una vez)
        assert summary.skipped_errors == []

        # 2) directamente, con un memo explícito: la cadena vacía no se guarda como clave
        memo = {}
        ctx = _build_record_context(_record(), None, NOW, adapter, None, NOW, memo)
        assert calls == []
        assert memo == {}  # ni "" ni ninguna otra clave

        # 3) y 4) ningún calibrador: campos de calibración en None
        out = ctx.calibration_output
        assert out.p_model_calibrated is None
        assert out.calibration_version is None
        assert out.calibration_method is None
        assert out.calibrated_at is None
        # 5) la probabilidad cruda se conserva sin cambios
        assert out.p_model_raw == 0.60

        for record in records:
            version_calibration, evaluation = _calibration_version(opp, record)
            assert version_calibration is None
            assert evaluation.calibration_output.p_model_calibrated is None
            assert evaluation.signal_inputs.p_model == 0.60

        outcomes[label] = (
            out.p_model_raw, out.p_model_calibrated, out.calibration_version, out.calibration_method,
            out.calibrated_at, out.model_version if label == "absent" else None, calls, memo,
        )

    # 6) el comportamiento coincide con model_version ausente
    empty, absent = outcomes["empty"], outcomes["absent"]
    assert empty[:5] == absent[:5]
    assert empty[6:] == absent[6:]
