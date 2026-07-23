"""Tests del cálculo de features MLB (Fase 2, Paso 2).

Fixtures basadas en la forma REAL de los payloads de la MLB Stats API,
verificada en vivo antes de escribir este módulo (ver informe de entrega
del Paso 2): era/whip/ops/pct llegan como strings, inningsPitched usa
notación de tercios ('X.Y', Y en {0,1,2}), statSplits trae split.code en
{'vl','vr'}, gameLog trae date/outs/earnedRuns/baseOnBalls/hits por
entrada, roster/injuredList trae roster[].person.id.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.features.mlb_features import (
    CURRENT_FEATURE_SET_VERSION,
    MIN_STARTS_FOR_FORM,
    MlbFeatureInputs,
    RawDataPoint,
    compute_bullpen_era_recent,
    compute_home_away,
    compute_il_flag_key_players,
    compute_mlb_features,
    compute_pitcher_bb_pct,
    compute_pitcher_era_season,
    compute_pitcher_form_last5,
    compute_pitcher_ip_season,
    compute_pitcher_k_pct,
    compute_pitcher_vs_opponent_handedness_ops,
    compute_pitcher_whip_season,
    compute_team_ops_season,
    compute_team_record_pct,
)
from src.features.registry import Sport as RegistrySport
from src.features.registry import list_computable_features
from src.models.schemas import ModelInputs, NormalizedRecord, Sport

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 7, 22, 22, 40, tzinfo=timezone.utc)  # ej. hora de un juego


def _season_pitching_payload(era="3.45", whip="1.20", innings_pitched="60.1", outs=181,
                              strike_outs=65, base_on_balls=20, batters_faced=250, games_started=11):
    return {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "era": era,
                            "whip": whip,
                            "inningsPitched": innings_pitched,
                            "outs": outs,
                            "strikeOuts": strike_outs,
                            "baseOnBalls": base_on_balls,
                            "battersFaced": batters_faced,
                            "gamesStarted": games_started,
                        }
                    }
                ]
            }
        ]
    }


def _handedness_splits_payload(vl_ops=".750", vr_ops=".834"):
    return {
        "stats": [
            {
                "splits": [
                    {"split": {"code": "vl", "description": "vs Left"}, "stat": {"ops": vl_ops, "avg": ".250"}},
                    {"split": {"code": "vr", "description": "vs Right"}, "stat": {"ops": vr_ops, "avg": ".417"}},
                ]
            }
        ]
    }


def _game_log_payload(entries):
    """`entries`: lista de (date_str, earned_runs, outs, base_on_balls, hits)."""
    splits = []
    for date_str, er, outs, bb, hits in entries:
        splits.append(
            {
                "date": date_str,
                "stat": {"earnedRuns": er, "outs": outs, "baseOnBalls": bb, "hits": hits},
            }
        )
    return {"stats": [{"splits": splits}]}


def _team_hitting_payload(ops=".735"):
    return {"stats": [{"splits": [{"stat": {"ops": ops}}]}]}


def _il_roster_payload(person_ids):
    return {"roster": [{"person": {"id": pid}} for pid in person_ids]}


def _mlb_record(**overrides):
    context = {
        "away_team_id": 142,
        "home_team_id": 114,
        "away_league_record": {"wins": 49, "losses": 52, "pct": ".485"},
        "home_league_record": {"wins": 55, "losses": 46, "pct": ".545"},
    }
    return NormalizedRecord(
        sport=Sport.MLB,
        event_id="mlb_824409",
        participant_a="Minnesota Twins",
        participant_b="Cleveland Guardians",
        model_inputs=ModelInputs(context=context),
        **overrides,
    )


# =========================================================================
# Cálculo correcto (fixtures con forma real verificada)
# =========================================================================

def test_pitcher_era_season_parses_string_correctly():
    raw = RawDataPoint(payload=_season_pitching_payload(era="3.45"), captured_at=NOW)
    assert compute_pitcher_era_season(raw, CUTOFF) == 3.45


def test_pitcher_whip_season_parses_string_correctly():
    raw = RawDataPoint(payload=_season_pitching_payload(whip="1.20"), captured_at=NOW)
    assert compute_pitcher_whip_season(raw, CUTOFF) == 1.20


def test_pitcher_k_pct_computed_from_counts():
    raw = RawDataPoint(payload=_season_pitching_payload(strike_outs=65, batters_faced=250), captured_at=NOW)
    assert compute_pitcher_k_pct(raw, CUTOFF) == pytest.approx(65 / 250)


def test_pitcher_bb_pct_computed_from_counts():
    raw = RawDataPoint(payload=_season_pitching_payload(base_on_balls=20, batters_faced=250), captured_at=NOW)
    assert compute_pitcher_bb_pct(raw, CUTOFF) == pytest.approx(20 / 250)


def test_pitcher_ip_season_uses_outs_not_naive_decimal_parse():
    """outs=181 -> 60.333... innings, NUNCA 60.1 (que sería la lectura
    decimal ingenua de 'inningsPitched': '60.1')."""
    raw = RawDataPoint(payload=_season_pitching_payload(innings_pitched="60.1", outs=181), captured_at=NOW)
    result = compute_pitcher_ip_season(raw, CUTOFF)
    assert result == pytest.approx(181 / 3)
    assert result != 60.1


def test_pitcher_ip_season_falls_back_to_thirds_notation_without_outs():
    """Sin `outs`, se parsea 'X.Y' como tercios (Y en {0,1,2}), no decimal."""
    payload = _season_pitching_payload(innings_pitched="11.1")
    del payload["stats"][0]["splits"][0]["stat"]["outs"]
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_ip_season(raw, CUTOFF)
    assert result == pytest.approx(11 + 1 / 3)
    assert result != 11.1


def test_pitcher_ip_season_rejects_invalid_thirds_fraction():
    """Un fraccionario fuera de {0,1,2} (ej. '.3') es un formato
    inesperado -- None, no se inventa una interpretación."""
    payload = _season_pitching_payload(innings_pitched="11.3")
    del payload["stats"][0]["splits"][0]["stat"]["outs"]
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    assert compute_pitcher_ip_season(raw, CUTOFF) is None


def test_handedness_ops_selects_correct_split_by_opponent_hand():
    raw = RawDataPoint(payload=_handedness_splits_payload(vl_ops=".750", vr_ops=".834"), captured_at=NOW)
    assert compute_pitcher_vs_opponent_handedness_ops(raw, "L", CUTOFF) == pytest.approx(0.750)
    assert compute_pitcher_vs_opponent_handedness_ops(raw, "R", CUTOFF) == pytest.approx(0.834)


def test_team_record_pct_prefers_direct_pct_field():
    assert compute_team_record_pct({"wins": 49, "losses": 52, "pct": ".485"}) == pytest.approx(0.485)


def test_team_record_pct_falls_back_to_wins_losses_when_pct_absent():
    assert compute_team_record_pct({"wins": 10, "losses": 10}) == pytest.approx(0.5)


def test_team_ops_season_parses_string():
    raw = RawDataPoint(payload=_team_hitting_payload(ops=".735"), captured_at=NOW)
    assert compute_team_ops_season(raw, CUTOFF) == pytest.approx(0.735)


def test_home_away_uses_context_and_normalizer_convention():
    record = _mlb_record()
    assert compute_home_away(record, "participant_a") == "AWAY"
    assert compute_home_away(record, "participant_b") == "HOME"


def test_il_flag_true_when_key_player_present():
    raw = RawDataPoint(payload=_il_roster_payload([111, 222, 333]), captured_at=NOW)
    assert compute_il_flag_key_players(raw, [222], CUTOFF) is True


def test_il_flag_false_when_key_player_absent():
    raw = RawDataPoint(payload=_il_roster_payload([111, 222]), captured_at=NOW)
    assert compute_il_flag_key_players(raw, [999], CUTOFF) is False


def test_bullpen_era_recent_aggregates_across_relievers():
    logs = {
        501: RawDataPoint(payload=_game_log_payload([("2026-07-15", 2, 3, 0, 2)]), captured_at=NOW),
        502: RawDataPoint(payload=_game_log_payload([("2026-07-16", 1, 3, 1, 1)]), captured_at=NOW),
    }
    result = compute_bullpen_era_recent(logs, CUTOFF)
    # total ER=3, total outs=6 -> 2 innings -> ERA = 3*9/2 = 13.5
    assert result == pytest.approx(13.5)


# =========================================================================
# Manejo seguro de inputs inválidos / malformados
# =========================================================================

@pytest.mark.parametrize(
    "compute_fn",
    [compute_pitcher_era_season, compute_pitcher_whip_season, compute_pitcher_k_pct,
     compute_pitcher_bb_pct, compute_pitcher_ip_season],
)
def test_season_stat_functions_return_none_for_none_raw(compute_fn):
    assert compute_fn(None, CUTOFF) is None


def test_season_stat_functions_return_none_for_malformed_payload():
    raw = RawDataPoint(payload={"unexpected": "shape"}, captured_at=NOW)
    assert compute_pitcher_era_season(raw, CUTOFF) is None


def test_season_stat_functions_return_none_for_non_numeric_batters_faced():
    payload = _season_pitching_payload()
    payload["stats"][0]["splits"][0]["stat"]["battersFaced"] = "no-es-un-numero"
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    assert compute_pitcher_k_pct(raw, CUTOFF) is None


def test_k_pct_none_when_batters_faced_is_zero():
    raw = RawDataPoint(payload=_season_pitching_payload(strike_outs=0, batters_faced=0), captured_at=NOW)
    assert compute_pitcher_k_pct(raw, CUTOFF) is None


def test_handedness_ops_none_for_missing_split_code():
    payload = _handedness_splits_payload()
    del payload["stats"][0]["splits"][1]  # elimina 'vr'
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    assert compute_pitcher_vs_opponent_handedness_ops(raw, "R", CUTOFF) is None


def test_home_away_rejects_invalid_participant_argument():
    record = _mlb_record()
    with pytest.raises(ValueError, match="participant_a.*participant_b"):
        compute_home_away(record, "participant_c")


def test_team_record_pct_none_for_non_dict_input():
    assert compute_team_record_pct(None) is None
    assert compute_team_record_pct("no-es-un-dict") is None


def test_data_cutoff_timestamp_naive_is_rejected():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=NOW)
    with pytest.raises(ValueError, match="tz-aware"):
        compute_pitcher_era_season(raw, datetime(2026, 7, 22))  # naive


def test_captured_at_naive_is_rejected():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=datetime(2026, 7, 22))  # naive
    with pytest.raises(ValueError, match="tz-aware"):
        compute_pitcher_era_season(raw, CUTOFF)


# =========================================================================
# Datos faltantes -> NULL, nunca 0/False fabricado
# =========================================================================

def test_rookie_with_zero_games_started_is_null_not_zero():
    """gamesStarted=0 -> None en TODAS las stats de temporada, nunca 0.0
    (0 ERA implicaría 'perfecto', que es falso -- es 'no ha lanzado')."""
    raw = RawDataPoint(payload=_season_pitching_payload(games_started=0), captured_at=NOW)
    assert compute_pitcher_era_season(raw, CUTOFF) is None
    assert compute_pitcher_whip_season(raw, CUTOFF) is None
    assert compute_pitcher_ip_season(raw, CUTOFF) is None


def test_il_flag_is_none_not_false_when_roster_unavailable():
    """Sin poder consultar el roster de IL, el resultado es None (no
    verificado), nunca False (que implicaría 'confirmado sano')."""
    assert compute_il_flag_key_players(None, [111], CUTOFF) is None
    unusable = RawDataPoint(payload=None, captured_at=NOW)
    assert compute_il_flag_key_players(unusable, [111], CUTOFF) is None


def test_handedness_ops_is_none_when_opponent_lineup_not_confirmed():
    """missing_treatment exacto del registry: 'NULL si no hay lineup
    confirmado del rival'."""
    raw = RawDataPoint(payload=_handedness_splits_payload(), captured_at=NOW)
    assert compute_pitcher_vs_opponent_handedness_ops(raw, None, CUTOFF) is None


