from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import importlib
import re
import time
import warnings
from typing import Any

import pandas as pd

Progress = Callable[[str], None]


class AkshareFundamentalSource:
    """Lazy akshare-backed spot and inventory loader."""

    _DATE_COLUMNS = ("日期", "date", "datetime", "trade_date", "trading_day")
    _DEFAULT_SPOT_SYMBOLS = {
        "A": "豆一",
        "AG": "白银",
        "AL": "铝",
        "AP": "苹果",
        "AU": "黄金",
        "B": "豆二",
        "BU": "沥青",
        "C": "玉米",
        "CF": "棉花",
        "CS": "玉米淀粉",
        "CU": "CU",
        "FG": "玻璃",
        "HC": "热轧卷板",
        "I": "铁矿石",
        "J": "焦炭",
        "JM": "焦煤",
        "JD": "鸡蛋",
        "L": "聚乙烯",
        "MA": "甲醇",
        "M": "豆粕",
        "NI": "镍",
        "OI": "豆油",
        "P": "棕榈油",
        "PB": "铅",
        "PP": "聚丙烯",
        "RB": "螺纹钢",
        "RU": "橡胶",
        "SC": "原油",
        "SF": "硅铁",
        "SM": "锰硅",
        "SR": "白糖",
        "TA": "PTA",
        "V": "PVC",
        "Y": "豆油",
        "ZN": "锌",
    }
    _DEFAULT_INVENTORY_SYMBOLS = {
        "AG": "沪银",
        "AL": "沪铝",
        "AP": "苹果",
        "AU": "沪金",
        "BU": "沥青",
        "C": "玉米",
        "CF": "郑棉",
        "CS": "玉米淀粉",
        "CU": "沪铜",
        "FG": "玻璃",
        "HC": "热卷",
        "I": "铁矿石",
        "J": "焦炭",
        "JD": "鸡蛋",
        "JM": "焦煤",
        "L": "塑料",
        "MA": "甲醇",
        "M": "豆粕",
        "NI": "镍",
        "OI": "菜油",
        "P": "棕榈",
        "PB": "沪铅",
        "PP": "聚丙烯",
        "RB": "螺纹钢",
        "RU": "橡胶",
        "SC": "原油",
        "SA": "纯碱",
        "SF": "硅铁",
        "SM": "锰硅",
        "SR": "白糖",
        "TA": "PTA",
        "UR": "尿素",
        "V": "PVC",
        "Y": "豆油",
        "ZN": "沪锌",
    }

    def __init__(
        self,
        *,
        sdk: Any | None = None,
        spot_symbol_map: dict[str, str] | None = None,
    ) -> None:
        self._sdk = sdk
        merged = dict(self._DEFAULT_SPOT_SYMBOLS)
        if spot_symbol_map:
            merged.update({str(key).upper(): str(value) for key, value in spot_symbol_map.items()})
        self._spot_symbol_map = merged
        self._inventory_symbol_map = dict(self._DEFAULT_INVENTORY_SYMBOLS)
        self._spot_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._inventory_cache: dict[str, pd.DataFrame] = {}

    @staticmethod
    def _emit_progress(progress: Progress | None, message: str) -> None:
        if progress is not None:
            progress(message)

    def _client(self) -> Any | None:
        if self._sdk is not None:
            return self._sdk
        try:
            self._sdk = importlib.import_module("akshare")
        except ImportError:
            return None
        return self._sdk

    @staticmethod
    def _product_from_symbol(symbol: str) -> str:
        match = re.match(r"^[A-Za-z]+", str(symbol))
        return match.group(0).upper() if match else str(symbol).upper()

    @staticmethod
    def _first_existing_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        for candidate in candidates:
            if candidate in frame.columns:
                return candidate
        return None

    @staticmethod
    def _filter_dates(
        frame: pd.DataFrame,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> pd.DataFrame:
        if frame.empty or "datetime" not in frame.columns:
            return frame
        result = frame.copy()
        result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
        result = result.dropna(subset=["datetime"])
        if start_date is not None:
            result = result[result["datetime"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            result = result[result["datetime"] <= pd.Timestamp(end_date) + pd.Timedelta(days=1)]
        return result.sort_values("datetime").reset_index(drop=True)

    @staticmethod
    def _format_day(value: datetime | None) -> str | None:
        if value is None:
            return None
        return pd.Timestamp(value).strftime("%Y%m%d")

    @staticmethod
    def _merge_daily_values(frame: pd.DataFrame, addition: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or addition.empty:
            return frame

        result = frame.copy()
        result["_fundamental_date"] = pd.to_datetime(result["datetime"], errors="coerce").dt.normalize()
        extra = addition.copy()
        extra["_fundamental_date"] = pd.to_datetime(extra["datetime"], errors="coerce").dt.normalize()
        extra = extra.dropna(subset=["_fundamental_date"])
        extra = extra.sort_values("_fundamental_date").drop_duplicates("_fundamental_date", keep="last")

        merge_columns = [column for column in extra.columns if column not in {"datetime", "_fundamental_date"}]
        if not merge_columns:
            return frame

        merged = result.merge(
            extra[["_fundamental_date", *merge_columns]],
            on="_fundamental_date",
            how="left",
        )
        return merged.drop(columns=["_fundamental_date"])

    def _resolve_spot_symbol(self, product: str) -> str:
        product = self._product_from_symbol(product)
        return self._spot_symbol_map.get(product, product)

    def _resolve_inventory_symbol(self, product: str) -> str:
        product = self._product_from_symbol(product)
        return self._inventory_symbol_map.get(product, product)

    def _load_spot_history(
        self,
        product: str,
        start_date: datetime | None,
        end_date: datetime | None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        client = self._client()
        if client is None or not hasattr(client, "futures_spot_price_daily"):
            return pd.DataFrame()

        product_code = self._product_from_symbol(product)
        spot_symbol = self._resolve_spot_symbol(product)
        cache_key = (
            spot_symbol.upper(),
            self._format_day(start_date) or "",
            self._format_day(end_date) or "",
        )
        if cache_key not in self._spot_cache:
            candidates = [spot_symbol]
            if spot_symbol.upper() != product_code:
                candidates.append(product_code)
            self._spot_cache[cache_key] = pd.DataFrame()
            for candidate in dict.fromkeys(candidates):
                try:
                    self._emit_progress(progress, f"正在拉取现货价：{candidate}")
                    fetch_start = time.perf_counter()
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message=r".*非交易日.*", category=UserWarning)
                        raw = client.futures_spot_price_daily(
                            start_day=self._format_day(start_date) or "20000101",
                            end_day=self._format_day(end_date) or "20991231",
                            vars_list=[candidate],
                        )
                    self._emit_progress(progress, f"现货价请求完成：{candidate}（{time.perf_counter() - fetch_start:.2f}s）")
                except Exception:
                    continue
                if raw is None or raw.empty:
                    continue
                self._emit_progress(progress, f"正在解析现货价结果：{candidate}")
                parse_start = time.perf_counter()
                frame = raw.copy()
                date_column = self._first_existing_column(frame, self._DATE_COLUMNS)
                if date_column is None:
                    continue
                rename: dict[str, str] = {date_column: "datetime"}
                if "spot_price" not in frame.columns and "现货价格" in frame.columns:
                    rename["现货价格"] = "spot_price"
                if "spot_price" not in frame.columns and "spot" in frame.columns:
                    rename["spot"] = "spot_price"
                frame = frame.rename(columns=rename)
                if "spot_price" not in frame.columns:
                    continue
                frame["spot_price"] = pd.to_numeric(frame["spot_price"], errors="coerce")
                frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
                frame = frame.dropna(subset=["datetime", "spot_price"])
                keep = ["datetime", "spot_price"]
                for column in (
                    "near_contract",
                    "near_contract_price",
                    "dominant_contract",
                    "dominant_contract_price",
                    "near_basis",
                    "dom_basis",
                ):
                    if column in frame.columns:
                        keep.append(column)
                self._spot_cache[cache_key] = frame[keep].sort_values("datetime").reset_index(drop=True)
                self._emit_progress(progress, f"现货价解析完成：{candidate}（{time.perf_counter() - parse_start:.2f}s）")
                if not self._spot_cache[cache_key].empty:
                    break
        else:
            self._emit_progress(progress, f"现货价已命中缓存：{spot_symbol}")
        return self._filter_dates(self._spot_cache[cache_key].copy(), start_date, end_date)

    def _load_inventory_history(
        self,
        product: str,
        start_date: datetime | None,
        end_date: datetime | None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        client = self._client()
        if client is None or not hasattr(client, "futures_inventory_em"):
            return pd.DataFrame()

        inventory_symbol = self._resolve_inventory_symbol(product)
        cache_key = inventory_symbol.upper()
        if cache_key not in self._inventory_cache:
            try:
                self._emit_progress(progress, f"正在拉取库存：{inventory_symbol}")
                fetch_start = time.perf_counter()
                raw = client.futures_inventory_em(symbol=inventory_symbol)
                self._emit_progress(progress, f"库存请求完成：{inventory_symbol}（{time.perf_counter() - fetch_start:.2f}s）")
            except Exception:
                self._inventory_cache[cache_key] = pd.DataFrame()
            else:
                if raw is None or raw.empty:
                    self._inventory_cache[cache_key] = pd.DataFrame()
                else:
                    self._emit_progress(progress, f"正在解析库存结果：{inventory_symbol}")
                    parse_start = time.perf_counter()
                    frame = raw.copy()
                    date_column = self._first_existing_column(frame, self._DATE_COLUMNS)
                    inventory_column = self._first_existing_column(frame, ("库存", "inventory"))
                    if date_column is None or inventory_column is None:
                        self._inventory_cache[cache_key] = pd.DataFrame()
                    else:
                        rename = {date_column: "datetime", inventory_column: "inventory"}
                        if "增减" in frame.columns:
                            rename["增减"] = "inventory_change"
                        frame = frame.rename(columns=rename)
                        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
                        frame["inventory"] = pd.to_numeric(frame["inventory"], errors="coerce")
                        if "inventory_change" in frame.columns:
                            frame["inventory_change"] = pd.to_numeric(frame["inventory_change"], errors="coerce")
                        frame = frame.dropna(subset=["datetime", "inventory"])
                        keep = ["datetime", "inventory"]
                        if "inventory_change" in frame.columns:
                            keep.append("inventory_change")
                        self._inventory_cache[cache_key] = frame[keep].sort_values("datetime").reset_index(drop=True)
                    self._emit_progress(progress, f"库存解析完成：{inventory_symbol}（{time.perf_counter() - parse_start:.2f}s）")
        else:
            self._emit_progress(progress, f"库存已命中缓存：{inventory_symbol}")
        return self._filter_dates(self._inventory_cache[cache_key].copy(), start_date, end_date)

    def enrich_frame(
        self,
        frame: pd.DataFrame,
        product: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        if frame.empty:
            return frame
        result = frame.copy()
        self._emit_progress(progress, f"开始补充 {product} 的现货和库存历史")
        start = time.perf_counter()
        spot = self._load_spot_history(product, start_date, end_date, progress=progress)
        inventory = self._load_inventory_history(product, start_date, end_date, progress=progress)
        result = self._merge_daily_values(result, spot)
        result = self._merge_daily_values(result, inventory)
        self._emit_progress(progress, f"完成补充 {product} 的现货和库存历史（{time.perf_counter() - start:.2f}s）")
        return result.sort_values("datetime").reset_index(drop=True)

    def load_spot_history(
        self,
        product: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        """Load spot price history only."""
        return self._load_spot_history(product, start_date, end_date, progress=progress)

    def load_inventory_history(
        self,
        product: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        """Load inventory history only."""
        return self._load_inventory_history(product, start_date, end_date, progress=progress)
