from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.accounts import (
    AccountEvidenceRecords,
    AccountPlanningEvidenceBundle,
    AccountPlanningSnapshot,
    account_evidence_bundle,
    account_evidence_records,
    experiment_state_evidence,
    make_account_planning_snapshot,
    open_risk_evidence,
    position_evidence,
    valuation_evidence,
    wallet_ledger_evidence,
)
from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_sha256,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_sha256
from pa_agent.research_backtest.domain.enums import ExperimentState, ResearchStage, Side
from pa_agent.research_backtest.planning.funding import count_funding_events
from pa_agent.research_backtest.simulation.domain import EngineState, PathState, SimulationConfig
from pa_agent.research_backtest.simulation.inputs import MinuteInputSlice

SIMULATION_EVIDENCE_CATALOG_VERSION = "SIMULATION_EVIDENCE_CATALOG_V1"


def _ordered(values: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(sorted(values, key=canonical_sha256))


@dataclass(frozen=True, slots=True)
class SimulationEvidenceCatalog:
    schema_version: str
    catalog_id: str
    catalog_content_hash: str
    target_opens: tuple[object, ...]
    watermarks: tuple[object, ...]
    contracts: tuple[object, ...]
    costs: tuple[object, ...]
    funding_schedules: tuple[object, ...]
    funding_risks: tuple[object, ...]
    maintenance: tuple[object, ...]
    stage: ResearchStage
    split_start_utc_ms: int
    split_end_utc_ms: int
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != SIMULATION_EVIDENCE_CATALOG_VERSION:
            raise ValueError("unsupported simulation evidence catalog")
        for name in (
            "target_opens",
            "watermarks",
            "contracts",
            "costs",
            "funding_schedules",
            "funding_risks",
            "maintenance",
        ):
            if getattr(self, name) != _ordered(getattr(self, name)):
                raise ValueError(f"{name} must be canonically ordered")
        if not isinstance(self.stage, ResearchStage):
            raise ValueError("catalog stage must be formal ResearchStage")
        if (
            type(self.split_start_utc_ms) is not int
            or type(self.split_end_utc_ms) is not int
            or self.split_start_utc_ms < 0
            or self.split_end_utc_ms < self.split_start_utc_ms
        ):
            raise ValueError("invalid catalog split interval")
        require_commit(self.code_commit)
        require_sha256(self.dependency_lock_hash, "dependency_lock_hash")
        verify_formal_identity(
            self,
            id_field="catalog_id",
            hash_field="catalog_content_hash",
            prefix="simevidence_",
        )


def make_simulation_evidence_catalog(
    *,
    target_opens: tuple[object, ...],
    watermarks: tuple[object, ...],
    contracts: tuple[object, ...],
    costs: tuple[object, ...],
    funding_schedules: tuple[object, ...],
    funding_risks: tuple[object, ...],
    maintenance: tuple[object, ...],
    stage: ResearchStage,
    split_start_utc_ms: int,
    split_end_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> SimulationEvidenceCatalog:
    payload = {
        "schema_version": SIMULATION_EVIDENCE_CATALOG_VERSION,
        "target_opens": _ordered(target_opens),
        "watermarks": _ordered(watermarks),
        "contracts": _ordered(contracts),
        "costs": _ordered(costs),
        "funding_schedules": _ordered(funding_schedules),
        "funding_risks": _ordered(funding_risks),
        "maintenance": _ordered(maintenance),
        "stage": stage,
        "split_start_utc_ms": split_start_utc_ms,
        "split_end_utc_ms": split_end_utc_ms,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    object_id, digest = formal_identity("simevidence_", payload)
    return SimulationEvidenceCatalog(
        catalog_id=object_id,
        catalog_content_hash=digest,
        **payload,
    )


def empty_simulation_evidence_catalog(config: SimulationConfig) -> SimulationEvidenceCatalog:
    return make_simulation_evidence_catalog(
        target_opens=(),
        watermarks=(),
        contracts=(),
        costs=(),
        funding_schedules=(),
        funding_risks=(),
        maintenance=(),
        stage=ResearchStage.BACKTEST,
        split_start_utc_ms=config.simulation_start_utc_ms,
        split_end_utc_ms=config.simulation_end_exit_open_utc_ms,
        code_commit=config.code_commit,
        dependency_lock_hash=config.dependency_lock_hash,
    )


@dataclass(frozen=True, slots=True)
class PlanningEvidenceFromEngine:
    account: AccountPlanningSnapshot
    account_evidence_bundle: AccountPlanningEvidenceBundle
    account_evidence_records: AccountEvidenceRecords
    minute: MinuteInputSlice
    catalog: SimulationEvidenceCatalog


def _one(values: tuple[object, ...], predicate, label: str) -> object:
    matches = tuple(item for item in values if predicate(item))
    if len(matches) != 1:
        raise ValueError(f"{label} evidence must have exactly one matching record")
    return matches[0]


def _position_unrealized(position: object, mark: Decimal) -> Decimal:
    if position.side is Side.LONG:
        return position.quantity * (mark - position.entry_price)
    return position.quantity * (position.entry_price - mark)


def build_planning_evidence_from_engine(
    *,
    state: EngineState,
    minute: MinuteInputSlice,
    catalog: SimulationEvidenceCatalog,
) -> PlanningEvidenceFromEngine:
    if state.pending_plan_reserve != 0:
        raise ValueError("pending Plan reserve lacks replayable per-Plan evidence")
    mark_by_symbol = {bar.symbol: bar.open for bar in minute.mark_bars}
    valuations = []
    position_records = []
    risks = []
    for position in state.positions:
        if position.symbol not in mark_by_symbol:
            raise ValueError("current mark-open evidence is unavailable for position")
        valuations.append(
            valuation_evidence(
                symbol=position.symbol,
                event_time_utc_ms=minute.minute_open_utc_ms,
                unrealized_pnl=_position_unrealized(position, mark_by_symbol[position.symbol]),
            )
        )
        position_records.append(position_evidence(symbol=position.symbol))
        risks.append(open_risk_evidence(symbol=position.symbol, risk=position.planned_risk))
    records = account_evidence_records(
        wallet=wallet_ledger_evidence(
            wallet_balance=state.wallet_balance,
            locked_initial_margin=state.locked_initial_margin,
            locked_fee_reserve=state.locked_fee_reserve,
            locked_funding_reserve=state.locked_funding_reserve,
        ),
        valuations=tuple(valuations),
        positions=tuple(position_records),
        open_risks=tuple(risks),
        pending_plans=(),
        experiment_state=experiment_state_evidence(
            event_time_utc_ms=minute.minute_open_utc_ms,
            state=(
                ExperimentState.HALTED
                if state.path_state is PathState.HALTED
                else ExperimentState.RUNNING
            ),
        ),
    )
    bundle = account_evidence_bundle(
        records,
        event_time_utc_ms=minute.minute_open_utc_ms,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )
    account = make_account_planning_snapshot(
        bundle,
        records,
        eligible_time_utc_ms=minute.minute_open_utc_ms,
    )
    return PlanningEvidenceFromEngine(account, bundle, records, minute, catalog)


def build_entry_batch_inputs_from_engine(
    *,
    state: EngineState,
    due_intents: tuple[object, ...],
    minute: MinuteInputSlice,
    candidates: tuple[object, ...],
    catalog: SimulationEvidenceCatalog,
):
    from pa_agent.research_backtest.simulation.planning import (
        EntryBatchItemEvidence,
        EntryBatchPlanningInputs,
    )

    if not due_intents:
        raise ValueError("production entry batch requires due Intents")
    if any(item.target_execution_time_utc_ms != minute.minute_open_utc_ms for item in due_intents):
        raise ValueError("future or stale EntryIntent reached production evidence bridge")
    evidence = build_planning_evidence_from_engine(
        state=state,
        minute=minute,
        catalog=catalog,
    )
    trade_by_symbol = {bar.symbol: bar for bar in minute.trade_bars}
    candidate_by_id = {item.candidate_id: item for item in candidates}
    items = []
    for intent in sorted(due_intents, key=lambda item: (item.symbol, item.intent_id)):
        candidate = candidate_by_id.get(intent.candidate_id)
        if candidate is None:
            raise ValueError("EntryIntent Candidate is absent from visible Candidate index")
        target = intent.target_execution_time_utc_ms
        symbol = intent.symbol
        target_open = _one(
            catalog.target_opens,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.open_time_utc_ms == target
            ),
            "target-open",
        )
        watermark = _one(
            catalog.watermarks,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.target_open_time_utc_ms == target
            ),
            "watermark",
        )
        contract = _one(
            catalog.contracts,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.query_time_utc_ms == target
            ),
            "contract",
        )
        cost = _one(
            catalog.costs,
            lambda item, symbol=symbol: item.symbol == symbol,
            "cost",
        )
        schedule = _one(
            catalog.funding_schedules,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol
                and item.effective_from_utc_ms <= target < item.effective_to_utc_ms
            ),
            "funding schedule",
        )
        funding_risk = _one(
            catalog.funding_risks,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol
                and item.evidence_time_utc_ms == target
                and item.effective_from_utc_ms <= target < item.effective_to_utc_ms
            ),
            "funding risk",
        )
        trade_bar = trade_by_symbol.get(symbol)
        if trade_bar is None or trade_bar.open != target_open.open_price:
            raise ValueError("target-open evidence does not match current trade open")
        items.append(
            EntryBatchItemEvidence(
                candidate=candidate,
                intent=intent,
                target_open=target_open,
                watermark=watermark,
                contract=contract,
                cost=cost,
                funding_schedule=schedule,
                funding_risk=funding_risk,
                funding_event_upper_bound=count_funding_events(
                    target,
                    target + 48 * 60 * 60 * 1000,
                    schedule,
                ),
            )
        )
    return EntryBatchPlanningInputs(
        items=tuple(items),
        account=evidence.account,
        account_evidence_bundle=evidence.account_evidence_bundle,
        account_evidence_records=evidence.account_evidence_records,
        open_risk_evidence_records=evidence.account_evidence_records.open_risks,
        stage=catalog.stage,
        split_start_utc_ms=catalog.split_start_utc_ms,
        split_end_utc_ms=catalog.split_end_utc_ms,
        code_commit=catalog.code_commit,
        dependency_lock_hash=catalog.dependency_lock_hash,
    )