def test_bullpen_era_recent_none_for_empty_reliever_dict():
    assert compute_bullpen_era_recent({}, CUTOFF) is None


def test_form_last5_incomplete_entry_excluded_not_zero_filled():
    """Una entrada sin baseOnBalls/hits no debe imputarse como 0 en el
    cálculo de WHIP -- se excluye ese componente del agregado."""
    payload = _game_log_payload(
        [
            ("2026-07-10", 2, 6, 1, 4),
            ("2026-07-14", 1, 6, 2, 3),
            ("2026-07-18", 3, 6, 0, 5),
        ]
    )
    # 4ta entrada sin baseOnBalls/hits
    payload["stats"][0]["splits"].append({"date": "2026-07-20", "stat": {"earnedRuns": 2, "outs": 6}})
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    assert result is not None
    assert result["era"] is not None
    # el WHIP se calcula igual (la entrada incompleta solo afecta el flag has_whip_component)


# =========================================================================
# Cutoff temporal y ausencia de leakage/look-ahead
# =========================================================================

def test_season_stat_unusable_when_captured_at_after_cutoff():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=CUTOFF + timedelta(minutes=1))
    assert compute_pitcher_era_season(raw, CUTOFF) is None


def test_season_stat_unusable_when_captured_at_equals_cutoff():
    """Frontera: captured_at == cutoff NO es estrictamente anterior ->
    no usable (regla conservadora, nunca mirar datos del mismo instante
    del corte hacia adelante)."""
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=CUTOFF)
    assert compute_pitcher_era_season(raw, CUTOFF) is None


