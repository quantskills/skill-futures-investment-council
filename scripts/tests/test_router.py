from __future__ import annotations

import unittest
from pathlib import Path

from skill_futures_investment_council.investment_council.router import route_experts


class RouterTest(unittest.TestCase):
    def test_routes_from_full_expert_pack(self) -> None:
        root = Path(__file__).resolve().parents[2]
        features = {
            "trend": {
                "ma_alignment": {"available": True, "state": "bullish"},
                "adx": {"available": True, "trend_strength": "strong_trend"},
                "breakout": {"available": True, "breakout_20": True},
                "macd": {"available": True, "state": "bullish"},
            },
            "fundamental": {
                "spot_price": {"available": True, "spot_price": 100.0},
                "inventory_state": {"available": True, "state": "decreasing", "inventory": 10.0, "change": -1.0},
                "supply_demand_balance": {"available": False, "state": "unknown"},
            },
            "futures": {
                "basis": {"available": True},
                "curve_structure": {"available": True, "state": "contango"},
            },
            "risk": {"drawdown": {"available": True, "current_drawdown": -0.05}},
        }

        experts = route_experts("CU_INDEX", features, root=root)

        self.assertGreaterEqual(len(experts), 4)
        self.assertIn("jesse_livermore", [expert["id"] for expert in experts])
        self.assertIn("fu_haitang", [expert["id"] for expert in experts])
        self.assertTrue(any("references\\experts" in expert["path"] or "references/experts" in expert["path"] for expert in experts))


if __name__ == "__main__":
    unittest.main()
