"""Baseline Elo simple MLB (Paso 6). Ver PLAN_PHASE2.md §12 ("Paso 6 --
Elo simple MLB (Baseline 2): mismo patrón infra/entrenado que 5a/5b, con
un piso de datos menor pero igualmente dependiente de resultados reales
del Paso 0") y el Design Proposal explícitamente aprobado antes de esta
implementación (fórmulas, parámetros y umbral citados abajo son
exactamente los aprobados ahí).

A diferencia del baseline de regresión logística (Paso 5a/5b), Elo:
  - NO usa `feature_snapshots` en absoluto -- solo necesita identidad de
    equipos (`event_snapshots.normalized_record_json`, campo
    `model_inputs.context.{away,home}_team_id`) + resultado
    (`event_results`). Esto es lo que el plan llama "piso de datos menor".
  - Se entrena con actualización SECUENCIAL estrictamente cronológica
    (`event_start_time` ascendente) -- no es un conjunto de muestras i.i.d.
    con split train/validation como en 5a/5b.
  - Tiene persistencia PROPIA e independiente (JSON simple -- el artefacto
    completo, `{team_id: rating}` + metadata, es directamente
    serializable, sin necesitar scikit-learn/joblib). No se modifica ni se
    reutiliza `src/models/registry.py` (tipado específicamente al
    artefacto de 5a/5b).
  - Reutiliza `PModelOutput`/`ModelStatus` de `src/models/base.py` sin
    modificarlos (declarados ahí como "independientes del deporte o del
    algoritmo concreto").

Limitación deliberada, documentada para una versión posterior: NO se
implementa regresión entre temporadas (season regression-to-mean). No hay
todavía suficientes temporadas históricas acumuladas para que tenga
sentido, y el plan pide explícitamente "Elo SIMPLE".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import DATA_MODELS_DIR
from src.models.base import ModelStatus, PModelOutput
from src.models.schemas import NormalizedRecord
from src.storage.history_repository import HistoryRepository

# Parámetros HEURISTIC, aprobados explícitamente (Design Proposal +
# ajustes del usuario) -- no derivados, revisables con evidencia futura.
DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K = 20.0
DEFAULT_HOME_ADVANTAGE = 25.0  # puntos Elo sumados al rating del equipo local (participant_b)
DEFAULT_MIN_GAMES = 50  # piso de suficiencia, menor que el de 5a/5b (~300-500) a propósito

# Elo no usa el feature registry (src/features/registry.py) -- este valor
# ocupa el campo `feature_set_version` del contrato compartido de
# PModelOutput únicamente para identificar la metodología, no una versión
# de features calculadas.
ELO_FEATURE_SET_VERSION = "mlb_elo_v1_no_features"

_VALID_RESULTS = {"PARTICIPANT_A_WON": 1, "PARTICIPANT_B_WON": 0}


# ---------------------------------------------------------------------
# 1. Secuencia cronológica de partidos (dataset builder de Elo)
# ---------------------------------------------------------------------


@dataclass
class EloGameRecord:
    event_id: str
    team_a_id: int  # participant_a = away, mismo convenio ya establecido en mlb_baseline.py
    team_b_id: int  # participant_b = home
    label: int  # 1 = team_a (away) ganó, 0 = team_b (home) ganó
    game_time: datetime  # event_start_time real del partido, NUNCA captured_at/recorded_at


@dataclass
class EloGameSequence:
    games: List[EloGameRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.games)


def build_mlb_elo_game_sequence(history_repository: HistoryRepository) -> EloGameSequence:
    """Construye la secuencia de partidos MLB ya decididos, en orden
    cronológico ESTRICTO por `event_start_time` (el momento real del
    partido, no cuándo lo capturamos) -- nunca aleatorio. Excluye (nunca
    fabrica) partidos sin `team_id` identificable, sin `event_start_time`,
    sin resultado, o con resultado no binario (CANCELLED/POSTPONED/
    NO_CONTEST)."""
    warnings: List[str] = []

    snapshot_rows = history_repository.get_all_event_snapshots()
    result_rows = history_repository.get_all_event_results()

    latest_result_by_event: Dict[str, Dict[str, Any]] = {}
    for row in result_rows:
        event_id = row["event_id"]
        existing = latest_result_by_event.get(event_id)
        if existing is None or row["recorded_at"] > existing["recorded_at"]:
            latest_result_by_event[event_id] = row

    # Una sola identidad por evento -- participantes/event_start_time no
    # cambian entre snapshots sucesivos del mismo event_id (solo precios).
    identity_by_event: Dict[str, Dict[str, Any]] = {}
    for row in snapshot_rows:
        event_id = row["event_id"]
        if event_id not in identity_by_event:
            identity_by_event[event_id] = row

    excluded_wrong_sport = 0
    excluded_no_result = 0
    excluded_non_binary_result = 0
    excluded_missing_identity = 0
    excluded_missing_start_time = 0

    games: List[EloGameRecord] = []
    for event_id, snap_row in identity_by_event.items():
        if not event_id.startswith("mlb_"):
            excluded_wrong_sport += 1
            continue

        result = latest_result_by_event.get(event_id)
        if result is None:
            excluded_no_result += 1
            continue
        result_value = result["result"]
        if result_value not in _VALID_RESULTS:
            excluded_non_binary_result += 1
            continue

        record_json = json.loads(snap_row["normalized_record_json"])
        context = ((record_json.get("model_inputs") or {}).get("context")) or {}
        team_a_id = context.get("away_team_id")
        team_b_id = context.get("home_team_id")
        if team_a_id is None or team_b_id is None:
            excluded_missing_identity += 1
            continue

        start_time_raw = snap_row["event_start_time"]
        if not start_time_raw:
            excluded_missing_start_time += 1
            continue
        game_time = datetime.fromisoformat(start_time_raw)

        games.append(
            EloGameRecord(
                event_id=event_id,
                team_a_id=int(team_a_id),
                team_b_id=int(team_b_id),
                label=_VALID_RESULTS[result_value],
                game_time=game_time,
            )
        )

    # Orden cronológico ESTRICTO -- la actualización de ratings depende de
    # procesar los partidos en el orden real en que ocurrieron.
    games.sort(key=lambda g: (g.game_time, g.event_id))

    if excluded_wrong_sport:
        warnings.append(f"{excluded_wrong_sport} event_snapshots excluidos: event_id no tiene prefijo 'mlb_'")
    if excluded_no_result:
        warnings.append(f"{excluded_no_result} event_snapshots excluidos: sin event_result todavía")
    if excluded_non_binary_result:
        warnings.append(
            f"{excluded_non_binary_result} event_snapshots excluidos: resultado no es "
            f"PARTICIPANT_A_WON/PARTICIPANT_B_WON"
        )
    if excluded_missing_identity:
        warnings.append(f"{excluded_missing_identity} event_snapshots excluidos: sin away_team_id/home_team_id")
    if excluded_missing_start_time:
        warnings.append(f"{excluded_missing_start_time} event_snapshots excluidos: sin event_start_time")

    return EloGameSequence(games=games, warnings=warnings)


# ---------------------------------------------------------------------
# 2. Cálculo de ratings -- función pura, sin I/O
# ---------------------------------------------------------------------


def compute_mlb_elo_ratings(
    games: List[EloGameRecord],
    k: float = DEFAULT_K,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    initial_rating: float = DEFAULT_INITIAL_RATING,
) -> Dict[int, float]:
    """Actualiza ratings Elo procesando `games` EN EL ORDEN YA DADO
    (el llamador es responsable del orden cronológico -- esta función no
    reordena nada, para que el orden usado sea siempre explícito y
    auditable). Equipo nunca visto arranca en `initial_rating`."""
    ratings: Dict[int, float] = {}
    for game in games:
        r_a = ratings.get(game.team_a_id, initial_rating)
        r_b = ratings.get(game.team_b_id, initial_rating)

        r_b_effective = r_b + home_advantage
        expected_a = 1.0 / (1.0 + 10.0 ** ((r_b_effective - r_a) / 400.0))
        actual_a = float(game.label)
        delta = k * (actual_a - expected_a)

        ratings[game.team_a_id] = r_a + delta
        ratings[game.team_b_id] = r_b - delta

    return ratings


# ---------------------------------------------------------------------
# 3. Training pipeline + persistencia independiente (JSON, sin joblib)
# ---------------------------------------------------------------------


@dataclass
class EloArtifact:
    model_version: str
    sport: str
    algorithm: str
    trained_at: datetime
    team_ratings: Dict[int, float]
    k: float
    home_advantage: float
    initial_rating: float
    n_games: int
    file_path: Path


def train_mlb_elo_model(
    history_repository: HistoryRepository,
    models_dir: Path = DATA_MODELS_DIR,
    min_games: int = DEFAULT_MIN_GAMES,
    k: float = DEFAULT_K,
    home_advantage: float = DEFAULT_HOME_ADVANTAGE,
    initial_rating: float = DEFAULT_INITIAL_RATING,
    now: Optional[datetime] = None,
) -> "tuple[ModelStatus, Optional[EloArtifact], List[str]]":
    """Training pipeline de Elo (Paso 6): SABE calcular ratings apenas
    exista una secuencia de partidos suficiente. Nunca calcula ratings por
    debajo de `min_games` -- devuelve `INSUFFICIENT_HISTORY` de forma
    honesta, sin fabricar ningún artefacto."""
    sequence = build_mlb_elo_game_sequence(history_repository)
    warnings = list(sequence.warnings)

    if sequence.size < min_games:
        warnings.append(
            f"secuencia con {sequence.size} partido(s), por debajo del umbral mínimo ({min_games}) "
            f"-- no se calculan ratings Elo (PLAN_PHASE2.md Paso 6)."
        )
        return ModelStatus.INSUFFICIENT_HISTORY, None, warnings

    team_ratings = compute_mlb_elo_ratings(
        sequence.games, k=k, home_advantage=home_advantage, initial_rating=initial_rating
    )

    now = now or datetime.now(timezone.utc)
    model_version = f"mlb_elo_v1_{now:%Y%m%dT%H%M%SZ}"
    models_dir.mkdir(parents=True, exist_ok=True)
    file_path = models_dir / f"{model_version}.json"

    artifact = EloArtifact(
        model_version=model_version,
        sport="MLB",
        algorithm="elo_v1",
        trained_at=now,
        team_ratings=team_ratings,
        k=k,
        home_advantage=home_advantage,
        initial_rating=initial_rating,
        n_games=sequence.size,
        file_path=file_path,
    )
    _save_elo_artifact(artifact)

    return ModelStatus.TRAINED, artifact, warnings


def _save_elo_artifact(artifact: EloArtifact) -> None:
    """Persistencia propia e independiente de `src/models/registry.py`
    (Paso 5a/5b, tipado a artefactos scikit-learn) -- el artefacto de Elo
    es enteramente JSON-serializable, sin necesitar joblib."""
    payload = {
        "model_version": artifact.model_version,
        "sport": artifact.sport,
        "algorithm": artifact.algorithm,
        "trained_at": artifact.trained_at.isoformat(),
        "team_ratings": {str(team_id): rating for team_id, rating in artifact.team_ratings.items()},
        "k": artifact.k,
        "home_advantage": artifact.home_advantage,
        "initial_rating": artifact.initial_rating,
        "n_games": artifact.n_games,
    }
    artifact.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_latest_mlb_elo_artifact(models_dir: Path = DATA_MODELS_DIR) -> Optional[EloArtifact]:
    """Devuelve el `EloArtifact` MLB más reciente por `trained_at`, o
    `None` si no hay ninguno todavía -- estado perfectamente válido
    (`model_status=MODEL_NOT_TRAINED` en inferencia)."""
    if not models_dir.exists():
        return None

    latest_data: Optional[dict] = None
    latest_trained_at: Optional[datetime] = None
    latest_path: Optional[Path] = None
    for path in sorted(models_dir.glob("mlb_elo_v1_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        trained_at = datetime.fromisoformat(data["trained_at"])
        if latest_trained_at is None or trained_at > latest_trained_at:
            latest_trained_at = trained_at
            latest_data = data
            latest_path = path

    if latest_data is None:
        return None

    return EloArtifact(
        model_version=latest_data["model_version"],
        sport=latest_data["sport"],
        algorithm=latest_data["algorithm"],
        trained_at=latest_trained_at,
        team_ratings={int(team_id): rating for team_id, rating in latest_data["team_ratings"].items()},
        k=latest_data["k"],
        home_advantage=latest_data["home_advantage"],
        initial_rating=latest_data["initial_rating"],
        n_games=latest_data["n_games"],
        file_path=latest_path,
    )


# ---------------------------------------------------------------------
# 4. Inference contract -- reutiliza PModelOutput/ModelStatus sin
#    modificarlos. Funciona con loaded_artifact=None.
# ---------------------------------------------------------------------


def predict_mlb_elo(record: NormalizedRecord, loaded_artifact: Optional[EloArtifact]) -> PModelOutput:
    """Contrato de inferencia de Elo (Paso 6). A diferencia de
    `predict_mlb_baseline`, no calcula features en vivo (Elo no las usa) --
    solo necesita `away_team_id`/`home_team_id` del propio registro.
    `data_cutoff_timestamp` es `trained_at` del artefacto (hasta cuándo se
    actualizaron los ratings), no "ahora" -- Elo no mira datos en vivo más
    allá de qué ratings ya calculó."""
    prediction_timestamp = datetime.now(timezone.utc)

    if loaded_artifact is None:
        return PModelOutput(
            p_model_yes=None,
            model_version=None,
            model_status=ModelStatus.MODEL_NOT_TRAINED,
            feature_set_version=ELO_FEATURE_SET_VERSION,
            prediction_timestamp=prediction_timestamp,
            data_cutoff_timestamp=prediction_timestamp,
            missing_features=[],
            warnings=[],
        )

    context = record.model_inputs.context or {}
    team_a_id = context.get("away_team_id")
    team_b_id = context.get("home_team_id")

    if team_a_id is None or team_b_id is None:
        missing = []
        if team_a_id is None:
            missing.append("away_team_id")
        if team_b_id is None:
            missing.append("home_team_id")
        return PModelOutput(
            p_model_yes=None,
            model_version=None,
            model_status=ModelStatus.MODEL_NOT_TRAINED,
            feature_set_version=ELO_FEATURE_SET_VERSION,
            prediction_timestamp=prediction_timestamp,
            data_cutoff_timestamp=loaded_artifact.trained_at,
            missing_features=missing,
            warnings=["team_id ausente -- no se puede evaluar Elo para este registro"],
        )

    warnings: List[str] = []
    r_a = loaded_artifact.team_ratings.get(int(team_a_id))
    if r_a is None:
        r_a = loaded_artifact.initial_rating
        warnings.append(f"team_id {team_a_id} sin historial en el artefacto -- se usó initial_rating como prior neutro")
    r_b = loaded_artifact.team_ratings.get(int(team_b_id))
    if r_b is None:
        r_b = loaded_artifact.initial_rating
        warnings.append(f"team_id {team_b_id} sin historial en el artefacto -- se usó initial_rating como prior neutro")

    r_b_effective = r_b + loaded_artifact.home_advantage
    p_a = 1.0 / (1.0 + 10.0 ** ((r_b_effective - r_a) / 400.0))

    return PModelOutput(
        p_model_yes=p_a,
        model_version=loaded_artifact.model_version,
        model_status=ModelStatus.TRAINED,
        feature_set_version=ELO_FEATURE_SET_VERSION,
        prediction_timestamp=prediction_timestamp,
        data_cutoff_timestamp=loaded_artifact.trained_at,
        missing_features=[],
        warnings=warnings,
    )