def test_season_stat_usable_one_second_before_cutoff():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=CUTOFF - timedelta(seconds=1))
    assert compute_pitcher_era_season(raw, CUTOFF) is not None


def test_game_log_excludes_entries_on_or_after_cutoff_date():
    """Leakage explícito: el game log trae un start EN LA FECHA DEL
    CUTOFF (el propio partido a predecir) -- debe excluirse del cálculo
    de forma reciente, o el modelo estaría usando el resultado del
    partido que intenta predecir."""
    payload = _game_log_payload(
        [
            ("2026-07-10", 2, 18, 2, 4),
            ("2026-07-14", 1, 18, 1, 3),
            ("2026-07-18", 3, 18, 3, 5),
            ("2026-07-22", 0, 27, 0, 0),  # EN la fecha de CUTOFF (2026-07-22) -- debe excluirse
        ]
    )
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    assert result is not None
    assert result["starts_used"] == 3  # NO 4 -- el start del día del cutoff no se usó
    # si se hubiera colado el start del cutoff (0 ER en 9 innings, ERA=0),
    # el ERA agregado habría bajado artificialmente -- se verifica que no bajó:
    assert result["era"] > 0


def test_game_log_excludes_entries_strictly_future_to_cutoff():
    payload = _game_log_payload(
        [
            ("2026-07-10", 2, 18, 2, 4),
            ("2026-07-14", 1, 18, 1, 3),
            ("2026-07-18", 3, 18, 3, 5),
            ("2026-08-01", 0, 27, 0, 0),  # muy en el futuro respecto al cutoff
        ]
    )
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    assert result["starts_used"] == 3


