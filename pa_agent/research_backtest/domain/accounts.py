from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_agent.research_backtest.domain.base import (
    formal_identity,
    require_commit,
    require_nonempty_string,
    require_sha256,
    require_utc_ms,
    verify_formal_identity,
)
from pa_agent.research_backtest.domain.canonical import canonical_dumps, canonical_sha256
from pa_agent.research_backtest.domain.enums import ExperimentState, PlanningPhase, ValuationBasis
from pa_agent.research_backtest.versions import (
    ACCOUNT_EQUITY_MODEL_VERSION,
    ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION,
    ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_VERSION,
    PLANNING_PHASE_VERSION,
)

OPEN_RISK_MODEL_VERSION = "OPEN_RISK_MODEL_V1"


class RequiredAccountEvidenceUnavailableError(ValueError):
    pass


def _money(value: Decimal, name: str, *, nonnegative: bool = True) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be finite Decimal")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _record_identity(prefix: str, payload: dict[str, object]) -> tuple[str, str]:
    return formal_identity(prefix, payload)


def _set_hash(ids: tuple[str, ...], hashes: tuple[str, ...]) -> str:
    return canonical_sha256({"record_ids": ids, "record_content_hashes": hashes})


@dataclass(frozen=True, slots=True)
class WalletLedgerEvidence:
    source_id: str
    source_content_hash: str
    wallet_balance: Decimal
    locked_initial_margin: Decimal
    locked_fee_reserve: Decimal
    locked_funding_reserve: Decimal

    def __post_init__(self) -> None:
        for name in (
            "wallet_balance",
            "locked_initial_margin",
            "locked_fee_reserve",
            "locked_funding_reserve",
        ):
            _money(getattr(self, name), name)
        verify_formal_identity(
            self,
            id_field="source_id",
            hash_field="source_content_hash",
            prefix="wallet_",
        )


@dataclass(frozen=True, slots=True)
class ValuationEvidence:
    record_id: str
    record_content_hash: str
    symbol: str
    event_time_utc_ms: int
    valuation_basis: ValuationBasis
    unrealized_pnl: Decimal

    def __post_init__(self) -> None:
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported valuation symbol")
        require_utc_ms(self.event_time_utc_ms, "valuation event time")
        if self.valuation_basis is not ValuationBasis.MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1:
            raise ValueError("unsupported valuation basis")
        _money(self.unrealized_pnl, "unrealized_pnl", nonnegative=False)
        verify_formal_identity(
            self,
            id_field="record_id",
            hash_field="record_content_hash",
            prefix="valuation_",
        )


@dataclass(frozen=True, slots=True)
class PositionEvidence:
    record_id: str
    record_content_hash: str
    symbol: str

    def __post_init__(self) -> None:
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported position symbol")
        verify_formal_identity(
            self,
            id_field="record_id",
            hash_field="record_content_hash",
            prefix="position_",
        )


@dataclass(frozen=True, slots=True)
class OpenRiskEvidence:
    record_id: str
    record_content_hash: str
    symbol: str
    risk: Decimal

    def __post_init__(self) -> None:
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported open-risk symbol")
        _money(self.risk, "open risk")
        verify_formal_identity(
            self,
            id_field="record_id",
            hash_field="record_content_hash",
            prefix="openrisk_",
        )


@dataclass(frozen=True, slots=True)
class PendingPlanEvidence:
    record_id: str
    record_content_hash: str
    symbol: str
    planned_risk: Decimal
    required_reserve: Decimal

    def __post_init__(self) -> None:
        if self.symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("unsupported pending-plan symbol")
        _money(self.planned_risk, "pending planned risk")
        _money(self.required_reserve, "pending required reserve")
        verify_formal_identity(
            self,
            id_field="record_id",
            hash_field="record_content_hash",
            prefix="pending_",
        )


@dataclass(frozen=True, slots=True)
class ExperimentStateEvidence:
    state_id: str
    state_hash: str
    event_time_utc_ms: int
    state: ExperimentState

    def __post_init__(self) -> None:
        require_utc_ms(self.event_time_utc_ms, "experiment state event time")
        if not isinstance(self.state, ExperimentState):
            raise ValueError("unsupported experiment state")
        verify_formal_identity(
            self,
            id_field="state_id",
            hash_field="state_hash",
            prefix="estate_",
        )


