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
from pa_agent.research_backtest.domain.enums import (
    ExecutionRejectionReason,
    ExperimentState,
    ResearchStage,
    Side,
)
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


class ProductionEvidenceError(ValueError):
    """A production evidence defect that must cross planning as a formal rejection."""

    def __init__(
        self,
        reason: ExecutionRejectionReason,
        label: str,
        catalog: SimulationEvidenceCatalog,
    ) -> None:
        super().__init__(f"{label} production evidence is unavailable or contradictory")
        self.reason = reason
        self.label = label
        self.stage = catalog.stage
        self.code_commit = catalog.code_commit
        self.dependency_lock_hash = catalog.dependency_lock_hash


def _matches(values: tuple[object, ...], predicate) -> tuple[object, ...]:
    return tuple(item for item in values if predicate(item))


def _required_production_evidence(
    values: tuple[object, ...],
    predicate,
    label: str,
    catalog: SimulationEvidenceCatalog,
    *,
    missing_reason: ExecutionRejectionReason,
) -> object:
    matches = _matches(values, predicate)
    if len(matches) > 1:
        raise ProductionEvidenceError(ExecutionRejectionReason.DATA_INVALID, label, catalog)
    if not matches:
        raise ProductionEvidenceError(missing_reason, label, catalog)
    return matches[0]


