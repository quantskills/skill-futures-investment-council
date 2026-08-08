from __future__ import annotations

import unittest

import pandas as pd

from skill_futures_investment_council.features import calculate_feature_set


class FeatureEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        closes = [100 + index * 0.8 for index in range(160)]
        self.frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-01-01", periods=160, freq="D"),
                "symbol": ["CU_INDEX"] * 160,
                "open": [value - 0.3 for value in closes],
                "high": [value + 0.8 for value in closes],
                "low": [value - 1.1 for value in closes],
                "close": closes,
                "volume": [1000 + index for index in range(160)],
                "open_interest": [2000 + index * 3 for index in range(160)],
            }
        )

    def test_feature_set_contains_expected_sections(self) -> None:
        features = calculate_feature_set(self.frame, {})
        self.assertIn("trend", features)
        self.assertIn("momentum", features)
        self.assertIn("volatility", features)
        self.assertIn("futures", features)
        self.assertIn("risk", features)
        self.assertEqual("CU_INDEX", features["symbol"])
        self.assertEqual("bullish", features["trend"]["ma_alignment"]["state"])
        self.assertTrue(features["trend"]["breakout"]["available"])
        self.assertIn(features["volatility"]["regime"]["state"], {"expanding", "normal", "contracting"})

    def test_open_interest_degrades_when_missing(self) -> None:
        frame = self.frame.drop(columns=["open_interest"])
        features = calculate_feature_set(frame, {})
        self.assertEqual("missing", features["data_quality"]["open_interest"])
        self.assertFalse(features["futures"]["open_interest"]["available"])
        self.assertIn("open_interest", features["futures"]["open_interest"]["reason"])

    def test_fundamentals_are_recognized(self) -> None:
        frame = self.frame.copy()
        frame["spot_price"] = frame["close"] + 1.5
        frame["inventory"] = [1000 + index * 10 for index in range(len(frame))]
        features = calculate_feature_set(frame, {})
        self.assertEqual("partial", features["data_quality"]["fundamental"])
        self.assertTrue(features["fundamental"]["spot_price"]["available"])
        self.assertTrue(features["fundamental"]["inventory_state"]["available"])
        self.assertEqual("increasing", features["fundamental"]["inventory_state"]["state"])

    def test_curve_snapshot_is_recognized(self) -> None:
        frame = self.frame.copy()
        frame["curve_snapshot"] = None
        frame.at[frame.index[-1], "curve_snapshot"] = [
            {"symbol": "CU2608", "contract_month": "2608", "settlement": 100.0, "datetime": "2026-08-06"},
            {"symbol": "CU2609", "contract_month": "2609", "settlement": 103.0, "datetime": "2026-08-06"},
        ]
        features = calculate_feature_set(frame, {})
        curve = features["futures"]["curve_structure"]
        self.assertTrue(curve["available"])
        self.assertEqual("contango", curve["state"])
        self.assertEqual("CU2608", curve["front_symbol"])


if __name__ == "__main__":
    unittest.main()