@dataclass(frozen=True, slots=True)
class AccountEvidenceRecords:
    wallet: WalletLedgerEvidence
    valuations: tuple[ValuationEvidence, ...]
    positions: tuple[PositionEvidence, ...]
    open_risks: tuple[OpenRiskEvidence, ...]
    pending_plans: tuple[PendingPlanEvidence, ...]
    experiment_state: ExperimentStateEvidence


@dataclass(frozen=True, slots=True)
class AccountEvidenceAggregates:
    current_equity: Decimal
    available_balance: Decimal
    existing_open_risk: Decimal
    pending_plan_risk: Decimal
    pending_plan_reserve: Decimal


@dataclass(frozen=True, slots=True)
class AccountPlanningEvidenceBundle:
    schema_version: str
    bundle_id: str
    bundle_content_hash: str
    event_time_utc_ms: int
    planning_phase: PlanningPhase
    planning_phase_version: str
    wallet_ledger_source_id: str
    wallet_ledger_source_content_hash: str
    wallet_balance: Decimal
    locked_initial_margin: Decimal
    locked_fee_reserve: Decimal
    locked_funding_reserve: Decimal
    valuation_snapshot_ids: tuple[str, ...]
    valuation_snapshot_content_hashes: tuple[str, ...]
    valuation_snapshot_set_hash: str
    valuation_basis: ValuationBasis
    equity_model_version: str
    equity_source_snapshot_id: str
    equity_source_content_hash: str
    unrealized_pnl: Decimal
    current_equity: Decimal
    existing_position_record_ids: tuple[str, ...]
    existing_position_record_content_hashes: tuple[str, ...]
    existing_position_set_hash: str
    existing_position_symbols: tuple[str, ...]
    open_risk_record_ids: tuple[str, ...]
    open_risk_record_content_hashes: tuple[str, ...]
    open_risk_model_version: str
    open_risk_source_hash: str
    existing_open_risk: Decimal
    pending_plan_record_ids: tuple[str, ...]
    pending_plan_record_content_hashes: tuple[str, ...]
    pending_plan_set_hash: str
    pending_plan_risk: Decimal
    pending_plan_reserve: Decimal
    experiment_state: ExperimentState
    experiment_state_id: str
    experiment_state_hash: str
    available_balance: Decimal
    code_commit: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION:
            raise ValueError("unsupported account evidence bundle schema")
        require_utc_ms(self.event_time_utc_ms, "account evidence event time")
        if (
            self.planning_phase
            is not PlanningPhase.POST_SAME_TIME_FUNDING_AND_SCHEDULED_EXITS_PRE_ENTRY_BATCH_V1
            or self.planning_phase_version != PLANNING_PHASE_VERSION
        ):
            raise ValueError("unsupported account planning phase")
        for name in (
            "wallet_ledger_source_content_hash",
            "valuation_snapshot_set_hash",
            "equity_source_content_hash",
            "existing_position_set_hash",
            "open_risk_source_hash",
            "pending_plan_set_hash",
            "experiment_state_hash",
            "dependency_lock_hash",
        ):
            require_sha256(getattr(self, name), name)
        require_nonempty_string(self.wallet_ledger_source_id, "wallet_ledger_source_id")
        for ids, hashes, name in (
            (
                self.valuation_snapshot_ids,
                self.valuation_snapshot_content_hashes,
                "valuation",
            ),
            (
                self.existing_position_record_ids,
                self.existing_position_record_content_hashes,
                "position",
            ),
            (self.open_risk_record_ids, self.open_risk_record_content_hashes, "open-risk"),
            (
                self.pending_plan_record_ids,
                self.pending_plan_record_content_hashes,
                "pending-plan",
            ),
        ):
            if len(ids) != len(hashes) or ids != tuple(sorted(set(ids))):
                raise ValueError(f"{name} evidence IDs/hashes are inconsistent")
            for digest in hashes:
                require_sha256(digest, f"{name} content hash")
        if self.valuation_snapshot_set_hash != _set_hash(
            self.valuation_snapshot_ids, self.valuation_snapshot_content_hashes
        ):
            raise ValueError("valuation set hash does not match records")
        if self.existing_position_set_hash != _set_hash(
            self.existing_position_record_ids,
            self.existing_position_record_content_hashes,
        ):
            raise ValueError("position set hash does not match records")
        if self.open_risk_source_hash != _set_hash(
            self.open_risk_record_ids, self.open_risk_record_content_hashes
        ):
            raise ValueError("open-risk source hash does not match records")
        if self.pending_plan_set_hash != _set_hash(
            self.pending_plan_record_ids, self.pending_plan_record_content_hashes
        ):
            raise ValueError("pending-plan set hash does not match records")
        if self.valuation_basis is not ValuationBasis.MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1:
            raise ValueError("unsupported valuation basis")
        if self.equity_model_version != ACCOUNT_EQUITY_MODEL_VERSION:
            raise ValueError("unsupported account equity model")
        if self.open_risk_model_version != OPEN_RISK_MODEL_VERSION:
            raise ValueError("unsupported open-risk model")
        require_nonempty_string(self.equity_source_snapshot_id, "equity_source_snapshot_id")
        if self.current_equity != self.wallet_balance + self.unrealized_pnl:
            raise ValueError("current equity does not replay from wallet and unrealized PnL")
        expected_available = (
            self.wallet_balance
            - self.locked_initial_margin
            - self.locked_fee_reserve
            - self.locked_funding_reserve
        )
        if self.available_balance != expected_available or self.available_balance < 0:
            raise ValueError("available balance does not replay from wallet locks")
        for name in (
            "wallet_balance",
            "locked_initial_margin",
            "locked_fee_reserve",
            "locked_funding_reserve",
            "existing_open_risk",
            "pending_plan_risk",
            "pending_plan_reserve",
        ):
            _money(getattr(self, name), name)
        _money(self.unrealized_pnl, "unrealized_pnl", nonnegative=False)
        _money(self.current_equity, "current_equity", nonnegative=False)
        if self.pending_plan_reserve > self.available_balance:
            raise ValueError("pending reserve exceeds available balance")
        if self.existing_position_symbols != tuple(sorted(set(self.existing_position_symbols))):
            raise ValueError("existing position symbols must be unique and sorted")
        if not isinstance(self.experiment_state, ExperimentState):
            raise ValueError("invalid experiment state")
        require_nonempty_string(self.experiment_state_id, "experiment_state_id")
        require_commit(self.code_commit)
        verify_formal_identity(
            self,
            id_field="bundle_id",
            hash_field="bundle_content_hash",
            prefix="aeb_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


@dataclass(frozen=True, slots=True)
class AccountPlanningSnapshot:
    schema_version: str
    snapshot_id: str
    snapshot_hash: str
    event_time_utc_ms: int
    planning_phase: PlanningPhase
    planning_phase_version: str
    wallet_balance: Decimal
    unrealized_pnl: Decimal
    current_equity: Decimal
    equity_model_version: str
    equity_source_snapshot_id: str
    equity_source_content_hash: str
    valuation_basis: ValuationBasis
    valuation_snapshot_set_hash: str
    account_evidence_bundle_id: str
    account_evidence_bundle_content_hash: str
    locked_initial_margin: Decimal
    locked_fee_reserve: Decimal
    locked_funding_reserve: Decimal
    available_balance: Decimal
    existing_open_risk: Decimal
    open_risk_model_version: str
    open_risk_source_hash: str
    pending_plan_reserve: Decimal
    pending_plan_risk: Decimal
    pending_plan_set_hash: str
    existing_position_set_hash: str
    existing_position_symbols: tuple[str, ...]
    experiment_state: ExperimentState
    experiment_state_id: str
    experiment_state_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported account planning snapshot schema")
        require_utc_ms(self.event_time_utc_ms, "account snapshot event time")
        if (
            self.planning_phase
            is not PlanningPhase.POST_SAME_TIME_FUNDING_AND_SCHEDULED_EXITS_PRE_ENTRY_BATCH_V1
            or self.planning_phase_version != PLANNING_PHASE_VERSION
        ):
            raise ValueError("unsupported account snapshot planning phase")
        if self.equity_model_version != ACCOUNT_EQUITY_MODEL_VERSION:
            raise ValueError("unsupported account snapshot equity model")
        if self.valuation_basis is not ValuationBasis.MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1:
            raise ValueError("unsupported account snapshot valuation basis")
        if self.open_risk_model_version != OPEN_RISK_MODEL_VERSION:
            raise ValueError("unsupported account snapshot open-risk model")
        if self.current_equity != self.wallet_balance + self.unrealized_pnl:
            raise ValueError("account snapshot current equity is inconsistent")
        if self.current_equity <= 0:
            raise ValueError("account snapshot equity must be positive for new planning")
        expected_available = (
            self.wallet_balance
            - self.locked_initial_margin
            - self.locked_fee_reserve
            - self.locked_funding_reserve
        )
        if self.available_balance != expected_available or self.available_balance < 0:
            raise ValueError("account snapshot available balance is inconsistent")
        if self.pending_plan_reserve > self.available_balance:
            raise ValueError("account snapshot pending reserve exceeds available balance")
        for name in (
            "wallet_balance",
            "locked_initial_margin",
            "locked_fee_reserve",
            "locked_funding_reserve",
            "existing_open_risk",
            "pending_plan_reserve",
            "pending_plan_risk",
        ):
            _money(getattr(self, name), name)
        _money(self.unrealized_pnl, "unrealized_pnl", nonnegative=False)
        if self.existing_position_symbols != tuple(sorted(set(self.existing_position_symbols))):
            raise ValueError("account snapshot position symbols must be unique and sorted")
        if not isinstance(self.experiment_state, ExperimentState):
            raise ValueError("invalid account snapshot experiment state")
        for name in (
            "equity_source_content_hash",
            "valuation_snapshot_set_hash",
            "account_evidence_bundle_content_hash",
            "open_risk_source_hash",
            "pending_plan_set_hash",
            "existing_position_set_hash",
            "experiment_state_hash",
        ):
            require_sha256(getattr(self, name), name)
        verify_formal_identity(
            self,
            id_field="snapshot_id",
            hash_field="snapshot_hash",
            prefix="acct_",
        )

    def canonical_json(self) -> str:
        return canonical_dumps(self)


def wallet_ledger_evidence(
    *,
    wallet_balance: Decimal,
    locked_initial_margin: Decimal,
    locked_fee_reserve: Decimal,
    locked_funding_reserve: Decimal,
) -> WalletLedgerEvidence:
    payload = {
        "wallet_balance": wallet_balance,
        "locked_initial_margin": locked_initial_margin,
        "locked_fee_reserve": locked_fee_reserve,
        "locked_funding_reserve": locked_funding_reserve,
    }
    source_id, digest = _record_identity("wallet_", payload)
    return WalletLedgerEvidence(source_id, digest, **payload)


def valuation_evidence(
    *, symbol: str, event_time_utc_ms: int, unrealized_pnl: Decimal
) -> ValuationEvidence:
    payload = {
        "symbol": symbol,
        "event_time_utc_ms": event_time_utc_ms,
        "valuation_basis": ValuationBasis.MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1,
        "unrealized_pnl": unrealized_pnl,
    }
    record_id, digest = _record_identity("valuation_", payload)
    return ValuationEvidence(record_id, digest, **payload)


def position_evidence(*, symbol: str) -> PositionEvidence:
    payload = {"symbol": symbol}
    record_id, digest = _record_identity("position_", payload)
    return PositionEvidence(record_id, digest, **payload)


def open_risk_evidence(*, symbol: str, risk: Decimal) -> OpenRiskEvidence:
    payload = {"symbol": symbol, "risk": risk}
    record_id, digest = _record_identity("openrisk_", payload)
    return OpenRiskEvidence(record_id, digest, **payload)


def pending_plan_evidence(
    *, symbol: str, planned_risk: Decimal, required_reserve: Decimal
) -> PendingPlanEvidence:
    payload = {
        "symbol": symbol,
        "planned_risk": planned_risk,
        "required_reserve": required_reserve,
    }
    record_id, digest = _record_identity("pending_", payload)
    return PendingPlanEvidence(record_id, digest, **payload)


def experiment_state_evidence(
    *, event_time_utc_ms: int, state: str | ExperimentState
) -> ExperimentStateEvidence:
    payload = {"event_time_utc_ms": event_time_utc_ms, "state": ExperimentState(state)}
    state_id, digest = _record_identity("estate_", payload)
    return ExperimentStateEvidence(state_id, digest, **payload)


def account_evidence_records(
    *,
    wallet: WalletLedgerEvidence,
    valuations: tuple[ValuationEvidence, ...],
    positions: tuple[PositionEvidence, ...],
    open_risks: tuple[OpenRiskEvidence, ...],
    pending_plans: tuple[PendingPlanEvidence, ...],
    experiment_state: ExperimentStateEvidence,
) -> AccountEvidenceRecords:
    ordered_valuations = tuple(sorted(valuations, key=lambda item: item.record_id))
    ordered_positions = tuple(sorted(positions, key=lambda item: item.record_id))
    ordered_risks = tuple(sorted(open_risks, key=lambda item: item.record_id))
    ordered_pending = tuple(sorted(pending_plans, key=lambda item: item.record_id))
    position_symbols = {item.symbol for item in ordered_positions}
    risk_symbols = {item.symbol for item in ordered_risks}
    if position_symbols != risk_symbols:
        raise RequiredAccountEvidenceUnavailableError(
            "open-risk evidence must cover every existing position"
        )
    if len(position_symbols) != len(ordered_positions):
        raise ValueError("at most one existing position record is allowed per symbol")
    if len(risk_symbols) != len(ordered_risks):
        raise ValueError("at most one open-risk record is allowed per symbol")
    times = {item.event_time_utc_ms for item in ordered_valuations}
    if times and times != {experiment_state.event_time_utc_ms}:
        raise ValueError("valuation evidence time must match experiment state event time")
    return AccountEvidenceRecords(
        wallet,
        ordered_valuations,
        ordered_positions,
        ordered_risks,
        ordered_pending,
        experiment_state,
    )


def _ids_hashes(records: tuple[object, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(record.record_id for record in records),
        tuple(record.record_content_hash for record in records),
    )


def account_evidence_bundle(
    records: AccountEvidenceRecords,
    *,
    event_time_utc_ms: int,
    code_commit: str,
    dependency_lock_hash: str,
) -> AccountPlanningEvidenceBundle:
    if records.experiment_state.event_time_utc_ms != event_time_utc_ms:
        raise ValueError("experiment state does not match account evidence event time")
    if any(item.event_time_utc_ms != event_time_utc_ms for item in records.valuations):
        raise ValueError("valuation evidence does not match eligible time")
    valuation_ids, valuation_hashes = _ids_hashes(records.valuations)
    position_ids, position_hashes = _ids_hashes(records.positions)
    risk_ids, risk_hashes = _ids_hashes(records.open_risks)
    pending_ids, pending_hashes = _ids_hashes(records.pending_plans)
    valuation_set_hash = _set_hash(valuation_ids, valuation_hashes)
    position_set_hash = _set_hash(position_ids, position_hashes)
    risk_set_hash = _set_hash(risk_ids, risk_hashes)
    pending_set_hash = _set_hash(pending_ids, pending_hashes)
    wallet = records.wallet
    unrealized_pnl = sum((item.unrealized_pnl for item in records.valuations), Decimal("0"))
    current_equity = wallet.wallet_balance + unrealized_pnl
    available_balance = (
        wallet.wallet_balance
        - wallet.locked_initial_margin
        - wallet.locked_fee_reserve
        - wallet.locked_funding_reserve
    )
    existing_open_risk = sum((item.risk for item in records.open_risks), Decimal("0"))
    pending_plan_risk = sum((item.planned_risk for item in records.pending_plans), Decimal("0"))
    pending_plan_reserve = sum(
        (item.required_reserve for item in records.pending_plans), Decimal("0")
    )
    payload = {
        "schema_version": ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "event_time_utc_ms": event_time_utc_ms,
        "planning_phase": PlanningPhase.POST_SAME_TIME_FUNDING_AND_SCHEDULED_EXITS_PRE_ENTRY_BATCH_V1,
        "planning_phase_version": PLANNING_PHASE_VERSION,
        "wallet_ledger_source_id": wallet.source_id,
        "wallet_ledger_source_content_hash": wallet.source_content_hash,
        "wallet_balance": wallet.wallet_balance,
        "locked_initial_margin": wallet.locked_initial_margin,
        "locked_fee_reserve": wallet.locked_fee_reserve,
        "locked_funding_reserve": wallet.locked_funding_reserve,
        "valuation_snapshot_ids": valuation_ids,
        "valuation_snapshot_content_hashes": valuation_hashes,
        "valuation_snapshot_set_hash": valuation_set_hash,
        "valuation_basis": ValuationBasis.MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1,
        "equity_model_version": ACCOUNT_EQUITY_MODEL_VERSION,
        "equity_source_snapshot_id": f"equity_{valuation_set_hash[:24]}",
        "equity_source_content_hash": valuation_set_hash,
        "unrealized_pnl": unrealized_pnl,
        "current_equity": current_equity,
        "existing_position_record_ids": position_ids,
        "existing_position_record_content_hashes": position_hashes,
        "existing_position_set_hash": position_set_hash,
        "existing_position_symbols": tuple(sorted(item.symbol for item in records.positions)),
        "open_risk_record_ids": risk_ids,
        "open_risk_record_content_hashes": risk_hashes,
        "open_risk_model_version": OPEN_RISK_MODEL_VERSION,
        "open_risk_source_hash": risk_set_hash,
        "existing_open_risk": existing_open_risk,
        "pending_plan_record_ids": pending_ids,
        "pending_plan_record_content_hashes": pending_hashes,
        "pending_plan_set_hash": pending_set_hash,
        "pending_plan_risk": pending_plan_risk,
        "pending_plan_reserve": pending_plan_reserve,
        "experiment_state": records.experiment_state.state,
        "experiment_state_id": records.experiment_state.state_id,
        "experiment_state_hash": records.experiment_state.state_hash,
        "available_balance": available_balance,
        "code_commit": code_commit,
        "dependency_lock_hash": dependency_lock_hash,
    }
    bundle_id, digest = formal_identity("aeb_", payload)
    return AccountPlanningEvidenceBundle(
        bundle_id=bundle_id,
        bundle_content_hash=digest,
        **payload,
    )


def replay_account_evidence(
    bundle: AccountPlanningEvidenceBundle,
    records: AccountEvidenceRecords | None,
) -> AccountEvidenceAggregates:
    if records is None:
        raise RequiredAccountEvidenceUnavailableError(
            "account record collections are required with the evidence bundle"
        )
    replayed = account_evidence_bundle(
        records,
        event_time_utc_ms=bundle.event_time_utc_ms,
        code_commit=bundle.code_commit,
        dependency_lock_hash=bundle.dependency_lock_hash,
    )
    if replayed != bundle:
        raise ValueError("account evidence bundle does not match replayed records")
    return AccountEvidenceAggregates(
        replayed.current_equity,
        replayed.available_balance,
        replayed.existing_open_risk,
        replayed.pending_plan_risk,
        replayed.pending_plan_reserve,
    )


def make_account_planning_snapshot(
    bundle: AccountPlanningEvidenceBundle,
    records: AccountEvidenceRecords,
    *,
    eligible_time_utc_ms: int,
) -> AccountPlanningSnapshot:
    if bundle.event_time_utc_ms != eligible_time_utc_ms:
        raise ValueError("account evidence does not match eligible time")
    replay_account_evidence(bundle, records)
    payload = {
        "schema_version": ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_VERSION,
        "event_time_utc_ms": bundle.event_time_utc_ms,
        "planning_phase": bundle.planning_phase,
        "planning_phase_version": bundle.planning_phase_version,
        "wallet_balance": bundle.wallet_balance,
        "unrealized_pnl": bundle.unrealized_pnl,
        "current_equity": bundle.current_equity,
        "equity_model_version": bundle.equity_model_version,
        "equity_source_snapshot_id": bundle.equity_source_snapshot_id,
        "equity_source_content_hash": bundle.equity_source_content_hash,
        "valuation_basis": bundle.valuation_basis,
        "valuation_snapshot_set_hash": bundle.valuation_snapshot_set_hash,
        "account_evidence_bundle_id": bundle.bundle_id,
        "account_evidence_bundle_content_hash": bundle.bundle_content_hash,
        "locked_initial_margin": bundle.locked_initial_margin,
        "locked_fee_reserve": bundle.locked_fee_reserve,
        "locked_funding_reserve": bundle.locked_funding_reserve,
        "available_balance": bundle.available_balance,
        "existing_open_risk": bundle.existing_open_risk,
        "open_risk_model_version": bundle.open_risk_model_version,
        "open_risk_source_hash": bundle.open_risk_source_hash,
        "pending_plan_reserve": bundle.pending_plan_reserve,
        "pending_plan_risk": bundle.pending_plan_risk,
        "pending_plan_set_hash": bundle.pending_plan_set_hash,
        "existing_position_set_hash": bundle.existing_position_set_hash,
        "existing_position_symbols": bundle.existing_position_symbols,
        "experiment_state": bundle.experiment_state,
        "experiment_state_id": bundle.experiment_state_id,
        "experiment_state_hash": bundle.experiment_state_hash,
    }
    snapshot_id, digest = formal_identity("acct_", payload)
    return AccountPlanningSnapshot(snapshot_id=snapshot_id, snapshot_hash=digest, **payload)
