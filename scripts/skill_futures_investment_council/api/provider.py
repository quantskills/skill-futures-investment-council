"""Market data provider boundary and standalone CSV implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
import importlib
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable

import pandas as pd

from .fundamentals import AkshareFundamentalSource

Progress = Callable[[str], None]


def _csv_symbol(path: Path) -> str:
    name = path.name
    for suffix in (".csv.gz", ".csv"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _skill_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "SKILL.md").exists():
            return parent
    return None


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


class MarketDataProvider(ABC):
    """Abstract data boundary used by the calculation pipeline."""

    @abstractmethod
    def resolve_symbols(
        self,
        selectors: Iterable[str] | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Resolve user selectors to concrete symbol metadata."""

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        symbol_info: dict[str, Any],
        start_date: datetime | None,
        end_date: datetime | None,
        frequency: str,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        """Return market bars for one symbol."""


class CsvMarketDataProvider(MarketDataProvider):
    """Read bars from a combined CSV file or a directory of symbol CSV files.

    A combined file must contain ``symbol`` and ``datetime`` columns. A directory
    may contain ``SYMBOL.csv`` or ``SYMBOL.csv.gz`` files; a symbol column is
    added from the filename when absent.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        symbol_column: str = "symbol",
        datetime_column: str = "datetime",
        security_type: str = "futures",
        contract_size: float | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.symbol_column = symbol_column
        self.datetime_column = datetime_column
        self.security_type = security_type
        self.contract_size = contract_size
        self._combined_cache: pd.DataFrame | None = None
        if not self.path.exists():
            raise FileNotFoundError(f"行情数据路径不存在: {self.path}")

    def _files(self) -> list[Path]:
        if self.path.is_file():
            return [self.path]
        return sorted(
            file
            for file in self.path.iterdir()
            if file.is_file() and file.name.lower().endswith((".csv", ".csv.gz"))
        )

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_combined_cache"] = None
        return state

    def _read_combined(self) -> pd.DataFrame:
        if self._combined_cache is None:
            frame = pd.read_csv(self.path)
            self._validate(frame, require_symbol=True)
            self._combined_cache = frame
        return self._combined_cache

    def _available_symbols(self) -> list[str]:
        if self.path.is_file():
            frame = self._read_combined()
            return sorted(frame[self.symbol_column].dropna().astype(str).unique())
        return sorted({_csv_symbol(file) for file in self._files()})

    def resolve_symbols(
        self,
        selectors: Iterable[str] | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> dict[str, dict[str, Any]]:
        available = self._available_symbols()
        available_lookup = {symbol.upper(): symbol for symbol in available}
        requested = list(selectors or ["all.all"])
        selected: list[str] = []

        for selector in requested:
            selector = str(selector)
            if selector.lower() in {"all", "all.all"}:
                selected.extend(available)
                continue
            raw_symbol = selector.split(".", 1)[0]
            resolved = available_lookup.get(raw_symbol.upper())
            if resolved is None:
                raise ValueError(
                    f"CSV 数据中不存在标的 {raw_symbol!r}; 可用标的: {', '.join(available[:20])}"
                )
            selected.append(resolved)

        result = {}
        for symbol in dict.fromkeys(selected):
            info = {"symbol": symbol, "security_type": self.security_type}
            if self.contract_size is not None:
                info["contract_size"] = self.contract_size
            result[symbol] = info
        return result

    def get_bars(
        self,
        symbol: str,
        symbol_info: dict[str, Any],
        start_date: datetime | None,
        end_date: datetime | None,
        frequency: str,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        if self.path.is_file():
            source = self._read_combined()
            frame = source[source[self.symbol_column].astype(str) == str(symbol)].copy()
        else:
            matches = [file for file in self._files() if _csv_symbol(file).upper() == symbol.upper()]
            if not matches:
                raise FileNotFoundError(f"未找到 {symbol} 对应的 CSV 文件")
            frame = pd.read_csv(matches[0])
            if self.symbol_column not in frame.columns:
                frame[self.symbol_column] = symbol

        self._validate(frame, require_symbol=True)
        frame[self.datetime_column] = pd.to_datetime(frame[self.datetime_column], errors="raise")
        if start_date is not None:
            frame = frame[frame[self.datetime_column] >= pd.Timestamp(start_date)]
        if end_date is not None:
            inclusive_end = pd.Timestamp(end_date) + pd.Timedelta(days=1)
            frame = frame[frame[self.datetime_column] < inclusive_end]
        return frame.sort_values(self.datetime_column).reset_index(drop=True)

    def _validate(self, frame: pd.DataFrame, *, require_symbol: bool) -> None:
        required = {self.datetime_column}
        if require_symbol:
            required.add(self.symbol_column)
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"行情 CSV 缺少必需列: {', '.join(sorted(missing))}")


class PandadataMarketDataProvider(MarketDataProvider):
    """Use the optional :mod:`panda_data` SDK as a market data source.

    The provider does not log in by default, so an SDK token already configured
    by the user is reused. Set ``auto_login`` to true to call ``init_token``
    from credentials stored in environment variables.
    """

    _DATE_COLUMNS = ("date", "datetime", "trade_date", "trading_day")
    _CONTRACT_SIZE_COLUMNS = ("contract_size", "contract_unit", "multiplier")
    _INDEX_PRICE_COLUMNS = (
        "open",
        "high",
        "low",
        "close",
        "settlement",
        "pre_settlement",
        "day_session_open",
        "limit_up",
        "limit_down",
    )
    _INDEX_SUM_COLUMNS = ("volume", "open_interest", "money")
    _INDEX_BATCH_SIZE = 20

    def __init__(
        self,
        *,
        auto_login: bool = False,
        username_env: str = "DEFAULT_USERNAME",
        password_env: str = "DEFAULT_PASSWORD",
        base_url_env: str | None = None,
        minute_frequency: str = "1m",
        index_weight_lag: int = 0,
        sdk: Any | None = None,
        fundamental_source: dict[str, Any] | None = None,
        fundamental_sdk: Any | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.auto_login = auto_login
        self.username_env = username_env
        self.password_env = password_env
        self.base_url_env = base_url_env
        self.minute_frequency = minute_frequency
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir is not None else None
        if index_weight_lag not in {0, 1}:
            raise ValueError("index_weight_lag 只能是 0 或 1")
        self.index_weight_lag = index_weight_lag
        self._sdk = sdk
        self._authenticated = False
        self._dotenv_loaded = False
        self._catalog_cache: dict[tuple[str | None, bool], pd.DataFrame] = {}
        source_cfg = fundamental_source or {}
        source_type = str(source_cfg.get("type", "akshare")).lower()
        if bool(source_cfg.get("enabled", True)) and source_type in {"akshare", "ak_share"}:
            self._fundamental_source = AkshareFundamentalSource(
                sdk=fundamental_sdk,
                spot_symbol_map=source_cfg.get("spot_symbol_map"),
            )
        else:
            self._fundamental_source = None

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_sdk"] = None
        state["_catalog_cache"] = {}
        state["_authenticated"] = False
        state["_dotenv_loaded"] = False
        state["_fundamental_source"] = None
        return state

    def _load_dotenv_files(self) -> None:
        if self._dotenv_loaded:
            return
        candidates: list[Path] = [Path.cwd() / ".env"]
        if self.base_dir is not None:
            candidates.append(self.base_dir / ".env")
        skill_root = _skill_root()
        if skill_root is not None:
            candidates.append(skill_root / ".env")
        seen: set[Path] = set()
        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            for key, value in _parse_dotenv(resolved).items():
                os.environ.setdefault(key, value)
        self._dotenv_loaded = True

    def _client(self) -> Any:
        if self._sdk is None:
            try:
                self._sdk = importlib.import_module("panda_data")
            except ImportError as exc:
                raise RuntimeError(
                    "Pandadata 数据源需要可选依赖 panda-data，请先在当前环境中安装"
                ) from exc
        if self.auto_login and not self._authenticated:
            self._load_dotenv_files()
            username = os.getenv(self.username_env)
            password = os.getenv(self.password_env)
            if not username or not password:
                raise RuntimeError(
                    "Pandadata auto_login 已开启，但环境变量 "
                    f"{self.username_env} / {self.password_env} 未完整设置；"
                    "也可以在 skill 根目录放一个 .env 文件"
                )
            kwargs: dict[str, str] = {"username": username, "password": password}
            base_url = os.getenv(self.base_url_env) if self.base_url_env else None
            if base_url:
                kwargs["base_url"] = base_url
            self._sdk.init_token(**kwargs)
            self._authenticated = True
        return self._sdk

    @staticmethod
    def _emit_progress(progress: Progress | None, message: str) -> None:
        if progress is not None:
            progress(message)

    @staticmethod
    def _first_value(row: pd.Series, names: Iterable[str]) -> Any:
        for name in names:
            if name in row and pd.notna(row[name]):
                return row[name]
        return None

    @staticmethod
    def _product_from_symbol(symbol: str) -> str:
        match = re.match(r"^[A-Za-z]+", str(symbol))
        return match.group(0).upper() if match else str(symbol).upper()

    def _normalise_catalog(self, frame: pd.DataFrame, security_type: str) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["symbol", "security_type", "product"])
        if "symbol" not in frame.columns:
            raise ValueError(f"Pandadata {security_type} 合约信息缺少 symbol 列")

        result = frame.copy()
        result["symbol"] = result["symbol"].astype(str).str.upper()
        result["security_type"] = security_type
        products = []
        for _, row in result.iterrows():
            underlying = self._first_value(
                row, ("underlying_symbol", "underlying", "product", "product_symbol")
            )
            products.append(self._product_from_symbol(underlying or row["symbol"]))
        result["product"] = products
        return result

    def _catalog(
        self,
        selectors: Iterable[str] | None = None,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        include_options: bool = False,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        requested = [str(value).strip() for value in (selectors or ["all.all"])]
        full_catalog = any(value.lower() in {"all", "all.all", "all.futures", "all.options"} for value in requested)
        product_symbols: list[str] = []
        for selector in requested:
            lowered = selector.lower()
            if lowered in {"all", "all.all", "all.futures", "all.options"}:
                continue
            raw = selector.split(".", 1)[0].strip().upper()
            if raw:
                product_symbols.append(self._product_from_symbol(raw))
        end_bound = pd.Timestamp(end_date) if end_date is not None else pd.Timestamp.now()
        start_bound = pd.Timestamp(start_date) if start_date is not None else end_bound - pd.Timedelta(days=730)
        start_label = start_bound.strftime("%Y%m%d")
        end_label = end_bound.strftime("%Y%m%d")
        cache_key = (
            None if full_catalog else "|".join(sorted(dict.fromkeys(product_symbols))) or None,
            None if full_catalog else start_label,
            None if full_catalog else end_label,
            include_options and full_catalog,
        )
        if cache_key in self._catalog_cache:
            return self._catalog_cache[cache_key]

        client = self._client()
        if full_catalog:
            self._emit_progress(progress, "正在获取 PandaData 全量合约目录")
            start = time.perf_counter()
            futures = self._normalise_catalog(client.get_future_detail(), "futures")
            self._emit_progress(progress, f"PandaData 全量合约目录完成（{time.perf_counter() - start:.2f}s）")
            frames = [futures]
            if include_options or any(value.lower() in {"all.options", "all.all"} for value in requested):
                self._emit_progress(progress, "正在获取 PandaData 期权合约目录")
                start = time.perf_counter()
                options = self._normalise_catalog(client.get_option_detail(), "option")
                self._emit_progress(progress, f"PandaData 期权合约目录完成（{time.perf_counter() - start:.2f}s）")
                frames.append(options)
            catalog = pd.concat(frames, ignore_index=True, sort=False)
        else:
            futures: list[pd.DataFrame] = []
            if product_symbols:
                for product in dict.fromkeys(product_symbols):
                    self._emit_progress(progress, f"正在获取 {product} 的合约池：{start_label}..{end_label}")
                    start = time.perf_counter()
                    frame = self._normalise_catalog(
                        client.get_future_contract_pool(
                            underlying_symbol=product,
                            start_date=start_label,
                            end_date=end_label,
                        ),
                        "futures",
                    )
                    self._emit_progress(progress, f"{product} 合约池完成（{time.perf_counter() - start:.2f}s）")
                    if not frame.empty:
                        sample_symbol = str(frame.iloc[0]["symbol"])
                        try:
                            self._emit_progress(progress, f"正在获取 {product} 的代表性合约详情：{sample_symbol}")
                            start = time.perf_counter()
                            sample_detail = self._normalise_catalog(
                                client.get_future_detail(symbol=sample_symbol),
                                "futures",
                            )
                            self._emit_progress(
                                progress,
                                f"{product} 代表性合约详情完成（{time.perf_counter() - start:.2f}s）",
                            )
                            if not sample_detail.empty:
                                representative = sample_detail.iloc[0]
                                for key in ("exchange", "contract_size"):
                                    if key in representative and pd.notna(representative[key]):
                                        frame[key] = representative[key]
                        except Exception:
                            pass
                    futures.append(frame)
            else:
                futures.append(self._normalise_catalog(client.get_future_detail(), "futures"))
            catalog = pd.concat(futures, ignore_index=True, sort=False)
        self._catalog_cache[cache_key] = catalog
        return catalog

    def _row_info(self, row: pd.Series) -> dict[str, Any]:
        info: dict[str, Any] = {
            "symbol": str(row["symbol"]),
            "security_type": str(row["security_type"]),
            "product": str(row["product"]),
        }
        for key in ("exchange", "underlying_symbol", "option_type", "strike_price"):
            if key in row and pd.notna(row[key]):
                info[key] = row[key]
        contract_size = self._first_value(row, self._CONTRACT_SIZE_COLUMNS)
        if contract_size is not None:
            info["contract_size"] = contract_size
        return info

    @staticmethod
    def _derived_info(product: str, kind: str) -> dict[str, Any]:
        symbol = f"{product.upper()}_{kind.upper()}"
        return {
            "symbol": symbol,
            "security_type": "futures",
            "product": product.upper(),
            "derived_type": kind.lower(),
        }

    def resolve_symbols(
        self,
        selectors: Iterable[str] | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        progress: Progress | None = None,
    ) -> dict[str, dict[str, Any]]:
        requested = [str(value).strip() for value in (selectors or ["all.all"])]
        self._emit_progress(progress, f"正在解析选择器：{', '.join(requested)}")
        catalog = self._catalog(selectors, start_date=start_date, end_date=end_date, progress=progress)
        result: dict[str, dict[str, Any]] = {}
        products = sorted(catalog.loc[catalog["security_type"] == "futures", "product"].unique())

        def add_rows(rows: pd.DataFrame) -> None:
            for _, row in rows.iterrows():
                info = self._row_info(row)
                result.setdefault(info["symbol"], info)

        def add_derived(selected_products: Iterable[str], kind: str) -> None:
            for product in selected_products:
                info = self._derived_info(str(product), kind)
                product_rows = catalog[
                    (catalog["security_type"] == "futures")
                    & (catalog["product"] == str(product).upper())
                ]
                if not product_rows.empty:
                    representative = self._row_info(product_rows.iloc[0])
                    for key in ("exchange", "contract_size"):
                        if key in representative:
                            info[key] = representative[key]
                result.setdefault(info["symbol"], info)

        for selector in requested:
            lowered = selector.lower()
            if lowered in {"all", "all.all"}:
                add_rows(catalog)
                continue
            if lowered in {"all.index", "all.dominant"}:
                add_derived(products, selector.rsplit(".", 1)[1])
                continue
            if lowered == "all.futures":
                add_rows(catalog[catalog["security_type"] == "futures"])
                continue
            if lowered == "all.options":
                add_rows(catalog[catalog["security_type"] == "option"])
                continue

            raw = selector.upper()
            if raw.endswith("_INDEX"):
                add_derived([raw.removesuffix("_INDEX")], "index")
                continue
            if raw.endswith("_DOMINANT"):
                add_derived([raw.removesuffix("_DOMINANT")], "dominant")
                continue

            exact = catalog[catalog["symbol"] == raw]
            if not exact.empty:
                add_rows(exact)
                continue
            by_product = catalog[catalog["product"] == raw]
            if not by_product.empty:
                add_rows(by_product)
                add_derived([raw], "index")
                add_derived([raw], "dominant")
                continue
            raise ValueError(f"Pandadata 合约目录中无法解析选择器: {selector!r}")

        return result

    @staticmethod
    def _format_date(value: datetime | None, name: str) -> str:
        if value is None:
            raise ValueError(f"Pandadata 数据源要求 jobs 中配置 {name}")
        return pd.Timestamp(value).strftime("%Y%m%d")

    @classmethod
    def _normalise_bars(cls, frame: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        result = frame.copy()
        date_column = next((name for name in cls._DATE_COLUMNS if name in result.columns), None)
        if date_column is None:
            raise ValueError("Pandadata 行情结果缺少日期列")
        if date_column != "datetime":
            result = result.rename(columns={date_column: "datetime"})
        if "money" not in result.columns:
            for source in ("amount", "turnover"):
                if source in result.columns:
                    result = result.rename(columns={source: "money"})
                    break
        if symbol is not None:
            result["symbol"] = symbol
        elif "symbol" not in result.columns:
            raise ValueError("Pandadata 行情结果缺少 symbol 列")
        else:
            result["symbol"] = result["symbol"].astype(str).str.upper()
        result["datetime"] = pd.to_datetime(result["datetime"], errors="raise")
        return result.sort_values("datetime").reset_index(drop=True)

    def _index_contracts(
        self,
        product: str,
        start_date: datetime | None,
        end_date: datetime | None,
        progress: Progress | None = None,
    ) -> list[str]:
        self._emit_progress(progress, f"正在整理 {product} 的可用合约")
        catalog = self._catalog([product], start_date=start_date, end_date=end_date, progress=progress)
        rows = catalog[
            (catalog["security_type"] == "futures")
            & (catalog["product"] == product.upper())
        ].copy()
        rows = rows[~rows["symbol"].str.contains("_DOMINANT|_INDEX", regex=True)]
        rows = rows[rows["symbol"].str.contains(r"\d", regex=True)]

        start = pd.Timestamp(start_date) if start_date is not None else None
        end = pd.Timestamp(end_date) if end_date is not None else None
        if start is not None:
            for column in ("expiration_date", "de_listed_date", "delisted_date"):
                if column in rows.columns:
                    expiry = pd.to_datetime(rows[column], errors="coerce")
                    rows = rows[expiry.isna() | (expiry >= start)]
                    break
        if end is not None:
            for column in ("listed_date", "listing_date"):
                if column in rows.columns:
                    listed = pd.to_datetime(rows[column], errors="coerce")
                    rows = rows[listed.isna() | (listed <= end)]
                    break

        symbols = sorted(rows["symbol"].dropna().astype(str).str.upper().unique())
        if not symbols:
            raise ValueError(f"Pandadata 合约目录中没有 {product}_INDEX 可用的真实合约")
        return symbols

    def _compose_index(self, frame: pd.DataFrame, index_symbol: str) -> pd.DataFrame:
        bars = self._normalise_bars(frame)
        if bars.empty:
            return bars
        if "open_interest" not in bars.columns:
            raise ValueError("合成期货指数需要 Pandadata 返回 open_interest 列")

        bars["open_interest"] = pd.to_numeric(bars["open_interest"], errors="coerce")
        bars = bars.sort_values(["symbol", "datetime"]).reset_index(drop=True)
        if self.index_weight_lag:
            bars["_index_weight"] = bars.groupby("symbol")["open_interest"].shift(1)
        else:
            bars["_index_weight"] = bars["open_interest"]
        bars = bars[bars["_index_weight"].gt(0)].copy()
        if bars.empty:
            raise ValueError(f"{index_symbol} 没有可用于加权的正持仓量行情")

        records: list[dict[str, Any]] = []
        for timestamp, group in bars.groupby("datetime", sort=True):
            record: dict[str, Any] = {"datetime": timestamp, "symbol": index_symbol}
            weights = pd.to_numeric(group["_index_weight"], errors="coerce")
            for column in self._INDEX_PRICE_COLUMNS:
                if column not in group.columns:
                    continue
                values = pd.to_numeric(group[column], errors="coerce")
                valid = values.notna() & weights.gt(0)
                if valid.any():
                    record[column] = (values[valid] * weights[valid]).sum() / weights[valid].sum()
            for column in self._INDEX_SUM_COLUMNS:
                if column in group.columns:
                    record[column] = pd.to_numeric(group[column], errors="coerce").sum(min_count=1)
            records.append(record)
        return pd.DataFrame.from_records(records).sort_values("datetime").reset_index(drop=True)

    @staticmethod
    def _contract_month(symbol: str) -> str | None:
        match = re.search(r"(\d{3,4})$", str(symbol).upper())
        return match.group(1) if match else None

    @staticmethod
    def _chunked(items: list[str], size: int) -> list[list[str]]:
        return [items[index : index + size] for index in range(0, len(items), size)]

    @staticmethod
    def _describe_contract_batch(batch: list[str]) -> str:
        if not batch:
            return ""
        if len(batch) <= 6:
            return ", ".join(batch)
        head = ", ".join(batch[:4])
        tail = ", ".join(batch[-2:])
        return f"{head}, ..., {tail}"

    def _curve_snapshot_from_bars(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        bars = self._normalise_bars(frame)
        if bars.empty or "symbol" not in bars.columns:
            return []

        value_column = "settlement" if "settlement" in bars.columns else "close"
        if value_column not in bars.columns:
            return []

        latest_date = bars["datetime"].max()
        snapshot = bars[bars["datetime"] == latest_date].copy()
        records: list[dict[str, Any]] = []
        for _, row in snapshot.iterrows():
            symbol = str(row.get("symbol", ""))
            contract_month = self._contract_month(symbol)
            value = pd.to_numeric(pd.Series([row.get(value_column)]), errors="coerce").iloc[0]
            if contract_month is None or pd.isna(value):
                continue
            record: dict[str, Any] = {
                "symbol": symbol,
                "contract_month": contract_month,
                "settlement": float(value),
                "datetime": pd.Timestamp(latest_date).strftime("%Y-%m-%d"),
            }
            if "open_interest" in row and pd.notna(row["open_interest"]):
                record["open_interest"] = float(row["open_interest"])
            records.append(record)

        return sorted(records, key=lambda item: item["contract_month"])

    @staticmethod
    def _attach_curve_snapshot(frame: pd.DataFrame, snapshot: list[dict[str, Any]]) -> pd.DataFrame:
        if frame.empty or not snapshot:
            return frame
        result = frame.copy()
        result["curve_snapshot"] = None
        result.at[result.index[-1], "curve_snapshot"] = snapshot
        return result

    def _get_index_bars(
        self,
        symbol: str,
        symbol_info: dict[str, Any],
        start_date: datetime | None,
        end_date: datetime | None,
        frequency: str,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        start = self._format_date(start_date, "start_date")
        end = self._format_date(end_date, "end_date")
        contracts = self._index_contracts(str(symbol_info["product"]), start_date, end_date, progress=progress)
        client = self._client()
        batches = self._chunked(contracts, self._INDEX_BATCH_SIZE)
        self._emit_progress(progress, f"正在向 PandaData 拉取 {symbol} 对应的 {len(contracts)} 个合约行情")
        frames: list[pd.DataFrame] = []
        api_frequency = self.minute_frequency if frequency in {"m", "min", "minute"} else frequency
        for index, batch in enumerate(batches, start=1):
            batch_label = self._describe_contract_batch(batch)
            self._emit_progress(
                progress,
                f"正在拉取 {symbol} 合约批次 {index}/{len(batches)}（{len(batch)} 个）：{batch_label}",
            )
            fetch_start = time.perf_counter()
            if frequency in {"d", "1d", "day", "daily"}:
                frame = client.get_future_daily(symbol=batch, start_date=start, end_date=end)
            else:
                frame = client.get_future_min(
                    symbol=batch,
                    start_date=start,
                    end_date=end,
                    frequency=api_frequency,
                )
            self._emit_progress(
                progress,
                f"{symbol} 批次 {index}/{len(batches)} 完成（{time.perf_counter() - fetch_start:.2f}s）",
            )
            if frame is not None and not frame.empty:
                frames.append(frame)
        if frames:
            frame = pd.concat(frames, ignore_index=True, sort=False)
        else:
            frame = pd.DataFrame()
        self._emit_progress(progress, f"{symbol} 合约行情拉取完成，共 {len(contracts)} 个合约")
        index_bars = self._compose_index(frame, symbol)
        if frequency in {"d", "1d", "day", "daily"}:
            index_bars = self._attach_curve_snapshot(index_bars, self._curve_snapshot_from_bars(frame))
        return index_bars

    def _augment_fundamentals(
        self,
        frame: pd.DataFrame,
        symbol: str,
        symbol_info: dict[str, Any],
        start_date: datetime | None,
        end_date: datetime | None,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        if self._fundamental_source is None or frame.empty:
            return frame
        product = str(symbol_info.get("product") or self._product_from_symbol(symbol))
        self._emit_progress(progress, f"正在补充 {product} 的库存、现货和供需字段")
        return self._fundamental_source.enrich_frame(
            frame,
            product,
            start_date,
            end_date,
            progress=progress,
        )

    def get_bars(
        self,
        symbol: str,
        symbol_info: dict[str, Any],
        start_date: datetime | None,
        end_date: datetime | None,
        frequency: str,
        progress: Progress | None = None,
    ) -> pd.DataFrame:
        start = self._format_date(start_date, "start_date")
        end = self._format_date(end_date, "end_date")
        client = self._client()
        security_type = str(symbol_info.get("security_type", "futures")).lower()
        frequency = str(frequency).lower()
        if symbol_info.get("derived_type") == "index":
            self._emit_progress(progress, f"正在构造指数 {symbol} 的合约加权行情")
            bars = self._get_index_bars(symbol, symbol_info, start_date, end_date, frequency, progress=progress)
            self._emit_progress(progress, f"正在补充 {symbol} 的基本面字段")
            return self._augment_fundamentals(bars, symbol, symbol_info, start_date, end_date, progress=progress)

        if security_type in {"option", "options"}:
            if frequency not in {"d", "1d", "day", "daily"}:
                raise ValueError("panda-data 0.0.9 暂未提供期权分钟行情接口")
            self._emit_progress(progress, f"正在拉取期权日线：{symbol}")
            fetch_start = time.perf_counter()
            frame = client.get_option_daily(symbol=symbol, start_date=start, end_date=end)
            self._emit_progress(progress, f"期权日线拉取完成：{symbol}（{time.perf_counter() - fetch_start:.2f}s）")
        elif frequency in {"d", "1d", "day", "daily"}:
            self._emit_progress(progress, f"正在拉取期货日线：{symbol}")
            fetch_start = time.perf_counter()
            frame = client.get_future_daily(symbol=symbol, start_date=start, end_date=end)
            self._emit_progress(progress, f"期货日线拉取完成：{symbol}（{time.perf_counter() - fetch_start:.2f}s）")
        else:
            api_frequency = self.minute_frequency if frequency in {"m", "min", "minute"} else frequency
            self._emit_progress(progress, f"正在拉取期货分钟线：{symbol}，频率={api_frequency}")
            fetch_start = time.perf_counter()
            frame = client.get_future_min(
                symbol=symbol,
                start_date=start,
                end_date=end,
                frequency=api_frequency,
            )
            self._emit_progress(progress, f"期货分钟线拉取完成：{symbol}（{time.perf_counter() - fetch_start:.2f}s）")
        bars = self._normalise_bars(frame, symbol)
        self._emit_progress(progress, f"正在补充 {symbol} 的基本面字段")
        return self._augment_fundamentals(bars, symbol, symbol_info, start_date, end_date, progress=progress)


def create_provider(setting: dict[str, Any], base_dir: str | Path | None = None) -> MarketDataProvider:
    config = setting.get("data_source") or {}
    provider_type = str(config.get("type", "csv")).lower()
    if provider_type in {"pandadata", "panda_data"}:
        return PandadataMarketDataProvider(
            auto_login=bool(config.get("auto_login", False)),
            username_env=config.get("username_env", "DEFAULT_USERNAME"),
            password_env=config.get("password_env", "DEFAULT_PASSWORD"),
            base_url_env=config.get("base_url_env"),
            minute_frequency=config.get("minute_frequency", "1m"),
            index_weight_lag=int(config.get("index_weight_lag", 0)),
            fundamental_source=config.get("fundamental_source"),
            base_dir=base_dir,
        )
    if provider_type != "csv":
        raise ValueError(f"暂不支持数据提供器类型: {provider_type}")

    raw_path = config.get("path")
    if not raw_path:
        raise ValueError("配置缺少 data_source.path")
    path = Path(raw_path)
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return CsvMarketDataProvider(
        path,
        symbol_column=config.get("symbol_column", "symbol"),
        datetime_column=config.get("datetime_column", "datetime"),
        security_type=config.get("security_type", "futures"),
        contract_size=config.get("contract_size"),
    )