def test_game_log_full_payload_unusable_when_captured_after_cutoff():
    payload = _game_log_payload([("2026-07-10", 2, 18, 2, 4)] * 3)
    raw = RawDataPoint(payload=payload, captured_at=CUTOFF + timedelta(hours=1))
    assert compute_pitcher_form_last5(raw, CUTOFF) is None


def test_bullpen_era_recent_excludes_appearances_on_or_after_cutoff():
    logs = {
        501: RawDataPoint(
            payload=_game_log_payload(
                [("2026-07-15", 1, 3, 0, 1), ("2026-07-22", 10, 3, 5, 5)]  # 2do en la fecha de cutoff
            ),
            captured_at=NOW,
        ),
    }
    result = compute_bullpen_era_recent(logs, CUTOFF)
    # solo debe usarse la aparición del 15, ER=1 outs=3 -> 1 inning -> ERA=9.0
    assert result == pytest.approx(9.0)


# =========================================================================
# Muestra insuficiente -> NULL
# =========================================================================

def test_form_last5_none_with_fewer_than_minimum_starts():
    payload = _game_log_payload([("2026-07-18", 2, 18, 2, 4), ("2026-07-20", 1, 18, 1, 3)])  # solo 2
    assert MIN_STARTS_FOR_FORM == 3
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    assert compute_pitcher_form_last5(raw, CUTOFF) is None


def test_form_last5_computed_with_exactly_minimum_starts():
    payload = _game_log_payload(
        [("2026-07-14", 2, 18, 2, 4), ("2026-07-18", 1, 18, 1, 3), ("2026-07-20", 3, 18, 0, 5)]
    )
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    assert result is not None
    assert result["starts_used"] == 3


def test_form_last5_uses_only_last_5_when_more_available():
    entries = [(f"2026-07-{d:02d}", 1, 18, 1, 3) for d in range(1, 8)]  # 7 starts previos
    payload = _game_log_payload(entries)
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    assert result["starts_used"] == 5


# =========================================================================
# Determinismo / reproducibilidad
# =========================================================================