def build_exit_inputs_from_engine(
    *,
    state: EngineState,
    intent: object,
    evidence: PlanningEvidenceFromEngine,
):
    from pa_agent.research_backtest.planning.exits import ExitPlanningInputs
    from pa_agent.research_backtest.simulation.positions import (
        exit_execution_position_snapshot,
    )

    target = intent.target_execution_time_utc_ms
    if target != evidence.minute.minute_open_utc_ms:
        raise ValueError("future or stale ExitIntent reached production evidence bridge")
    position = _one(
        state.positions,
        lambda item: item.position_id == intent.position_id and item.symbol == intent.symbol,
        "position",
    )
    target_open = _one(
        evidence.catalog.target_opens,
        lambda item: item.symbol == intent.symbol and item.open_time_utc_ms == target,
        "target-open",
    )
    watermark = _one(
        evidence.catalog.watermarks,
        lambda item: item.symbol == intent.symbol and item.target_open_time_utc_ms == target,
        "watermark",
    )
    contract = _one(
        evidence.catalog.contracts,
        lambda item: item.symbol == intent.symbol and item.query_time_utc_ms == target,
        "contract",
    )
    cost = _one(
        evidence.catalog.costs,
        lambda item: item.symbol == intent.symbol,
        "cost",
    )
    trade_bar = _one(
        evidence.minute.trade_bars,
        lambda item: item.symbol == intent.symbol,
        "trade bar",
    )
    if target_open.open_price != trade_bar.open:
        raise ValueError("target-open evidence does not match current trade open")
    if position.quantity != intent.full_exit_quantity:
        raise ValueError("ExitIntent quantity does not match current position")
    return ExitPlanningInputs(
        intent=intent,
        target_open=target_open,
        watermark=watermark,
        contract=contract,
        cost=cost,
        target_position_snapshot_hash=exit_execution_position_snapshot(
            position
        ).snapshot_content_hash,
        code_commit=evidence.catalog.code_commit,
        dependency_lock_hash=evidence.catalog.dependency_lock_hash,
        stage=evidence.catalog.stage,
    )


