"""Trading Advisory -- Phase 6, Tramo 5B (Position Management Advisory).

Alcance de Tramo 5B: capa nueva, separada, stateless y de solo lectura
que produce asesoría accionable para POSICIONES YA EXISTENTES en
`src.positions` (Tramo 1-4, sin cambios de comportamiento). Nunca
selecciona nuevas oportunidades, nunca calcula `entry`/`sizing`/
`reentry` de una entrada nueva, nunca ejecuta nada.

Dirección de dependencia (obligatoria, testeada en
`tests/unit/test_positions_never_references_matching.py`): este paquete
puede importar `src.positions` (contratos + lecturas), pero
`src.positions` nunca importa `src.advisory`. `src.advisory` tampoco
importa `src.policy`/`src.orchestration` ni ningún módulo deportivo
(`src.matching`/`src.payoff`/`src.pricing`/`src.pipelines`/
`src.connectors`/`src.calibration`/`src.evidence`/`src.health`/
`src.explainability`/`src.uncertainty`/`src.features`/
`src.normalization`/`src.quality`/`src.evaluation`) -- ese alcance
(Trading Advisory completo, `OpportunityDecision`, evaluación simétrica
de nuevas entradas) queda diferido a Tramo 5B-siguiente/6, bloqueado
hasta que Tramo 5A (cobertura de calibración) se resuelva -- ver
CONTINUITY.md.
"""