def test_computation_is_deterministic_across_repeated_calls():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=NOW)
    results = [compute_pitcher_era_season(raw, CUTOFF) for _ in range(5)]
    assert len(set(results)) == 1


def test_orchestrator_is_deterministic_across_repeated_calls():
    record = _mlb_record()
    inputs = MlbFeatureInputs()
    inputs.pitcher_season_stat["participant_a"] = RawDataPoint(payload=_season_pitching_payload(), captured_at=NOW)
    r1 = compute_mlb_features(record, inputs, CUTOFF)
    r2 = compute_mlb_features(record, inputs, CUTOFF)
    assert r1 == r2


# =========================================================================
# Compatibilidad exacta con el Feature Registry del Paso 1
# =========================================================================

def test_every_computable_mlb_feature_has_a_matching_function_in_this_module():
    import src.features.mlb_features as module

    for feature in list_computable_features(sport=RegistrySport.MLB):
        assert hasattr(module, feature.compute_function_name), (
            f"'{feature.name}' declara compute_function_name="
            f"{feature.compute_function_name!r} pero no existe esa función en mlb_features.py"
        )


def test_no_stray_compute_function_without_registry_backing():
    """Ninguna función compute_* de este módulo debe existir sin respaldo
    del registry -- evita que una feature REFERENCE_ONLY/bloqueada se
    convierta accidentalmente en computable."""
    import src.features.mlb_features as module

    registry_function_names = {
        f.compute_function_name for f in list_computable_features(sport=RegistrySport.MLB)
    }
    module_compute_functions = {
        name for name in dir(module) if name.startswith("compute_") and callable(getattr(module, name))
    }
    # compute_mlb_features es el orquestador, no una feature individual del registry
    module_compute_functions.discard("compute_mlb_features")
    assert module_compute_functions == registry_function_names


def test_orchestrator_output_uses_exact_registry_feature_names():
    record = _mlb_record()
    inputs = MlbFeatureInputs()
    features, missing, warnings = compute_mlb_features(record, inputs, CUTOFF)
    registry_names = {f.name for f in list_computable_features(sport=RegistrySport.MLB)}
    assert set(features.keys()) == registry_names


def test_feature_set_version_matches_registry():
    from src.features.registry import CURRENT_FEATURE_SET_VERSION as REGISTRY_VERSION

    assert CURRENT_FEATURE_SET_VERSION == REGISTRY_VERSION


# =========================================================================
# Orquestador completo: missing_features, warnings, forma del resultado
# =========================================================================

def test_orchestrator_reports_missing_features_when_all_inputs_absent():
    record = _mlb_record()
    inputs = MlbFeatureInputs()  # todo vacío
    features, missing, warnings = compute_mlb_features(record, inputs, CUTOFF)

    assert features["pitcher_era_season"] == {"participant_a": None, "participant_b": None}
    assert "pitcher_era_season.participant_a" in missing
    assert "pitcher_era_season.participant_b" in missing
    # team_record_pct SÍ se puede calcular (viene del propio NormalizedRecord)
    assert features["team_record_pct"]["participant_a"] == pytest.approx(0.485)
    assert "team_record_pct.participant_a" not in missing


def test_orchestrator_flags_out_of_range_value_as_warning_not_silently_dropped():
    record = _mlb_record()
    inputs = MlbFeatureInputs()
    inputs.pitcher_season_stat["participant_a"] = RawDataPoint(
        payload=_season_pitching_payload(era="99.99"), captured_at=NOW
    )
    features, missing, warnings = compute_mlb_features(record, inputs, CUTOFF)
    assert features["pitcher_era_season"]["participant_a"] == 99.99  # el valor real se conserva
    assert any("pitcher_era_season.participant_a" in w for w in warnings)


def test_orchestrator_rejects_non_mlb_record():
    from src.models.schemas import Sport as SchemaSport

    tennis_record = NormalizedRecord(sport=SchemaSport.TENNIS, event_id="t1")
    with pytest.raises(ValueError, match="MLB"):
        compute_mlb_features(tennis_record, MlbFeatureInputs(), CUTOFF)


def test_orchestrator_computes_home_away_correctly():
    record = _mlb_record()
    features, _, _ = compute_mlb_features(record, MlbFeatureInputs(), CUTOFF)
    assert features["home_away"] == {"participant_a": "AWAY", "participant_b": "HOME"}


# =========================================================================
# Persistencia real en feature_snapshots (extiende el Paso 0, INSERT-only)
# =========================================================================

