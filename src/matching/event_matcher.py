"""Event matching entre una fuente de calendario/resultados (MLB Stats API,
ESPN Tennis) y un evento de Kalshi.

No se une por texto exacto. Se combina:
  - similitud de nombres de participantes (normalizados, tolerante a
    abreviaturas/ciudades vs nombre completo del equipo, iniciales/nombre
    completo de tenistas)
  - proximidad temporal (tolerancia configurable)
  - IDs de fuente cuando ya existan (ej. si un registro ya trae el ticker
    de Kalshi guardado de una corrida anterior)

Cada intento de match produce un `MatchResult` con `confidence`, `method` y
`warnings`. Si es ambiguo, NUNCA se fuerza: se marca `needs_review=True`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from config.settings import EVENT_NAME_MATCH_MIN_CONFIDENCE, EVENT_TIME_MATCH_TOLERANCE_MINUTES
from src.models.schemas import MatchMethod

_ABBREVIATIONS = {
    "st": "saint",
    "st.": "saint",
}

# Letras latinas extendidas que unicodedata.normalize("NFKD", ...) NO
# descompone en base+diacrítico (no son formas de compatibilidad), por lo
# que un simple .encode("ascii","ignore") las ELIMINA por completo en vez
# de transliterarlas -- ej. "Łukasz" quedaba en "ukasz" (perdiendo la L),
# "Đoković" en "okovic" (perdiendo la D). Se traducen explícitamente antes
# de la descomposición NFKD para nombres reales de tenistas con estas letras.
_SPECIAL_CHAR_MAP = str.maketrans(
    {
        "Ł": "L", "ł": "l",
        "Đ": "D", "đ": "d",
        "Ø": "O", "ø": "o",
        "Þ": "Th", "þ": "th",
        "ß": "ss",
        "Æ": "Ae", "æ": "ae",
        "Œ": "Oe", "œ": "oe",
    }
)


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    text = name.translate(_SPECIAL_CHAR_MAP)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    for ch in ".,'-":
        text = text.replace(ch, " ")
    tokens = [t for t in text.split() if t]
    tokens = [_ABBREVIATIONS.get(t, t) for t in tokens]
    return " ".join(tokens)


def _tokens_align(t1: str, t2: str) -> bool:
    """True si dos tokens son iguales o uno es prefijo del otro (ej. "c" es
    un prefijo válido de "cubs", el diferenciador que usa Kalshi para
    "Chicago Cubs"). Un prefijo de 1 carácter solo es señal fiable cuando ya
    hay otro token en común en el nombre completo (ver `_align_tokens`), así
    que aquí no se impone un largo mínimo."""
    if t1 == t2:
        return True
    shorter, longer = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    return len(shorter) >= 1 and longer.startswith(shorter)


def _acronym_match(token: str, remaining_pool: List[str]) -> Optional[int]:
    """¿Es `token` el acrónimo (iniciales) de una secuencia consecutiva de
    palabras al inicio de `remaining_pool`? Ej. "ws" -> ["white","sox"].
    Devuelve cuántas palabras de `remaining_pool` consumió, o None."""
    if len(token) < 2:
        return None
    max_window = min(len(token), len(remaining_pool))
    for window in range(2, max_window + 1):
        candidate_words = remaining_pool[:window]
        if "".join(w[0] for w in candidate_words if w) == token:
            return window
    return None


def _alignment_coverage(shorter: List[str], longer: List[str]) -> float:
    """Fracción de tokens de `shorter` que encuentran correspondencia
    (exacta, prefijo, o acrónimo de varias palabras) en `longer`, preservando
    cada palabra de `longer` para un solo uso. Cubre abreviaturas legítimas
    ("Kansas City" -> "Kansas City Royals", "Chicago Cubs" -> "Chicago C",
    "Chicago White Sox" -> "Chicago WS") sin premiar solapamiento de
    caracteres suelto entre nombres distintos (ver docstring de módulo)."""
    if not shorter:
        return 0.0
    pool = list(longer)
    matched = 0
    for tok in shorter:
        found_idx = None
        for i, cand in enumerate(pool):
            if _tokens_align(tok, cand):
                found_idx = i
                break
        if found_idx is not None:
            del pool[found_idx]
            matched += 1
            continue
        window = _acronym_match(tok, pool)
        if window:
            pool = pool[window:]
            matched += 1
    return matched / len(shorter)


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Similitud [0,1] pensada para identidad de equipos/jugadores, NO para
    texto libre. Dos señales, sin mezclarlas nunca en un max() ciego:

    1. Alineación de tokens (exacta/prefijo/acrónimo): si TODOS los tokens
       del nombre más corto encuentran correspondencia en el más largo ->
       1.0. Cubre las abreviaturas reales observadas en Kalshi ("Kansas
       City" por "Kansas City Royals", "Chicago C" por "Chicago Cubs",
       "Chicago WS" por "Chicago White Sox").
    2. Si la alineación NO es completa, el único crédito es solapamiento de
       tokens EXACTOS (Jaccard) -- nunca similitud de caracteres suelta.
       Esto es deliberado: "Ben Shelton" vs "Bryan Shelton" o "Chicago Cubs"
       vs "Chicago WS" comparten muchos caracteres pero son entidades
       distintas; SequenceMatcher.ratio() los puntuaba >0.8 (por encima del
       umbral de matching) solo por el substring compartido. Ver
       tests/unit/test_event_matcher.py para los casos que motivaron este
       diseño.
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    tokens_a, tokens_b = na.split(), nb.split()
    shorter, longer = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)

    if _alignment_coverage(shorter, longer) == 1.0:
        return 1.0

    set_a, set_b = set(tokens_a), set(tokens_b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def participants_similarity(
    source_a: Optional[str],
    source_b: Optional[str],
    target_a: Optional[str],
    target_b: Optional[str],
) -> Tuple[float, bool]:
    """Prueba ambos órdenes (home/away vs yes/no puede venir invertido) y
    devuelve (mejor_score, swapped)."""
    direct = min(name_similarity(source_a, target_a), name_similarity(source_b, target_b))
    swapped = min(name_similarity(source_a, target_b), name_similarity(source_b, target_a))
    if swapped > direct:
        return swapped, True
    return direct, False


_CONFIDENT_METHODS = (MatchMethod.SOURCE_ID, MatchMethod.EXACT_NAME_TIME, MatchMethod.FUZZY_NAME_TIME)


@dataclass
class MatchResult:
    confidence: float
    method: MatchMethod
    warnings: List[str] = field(default_factory=list)
    needs_review: bool = False
    swapped: bool = False

    @property
    def is_confident(self) -> bool:
        """True solo si el match es lo bastante bueno como para adjuntar
        datos de mercado al registro final. NEEDS_REVIEW/NO_MATCH NUNCA son
        confidentes: un candidato "mejor disponible" con confianza baja no
        debe hacerse pasar por un match confirmado (ver
        src/pipelines/mlb_pipeline.py y tennis_pipeline.py)."""
        return not self.needs_review and self.method in _CONFIDENT_METHODS


def match_event(
    source_participant_a: Optional[str],
    source_participant_b: Optional[str],
    source_start_time: Optional[datetime],
    target_participant_a: Optional[str],
    target_participant_b: Optional[str],
    target_start_time: Optional[datetime],
    tolerance_minutes: int = EVENT_TIME_MATCH_TOLERANCE_MINUTES,
    min_confidence: float = EVENT_NAME_MATCH_MIN_CONFIDENCE,
) -> MatchResult:
    warnings: List[str] = []

    if not source_participant_a or not source_participant_b:
        return MatchResult(0.0, MatchMethod.NO_MATCH, ["source participants incompletos"], needs_review=True)
    if not target_participant_a or not target_participant_b:
        return MatchResult(0.0, MatchMethod.NO_MATCH, ["target participants incompletos"], needs_review=True)

    name_score, swapped = participants_similarity(
        source_participant_a, source_participant_b, target_participant_a, target_participant_b
    )

    time_ok = True
    time_delta_minutes: Optional[float] = None
    if source_start_time is not None and target_start_time is not None:
        time_delta_minutes = abs((source_start_time - target_start_time).total_seconds()) / 60.0
        time_ok = time_delta_minutes <= tolerance_minutes
        if not time_ok:
            warnings.append(
                f"diferencia temporal {time_delta_minutes:.0f}min excede tolerancia de {tolerance_minutes}min"
            )
    else:
        warnings.append("start_time ausente en alguna de las fuentes; no se pudo validar proximidad temporal")

    if name_score >= 0.97 and time_ok:
        method = MatchMethod.EXACT_NAME_TIME
    elif name_score >= min_confidence and time_ok:
        method = MatchMethod.FUZZY_NAME_TIME
        warnings.append(f"similitud de nombres {name_score:.2f} (fuzzy, no exacta)")
    else:
        method = MatchMethod.NEEDS_REVIEW

    needs_review = method == MatchMethod.NEEDS_REVIEW or not time_ok
    if name_score < min_confidence:
        warnings.append(f"confianza de nombre {name_score:.2f} por debajo del umbral {min_confidence}")
    if swapped:
        warnings.append("orden de participantes invertido respecto a la fuente objetivo")

    return MatchResult(
        confidence=round(name_score if time_ok else name_score * 0.5, 4),
        method=method,
        warnings=warnings,
        needs_review=needs_review,
        swapped=swapped,
    )
