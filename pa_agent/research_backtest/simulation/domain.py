from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_sha256,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.enums import MarginMode, PositionMode
from pa_agent.research_backtest.simulation.versions import (
    INTRAMINUTE_HALT_POLICY_VERSION,
    LIQUIDATION_MODEL_VERSION,
    MINUTE_EVENT_ORDER_VERSION,
    SIMULATION_CONFIG_VERSION,
)

SUPPORTED_SYMBOLS = ("BTCUSDT", "ETHUSDT")


class PathKind(StrEnum):
    BASELINE = "BASELINE"
    CONSERVATIVE = "CONSERVATIVE"


class PathState(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    HALTED = "HALTED"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    schema_version: str
    config_id: str
    config_content_hash: str
    symbols: tuple[str, ...]
    simulation_start_utc_ms: int
    simulation_end_exit_open_utc_ms: int
    initial_wallet_balance: Decimal
    leverage: int
    position_mode: PositionMode
    margin_mode: MarginMode
    active_path_kinds: tuple[PathKind, ...]
    minute_event_order_version: str
    intraminute_halt_policy_version: str
    liquidation_model_version: str
    cost_model_version: str
    funding_model_version: str
    two_a_version: str
    two_b_planner_version: str
    two_b_planner_config_hash: str
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != SIMULATION_CONFIG_VERSION:
            raise ValueError("unsupported SimulationConfig schema")
        if self.symbols != SUPPORTED_SYMBOLS:
            raise ValueError("symbols must be the frozen BTC/ETH pair")
        if (
            type(self.simulation_start_utc_ms) is not int
            or type(self.simulation_end_exit_open_utc_ms) is not int
            or self.simulation_start_utc_ms < 0
            or self.simulation_end_exit_open_utc_ms < self.simulation_start_utc_ms
            or self.simulation_start_utc_ms % 60_000
            or self.simulation_end_exit_open_utc_ms % 60_000
        ):
            raise ValueError("simulation times must be valid UTC one-minute open boundaries")
        if (
            not isinstance(self.initial_wallet_balance, Decimal)
            or not self.initial_wallet_balance.is_finite()
            or self.initial_wallet_balance <= 0
        ):
            raise ValueError("initial_wallet_balance must be a positive finite Decimal")
        if self.leverage != 1:
            raise ValueError("2C leverage must equal one")
        if self.position_mode is not PositionMode.ONE_WAY:
            raise ValueError("2C position mode must be one-way")
        if self.margin_mode is not MarginMode.ISOLATED:
            raise ValueError("2C margin mode must be isolated")
        if self.active_path_kinds != (PathKind.BASELINE, PathKind.CONSERVATIVE):
            raise ValueError("2C paths must be baseline and conservative")
        if self.minute_event_order_version != MINUTE_EVENT_ORDER_VERSION:
            raise ValueError("unsupported minute event order")
        if self.intraminute_halt_policy_version != INTRAMINUTE_HALT_POLICY_VERSION:
            raise ValueError("unsupported intraminute halt policy")
        if self.liquidation_model_version != LIQUIDATION_MODEL_VERSION:
            raise ValueError("unsupported liquidation model")
        for name in ("two_b_planner_config_hash", "dependency_lock_hash"):
            require_sha256(getattr(self, name), name)
        require_commit(self.code_commit)
        verify_formal_identity(
            self,
            id_field="config_id",
            hash_field="config_content_hash",
            prefix="simcfg_",
        )


def make_simulation_config(
    *,
    symbols: tuple[str, ...],
    simulation_start_utc_ms: int,
    simulation_end_exit_open_utc_ms: int,
    initial_wallet_balance: Decimal,
    cost_model_version: str,
    funding_model_version: str,
    two_a_version: str,
    two_b_planner_version: str,
    two_b_planner_config_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> SimulationConfig:
    if (
        not isinstance(initial_wallet_balance, Decimal)
        or not initial_wallet_balance.is_finite()
        or initial_wallet_balance <= 0
    ):
        raise ValueError("initial_wallet_balance must be a positive finite Decimal")
    payload = {
        "schema_version": SIMULATION_CONFIG_VERSION,
        "symbols": symbols,
        "simulation_start_utc_ms": simulation_start_utc_ms,
        "simulation_end_exit_open_utc_ms": simulation_end_exit_open_utc_ms,
        "initial_wallet_balance": initial_wallet_balance,
        "leverage": 1,
        "position_mode": PositionMode.ONE_WAY,
        "margin_mode": MarginMode.ISOLATED,
        "active_path_kinds": (PathKind.BASELINE, PathKind.CONSERVATIVE),
        "minute_event_order_version": MINUTE_EVENT_ORDER_VERSION,
        "intraminute_halt_policy_version": INTRAMINUTE_HALT_POLICY_VERSION,
        "liquidation_model_version": LIQUIDATION_MODEL_VERSION,
        "cost_model_version": cost_model_version,
        "funding_model_version": funding_model_version,
        "two_a_version": two_a_version,
        "two_b_planner_version": two_b_planner_version,
        "two_b_planner_config_hash": two_b_planner_config_hash,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    object_id, digest = formal_identity("simcfg_", payload)
    return SimulationConfig(config_id=object_id, config_content_hash=digest, **payload)


@dataclass(frozen=True, slots=True)
class EngineState:
    path_kind: PathKind
    path_state: PathState
    wallet_balance: Decimal
    locked_initial_margin: Decimal
    locked_fee_reserve: Decimal
    locked_funding_reserve: Decimal
    pending_plan_reserve: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    peak_equity: Decimal
    positions: tuple[object, ...]
    consumed_plan_ids: tuple[str, ...]
    consumed_funding_ids: tuple[str, ...]
    consumed_close_ids: tuple[str, ...]
    consumed_ledger_ids: tuple[str, ...]
    halt_trigger_time_utc_ms: int | None
    halt_reason: str | None
    flat_after_halt_time_utc_ms: int | None
    final_processed_time_utc_ms: int | None


def initial_engine_state(config: SimulationConfig, path_kind: PathKind = PathKind.BASELINE) -> EngineState:
    zero = Decimal("0")
    return EngineState(
        path_kind=path_kind,
        path_state=PathState.VALID,
        wallet_balance=config.initial_wallet_balance,
        locked_initial_margin=zero,
        locked_fee_reserve=zero,
        locked_funding_reserve=zero,
        pending_plan_reserve=zero,
        unrealized_pnl=zero,
        equity=config.initial_wallet_balance,
        peak_equity=config.initial_wallet_balance,
        positions=(),
        consumed_plan_ids=(),
        consumed_funding_ids=(),
        consumed_close_ids=(),
        consumed_ledger_ids=(),
        halt_trigger_time_utc_ms=None,
        halt_reason=None,
        flat_after_halt_time_utc_ms=None,
        final_processed_time_utc_ms=None,
    )