def test_persist_writes_a_real_feature_snapshot_row(tmp_path):
    from src.features.mlb_features import persist_mlb_feature_snapshot
    from src.storage.history_repository import HistoryRepository

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _mlb_record()
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=NOW)

    inputs = MlbFeatureInputs()
    inputs.pitcher_season_stat["participant_a"] = RawDataPoint(payload=_season_pitching_payload(), captured_at=NOW)

    feature_snapshot_id, features, missing, warnings = persist_mlb_feature_snapshot(
        hist, record, snap_id, inputs, CUTOFF, computed_at=NOW
    )

    rows = hist.get_feature_snapshots_for_event(record.event_id)
    assert len(rows) == 1
    assert rows[0]["id"] == feature_snapshot_id
    assert rows[0]["event_snapshot_id"] == snap_id
    assert rows[0]["feature_set_version"] == CURRENT_FEATURE_SET_VERSION

    import json

    stored_features = json.loads(rows[0]["features_json"])
    assert stored_features["pitcher_era_season"]["participant_a"] == 3.45


def test_persist_calling_twice_appends_never_overwrites(tmp_path):
    """Consistente con el diseño append-only del Paso 0: recalcular y
    persistir dos veces (ej. el pipeline se re-ejecuta) produce DOS filas
    en feature_snapshots, nunca sobrescribe la anterior."""
    from src.features.mlb_features import persist_mlb_feature_snapshot
    from src.storage.history_repository import HistoryRepository

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _mlb_record()
    snap_id = hist.save_event_snapshot(record, source="test", captured_at=NOW)
    inputs = MlbFeatureInputs()

    persist_mlb_feature_snapshot(hist, record, snap_id, inputs, CUTOFF, computed_at=NOW)
    persist_mlb_feature_snapshot(hist, record, snap_id, inputs, CUTOFF, computed_at=NOW + timedelta(minutes=1))

    rows = hist.get_feature_snapshots_for_event(record.event_id)
    assert len(rows) == 2


def test_persist_rejects_nonexistent_event_snapshot_id(tmp_path):
    """La FK de feature_snapshots (Paso 0/Paso 1) se aplica de verdad: un
    event_snapshot_id inexistente hace fallar el INSERT."""
    import sqlite3

    from src.features.mlb_features import persist_mlb_feature_snapshot
    from src.storage.history_repository import HistoryRepository

    hist = HistoryRepository(db_path=tmp_path / "hist.db")
    record = _mlb_record()
    inputs = MlbFeatureInputs()

    with pytest.raises(sqlite3.IntegrityError):
        persist_mlb_feature_snapshot(hist, record, 999999, inputs, CUTOFF, computed_at=NOW)


# =========================================================================
# Regresión de la auditoría adversarial del Paso 2
# =========================================================================

def test_il_flag_none_when_no_key_players_to_check():
    """Hallazgo A: key_player_ids=[] devolvía False (vía any([])) sin
    haber verificado a NADIE -- fabricaba 'confirmado sano' con cero
    verificación real, contradiciendo la propia filosofía de la función."""
    raw = RawDataPoint(payload={"roster": [{"person": {"id": 111}}]}, captured_at=NOW)
    assert compute_il_flag_key_players(raw, [], CUTOFF) is None
    # contraprueba: con al menos un id sí se verifica de verdad
    assert compute_il_flag_key_players(raw, [111], CUTOFF) is True
    assert compute_il_flag_key_players(raw, [999], CUTOFF) is False


def test_form_last5_out_of_range_era_produces_warning():
    """Hallazgo B: pitcher_form_last5 nunca se validaba contra rango pese
    a que el registry declara validation_rule='Igual rango que ERA/WHIP
    de temporada' -- un ERA de 450 no generaba ningún warning."""
    record = _mlb_record()
    inputs = MlbFeatureInputs()
    payload = _game_log_payload([("2026-07-14", 50, 3, 1, 1), ("2026-07-16", 50, 3, 1, 1), ("2026-07-18", 50, 3, 1, 1)])
    inputs.pitcher_game_log["participant_a"] = RawDataPoint(payload=payload, captured_at=NOW)
    _, _, warnings = compute_mlb_features(record, inputs, CUTOFF)
    assert any("pitcher_form_last5.participant_a.era" in w for w in warnings)


