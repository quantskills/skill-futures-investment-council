from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from skill_futures_investment_council.api.provider import CsvMarketDataProvider
from skill_futures_investment_council.calculators.chain_calculator import ChainCalculator


class StandalonePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "TEST_INDEX.csv"
        closes = [100 + index + ((index % 3) - 1) * 0.5 for index in range(40)]
        pd.DataFrame(
            {
                "datetime": pd.date_range("2026-01-01", periods=40, freq="D"),
                "symbol": ["TEST_INDEX"] * 40,
                "open": [value - 0.5 for value in closes],
                "high": [value + 1 for value in closes],
                "low": [value - 1 for value in closes],
                "close": closes,
                "volume": [100 + index for index in range(40)],
                "open_interest": [200 + index for index in range(40)],
                "money": [value * (100 + index) for index, value in enumerate(closes)],
            }
        ).to_csv(self.source, index=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_csv_provider_and_indicator_chain(self) -> None:
        provider = CsvMarketDataProvider(self.root)
        symbols = provider.resolve_symbols(["all.all"])
        self.assertEqual(["TEST_INDEX"], list(symbols))

        setting = {
            "name": "test",
            "md_freq": "d",
            "output_path": str(self.root / "output"),
            "compression": False,
            "tasks": [
                {"name": "change_rate", "inputs": "close", "output": "change_rate"},
                {"name": "moving_average", "inputs": "close", "output": "MA", "windows": [3]},
                {"name": "macd", "inputs": "close"},
                {"name": "rsi", "inputs": "close", "timeperiod": 14},
            ],
        }
        calculator = ChainCalculator("TEST_INDEX", symbols["TEST_INDEX"], setting, provider)
        output = Path(calculator.execute())
        result = pd.read_csv(output)

        self.assertTrue(output.exists())
        self.assertIn("close_change_rate", result.columns)
        self.assertIn("close_MA_3", result.columns)
        self.assertIn("close_MACD_Hist", result.columns)
        self.assertIn("close_RSI", result.columns)
        self.assertFalse(pd.isna(result.iloc[-1]["close_MACD_Hist"]))
        self.assertFalse(pd.isna(result.iloc[-1]["close_RSI"]))


if __name__ == "__main__":
    unittest.main()
