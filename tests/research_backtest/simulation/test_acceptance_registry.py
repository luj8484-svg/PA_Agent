from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from pa_agent.research_backtest.domain.canonical import canonical_sha256

ROOT = Path(__file__).parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


def test_master_requirement_registry_is_bidirectionally_complete() -> None:
    path = FIXTURES / "master_test_registry_v1.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 60
    ids = tuple(row["requirement_id"] for row in rows)
    assert len(set(ids)) == 60
    expected_counts = {
        "LIFE": 12,
        "FILL": 10,
        "COST": 9,
        "POS": 7,
        "ACCT": 10,
        "DATA": 6,
        "ID": 3,
        "SCOPE": 3,
    }
    assert Counter(item.split("-")[1] for item in ids) == expected_counts
    for row in rows:
        test_path = ROOT / row["test_file"]
        implementation = ROOT / row["implementation_file"]
        assert test_path.is_file(), row
        assert implementation.is_file(), row
        assert f"def {row['test_name']}(" in test_path.read_text(encoding="utf-8"), row


def test_timeline_golden_manifest_has_23_content_addressed_cases() -> None:
    path = FIXTURES / "timeline_golden_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"), parse_float=lambda _: None)
    cases = payload["cases"]
    assert payload["schema_version"] == "TIMELINE_GOLDEN_V1"
    assert [item["timeline_id"] for item in cases] == [f"TL-{index:02d}" for index in range(1, 24)]
    for item in cases:
        content = {key: value for key, value in item.items() if key != "content_hash"}
        assert item["content_hash"] == canonical_sha256(content)
        test_path = ROOT / item["test_file"]
        assert test_path.is_file()
        assert f"def {item['test_name']}(" in test_path.read_text(encoding="utf-8")


def test_timeline_manifest_is_canonical_and_has_no_placeholders() -> None:
    text = (FIXTURES / "timeline_golden_v1.json").read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "PLACEHOLDER" not in text
    payload = json.loads(text)
    content = {key: value for key, value in payload.items() if key != "manifest_content_hash"}
    assert canonical_sha256(content) == payload["manifest_content_hash"]


def test_red_team_registry_has_34_direct_defenses() -> None:
    path = FIXTURES / "red_team_registry_v1.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle, delimiter="\t"))
    assert [row["scenario_id"] for row in rows] == [f"RT-{index:02d}" for index in range(1, 35)]
    for row in rows:
        test_path = ROOT / row["test_file"]
        assert test_path.is_file(), row
        assert f"def {row['test_name']}(" in test_path.read_text(encoding="utf-8"), row
