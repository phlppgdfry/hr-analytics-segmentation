"""Tests voor de HTML-rapportgenerator."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.report import call_list, latest_segmented_file, write_report

SEGMENTS = ["Champions", "Potentials", "At Risk", "Lost"]


@pytest.fixture
def processed(tmp_path: Path) -> Path:
    rows = []
    for i in range(40):
        segment = SEGMENTS[i % 4]
        rows.append(
            {
                "employer_id": f"EMP{i:05d}",
                "sector": "tech",
                "company_size": "small",
                "region": "Gent",
                "recency_days": 10 * i,
                "frequency_12m": i % 7,
                "revenue_potential": 1000.0 * (i + 1),
                "segment_name": segment,
            }
        )
    pd.DataFrame(rows).to_csv(tmp_path / "employers_segmented_20260101.csv", index=False)
    pd.DataFrame(
        {
            "segment_name": SEGMENTS,
            "count": [10, 10, 10, 10],
            "avg_rfm_score": [0.5, 0.4, 0.3, 0.1],
            "avg_priority_score": [40, 45, 60, 90],
            "avg_revenue_potential": [5000, 4000, 3000, 2000],
        }
    ).to_csv(tmp_path / "segment_profiles.csv", index=False)
    return tmp_path


def test_call_list_contains_only_at_risk_sorted_by_value(processed: Path) -> None:
    df = pd.read_csv(latest_segmented_file(processed))
    calls = call_list(df, limit=5)
    assert len(calls) == 5
    assert calls["revenue_potential"].is_monotonic_decreasing
    at_risk_ids = set(df.loc[df["segment_name"] == "At Risk", "employer_id"])
    assert set(calls["employer_id"]) <= at_risk_ids


def test_report_is_self_contained_and_has_no_personal_data(processed: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    target = write_report(processed, out, generated_on=date(2026, 1, 1))
    page = target.read_text(encoding="utf-8")
    assert page.count("data:image/png;base64,") == 2
    assert "Who to call first" in page
    assert "contact_email" not in page and "contact_name" not in page
    assert (out / "segments.png").exists() and (out / "rfm-map.png").exists()


def test_missing_pipeline_output_gives_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Run `python -m src.main` first"):
        latest_segmented_file(tmp_path)
