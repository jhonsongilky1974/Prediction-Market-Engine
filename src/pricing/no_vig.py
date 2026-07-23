"""De-vig intra-bookmaker, multiplicativo v1 (Fase 2, Paso 4, Paso A de §7/§8).

Implementa únicamente el Paso A de PLAN_PHASE2.md §8: dado un par de
cuotas decimales YA etiquetadas como YES/NO para UN bookmaker, calcula
las probabilidades sin vig de ese bookmaker. No mezcla datos entre
bookmakers -- eso es responsabilidad de `odds_consensus.py` (Paso B).

```
p_raw_YES_i    = 1 / decimal_odds_YES_i
p_raw_NO_i     = 1 / decimal_odds_NO_i
overround_i    = p_raw_YES_i + p_raw_NO_i        (> 1, contiene el vig)
p_no_vig_YES_i = p_raw_YES_i / overround_i
p_no_vig_NO_i  = p_raw_NO_i  / overround_i
```

DECISIÓN DE ARQUITECTURA (Opción A, aprobada explícitamente por el
usuario tras el hallazgo de la revisión contractual del Paso 4): este
módulo recibe `decimal_odds_yes`/`decimal_odds_no` YA etiquetados como
parámetros. Nunca deriva esa etiqueta a partir de nombres de
participante -- ver el docstring de `odds_consensus.py` para el detalle
completo de por qué esa resolución queda fuera de alcance del Paso 4.

Cómputo puro: sin llamadas de red, sin persistencia.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NoVigResult:
    """Resultado del de-vig de UN bookmaker. Todos los campos `None`
    cuando las cuotas de entrada faltan o son inválidas -- nunca se
    fabrica un valor."""

    p_no_vig_yes: Optional[float]
    p_no_vig_no: Optional[float]
    overround: Optional[float]


def devig_bookmaker(
    decimal_odds_yes: Optional[float],
    decimal_odds_no: Optional[float],
) -> NoVigResult:
    """Paso A de §8 para un único bookmaker.

    `None` (para los tres campos) cuando cualquiera de las dos cuotas
    falta o no es una cuota decimal válida (`> 0`) -- una cuota decimal
    de 0 o negativa no tiene interpretación de probabilidad y nunca se
    usa ni se sustituye por un valor por defecto.
    """
    if decimal_odds_yes is None or decimal_odds_no is None:
        return NoVigResult(None, None, None)
    if decimal_odds_yes <= 0 or decimal_odds_no <= 0:
        return NoVigResult(None, None, None)

    p_raw_yes = 1.0 / decimal_odds_yes
    p_raw_no = 1.0 / decimal_odds_no
    overround = p_raw_yes + p_raw_no

    p_no_vig_yes = p_raw_yes / overround
    p_no_vig_no = p_raw_no / overround
    return NoVigResult(p_no_vig_yes, p_no_vig_no, overround)
