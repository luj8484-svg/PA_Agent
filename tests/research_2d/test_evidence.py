from dataclasses import replace
from decimal import Decimal

from pa_agent.research_2d.evidence import EvidenceRequest, build_evidence_catalog
from pa_agent.research_backtest.planning.funding import effective_adverse_rate_cap


def test_catalog_freezes_approximated_rules_real_funding_and_costs() -> None:
    request = EvidenceRequest(
        split_start_utc_ms=1_700_000_000_000,
        split_end_exit_open_utc_ms=1_700_100_000_000,
        target_prices=(
            ("BTCUSDT", 1_700_000_060_000, Decimal("30000")),
            ("ETHUSDT", 1_700_000_060_000, Decimal("2000")),
        ),
        required_targets=(
            ("BTCUSDT", 1_700_000_060_000),
            ("BTCUSDT", 1_700_000_120_000),
            ("ETHUSDT", 1_700_000_060_000),
        ),
        entry_targets=(
            ("BTCUSDT", 1_700_000_060_000),
            ("ETHUSDT", 1_700_000_060_000),
        ),
        funding_times=(
            ("BTCUSDT", (1_700_006_400_000,)),
            ("ETHUSDT", (1_700_006_400_000,)),
        ),
        funding_rate_caps=(
            ("BTCUSDT", 1_700_000_060_000, Decimal("0.001")),
            ("ETHUSDT", 1_700_000_060_000, Decimal("0.002")),
        ),
        fee_rate=Decimal("0.0005"),
        slippage_rates=(("BTCUSDT", Decimal("0.0001")), ("ETHUSDT", Decimal("0.0002"))),
        cost_stress_multiplier=Decimal("1"),
        funding_stress_multiplier=Decimal("1"),
        source_manifest_hash="a" * 64,
        code_commit="b" * 40,
        dependency_lock_hash="c" * 64,
    )
    catalog = build_evidence_catalog(request)
    assert len(catalog.target_opens) == 2
    assert len(catalog.contracts) == 3
    assert {item.mode.value for item in catalog.contracts} == {"APPROXIMATED"}
    assert {item.mode for item in catalog.maintenance} == {"APPROXIMATED"}
    assert {item.fee_rate for item in catalog.costs} == {Decimal("0.0005")}
    assert all(
        item.watermark == "BASELINE_ASSUMPTION_NOT_VERIFIED" for item in catalog.funding_risks
    )
    for minute in (
        1_700_000_000_000,
        1_700_000_060_000,
        1_700_000_119_999,
        1_700_000_120_000,
    ):
        assert (
            sum(
                item.symbol == "BTCUSDT"
                and item.effective_from_utc_ms <= minute < item.effective_to_utc_ms
                for item in catalog.contracts
            )
            == 1
        )
    stressed = build_evidence_catalog(replace(request, funding_stress_multiplier=Decimal("2")))
    assert {effective_adverse_rate_cap(item) for item in stressed.funding_risks} == {
        Decimal("0.002"),
        Decimal("0.004"),
    }
