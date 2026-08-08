from __future__ import annotations

import unittest

import pandas as pd

from skill_futures_investment_council.features import calculate_feature_set
from skill_futures_investment_council.investment_council import (
    build_evidence_package,
    generate_council_report,
)


class CouncilReportTest(unittest.TestCase):
    def test_markdown_report_has_required_sections(self) -> None:
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-01-01", periods=50, freq="D"),
                "symbol": ["AU_INDEX"] * 50,
                "open": [100 + i for i in range(50)],
                "high": [101 + i for i in range(50)],
                "low": [99 + i for i in range(50)],
                "close": [100.5 + i for i in range(50)],
                "volume": [1000 + i for i in range(50)],
                "open_interest": [3000 + i for i in range(50)],
            }
        )
        features = calculate_feature_set(frame, {})
        evidence = build_evidence_package("AU_INDEX", features, {})
        report = generate_council_report(evidence)
        self.assertIsInstance(report, str)
        for section in ["市场概览", "市场状态", "期货结构", "专家观点", "置信度"]:
            self.assertIn(section, report)


if __name__ == "__main__":
    unittest.main()