def production_planning_evidence_factory(catalog: SimulationEvidenceCatalog):
    def factory(state: EngineState, minute: MinuteInputSlice) -> PlanningEvidenceFromEngine:
        return build_planning_evidence_from_engine(state=state, minute=minute, catalog=catalog)

    factory.catalog_id = catalog.catalog_id  # type: ignore[attr-defined]
    factory.catalog_content_hash = catalog.catalog_content_hash  # type: ignore[attr-defined]
    return factory


@dataclass(frozen=True, slots=True)
class ExecutionCostEvidence:
    symbol: str
    fee_rate: Decimal
    slippage_rate: Decimal
    tick_size: Decimal
    cost_snapshot_id: str
    contract_coverage_id: str


def production_execution_cost_factory(catalog: SimulationEvidenceCatalog):
    def factory(symbol: str, event_time_utc_ms: int) -> ExecutionCostEvidence:
        cost = _one(catalog.costs, lambda item: item.symbol == symbol, "cost")
        contract = _one(
            catalog.contracts,
            lambda item: (
                item.symbol == symbol
                and item.effective_from_utc_ms <= event_time_utc_ms < item.effective_to_utc_ms
            ),
            "contract",
        )
        return ExecutionCostEvidence(
            symbol=symbol,
            fee_rate=cost.effective_fee_rate,
            slippage_rate=cost.effective_slippage_rate,
            tick_size=contract.tick_size,
            cost_snapshot_id=cost.snapshot_id,
            contract_coverage_id=contract.coverage_id,
        )

    factory.catalog_id = catalog.catalog_id  # type: ignore[attr-defined]
    factory.catalog_content_hash = catalog.catalog_content_hash  # type: ignore[attr-defined]
    return factory


def production_maintenance_evidence_factory(catalog: SimulationEvidenceCatalog):
    def factory(position: object, event_time_utc_ms: int):
        notional = position.quantity * position.entry_price
        return _one(
            catalog.maintenance,
            lambda item: (
                item.symbol == position.symbol
                and item.effective_start_utc_ms <= event_time_utc_ms < item.effective_end_utc_ms
                and item.notional_floor <= notional < item.notional_cap
            ),
            "maintenance",
        )

    factory.catalog_id = catalog.catalog_id  # type: ignore[attr-defined]
    factory.catalog_content_hash = catalog.catalog_content_hash  # type: ignore[attr-defined]
    return factory