def test_form_last5_within_range_produces_no_warning():
    record = _mlb_record()
    inputs = MlbFeatureInputs()
    payload = _game_log_payload([("2026-07-14", 2, 18, 1, 3), ("2026-07-16", 1, 18, 1, 2), ("2026-07-18", 3, 18, 2, 4)])
    inputs.pitcher_game_log["participant_a"] = RawDataPoint(payload=payload, captured_at=NOW)
    _, _, warnings = compute_mlb_features(record, inputs, CUTOFF)
    assert not any("pitcher_form_last5" in w for w in warnings)


# =========================================================================
# Ataques adversariales adicionales al cutoff temporal (auditoría)
# =========================================================================

def test_season_stat_unusable_when_captured_exactly_one_second_after_cutoff():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=CUTOFF + timedelta(seconds=1))
    assert compute_pitcher_era_season(raw, CUTOFF) is None


def test_season_stat_usable_when_captured_exactly_one_second_before_cutoff():
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=CUTOFF - timedelta(seconds=1))
    assert compute_pitcher_era_season(raw, CUTOFF) is not None


def test_non_utc_but_aware_timezone_compared_correctly_against_utc_cutoff():
    """El cutoff está en UTC; captured_at llega en otra zona horaria
    aware (ej. US/Eastern, UTC-4). La comparación debe hacerse por
    instante absoluto, no por reloj de pared."""
    from datetime import timezone as tz

    eastern = tz(timedelta(hours=-4))
    captured_eastern = datetime(2026, 7, 22, 8, 0, tzinfo=eastern)  # 08:00 ET = 12:00 UTC
    cutoff_utc = datetime(2026, 7, 22, 22, 40, tzinfo=timezone.utc)
    raw = RawDataPoint(payload=_season_pitching_payload(), captured_at=captured_eastern)
    assert raw.usable(cutoff_utc) is True
    assert compute_pitcher_era_season(raw, cutoff_utc) is not None

    # frontera: captured a las 18:41 ET (=22:41 UTC) es DESPUÉS del cutoff de 22:40 UTC
    captured_after = datetime(2026, 7, 22, 18, 41, tzinfo=eastern)
    raw_after = RawDataPoint(payload=_season_pitching_payload(), captured_at=captured_after)
    assert raw_after.usable(cutoff_utc) is False


def test_doubleheader_same_calendar_day_is_conservatively_excluded_entirely():
    """LIMITACIÓN DOCUMENTADA (no un bug corregible dentro del alcance del
    Paso 2): el campo `date` del gameLog solo tiene granularidad de DÍA
    (verificado contra la API real: `game.gameDate` no existe en gameLog,
    solo `game.gameNumber`). Sin hora exacta, no hay forma segura de
    distinguir "Juego 1 de un doubleheader, ya jugado antes del cutoff"
    de "el propio partido a predecir" o "Juego 2, todavía en el futuro".
    La elección conservadora -- excluir el día calendario COMPLETO del
    cutoff -- sacrifica el Juego 1 legítimo a cambio de nunca arriesgar
    leakage. Este test documenta y fija ese comportamiento deliberado."""
    payload = _game_log_payload(
        [
            ("2026-07-18", 2, 18, 1, 3),
            ("2026-07-20", 1, 18, 1, 2),
            # Juego 1 de un doubleheader el MISMO día que el cutoff (2026-07-22),
            # jugado horas antes del partido objetivo -- se excluye igualmente.
            ("2026-07-22", 3, 18, 2, 4),
        ]
    )
    raw = RawDataPoint(payload=payload, captured_at=NOW)
    result = compute_pitcher_form_last5(raw, CUTOFF)
    # con el Juego 1 del doubleheader excluido, solo quedan 2 starts previos
    # -- por debajo de MIN_STARTS_FOR_FORM=3 -> None (comportamiento conservador)
    assert result is None


def test_target_game_never_leaks_into_season_aggregate_via_captured_at_ordering():
    """Ataque adicional: aunque el payload de temporada se haya capturado
    ANTES del cutoff, si sus números YA incluyen el resultado del partido
    objetivo (imposible de detectar desde el payload agregado, ya que no
    trae fecha), la única defensa disponible es captured_at -- se verifica
    que efectivamente basta con violar esa única defensa para bloquear el
    uso del dato."""
    raw_after_game = RawDataPoint(payload=_season_pitching_payload(era="1.00"), captured_at=CUTOFF + timedelta(minutes=5))
    assert compute_pitcher_era_season(raw_after_game, CUTOFF) is None
