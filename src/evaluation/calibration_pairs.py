"""Pares de calibración por EVENTO -- corrección metodológica YES/NO
(CONTINUITY.md §0.38).

Contrato semántico (fijo, no se reinterpreta para favorecer métricas):
- `p_model` / `PModelOutput.p_model_yes` = P(participante A gana). El
  `market_id` de un `NormalizedRecord` es, por construcción (D-2, §0.17),
  el contrato Kalshi cuyo YES corresponde a `participant_a`.
- Lado YES de un evento: `p = p_model_yes`, `y = 1` si `PARTICIPANT_A_WON`.
- Lado NO del mismo evento: `p = 1 - p_model_yes`, `y = 1 - y_yes` -- el
  ESPEJO exacto del lado YES, sin información nueva.

`signal_inputs.p_model` guarda `p_model_yes` TAL CUAL en ambas
oportunidades (YES y NO) del evento; emparejarlo con `y` del lado NO sin
invertirlo mezcla etiquetas complementarias con la misma probabilidad
(frecuencia observada artificial de 0.5) y contar ambos lados duplica `n`.
La unidad de calibración es el EVENTO: un único par `(p_A, y_A)` por
`event_id`, y `n >= 30` se cuenta en eventos, nunca en filas/lados/snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from src.backtesting.metrics import DEFAULT_CALIBRATION_BINS, calibration_curve

_RESULT_TO_Y = {"PARTICIPANT_A_WON": 1, "PARTICIPANT_B_WON": 0}
MIN_EVENTS_PER_BUCKET = 30


class DuplicateEventPairError(ValueError):
    """Más de un par para el mismo `event_id` -- p.ej. YES y NO del mismo
    evento tratados como muestras independientes."""


@dataclass(frozen=True)
class EventCalibrationPair:
    event_id: str
    p_participant_a_wins: float
    y_participant_a_won: int

    def __post_init__(self) -> None:
        if not (0.0 <= self.p_participant_a_wins <= 1.0):
            raise ValueError(f"p_participant_a_wins fuera de [0,1]: {self.p_participant_a_wins}")
        if self.y_participant_a_won not in (0, 1):
            raise ValueError(f"y_participant_a_won debe ser 0/1: {self.y_participant_a_won}")


def build_event_pairs(
    rows: Iterable[Tuple[str, Optional[float], str]],
) -> List[EventCalibrationPair]:
    """`rows` = `(event_id, p_model_yes, result)` con `result` en
    `PARTICIPANT_A_WON`/`PARTICIPANT_B_WON`. Omite filas sin probabilidad
    (`None`: sin modelo, nunca se fabrica) y lanza `DuplicateEventPairError`
    si un `event_id` aparece más de una vez -- exige UNA fila por evento."""
    pairs: Dict[str, EventCalibrationPair] = {}
    for event_id, p_model_yes, result in rows:
        if event_id in pairs:
            raise DuplicateEventPairError(
                f"event_id={event_id!r} aparece más de una vez -- la unidad de calibración es el evento, "
                "no el lado (YES/NO) ni el snapshot"
            )
        if result not in _RESULT_TO_Y:
            raise ValueError(f"resultado no binario para event_id={event_id!r}: {result!r}")
        if p_model_yes is None:
            continue
        pairs[event_id] = EventCalibrationPair(
            event_id=event_id,
            p_participant_a_wins=p_model_yes,
            y_participant_a_won=_RESULT_TO_Y[result],
        )
    return list(pairs.values())


def mirror_to_no_side(pair: EventCalibrationPair) -> Tuple[float, int]:
    """Vista del lado NO del MISMO evento: `(1 - p, 1 - y)`. Es un espejo
    exacto (mismo Brier) y NO una muestra independiente adicional."""
    return 1.0 - pair.p_participant_a_wins, 1 - pair.y_participant_a_won


@dataclass(frozen=True)
class BucketCoverage:
    bin_lo: float
    bin_hi: float
    n_events: int
    sufficient: bool


@dataclass(frozen=True)
class CalibrationCoverage:
    n_events: int
    buckets: List[BucketCoverage]
    min_events_per_bucket: int

    @property
    def insufficient_buckets(self) -> List[BucketCoverage]:
        return [b for b in self.buckets if not b.sufficient]

    @property
    def fully_covered(self) -> bool:
        """`True` solo si CADA bucket (incluidos los vacíos) tiene
        `n_events >= min_events_per_bucket`. Mientras sea `False` no se
        puede afirmar que el modelo esté calibrado en todo el rango."""
        return all(b.sufficient for b in self.buckets)


def compute_calibration_coverage(
    pairs: List[EventCalibrationPair],
    n_bins: int = DEFAULT_CALIBRATION_BINS,
    min_events_per_bucket: int = MIN_EVENTS_PER_BUCKET,
) -> CalibrationCoverage:
    """Eventos por bucket reutilizando `calibration_curve` (mismos buckets
    ya existentes, sin inventar umbrales). Los buckets vacíos se reportan
    con `n_events=0` e `sufficient=False`."""
    if len({p.event_id for p in pairs}) != len(pairs):
        raise DuplicateEventPairError("pares duplicados por event_id")
    observed = {
        round(b.bin_lo, 6): b.n_samples
        for b in calibration_curve(
            [p.y_participant_a_won for p in pairs], [p.p_participant_a_wins for p in pairs], n_bins=n_bins
        )
    }
    width = 1.0 / n_bins
    buckets = [
        BucketCoverage(
            bin_lo=i * width,
            bin_hi=(i + 1) * width,
            n_events=observed.get(round(i * width, 6), 0),
            sufficient=observed.get(round(i * width, 6), 0) >= min_events_per_bucket,
        )
        for i in range(n_bins)
    ]
    return CalibrationCoverage(n_events=len(pairs), buckets=buckets, min_events_per_bucket=min_events_per_bucket)
