from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _latest(series: pd.Series) -> float | None:
    if series.empty:
        return None
    values = series.dropna()
    if values.empty:
        return None
    return _number(values.iloc[-1])


def _state(value: float | None, *, high: float, low: float) -> str:
    if value is None:
        return "unknown"
    if value >= high:
        return "high"
    if value <= low:
        return "low"
    return "normal"


def _require_columns(frame: pd.DataFrame, columns: set[str]) -> list[str]:
    return sorted(columns.difference(frame.columns))


def _latest_object(series: pd.Series) -> Any | None:
    for value in reversed(series.tolist()):
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        return value
    return None


def _prepare_bars(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "datetime" in data.columns:
        data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
        data = data.sort_values("datetime")
    return data.reset_index(drop=True)


def calculate_ma_alignment(
    frame: pd.DataFrame,
    windows: list[int] | None = None,
    price_col: str = "close",
) -> dict[str, Any]:
    windows = windows or [20, 60, 120]
    missing = _require_columns(frame, {price_col})
    if missing:
        return {"state": "unknown", "available": False, "reason": f"missing columns: {missing}"}

    values = pd.to_numeric(frame[price_col], errors="coerce")
    mas = {window: values.rolling(window, min_periods=window).mean() for window in windows}
    latest = {f"ma_{window}": _latest(series) for window, series in mas.items()}
    ordered = [latest[f"ma_{window}"] for window in windows]
    if any(value is None for value in ordered):
        state = "unknown"
    elif all(ordered[index] > ordered[index + 1] for index in range(len(ordered) - 1)):
        state = "bullish"
    elif all(ordered[index] < ordered[index + 1] for index in range(len(ordered) - 1)):
        state = "bearish"
    else:
        state = "mixed"
    return {"state": state, "available": state != "unknown", **latest}


def calculate_macd(
    frame: pd.DataFrame,
    price_col: str = "close",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, Any]:
    missing = _require_columns(frame, {price_col})
    if missing:
        return {"available": False, "state": "unknown", "reason": f"missing columns: {missing}"}
    close = pd.to_numeric(frame[price_col], errors="coerce")
    fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd = fast_ema - slow_ema
    signal_line = macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd - signal_line
    hist_value = _latest(hist)
    previous = _latest(hist.iloc[:-1])
    if hist_value is None:
        state = "unknown"
    elif previous is not None and previous <= 0 < hist_value:
        state = "bullish_cross"
    elif previous is not None and previous >= 0 > hist_value:
        state = "bearish_cross"
    elif hist_value > 0:
        state = "bullish"
    elif hist_value < 0:
        state = "bearish"
    else:
        state = "neutral"
    return {
        "available": state != "unknown",
        "macd": _latest(macd),
        "signal": _latest(signal_line),
        "histogram": hist_value,
        "state": state,
    }


def calculate_adx(frame: pd.DataFrame, window: int = 14) -> dict[str, Any]:
    missing = _require_columns(frame, {"high", "low", "close"})
    if missing:
        return {"available": False, "adx": None, "trend_strength": "unknown", "reason": f"missing columns: {missing}"}

    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    plus_dm = (high.diff()).where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
    minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    value = _latest(adx)
    if value is None:
        strength = "unknown"
    elif value >= 25:
        strength = "strong_trend"
    elif value >= 18:
        strength = "weak_trend"
    else:
        strength = "range"
    return {"available": value is not None, "adx": value, "trend_strength": strength}


def calculate_breakout(frame: pd.DataFrame, windows: list[int] | None = None) -> dict[str, Any]:
    windows = windows or [20, 55]
    missing = _require_columns(frame, {"high", "low", "close"})
    if missing:
        return {"available": False, "reason": f"missing columns: {missing}"}
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    result: dict[str, Any] = {"available": True}
    for window in windows:
        prior_high = high.shift(1).rolling(window, min_periods=window).max()
        prior_low = low.shift(1).rolling(window, min_periods=window).min()
        value = _latest(close)
        upper = _latest(prior_high)
        lower = _latest(prior_low)
        result[f"breakout_{window}"] = bool(value is not None and upper is not None and value > upper)
        result[f"breakdown_{window}"] = bool(value is not None and lower is not None and value < lower)
        result[f"prior_high_{window}"] = upper
        result[f"prior_low_{window}"] = lower
    return result


def calculate_rsi_state(
    frame: pd.DataFrame,
    window: int = 14,
    overbought: float = 70,
    oversold: float = 30,
    price_col: str = "close",
) -> dict[str, Any]:
    missing = _require_columns(frame, {price_col})
    if missing:
        return {"available": False, "rsi": None, "state": "unknown", "reason": f"missing columns: {missing}"}
    close = pd.to_numeric(frame[price_col], errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    value = _latest(rsi)
    if value is None:
        state = "unknown"
    elif value >= overbought:
        state = "overbought"
    elif value >= 55:
        state = "bullish_momentum"
    elif value <= oversold:
        state = "oversold"
    elif value <= 45:
        state = "bearish_momentum"
    else:
        state = "neutral"
    return {"available": value is not None, "rsi": value, "state": state}


def calculate_rate_of_change(frame: pd.DataFrame, windows: list[int] | None = None) -> dict[str, Any]:
    windows = windows or [5, 20, 60]
    missing = _require_columns(frame, {"close"})
    if missing:
        return {"available": False, "reason": f"missing columns: {missing}"}
    close = pd.to_numeric(frame["close"], errors="coerce")
    result: dict[str, Any] = {"available": True}
    for window in windows:
        result[f"roc_{window}"] = _latest(close.pct_change(window))
    return result


def calculate_atr(frame: pd.DataFrame, window: int = 14) -> tuple[pd.Series, dict[str, Any]]:
    missing = _require_columns(frame, {"high", "low", "close"})
    if missing:
        return pd.Series(dtype=float), {"available": False, "atr": None, "atr_percent": None, "reason": f"missing columns: {missing}"}
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    atr_value = _latest(atr)
    close_value = _latest(close)
    atr_percent = atr_value / close_value if atr_value is not None and close_value else None
    return atr, {"available": atr_value is not None, "atr": atr_value, "atr_percent": atr_percent}


def calculate_volatility_regime(
    frame: pd.DataFrame,
    short_window: int = 20,
    long_window: int = 60,
) -> dict[str, Any]:
    missing = _require_columns(frame, {"close"})
    if missing:
        return {"available": False, "state": "unknown", "reason": f"missing columns: {missing}"}
    returns = pd.to_numeric(frame["close"], errors="coerce").pct_change()
    short_vol = returns.rolling(short_window, min_periods=short_window).std()
    long_vol = returns.rolling(long_window, min_periods=long_window).std()
    short_value = _latest(short_vol)
    long_value = _latest(long_vol)
    if short_value is None or long_value in {None, 0}:
        state = "unknown"
    else:
        ratio = short_value / long_value
        if ratio >= 1.2:
            state = "expanding"
        elif ratio <= 0.8:
            state = "contracting"
        else:
            state = "normal"
    return {
        "available": state != "unknown",
        "state": state,
        "short_vol": short_value,
        "long_vol": long_value,
    }


def calculate_open_interest_change(
    frame: pd.DataFrame,
    windows: list[int] | None = None,
) -> dict[str, Any]:
    windows = windows or [1, 5, 20]
    if "open_interest" not in frame.columns:
        return {"available": False, "reason": "open_interest not provided"}
    oi = pd.to_numeric(frame["open_interest"], errors="coerce")
    result: dict[str, Any] = {"available": True}
    for window in windows:
        result[f"oi_change_{window}"] = _latest(oi.pct_change(window))
    return result


def calculate_price_oi_signal(frame: pd.DataFrame) -> dict[str, Any]:
    if "open_interest" not in frame.columns:
        return {"available": False, "state": "unknown", "reason": "open_interest not provided"}
    missing = _require_columns(frame, {"close"})
    if missing:
        return {"available": False, "state": "unknown", "reason": f"missing columns: {missing}"}
    close_change = _latest(pd.to_numeric(frame["close"], errors="coerce").pct_change())
    oi_change = _latest(pd.to_numeric(frame["open_interest"], errors="coerce").pct_change())
    if close_change is None or oi_change is None:
        state = "unknown"
    elif close_change > 0 and oi_change > 0:
        state = "price_up_oi_up"
    elif close_change > 0 and oi_change <= 0:
        state = "price_up_oi_down"
    elif close_change < 0 and oi_change > 0:
        state = "price_down_oi_up"
    elif close_change < 0 and oi_change <= 0:
        state = "price_down_oi_down"
    else:
        state = "flat"
    return {"available": state != "unknown", "state": state, "price_change_1d": close_change, "oi_change_1d": oi_change}


def calculate_basis(frame: pd.DataFrame) -> dict[str, Any]:
    if "spot_price" not in frame.columns:
        return {"available": False, "basis": None, "state": "unknown", "reason": "spot_price not provided"}
    missing = _require_columns(frame, {"close"})
    if missing:
        return {"available": False, "basis": None, "state": "unknown", "reason": f"missing columns: {missing}"}
    spot = _latest(pd.to_numeric(frame["spot_price"], errors="coerce"))
    futures = _latest(pd.to_numeric(frame["close"], errors="coerce"))
    basis = spot - futures if spot is not None and futures is not None else None
    if basis is None:
        state = "unknown"
    elif basis > 0:
        state = "positive_basis"
    elif basis < 0:
        state = "negative_basis"
    else:
        state = "flat_basis"
    return {"available": basis is not None, "basis": basis, "state": state, "convention": "spot_minus_futures"}


def calculate_spot_price(frame: pd.DataFrame) -> dict[str, Any]:
    if "spot_price" not in frame.columns:
        return {"available": False, "spot_price": None, "reason": "spot_price not provided"}
    spot = _latest(pd.to_numeric(frame["spot_price"], errors="coerce"))
    return {"available": spot is not None, "spot_price": spot, "reason": None if spot is not None else "spot_price missing after coercion"}


def calculate_inventory_state(frame: pd.DataFrame) -> dict[str, Any]:
    if "inventory" not in frame.columns:
        return {"available": False, "state": "unknown", "inventory": None, "change": None, "reason": "inventory not provided"}
    inventory = pd.to_numeric(frame["inventory"], errors="coerce")
    values = inventory.dropna()
    current = _latest(inventory)
    previous = _number(values.iloc[-2]) if len(values) >= 2 else None
    if current is None:
        state = "unknown"
        change = None
    else:
        change = current - previous if previous is not None else None
        if change is None:
            state = "unknown"
        elif change > 0:
            state = "increasing"
        elif change < 0:
            state = "decreasing"
        else:
            state = "stable"
    return {
        "available": current is not None,
        "state": state,
        "inventory": current,
        "change": change,
    }


def calculate_supply_demand_balance(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"production", "consumption", "imports", "exports"}
    available = required.intersection(frame.columns)
    if len(available) < len(required):
        missing = sorted(required.difference(frame.columns))
        reason = "supply/demand data not provided"
        if "inventory" in frame.columns:
            reason += f"; inventory available but missing {missing}"
        return {"available": False, "state": "unknown", "reason": reason}
    production = _latest(pd.to_numeric(frame["production"], errors="coerce"))
    consumption = _latest(pd.to_numeric(frame["consumption"], errors="coerce"))
    imports = _latest(pd.to_numeric(frame["imports"], errors="coerce"))
    exports = _latest(pd.to_numeric(frame["exports"], errors="coerce"))
    if any(value is None for value in (production, consumption, imports, exports)):
        return {"available": False, "state": "unknown", "reason": "supply/demand fields contain missing values"}
    net_supply = production + imports - consumption - exports
    if net_supply > 0:
        state = "loose"
    elif net_supply < 0:
        state = "tight"
    else:
        state = "balanced"
    return {
        "available": True,
        "state": state,
        "net_supply": net_supply,
        "production": production,
        "consumption": consumption,
        "imports": imports,
        "exports": exports,
    }


def calculate_curve_structure(frame: pd.DataFrame) -> dict[str, Any]:
    if "curve_snapshot" in frame.columns:
        snapshot_value = _latest_object(frame["curve_snapshot"])
        if snapshot_value is not None:
            if isinstance(snapshot_value, str):
                try:
                    snapshot_value = json.loads(snapshot_value)
                except json.JSONDecodeError:
                    snapshot_value = None
            if isinstance(snapshot_value, pd.DataFrame):
                snapshot = snapshot_value.copy()
            elif isinstance(snapshot_value, list):
                snapshot = pd.DataFrame(snapshot_value)
            else:
                snapshot = pd.DataFrame()
            parsed = _calculate_curve_from_snapshot(snapshot)
            if parsed.get("available"):
                return parsed

    required = {"contract_month", "settlement"}
    missing = _require_columns(frame, required)
    if missing:
        return {"available": False, "state": "unknown", "reason": "curve data not provided"}
    latest_date = frame["datetime"].max() if "datetime" in frame.columns else None
    snapshot = frame[frame["datetime"] == latest_date].copy() if latest_date is not None else frame.copy()
    snapshot = snapshot.sort_values("contract_month")
    settlements = pd.to_numeric(snapshot["settlement"], errors="coerce").dropna()
    if len(settlements) < 2:
        return {"available": False, "state": "unknown", "reason": "less than two curve points"}
    first = float(settlements.iloc[0])
    last = float(settlements.iloc[-1])
    tolerance = first * 0.002
    if last > first + tolerance:
        state = "contango"
    elif last < first - tolerance:
        state = "backwardation"
    else:
        state = "flat"
    return {"available": True, "state": state, "front": first, "back": last}


def _calculate_curve_from_snapshot(snapshot: pd.DataFrame) -> dict[str, Any]:
    if snapshot.empty:
        return {"available": False, "state": "unknown", "reason": "empty curve snapshot"}
    value_column = "settlement" if "settlement" in snapshot.columns else "close"
    missing = _require_columns(snapshot, {"contract_month", value_column})
    if missing:
        return {"available": False, "state": "unknown", "reason": f"curve snapshot missing columns: {missing}"}

    data = snapshot.copy()
    data["contract_month"] = data["contract_month"].astype(str)
    data[value_column] = pd.to_numeric(data[value_column], errors="coerce")
    data = data.dropna(subset=[value_column]).sort_values("contract_month")
    if len(data) < 2:
        return {"available": False, "state": "unknown", "reason": "less than two curve points"}

    front_row = data.iloc[0]
    back_row = data.iloc[-1]
    front = float(front_row[value_column])
    back = float(back_row[value_column])
    tolerance = front * 0.002
    if back > front + tolerance:
        state = "contango"
    elif back < front - tolerance:
        state = "backwardation"
    else:
        state = "flat"
    return {
        "available": True,
        "state": state,
        "front": front,
        "back": back,
        "spread": back - front,
        "contract_count": int(len(data)),
        "front_symbol": str(front_row.get("symbol", "")),
        "back_symbol": str(back_row.get("symbol", "")),
        "snapshot_date": str(back_row.get("datetime", "")),
        "source": "pandadata_curve_snapshot",
    }


def calculate_drawdown(frame: pd.DataFrame, window: int = 252) -> dict[str, Any]:
    missing = _require_columns(frame, {"close"})
    if missing:
        return {"available": False, "current_drawdown": None, "lookback_max_drawdown": None, "reason": f"missing columns: {missing}"}
    close = pd.to_numeric(frame["close"], errors="coerce")
    rolling_peak = close.cummax()
    drawdown = close / rolling_peak - 1
    lookback = drawdown.rolling(window, min_periods=1).min()
    return {
        "available": True,
        "current_drawdown": _latest(drawdown),
        "lookback_max_drawdown": _latest(lookback),
    }


def calculate_feature_set(frame: pd.DataFrame, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    features_config = config.get("features", {})
    data = _prepare_bars(frame)

    trend_items = features_config.get("trend", {}).get("items", {})
    momentum_items = features_config.get("momentum", {}).get("items", {})
    volatility_items = features_config.get("volatility", {}).get("items", {})
    futures_items = features_config.get("futures", {}).get("items", {})
    risk_items = features_config.get("risk", {}).get("items", {})

    ma_cfg = trend_items.get("ma", {})
    adx_cfg = trend_items.get("adx", {})
    breakout_cfg = trend_items.get("breakout", {})
    macd_cfg = trend_items.get("macd", {})
    rsi_cfg = momentum_items.get("rsi", {})
    roc_cfg = momentum_items.get("rate_of_change", {})
    atr_cfg = volatility_items.get("atr", {})
    vol_cfg = volatility_items.get("volatility_regime", {})
    oi_cfg = futures_items.get("open_interest_change", {})
    drawdown_cfg = risk_items.get("drawdown", {})

    atr_series, atr_payload = calculate_atr(data, window=int(atr_cfg.get("window", 14)))
    feature_set: dict[str, Any] = {
        "trend": {
            "ma_alignment": calculate_ma_alignment(data, ma_cfg.get("windows", [20, 60, 120])),
            "macd": calculate_macd(
                data,
                fast=int(macd_cfg.get("fast", 12)),
                slow=int(macd_cfg.get("slow", 26)),
                signal=int(macd_cfg.get("signal", 9)),
            ),
            "adx": calculate_adx(data, window=int(adx_cfg.get("window", 14))),
            "breakout": calculate_breakout(data, breakout_cfg.get("windows", [20, 55])),
        },
        "momentum": {
            "rsi": calculate_rsi_state(
                data,
                window=int(rsi_cfg.get("window", 14)),
                overbought=float(rsi_cfg.get("overbought", 70)),
                oversold=float(rsi_cfg.get("oversold", 30)),
            ),
            "rate_of_change": calculate_rate_of_change(data, roc_cfg.get("windows", [5, 20, 60])),
        },
        "volatility": {
            **atr_payload,
            "atr_regime": _state(atr_payload.get("atr_percent"), high=0.035, low=0.01),
            "regime": calculate_volatility_regime(
                data,
                short_window=int(vol_cfg.get("short_window", 20)),
                long_window=int(vol_cfg.get("long_window", 60)),
            ),
        },
        "futures": {
            "open_interest": calculate_open_interest_change(data, oi_cfg.get("windows", [1, 5, 20])),
            "price_oi_signal": calculate_price_oi_signal(data),
            "basis": calculate_basis(data),
            "curve_structure": calculate_curve_structure(data),
        },
        "fundamental": {
            "spot_price": calculate_spot_price(data),
            "inventory_state": calculate_inventory_state(data),
            "supply_demand_balance": calculate_supply_demand_balance(data),
            "seasonality": {"available": False, "state": "unknown", "reason": "seasonality model not configured"},
        },
        "risk": {
            "drawdown": calculate_drawdown(data, window=int(drawdown_cfg.get("window", 252))),
        },
    }

    missing_optional = []
    for column in ("open_interest", "spot_price", "inventory", "production", "consumption", "imports", "exports"):
        if column not in data.columns:
            missing_optional.append(column)
    fundamental_columns = ("spot_price", "inventory", "production", "consumption", "imports", "exports")
    feature_set["data_quality"] = {
        "bars": int(len(data)),
        "technical": "complete" if not _require_columns(data, {"open", "high", "low", "close", "volume"}) else "partial",
        "open_interest": "complete" if "open_interest" in data.columns else "missing",
        "fundamental": "partial" if any(column in data.columns for column in fundamental_columns) else "missing",
        "missing_optional_fields": missing_optional,
    }
    if "symbol" in data.columns and not data.empty:
        feature_set["symbol"] = str(data["symbol"].dropna().iloc[-1])
    if "datetime" in data.columns and not data.empty:
        value = data["datetime"].dropna().iloc[-1]
        feature_set["as_of"] = pd.Timestamp(value).strftime("%Y-%m-%d")
    if not atr_series.empty:
        feature_set["volatility"]["atr_series_available"] = True
    return feature_set
