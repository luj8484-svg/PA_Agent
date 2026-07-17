from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.simulation.domain import PathKind
from pa_agent.research_backtest.simulation.triggers import TriggerCandidate, TriggerKind

_PRIORITY = {
    TriggerKind.LIQUIDATION: 0,
    TriggerKind.STOP: 1,
    TriggerKind.TAKE_PROFIT: 2,
}


def resolve_ambiguity(
    path_kind: PathKind,
    parent_state: object,
    candidates: tuple[TriggerCandidate, ...],
) -> TriggerCandidate:
    del parent_state
    if not candidates:
        raise ValueError("ambiguity candidate set is empty")
    if path_kind is PathKind.BASELINE:
        def key(item: TriggerCandidate) -> tuple[Decimal, int]:
            distance = abs(item.trigger_price - item.open_price) / item.open_price
            return distance, _PRIORITY[item.kind]
    elif path_kind is PathKind.CONSERVATIVE:
        def key(item: TriggerCandidate) -> tuple[Decimal, int]:
            return item.minute_end_equity, _PRIORITY[item.kind]
    else:
        raise ValueError("unsupported path policy")
    return min(candidates, key=key)


@dataclass(frozen=True, slots=True)
class ResolvedPath:
    path_kind: PathKind
    selected_candidate: TriggerCandidate


def resolve_all_paths(
    path_kinds: tuple[PathKind, ...],
    parent_state: object,
    candidates: tuple[TriggerCandidate, ...],
) -> tuple[ResolvedPath, ...]:
    unique = tuple(dict.fromkeys(path_kinds))
    if set(unique) != {PathKind.BASELINE, PathKind.CONSERVATIVE} or len(unique) != 2:
        raise ValueError("active path set must contain exactly two stable identities")
    return tuple(
        ResolvedPath(kind, resolve_ambiguity(kind, parent_state, candidates))
        for kind in unique
    )

