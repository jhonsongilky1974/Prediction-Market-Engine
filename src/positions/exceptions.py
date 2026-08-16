"""Excepciones de dominio de Phase 6 (Position Management). Fail-closed:
ante estado incoherente, versión stale, cantidad imposible, fill
duplicado o violación de invariantes, el módulo siempre falla de forma
explícita -- nunca repara silenciosamente datos financieros.
"""
from __future__ import annotations


class PositionDomainError(Exception):
    """Base de todas las excepciones de `src.positions`."""


class InvalidStateTransitionError(PositionDomainError):
    """Transición de estado no permitida por la máquina de estados de
    Order o Position -- ver `src.positions.state_machine`."""


class InvariantViolationError(PositionDomainError):
    """Un invariante de dominio se violaría (open_contracts negativo,
    venta de más contratos de los abiertos, qty confirmada mayor a la
    solicitada, etc.). Nunca se repara en silencio: se rechaza la
    operación completa."""


class OptimisticLockError(PositionDomainError):
    """La versión esperada por el llamador no coincide con la versión
    almacenada -- alguien más escribió la fila primero. Nunca
    last-write-wins silencioso: exige relectura/reconciliación
    explícita por parte del llamador."""


class IdempotencyConflictError(PositionDomainError):
    """Se intentó reutilizar una clave de idempotencia (intent_id,
    fill_id) para una operación con datos distintos a los de la
    operación original ya registrada -- no es un duplicado inocuo, es
    una contradicción que debe fallar, no silenciarse."""


class NonTerminalOrderExistsError(PositionDomainError):
    """Ya existe una Order en estado no terminal (PLANNED/SUBMITTED/
    PENDING/PARTIALLY_FILLED/UNKNOWN) para esta Position -- no se puede
    crear otra hasta que se resuelva (idempotencia F5, Caso C)."""
