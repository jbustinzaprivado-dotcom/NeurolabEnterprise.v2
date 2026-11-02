"""Máquina de estados de los entrenamientos (RN-02, §10).

QUEUED → PREPARING → RUNNING → COMPLETED / FAILED / CANCELLED. Ningún trabajo
llega a RUNNING sin pasar por PREPARING y los estados finales son inmutables.
"""

from __future__ import annotations

QUEUED = "QUEUED"
PREPARING = "PREPARING"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TRANSITIONS: dict[str, frozenset[str]] = {
    QUEUED: frozenset({PREPARING, CANCELLED}),
    PREPARING: frozenset({RUNNING, FAILED, CANCELLED}),
    RUNNING: frozenset({COMPLETED, FAILED, CANCELLED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

ACTIVE = frozenset({QUEUED, PREPARING, RUNNING})
TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})
RETRYABLE = frozenset({FAILED, CANCELLED})


class InvalidTransition(ValueError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Transición no permitida: {current} → {target}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def ensure_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