def _optional_production_evidence(
    values: tuple[object, ...],
    predicate,
    label: str,
    catalog: SimulationEvidenceCatalog,
) -> object | None:
    matches = _matches(values, predicate)
    if len(matches) > 1:
        raise ProductionEvidenceError(ExecutionRejectionReason.DATA_INVALID, label, catalog)
    return matches[0] if matches else None


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
        raise ProductionEvidenceError(
            ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
            "pending Plan reserve",
            catalog,
        )
    mark_by_symbol = {bar.symbol: bar.open for bar in minute.mark_bars}
    valuations = []
    position_records = []
    risks = []
    for position in state.positions:
        if position.symbol not in mark_by_symbol:
            raise ProductionEvidenceError(
                ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
                "current mark-open",
                catalog,
            )
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
        raise ProductionEvidenceError(
            ExecutionRejectionReason.DATA_INVALID, "due EntryIntent", catalog
        )
    if any(item.target_execution_time_utc_ms != minute.minute_open_utc_ms for item in due_intents):
        raise ProductionEvidenceError(
            ExecutionRejectionReason.DATA_INVALID, "EntryIntent target time", catalog
        )
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
            raise ProductionEvidenceError(
                ExecutionRejectionReason.DATA_INVALID, "EntryIntent Candidate identity", catalog
            )
        target = intent.target_execution_time_utc_ms
        symbol = intent.symbol
        target_open = _required_production_evidence(
            catalog.target_opens,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.open_time_utc_ms == target
            ),
            "target-open",
            catalog,
            missing_reason=ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
        )
        watermark = _required_production_evidence(
            catalog.watermarks,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.target_open_time_utc_ms == target
            ),
            "watermark",
            catalog,
            missing_reason=ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
        )
        contract = _required_production_evidence(
            catalog.contracts,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol and item.query_time_utc_ms == target
            ),
            "contract",
            catalog,
            missing_reason=ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
        )
        cost = _required_production_evidence(
            catalog.costs,
            lambda item, symbol=symbol: item.symbol == symbol,
            "cost",
            catalog,
            missing_reason=ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
        )
        schedule = _required_production_evidence(
            catalog.funding_schedules,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol
                and item.effective_from_utc_ms <= target < item.effective_to_utc_ms
            ),
            "funding schedule",
            catalog,
            missing_reason=ExecutionRejectionReason.FUNDING_SCHEDULE_UNVERIFIED,
        )
        funding_risk = _required_production_evidence(
            catalog.funding_risks,
            lambda item, symbol=symbol, target=target: (
                item.symbol == symbol
                and item.evidence_time_utc_ms == target
                and item.effective_from_utc_ms <= target < item.effective_to_utc_ms
            ),
            "funding risk",
            catalog,
            missing_reason=ExecutionRejectionReason.FUNDING_RISK_CONFIG_UNAVAILABLE,
        )
        trade_bar = trade_by_symbol.get(symbol)
        if trade_bar is None or trade_bar.open != target_open.open_price:
            raise ProductionEvidenceError(
                ExecutionRejectionReason.DATA_INVALID, "target-open evidence", catalog
            )
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
    from pa_agent.research_backtest.domain.contracts import unavailable_contract_rule
    from pa_agent.research_backtest.planning.exits import ExitPlanningInputs
    from pa_agent.research_backtest.simulation.positions import (
        exit_execution_position_snapshot,
    )

    target = intent.target_execution_time_utc_ms
    if target != evidence.minute.minute_open_utc_ms:
        raise ProductionEvidenceError(
            ExecutionRejectionReason.DATA_INVALID,
            "ExitIntent target time",
            evidence.catalog,
        )
    position = _required_production_evidence(
        state.positions,
        lambda item: item.position_id == intent.position_id and item.symbol == intent.symbol,
        "position",
        evidence.catalog,
        missing_reason=ExecutionRejectionReason.DATA_INVALID,
    )
    target_open = _optional_production_evidence(
        evidence.catalog.target_opens,
        lambda item: item.symbol == intent.symbol and item.open_time_utc_ms == target,
        "target-open",
        evidence.catalog,
    )
    watermark = _required_production_evidence(
        evidence.catalog.watermarks,
        lambda item: item.symbol == intent.symbol and item.target_open_time_utc_ms == target,
        "watermark",
        evidence.catalog,
        missing_reason=ExecutionRejectionReason.TARGET_MINUTE_UNAVAILABLE,
    )
    contract = _optional_production_evidence(
        evidence.catalog.contracts,
        lambda item: item.symbol == intent.symbol and item.query_time_utc_ms == target,
        "contract",
        evidence.catalog,
    )
    cost = _optional_production_evidence(
        evidence.catalog.costs,
        lambda item: item.symbol == intent.symbol,
        "cost",
        evidence.catalog,
    )
    trade_bar = _required_production_evidence(
        evidence.minute.trade_bars,
        lambda item: item.symbol == intent.symbol,
        "trade bar",
        evidence.catalog,
        missing_reason=ExecutionRejectionReason.DATA_INVALID,
    )
    if target_open is not None and target_open.open_price != trade_bar.open:
        raise ProductionEvidenceError(
            ExecutionRejectionReason.DATA_INVALID,
            "target-open evidence",
            evidence.catalog,
        )
    if contract is None:
        contract = unavailable_contract_rule(
            symbol=intent.symbol,
            query_time_utc_ms=target,
            unavailable_reason="PRODUCTION_EVIDENCE_NOT_FOUND",
            searched_archive_hashes=(evidence.catalog.catalog_content_hash,),
        )
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
    def factory(
        state: EngineState, minute: MinuteInputSlice
    ) -> PlanningEvidenceFromEngine | ProductionEvidenceError:
        try:
            return build_planning_evidence_from_engine(state=state, minute=minute, catalog=catalog)
        except ProductionEvidenceError as error:
            return error

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
        cost = _required_production_evidence(
            catalog.costs,
            lambda item: item.symbol == symbol,
            "cost",
            catalog,
            missing_reason=ExecutionRejectionReason.COST_MODEL_UNAVAILABLE,
        )
        contract = _required_production_evidence(
            catalog.contracts,
            lambda item: (
                item.symbol == symbol
                and item.effective_from_utc_ms <= event_time_utc_ms < item.effective_to_utc_ms
            ),
            "contract",
            catalog,
            missing_reason=ExecutionRejectionReason.CONTRACT_RULE_UNAVAILABLE,
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
        return _required_production_evidence(
            catalog.maintenance,
            lambda item: (
                item.symbol == position.symbol
                and item.effective_start_utc_ms <= event_time_utc_ms < item.effective_end_utc_ms
                and item.notional_floor <= notional < item.notional_cap
            ),
            "maintenance",
            catalog,
            missing_reason=ExecutionRejectionReason.REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE,
        )

    factory.catalog_id = catalog.catalog_id  # type: ignore[attr-defined]
    factory.catalog_content_hash = catalog.catalog_content_hash  # type: ignore[attr-defined]
    return factory
