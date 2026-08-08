from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from skill_futures_investment_council.api import provider as provider_module
from skill_futures_investment_council.api.provider import PandadataMarketDataProvider, create_provider
from skill_futures_investment_council.research import _normalise_symbol


class FakePandadata:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def init_token(self, **kwargs) -> None:
        self.calls.append(("init_token", kwargs))

    def get_future_detail(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("future_detail", kwargs))
        rows = [
            {"symbol": "CU2606", "exchange": "SHFE", "contract_unit": 5},
            {"symbol": "CU2612", "exchange": "SHFE", "contract_unit": 5},
            {"symbol": "AU2606", "exchange": "SHFE", "contract_unit": 1000},
            {"symbol": "AU2612", "exchange": "SHFE", "contract_unit": 1000},
            {"symbol": "AG2606", "exchange": "SHFE", "contract_unit": 15},
        ]
        symbol = kwargs.get("symbol")
        if symbol is not None:
            if isinstance(symbol, list):
                wanted = {str(item).upper() for item in symbol}
                rows = [row for row in rows if row["symbol"].upper() in wanted]
            else:
                wanted = str(symbol).upper()
                rows = [row for row in rows if row["symbol"].upper() == wanted]
        return pd.DataFrame(
            rows
        )

    def get_future_contract_pool(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("future_contract_pool", kwargs))
        rows = [
            {"symbol": "CU2606", "underlying_symbol": "CU"},
            {"symbol": "CU2612", "underlying_symbol": "CU"},
            {"symbol": "AU2606", "underlying_symbol": "AU"},
            {"symbol": "AU2612", "underlying_symbol": "AU"},
            {"symbol": "AG2606", "underlying_symbol": "AG"},
        ]
        underlying = kwargs.get("underlying_symbol")
        if underlying is not None:
            if isinstance(underlying, list):
                wanted = {str(item).upper() for item in underlying}
                rows = [row for row in rows if row["underlying_symbol"].upper() in wanted]
            else:
                wanted = str(underlying).upper()
                rows = [row for row in rows if row["underlying_symbol"].upper() == wanted]
        return pd.DataFrame(rows)

    def get_option_detail(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "symbol": "AU2606C600",
                    "underlying_symbol": "AU2606",
                    "option_type": "call",
                    "contract_size": 1000,
                }
            ]
        )

    def get_future_daily(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("future_daily", kwargs))
        if isinstance(kwargs["symbol"], list):
            if kwargs["symbol"] == ["CU2606", "CU2612"]:
                return pd.DataFrame(
                    [
                        {"date": "20260801", "symbol": "CU2606", "open": 598, "high": 605, "low": 595, "close": 600, "settlement": 601, "volume": 10, "open_interest": 100, "amount": 10_000},
                        {"date": "20260801", "symbol": "CU2612", "open": 628, "high": 635, "low": 625, "close": 630, "settlement": 631, "volume": 30, "open_interest": 300, "amount": 30_000},
                        {"date": "20260802", "symbol": "CU2606", "open": 600, "high": 610, "low": 599, "close": 606, "settlement": 607, "volume": 20, "open_interest": 200, "amount": 20_000},
                        {"date": "20260802", "symbol": "CU2612", "open": 630, "high": 640, "low": 629, "close": 636, "settlement": 637, "volume": 40, "open_interest": 200, "amount": 40_000},
                    ]
                )
            return pd.DataFrame(
                [
                    {"date": "20260801", "symbol": "AU2606", "open": 598, "high": 605, "low": 595, "close": 600, "volume": 10, "open_interest": 100, "amount": 10_000},
                    {"date": "20260801", "symbol": "AU2612", "open": 628, "high": 635, "low": 625, "close": 630, "volume": 30, "open_interest": 300, "amount": 30_000},
                    {"date": "20260802", "symbol": "AU2606", "open": 600, "high": 610, "low": 599, "close": 606, "volume": 20, "open_interest": 200, "amount": 20_000},
                    {"date": "20260802", "symbol": "AU2612", "open": 630, "high": 640, "low": 629, "close": 636, "volume": 40, "open_interest": 200, "amount": 40_000},
                ]
            )
        return pd.DataFrame({"date": ["20260803"], "symbol": [kwargs["symbol"]], "close": [620.0], "amount": [100.0]})

    def get_future_min(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("future_min", kwargs))
        return pd.DataFrame({"date": ["2026-08-03 09:01:00"], "close": [620.0]})

    def get_option_daily(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("option_daily", kwargs))
        return pd.DataFrame({"date": ["20260803"], "symbol": [kwargs["symbol"]], "close": [8.0]})

    def futures_spot_price_daily(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("futures_spot_price_daily", kwargs))
        if kwargs["vars_list"] == ["CU"]:
            return pd.DataFrame(
                [
                    {"date": "20260801", "symbol": "CU", "spot_price": 598.0, "near_contract_price": 600.0, "dom_basis": -2.0},
                    {"date": "20260802", "symbol": "CU", "spot_price": 606.0, "near_contract_price": 606.0, "dom_basis": 0.0},
                ]
            )
        return pd.DataFrame()

    def futures_inventory_em(self, **kwargs) -> pd.DataFrame:
        self.calls.append(("futures_inventory_em", kwargs))
        if kwargs["symbol"] == "沪铜":
            return pd.DataFrame(
                [
                    {"日期": "2026-08-01", "库存": 120000.0, "增减": -1000.0},
                    {"日期": "2026-08-02", "库存": 119500.0, "增减": -500.0},
                ]
            )
        return pd.DataFrame()


class PandadataProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sdk = FakePandadata()
        self.provider = PandadataMarketDataProvider(sdk=self.sdk)

    def test_resolve_catalog_and_derived_symbols(self) -> None:
        symbols = self.provider.resolve_symbols(["AU2606", "AU_INDEX", "all.options"])
        self.assertEqual(["AU2606", "AU_INDEX", "AU2606C600"], list(symbols))
        self.assertEqual(1000, symbols["AU2606"]["contract_size"])
        self.assertEqual(1000, symbols["AU_INDEX"]["contract_size"])
        self.assertEqual("option", symbols["AU2606C600"]["security_type"])

    def test_symbol_catalog_is_scoped_to_product(self) -> None:
        self.provider.resolve_symbols(["CU_INDEX"])
        end_date = pd.Timestamp.now().strftime("%Y%m%d")
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=730)).strftime("%Y%m%d")
        self.assertEqual(
            ("future_contract_pool", {"underlying_symbol": "CU", "start_date": start_date, "end_date": end_date}),
            self.sdk.calls[0],
        )
        self.assertEqual(("future_detail", {"symbol": "CU2606"}), self.sdk.calls[1])

    def test_symbol_catalog_uses_requested_date_window(self) -> None:
        self.provider.resolve_symbols(
            ["CU_INDEX"],
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 8, 7),
        )
        self.assertEqual(
            (
                "future_contract_pool",
                {"underlying_symbol": "CU", "start_date": "20260101", "end_date": "20260807"},
            ),
            self.sdk.calls[0],
        )

    def test_daily_bars_are_normalised(self) -> None:
        bars = self.provider.get_bars(
            "AU2606",
            {"security_type": "futures"},
            datetime(2026, 8, 1),
            datetime(2026, 8, 3),
            "d",
        )
        self.assertIn("datetime", bars.columns)
        self.assertIn("money", bars.columns)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(bars["datetime"]))
        self.assertEqual("20260801", self.sdk.calls[0][1]["start_date"])

    def test_dominant_uses_sdk_native_symbol(self) -> None:
        self.provider.get_bars(
            "AU_DOMINANT",
            {"security_type": "futures", "product": "AU", "derived_type": "dominant"},
            datetime(2026, 8, 1),
            datetime(2026, 8, 3),
            "d",
        )
        self.assertEqual("AU_DOMINANT", self.sdk.calls[0][1]["symbol"])

    def test_index_is_composed_from_real_contracts(self) -> None:
        info = self.provider.resolve_symbols(["AU_INDEX"])["AU_INDEX"]
        bars = self.provider.get_bars(
            "AU_INDEX",
            info,
            datetime(2026, 8, 1),
            datetime(2026, 8, 2),
            "d",
        )
        self.assertEqual(["AU2606", "AU2612"], self.sdk.calls[-1][1]["symbol"])
        self.assertEqual(["AU_INDEX", "AU_INDEX"], bars["symbol"].tolist())
        self.assertAlmostEqual(622.5, bars.iloc[0]["close"])
        self.assertAlmostEqual(620.5, bars.iloc[0]["open"])
        self.assertEqual(40, bars.iloc[0]["volume"])
        self.assertEqual(400, bars.iloc[0]["open_interest"])
        self.assertEqual(40_000, bars.iloc[0]["money"])

    def test_fundamentals_are_merged_into_index_bars(self) -> None:
        provider = PandadataMarketDataProvider(sdk=self.sdk, fundamental_sdk=self.sdk)
        info = provider.resolve_symbols(["CU_INDEX"])["CU_INDEX"]
        bars = provider.get_bars(
            "CU_INDEX",
            info,
            datetime(2026, 8, 1),
            datetime(2026, 8, 2),
            "d",
        )
        self.assertIn("spot_price", bars.columns)
        self.assertIn("inventory", bars.columns)
        self.assertIn("curve_snapshot", bars.columns)
        self.assertAlmostEqual(598.0, bars.iloc[0]["spot_price"])
        self.assertAlmostEqual(120000.0, bars.iloc[0]["inventory"])
        self.assertAlmostEqual(-1000.0, bars.iloc[0]["inventory_change"])
        self.assertEqual("CU2606", bars.iloc[-1]["curve_snapshot"][0]["symbol"])

    def test_factory_accepts_pandadata_alias(self) -> None:
        provider = create_provider({"data_source": {"type": "panda_data"}})
        self.assertIsInstance(provider, PandadataMarketDataProvider)

    def test_auto_login_does_not_require_base_url(self) -> None:
        provider = PandadataMarketDataProvider(
            auto_login=True,
            username_env="PANDA_DATA_USERNAME",
            password_env="PANDA_DATA_PASSWORD",
            sdk=self.sdk,
        )
        with patch.dict(
            "os.environ",
            {"PANDA_DATA_USERNAME": "user", "PANDA_DATA_PASSWORD": "password"},
            clear=True,
        ):
            provider.resolve_symbols(["AU2606"])

        self.assertEqual("init_token", self.sdk.calls[0][0])
        self.assertEqual({"username": "user", "password": "password"}, self.sdk.calls[0][1])

    def test_auto_login_can_read_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(
                "PANDA_DATA_USERNAME=dotenv_user\nPANDA_DATA_PASSWORD=dotenv_pass\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                with patch.object(provider_module.Path, "cwd", return_value=root):
                    with patch.object(provider_module, "_skill_root", return_value=None):
                        provider = PandadataMarketDataProvider(
                            auto_login=True,
                            username_env="PANDA_DATA_USERNAME",
                            password_env="PANDA_DATA_PASSWORD",
                            sdk=self.sdk,
                        )
                        provider.resolve_symbols(["AU2606"])

        self.assertEqual("init_token", self.sdk.calls[0][0])
        self.assertEqual({"username": "dotenv_user", "password": "dotenv_pass"}, self.sdk.calls[0][1])

    def test_chinese_symbol_aliases_cover_common_products(self) -> None:
        cases = {
            "工业硅": "SI_INDEX",
            "多晶硅": "PS_INDEX",
            "碳酸锂": "LC_INDEX",
            "纯碱": "SA_INDEX",
            "沪深300": "IF_INDEX",
            "中证1000": "IM_INDEX",
            "十年国债": "TF_INDEX",
            "沪铜主连": "CU_DOMINANT",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, _normalise_symbol(raw))


if __name__ == "__main__":
    unittest.main()
