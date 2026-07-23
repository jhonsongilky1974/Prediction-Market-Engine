"""Feature registry para Fase 2 (Paso 1).

Definición TIPADA de qué features existen, sin ningún cálculo todavía (el
cálculo es Paso 2 — `mlb_features.py`/`tennis_features.py`, que este
módulo ni importa ni referencia). Cada entrada declara, como exige
PLAN_PHASE2.md §4: nombre, deporte, fuente, timestamp de disponibilidad,
fórmula, unidad, tratamiento de missing, riesgo de leakage, validación,
importancia esperada, y si está disponible ahora o bloqueada.

Dos niveles de detalle, fieles al plan aprobado:

- `SpecStatus.FULLY_SPECIFIED` — las features del baseline v1 (§4.1 MLB,
  §4.2 tenis), con las 10/11 dimensiones completas y un
  `compute_function_name` que ancla el contrato que Paso 2 deberá cumplir.
- `SpecStatus.REFERENCE_ONLY` — el resto del registry futuro (§4.3):
  nombre, deporte, disponibilidad y motivo de bloqueo/limitación. El plan
  es explícito en que estas NO se especifican en detalle todavía ("no se
  implementa antes de tener la fuente verificada") — por eso el modelo
  aquí no permite fabricar fórmula/leakage/importancia para ellas: esos
  campos quedan estructuralmente `None` hasta que se promuevan a
  `FULLY_SPECIFIED` en una revisión futura del registry.

`CURRENT_FEATURE_SET_VERSION` es la cadena que Paso 2 escribirá en
`feature_snapshots.feature_set_version` (histórico append-only, Paso 0):
ancla cada snapshot de features a la versión exacta de este registry que
lo produjo.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from pydantic import ConfigDict, model_validator

from src.models.schemas import Sport, StrictModel

CURRENT_FEATURE_SET_VERSION = "phase2_registry_v1"


class DataAvailability(str, Enum):
    """¿Existe HOY una fuente real que provea este dato? Independiente de
    si la feature ya está completamente especificada (ver SpecStatus)."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class SpecStatus(str, Enum):
    FULLY_SPECIFIED = "FULLY_SPECIFIED"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class LeakageRisk(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ExpectedImportance(str, Enum):
    LOW = "LOW"
    LOW_MEDIUM = "LOW_MEDIUM"
    MEDIUM = "MEDIUM"
    MEDIUM_HIGH = "MEDIUM_HIGH"
    HIGH = "HIGH"


class FeatureDefinition(StrictModel):
    """Metadata tipada de una feature. Ningún campo de cálculo: esto es
    contrato/documentación ejecutable, no lógica de negocio."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)

    name: str
    sport: Sport
    feature_set_version: str = CURRENT_FEATURE_SET_VERSION

    data_availability: DataAvailability
    spec_status: SpecStatus
    limitation_reason: Optional[str] = None
    """Por qué la disponibilidad no es AVAILABLE (motivo de bloqueo o de
    parcialidad). Obligatorio salvo que data_availability sea AVAILABLE."""

    source: str
    availability_timestamp: Optional[str] = None
    formula: Optional[str] = None
    unit: Optional[str] = None
    missing_treatment: Optional[str] = None
    leakage_risk: Optional[LeakageRisk] = None
    leakage_notes: Optional[str] = None
    validation_rule: Optional[str] = None
    expected_importance: Optional[ExpectedImportance] = None
    importance_explicitly_approved: bool = True
    """False cuando el plan aprobado no fijó explícitamente
    `expected_importance` para esta feature y se usó una inferencia de
    ingeniería razonable en su lugar (ver PLAN_PHASE2.md §4.1, grupo
    team_record_pct/team_ops_season/home_away) -- transparencia explícita
    en vez de aparentar que todo valor viene literalmente del plan."""

    compute_function_name: Optional[str] = None
    """Nombre de la función que Paso 2 deberá implementar en
    mlb_features.py/tennis_features.py. Es un contrato hacia adelante, no
    una referencia real todavía -- este módulo no importa Paso 2."""

    prohibited_as_model_input: bool = False
    """True solo para features que, aunque existieran, nunca deben
    alimentar P_model directamente (ver PLAN_PHASE2.md §15/§9: contaminaría
    la comparación P_model vs P_market). Hoy solo aplica a `market_context`."""

    @model_validator(mode="after")
    def _validate_conditional_requirements(self) -> "FeatureDefinition":
        if self.data_availability != DataAvailability.AVAILABLE and not self.limitation_reason:
            raise ValueError(
                f"'{self.name}': data_availability={self.data_availability.value} "
                "requiere limitation_reason (por qué no está disponible)"
            )

        if self.spec_status == SpecStatus.FULLY_SPECIFIED:
            if self.data_availability == DataAvailability.BLOCKED:
                raise ValueError(
                    f"'{self.name}': FULLY_SPECIFIED no es compatible con "
                    "data_availability=BLOCKED (PLAN_PHASE2.md §4.3: no se especifica "
                    "en detalle antes de tener la fuente verificada)"
                )
            required = {
                "availability_timestamp": self.availability_timestamp,
                "formula": self.formula,
                "unit": self.unit,
                "missing_treatment": self.missing_treatment,
                "leakage_risk": self.leakage_risk,
                "expected_importance": self.expected_importance,
                "compute_function_name": self.compute_function_name,
            }
            missing = [k for k, v in required.items() if v is None]
            if missing:
                raise ValueError(
                    f"'{self.name}' es FULLY_SPECIFIED pero le faltan campos "
                    f"obligatorios del registry: {missing}"
                )
        else:  # REFERENCE_ONLY
            if self.compute_function_name is not None:
                raise ValueError(
                    f"'{self.name}': REFERENCE_ONLY no debe declarar "
                    "compute_function_name todavía (aún no está especificada)"
                )

        return self


# =========================================================================
# Baseline v1 MLB — FULLY_SPECIFIED (PLAN_PHASE2.md §4.1)
# =========================================================================

_MLB_BASELINE: List[FeatureDefinition] = [
    FeatureDefinition(
        name="pitcher_era_season",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=season&group=pitching",
        availability_timestamp="En cuanto el pitcher probable esté confirmado en schedule (normalmente 1-5 días antes)",
        formula="Valor directo stat.era del pitcher probable de cada lado",
        unit="ERA (carreras/9 innings)",
        missing_treatment=(
            "NULL si el pitcher no tiene starts en la temporada (rookie) o si "
            "probablePitcher no está confirmado. Nunca 0 (0 ERA implicaría perfecto, falso)."
        ),
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Ninguno si se usa el ERA acumulado hasta antes de la fecha del juego a predecir (requiere filtrar por fecha)",
        validation_rule="Rango plausible [0, 15]; fuera de rango -> warning, no descarte silencioso",
        expected_importance=ExpectedImportance.HIGH,
        compute_function_name="compute_pitcher_era_season",
    ),
    FeatureDefinition(
        name="pitcher_whip_season",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=season&group=pitching, campo whip",
        availability_timestamp="Mismo patrón que pitcher_era_season",
        formula="Valor directo stat.whip del pitcher probable de cada lado",
        unit="WHIP (walks+hits/inning pitched)",
        missing_treatment="NULL si el pitcher no tiene starts en la temporada. Nunca 0.",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Mismo patrón que pitcher_era_season: usar snapshot pre-juego",
        validation_rule="Rango plausible [0, 5]",
        expected_importance=ExpectedImportance.HIGH,
        importance_explicitly_approved=False,
        compute_function_name="compute_pitcher_whip_season",
    ),
    FeatureDefinition(
        name="pitcher_k_pct",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=season&group=pitching, campos strikeOuts/battersFaced",
        availability_timestamp="Mismo patrón que pitcher_era_season",
        formula="stat.strikeOuts / stat.battersFaced",
        unit="fracción [0,1]",
        missing_treatment="NULL si el pitcher no tiene starts en la temporada. Nunca 0.",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Mismo patrón que pitcher_era_season: usar snapshot pre-juego",
        validation_rule="Rango plausible [0, 0.6]",
        expected_importance=ExpectedImportance.HIGH,
        importance_explicitly_approved=False,
        compute_function_name="compute_pitcher_k_pct",
    ),
    FeatureDefinition(
        name="pitcher_bb_pct",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=season&group=pitching, campos baseOnBalls/battersFaced",
        availability_timestamp="Mismo patrón que pitcher_era_season",
        formula="stat.baseOnBalls / stat.battersFaced",
        unit="fracción [0,1]",
        missing_treatment="NULL si el pitcher no tiene starts en la temporada. Nunca 0.",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Mismo patrón que pitcher_era_season: usar snapshot pre-juego",
        validation_rule="Rango plausible [0, 0.3]",
        expected_importance=ExpectedImportance.HIGH,
        importance_explicitly_approved=False,
        compute_function_name="compute_pitcher_bb_pct",
    ),
    FeatureDefinition(
        name="pitcher_ip_season",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=season&group=pitching, campo inningsPitched",
        availability_timestamp="Mismo patrón que pitcher_era_season",
        formula="Valor directo stat.inningsPitched",
        unit="innings",
        missing_treatment="NULL si el pitcher no tiene starts en la temporada. Nunca 0.",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Mismo patrón que pitcher_era_season: usar snapshot pre-juego",
        validation_rule="Rango plausible [0, 250]",
        expected_importance=ExpectedImportance.MEDIUM,
        importance_explicitly_approved=False,
        compute_function_name="compute_pitcher_ip_season",
    ),
    FeatureDefinition(
        name="pitcher_form_last5",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="MLB Stats API, people/{id}/stats?stats=gameLog&group=pitching, filtrado a los 5 starts previos con fecha < data_cutoff_timestamp",
        availability_timestamp="Disponible en cuanto haya al menos 3 starts previos en la temporada",
        formula="ERA/WHIP calculado SOLO sobre esos 5 starts (agregación propia, no un campo directo)",
        unit="ERA/WHIP (idem season)",
        missing_treatment=(
            "NULL si tiene menos de 3 starts previos disponibles (muestra insuficiente) -- "
            "no rellenar con el ERA de temporada como sustituto silencioso"
        ),
        leakage_risk=LeakageRisk.HIGH,
        leakage_notes=(
            "Alto si no se filtra por fecha correctamente -- el game log trae TODOS los "
            "starts de la temporada; hay que excluir explícitamente cualquier start con "
            "date >= data_cutoff_timestamp"
        ),
        validation_rule="Igual rango que ERA/WHIP de temporada",
        expected_importance=ExpectedImportance.MEDIUM_HIGH,
        compute_function_name="compute_pitcher_form_last5",
    ),
    FeatureDefinition(
        name="pitcher_vs_opponent_handedness_ops",
        sport=Sport.MLB,
        data_availability=DataAvailability.PARTIAL,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        limitation_reason="Requiere lineup confirmado del rival, que a menudo es MISSING con antelación",
        source="MLB Stats API, people/{id}/stats?stats=statSplits&group=pitching&sitCodes=vr,vl",
        availability_timestamp="Solo cuando el lineup rival esté confirmado (horas antes del juego)",
        formula=(
            "OPS permitido del pitcher contra bateadores del lado dominante del lineup rival "
            "(requiere conocer composición zurda/derecha del lineup rival)"
        ),
        unit="OPS permitido",
        missing_treatment="NULL si no hay lineup confirmado del rival",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Ninguno si el split es de temporada acumulada pre-juego",
        validation_rule="Rango plausible [0.300, 1.200]",
        expected_importance=ExpectedImportance.MEDIUM,
        compute_function_name="compute_pitcher_vs_opponent_handedness_ops",
    ),
    FeatureDefinition(
        name="bullpen_era_recent",
        sport=Sport.MLB,
        data_availability=DataAvailability.PARTIAL,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        limitation_reason="Requiere lógica de agregación nueva (no bloqueada por fuente, bloqueada por trabajo de implementación)",
        source="Derivado: teams/{id}/roster (relievers = gamesStarted=0) + people/{id}/stats?stats=gameLog por cada uno",
        availability_timestamp="Disponible en cuanto el roster activo y los game logs de los relevistas respondan",
        formula="ERA agregado del bullpen sobre sus últimas N apariciones (weighted por outs registrados, no promedio simple)",
        unit="ERA",
        missing_treatment=(
            "NULL si no se puede agregar (fallo de red en alguna sub-llamada) -- no "
            "promediar solo con los relievers que sí respondieron sin marcarlo como PARTIAL"
        ),
        leakage_risk=LeakageRisk.HIGH,
        leakage_notes="Igual que pitcher_form_last5: filtrar estrictamente por fecha",
        validation_rule="Rango plausible [0, 12]",
        expected_importance=ExpectedImportance.MEDIUM,
        compute_function_name="compute_bullpen_era_recent",
    ),
    FeatureDefinition(
        name="team_record_pct",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="schedule.teams.{home,away}.leagueRecord (ya en model_inputs.context)",
        availability_timestamp="Disponible con cada llamada a schedule",
        formula="wins / (wins + losses) del leagueRecord acumulado",
        unit="fracción [0,1]",
        missing_treatment="NULL si leagueRecord no está presente en el payload",
        leakage_risk=LeakageRisk.LOW,
        leakage_notes="Acumulado hasta la fecha de la llamada; hay que fijar el cutoff igual que el resto",
        expected_importance=ExpectedImportance.MEDIUM,
        importance_explicitly_approved=False,
        compute_function_name="compute_team_record_pct",
    ),
    FeatureDefinition(
        name="team_ops_season",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="teams/{id}/stats?stats=season&group=hitting",
        availability_timestamp="Disponible con cada llamada a teams/{id}/stats",
        formula="Valor directo stat.ops del equipo",
        unit="OPS",
        missing_treatment="NULL si el endpoint no responde o el campo está ausente",
        leakage_risk=LeakageRisk.LOW,
        leakage_notes="Acumulado hasta la fecha de la llamada; hay que fijar el cutoff igual que el resto",
        validation_rule="Rango plausible [0.500, 1.000]",
        expected_importance=ExpectedImportance.MEDIUM,
        importance_explicitly_approved=False,
        compute_function_name="compute_team_ops_season",
    ),
    FeatureDefinition(
        name="home_away",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="model_inputs.context (ya normalizado en Fase 1: home_team_id/away_team_id)",
        availability_timestamp="Disponible desde la normalización de Fase 1, sin llamada adicional",
        formula="Booleano: participant_a es home o away según schedule",
        unit="categórico (HOME/AWAY)",
        missing_treatment="NULL si context no trae home_team_id/away_team_id",
        leakage_risk=LeakageRisk.NONE,
        leakage_notes=(
            "Hecho estructural fijo del calendario (quién es local), no una estadística "
            "acumulada -- la justificación de 'fijar el cutoff' de la fila agrupada del plan "
            "aplica a team_record_pct/team_ops_season, no a este campo (hallazgo de auditoría "
            "del Paso 1: se corrigió de LOW a NONE)"
        ),
        expected_importance=ExpectedImportance.LOW_MEDIUM,
        importance_explicitly_approved=False,
        compute_function_name="compute_home_away",
    ),
    FeatureDefinition(
        name="il_flag_key_players",
        sport=Sport.MLB,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="teams/{id}/roster?rosterType=injuredList",
        availability_timestamp="Disponible con cada llamada al roster de IL",
        formula="Booleano/lista: ¿el pitcher probable o algún bateador titular reciente está en el IL?",
        unit="booleano / lista de nombres",
        missing_treatment=(
            "NULL (no False) si no se pudo consultar el roster de IL -- un False fabricado "
            "implicaría confirmado sano, que no es lo mismo que no verificado"
        ),
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Ninguno (estado en tiempo real, se consulta al momento de predecir)",
        expected_importance=ExpectedImportance.MEDIUM_HIGH,
        compute_function_name="compute_il_flag_key_players",
    ),
]

# =========================================================================
# Baseline v1 Tenis — FULLY_SPECIFIED (PLAN_PHASE2.md §4.2)
# =========================================================================

_TENNIS_BASELINE: List[FeatureDefinition] = [
    FeatureDefinition(
        name="rest_days",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        limitation_reason=None,
        source="Derivado del histórico de scoreboards de ESPN ya capturado por nuestro propio storage (Paso 0)",
        availability_timestamp="Requiere que Fase 2 haya acumulado al menos un partido previo del jugador (Paso 0 en marcha, histórico empieza vacío)",
        formula="start_time del partido a predecir menos start_time del último partido encontrado del mismo jugador en nuestro histórico",
        unit="días",
        missing_treatment=(
            "NULL si no tenemos un partido previo del jugador en nuestro histórico "
            "(típico al empezar a acumular datos) -- no asumir descansado con valor por defecto"
        ),
        leakage_risk=LeakageRisk.NONE,
        leakage_notes="Ninguno si se usa histórico estrictamente anterior a data_cutoff_timestamp",
        validation_rule="Rango plausible [0, 30] días; fuera de rango, revisar (podría indicar retorno de lesión)",
        expected_importance=ExpectedImportance.LOW_MEDIUM,
        compute_function_name="compute_rest_days",
    ),
    FeatureDefinition(
        name="tournament_round_context",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.AVAILABLE,
        spec_status=SpecStatus.FULLY_SPECIFIED,
        source="ESPN (grouping_name, nombre de torneo, notas de la competición)",
        availability_timestamp="Disponible con cada llamada al scoreboard de ESPN",
        formula="Directo (ronda del torneo, ya viene en el payload como texto)",
        unit="categórico",
        missing_treatment="NULL si ESPN no lo estructura para ese torneo",
        leakage_risk=LeakageRisk.NONE,
        expected_importance=ExpectedImportance.LOW,
        compute_function_name="compute_tournament_round_context",
    ),
]

# Nota: `rest_days` tiene limitation_reason=None explícito arriba porque su
# data_availability es AVAILABLE (la fuente en sí no está bloqueada); la
# dependencia de que Paso 0 acumule histórico es una condición operativa
# documentada en availability_timestamp, no una limitación de la fuente.

# =========================================================================
# Registry de referencia futuro — REFERENCE_ONLY (PLAN_PHASE2.md §4.3)
# Nunca se fabrica fórmula/leakage/importancia: el plan es explícito en que
# estas features "no se implementan antes de tener la fuente verificada".
# =========================================================================

_MLB_REFERENCE: List[FeatureDefinition] = [
    FeatureDefinition(
        name="opponent_splits",
        sport=Sport.MLB,
        data_availability=DataAvailability.PARTIAL,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Requiere agregación adicional más allá del split de handedness ya cubierto por pitcher_vs_opponent_handedness_ops",
        source="MLB Stats API (statSplits, variantes adicionales no cubiertas por el baseline v1)",
    ),
    FeatureDefinition(
        name="lineup_confirmed",
        sport=Sport.MLB,
        data_availability=DataAvailability.PARTIAL,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Depende de publicación del lineup (horas antes del juego)",
        source="MLB Stats API, boxscore.battingOrder",
    ),
    FeatureDefinition(
        name="platoon_advantage",
        sport=Sport.MLB,
        data_availability=DataAvailability.PARTIAL,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Depende de lineup confirmado + batSide por jugador",
        source="MLB Stats API, boxscore + people/{id}",
    ),
    FeatureDefinition(
        name="park_factors",
        sport=Sport.MLB,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Sin fuente ni histórico propio suficiente; MLB Stats API no expone un campo de park factor",
        source="Ninguna fuente aprobada todavía",
    ),
    FeatureDefinition(
        name="weather",
        sport=Sport.MLB,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Sin fuente de clima integrada ni aprobada",
        source="Ninguna fuente aprobada todavía",
    ),
    FeatureDefinition(
        name="travel_distance",
        sport=Sport.MLB,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Sin geolocalización de venues verificada",
        source="Ninguna fuente aprobada todavía",
    ),
    FeatureDefinition(
        name="market_context",
        sport=Sport.MLB,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Requiere ODDS_API_KEY configurada; además NUNCA debe usarse como input directo de P_model (contaminaría la comparación P_model vs P_market)",
        source="The Odds API (NOT_CONFIGURED en este entorno)",
        prohibited_as_model_input=True,
    ),
]

_TENNIS_REFERENCE: List[FeatureDefinition] = [
    FeatureDefinition(
        name="ranking_a",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado en este entorno (403 Cloudflare)",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="ranking_b",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado en este entorno (403 Cloudflare)",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="surface",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason=(
            "SofaScore bloqueado; ESPN no lo estructura como campo. NO se infiere por "
            "heurística de texto del nombre del torneo -- eso sería inventar disfrazado"
        ),
        source="SofaScore (estructurado) / ESPN (no estructurado, no usable)",
    ),
    FeatureDefinition(
        name="surface_record",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado en este entorno (403 Cloudflare)",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="h2h",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado en este entorno (403 Cloudflare)",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="h2h_by_surface",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado, y además requiere muestra suficiente por superficie una vez desbloqueado",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="aces",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; además solo existe post-partido, se usaría como forma reciente agregada de partidos ANTERIORES al cutoff, nunca del partido a predecir",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="double_faults",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="first_serve_pct",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="first_serve_points_won",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="second_serve_points_won",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="service_games_held",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="break_points_saved",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="break_points_converted",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="return_stats",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo matiz que aces (solo post-partido)",
        source="SofaScore, event/{id}/statistics",
    ),
    FeatureDefinition(
        name="last_5",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason=(
            "SofaScore bloqueado. NOTA de auditoría de Fase 2: una versión anterior del "
            "pipeline de tenis fabricó este campo con un placeholder (recuento de eventos, "
            "no forma real); ese bug fue corregido y esta entrada del registry permanece "
            "REFERENCE_ONLY deliberadamente hasta poder calcular W/L real verificado"
        ),
        source="SofaScore (requiere parsear winnerCode por evento)",
    ),
    FeatureDefinition(
        name="last_10",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="SofaScore bloqueado; mismo motivo que last_5",
        source="SofaScore (requiere parsear winnerCode por evento)",
    ),
    FeatureDefinition(
        name="match_duration_previa",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Depende de datos de partido de SofaScore",
        source="SofaScore",
    ),
    FeatureDefinition(
        name="fatigue",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Depende de match_duration_previa + rest_days combinados; el primero está bloqueado",
        source="Derivado (SofaScore + histórico propio)",
    ),
    FeatureDefinition(
        name="withdrawals_injuries",
        sport=Sport.TENNIS,
        data_availability=DataAvailability.BLOCKED,
        spec_status=SpecStatus.REFERENCE_ONLY,
        limitation_reason="Sin fuente estructurada confirmada; STATUS=CANCELLED/POSTPONED de ESPN es la única señal indirecta disponible hoy",
        source="Ninguna fuente estructurada aprobada todavía",
    ),
]

FEATURE_REGISTRY: Tuple[FeatureDefinition, ...] = tuple(
    _MLB_BASELINE + _TENNIS_BASELINE + _MLB_REFERENCE + _TENNIS_REFERENCE
)
"""Tupla inmutable, deliberadamente NO una lista (hallazgo de auditoría del
Paso 1: una `list` module-level permitía `FEATURE_REGISTRY.append(...)` /
`.clear()` externos, corrompiendo en silencio la fuente de verdad del
registry). Cada `FeatureDefinition` ya es inmutable (`frozen=True`); el
contenedor ahora también lo es."""


def validate_registry(registry: Iterable[FeatureDefinition]) -> None:
    """Invariantes a nivel de lote (cada FeatureDefinition ya se
    autovalida al construirse vía el model_validator). Lanza ValueError
    con TODOS los problemas encontrados, no solo el primero."""
    errors: List[str] = []

    names = [f.name for f in registry]
    seen: Dict[str, int] = {}
    for n in names:
        seen[n] = seen.get(n, 0) + 1
    duplicates = sorted(n for n, c in seen.items() if c > 1)
    if duplicates:
        errors.append(f"nombres de feature duplicados en el registry: {duplicates}")

    for feature in registry:
        if feature.feature_set_version != CURRENT_FEATURE_SET_VERSION:
            errors.append(
                f"'{feature.name}': feature_set_version={feature.feature_set_version!r} "
                f"no coincide con CURRENT_FEATURE_SET_VERSION={CURRENT_FEATURE_SET_VERSION!r}"
            )

    if errors:
        raise ValueError("Registry inválido:\n  - " + "\n  - ".join(errors))


# Fail-fast: un registry corrupto no debe poder importarse en silencio.
validate_registry(FEATURE_REGISTRY)


def get_feature(name: str) -> FeatureDefinition:
    for feature in FEATURE_REGISTRY:
        if feature.name == name:
            return feature
    raise KeyError(f"feature no encontrada en el registry: {name!r}")


def list_features(
    sport: Optional[Sport] = None,
    spec_status: Optional[SpecStatus] = None,
    data_availability: Optional[DataAvailability] = None,
) -> List[FeatureDefinition]:
    """Siempre devuelve una lista NUEVA (copia defensiva), incluso sin
    filtros -- hallazgo de auditoría del Paso 1: antes, `list_features()`
    sin argumentos devolvía la propia tupla/lista interna por referencia,
    y mutar el "resultado de una consulta" corrompía el registry real."""
    result: List[FeatureDefinition] = list(FEATURE_REGISTRY)
    if sport is not None:
        result = [f for f in result if f.sport == sport]
    if spec_status is not None:
        result = [f for f in result if f.spec_status == spec_status]
    if data_availability is not None:
        result = [f for f in result if f.data_availability == data_availability]
    return result


def list_computable_features(sport: Optional[Sport] = None) -> List[FeatureDefinition]:
    """Features FULLY_SPECIFIED -- las únicas para las que Paso 2 debe
    implementar `compute_function_name`."""
    return list_features(sport=sport, spec_status=SpecStatus.FULLY_SPECIFIED)
