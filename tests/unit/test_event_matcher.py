from datetime import datetime, timedelta, timezone

from src.matching.event_matcher import match_event, name_similarity, normalize_name
from src.models.schemas import MatchMethod


def test_name_similarity_city_vs_full_team_name():
    assert name_similarity("Kansas City", "Kansas City Royals") > 0.9


def test_name_similarity_identical_tennis_names():
    assert name_similarity("Daniel Merida", "Daniel Merida") == 1.0


def test_name_similarity_unrelated_names_low():
    assert name_similarity("Kansas City", "Boston Red Sox") < 0.5


def test_match_event_exact_name_and_time():
    t = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    result = match_event("Minnesota Twins", "Cleveland Guardians", t, "Minnesota Twins", "Cleveland Guardians", t)
    assert result.method == MatchMethod.EXACT_NAME_TIME
    assert result.needs_review is False
    assert result.confidence == 1.0


def test_match_event_swapped_order_detected():
    t = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    result = match_event("Cleveland Guardians", "Minnesota Twins", t, "Minnesota Twins", "Cleveland Guardians", t)
    assert result.swapped is True
    assert result.method == MatchMethod.EXACT_NAME_TIME


def test_match_event_time_outside_tolerance_needs_review():
    t1 = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=5)
    result = match_event("Minnesota Twins", "Cleveland Guardians", t1, "Minnesota Twins", "Cleveland Guardians", t2)
    assert result.needs_review is True
    assert any("tolerancia" in w for w in result.warnings)


def test_match_event_ambiguous_names_not_forced():
    t = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    result = match_event("Team A", "Team B", t, "Completely Different X", "Completely Different Y", t)
    assert result.method == MatchMethod.NEEDS_REVIEW
    assert result.needs_review is True


def test_match_event_missing_participants_never_forces_match():
    t = datetime(2026, 7, 21, 22, 40, tzinfo=timezone.utc)
    result = match_event(None, "Cleveland Guardians", t, "Minnesota Twins", "Cleveland Guardians", t)
    assert result.method == MatchMethod.NO_MATCH
    assert result.needs_review is True


def test_match_event_missing_start_time_flags_warning():
    result = match_event("Daniel Merida", "Kyrian Jacquet", None, "Daniel Merida", "Kyrian Jacquet", None)
    assert any("start_time ausente" in w for w in result.warnings)


# --- Regresión: name_similarity daba falsos positivos por apoyarse en
# SequenceMatcher.ratio() (similitud de caracteres), que premia substrings
# compartidos entre entidades DISTINTAS. Estos casos, con la implementación
# original, superaban el umbral de match (0.72) o incluso ganaban a la
# comparación correcta. Ver src/matching/event_matcher.py::name_similarity.

def test_name_similarity_same_city_different_mlb_teams_not_confused():
    """'Chicago Cubs' y 'Chicago White Sox' son equipos DISTINTOS que
    comparten ciudad. Antes del fix, 'Chicago Cubs' vs el diferenciador
    equivocado 'Chicago WS' puntuaba 0.818 (por encima del umbral 0.72 y
    por encima incluso de la comparación correcta 'Chicago White Sox' vs
    'Chicago WS' = 0.741), pudiendo ganar el matching por error."""
    assert name_similarity("Chicago Cubs", "Chicago WS") < 0.72
    assert name_similarity("Chicago White Sox", "Chicago C") < 0.72
    # las comparaciones correctas siguen siendo abreviaturas válidas (1.0)
    assert name_similarity("Chicago Cubs", "Chicago C") == 1.0
    assert name_similarity("Chicago White Sox", "Chicago WS") == 1.0


def test_name_similarity_same_city_wrong_disambiguator_below_correct():
    """La comparación incorrecta nunca debe puntuar >= que la correcta."""
    correct = name_similarity("New York Mets", "New York M")
    wrong = name_similarity("New York Mets", "New York Y")
    assert wrong < correct
    assert wrong < 0.72


def test_name_similarity_shared_surname_different_tennis_players():
    """Ben Shelton y Bryan Shelton son jugadores ATP reales y DISTINTOS que
    comparten apellido. La implementación anterior puntuaba 0.833 (por
    encima del umbral) solo por el substring 'shelton' compartido."""
    assert name_similarity("Ben Shelton", "Bryan Shelton") < 0.72


def test_name_similarity_shared_first_name_different_players():
    assert name_similarity("Andrey Rublev", "Andrey Kuznetsov") < 0.72
    assert name_similarity("Jack Draper", "Jack Sock") < 0.72


def test_name_similarity_unicode_letter_without_nfkd_decomposition():
    """Ł, Đ, Ø, Þ, ß no tienen forma de compatibilidad NFKD: un
    encode('ascii','ignore') ingenuo las BORRA en vez de transliterarlas
    ('Łukasz' -> 'ukasz', perdiendo la L). Afecta a tenistas reales
    (ej. Łukasz Kubot, dobles ATP)."""
    assert normalize_name("Łukasz Kubot") == "lukasz kubot"
    assert name_similarity("Łukasz Kubot", "Lukasz Kubot") == 1.0


def test_name_similarity_mlb_full_team_name_still_matches_city_alone():
    """No debe haber regresión en el caso legítimo de abreviatura por
    ciudad (sin necesidad de sufijo diferenciador)."""
    assert name_similarity("Kansas City", "Kansas City Royals") == 1.0
    assert name_similarity("Los Angeles Dodgers", "Los Angeles D") == 1.0
    assert name_similarity("Los Angeles Angels", "Los Angeles A") == 1.0
    assert name_similarity("Los Angeles Dodgers", "Los Angeles A") < 0.72
    assert name_similarity("Los Angeles Angels", "Los Angeles D") < 0.72
