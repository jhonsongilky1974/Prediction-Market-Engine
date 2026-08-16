"""Phase 6 -- Semi-Automated Position Management (Tramo 1: dominio +
matemática + persistencia). Ver CONTINUITY.md cuando se documente el
cierre de este tramo.

Aislado deliberadamente de `src/matching/`, `src/payoff/`, `src/pricing/`
y de los pipelines de MLB/tenis: este módulo consume decisiones externas
(ENTER/WATCH/PASS vía `src/opportunity/schemas.py::Opportunity`, opcional)
pero nunca participa en el pipeline de matching ni inventa una señal
deportiva retroactivamente. No ejecuta órdenes reales: es cálculo,
recomendación y registro de lo que el usuario ya hizo manualmente en
Robinhood.
"""
from __future__ import annotations
