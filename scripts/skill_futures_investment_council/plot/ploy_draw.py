"""Standalone Plotly helpers for generated analysis CSV files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from ..outer import SECTOR_MAP


class Ploty_Market_Analysis:
    """Retain the original public class name while removing vnpy dependencies."""

    def __init__(
        self,
        underlying: str,
        plot_settings: dict,
        start_date: str = "2005-01-04",
        end_date: str = "2025-12-30",
        base_dir: str | Path = "data",
        output_dir: str | Path = "output",
    ) -> None:
        self.underlying = underlying
        self.plot_settings = plot_settings
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.base_dir = Path(base_dir)
        self.base_output_dir = Path(output_dir)
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.sector = next(
            (sector for sector, symbols in SECTOR_MAP.items() if underlying in symbols),
            None,
        )

    def _read_symbol(self, symbol: str) -> pd.DataFrame:
        candidates = [
            self.base_dir / f"{symbol}.csv",
            self.base_dir / f"{symbol}.csv.gz",
            self.base_dir / f"calculate_all_{symbol}.csv",
        ]
        source = next((path for path in candidates if path.exists()), None)
        if source is None:
            return pd.DataFrame()
        frame = pd.read_csv(source)
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        return frame[
            frame["datetime"].between(self.start_date, self.end_date, inclusive="both")
        ].copy()

    def get_combined_sector_all_symbols_data(self) -> pd.DataFrame:
        if self.sector is None:
            raise ValueError(f"{self.underlying} 不属于内置板块")
        combined: pd.DataFrame | None = None
        for symbol in SECTOR_MAP[self.sector]:
            frame = self._read_symbol(symbol)
            if frame.empty or "close" not in frame:
                continue
            values = frame[["datetime", "close"]].rename(columns={"close": f"{symbol}_price"})
            combined = values if combined is None else combined.merge(values, on="datetime", how="outer")
        if combined is None:
            return pd.DataFrame()
        combined.sort_values("datetime", inplace=True)
        price_columns = [column for column in combined if column.endswith("_price")]
        for column in price_columns:
            first_valid = combined[column].dropna()
            if not first_valid.empty and first_valid.iloc[0] != 0:
                combined[column] = combined[column] / first_valid.iloc[0]
        combined.to_csv(self.base_output_dir / f"sector_{self.sector}.csv", index=False)
        return combined

    def plot_draw_sector_symbols(self) -> Path | None:
        frame = self.get_combined_sector_all_symbols_data()
        if frame.empty:
            return None
        figure = go.Figure()
        for column in (name for name in frame if name.endswith("_price")):
            figure.add_trace(go.Scatter(x=frame["datetime"], y=frame[column], mode="lines", name=column))
        figure.update_layout(title=f"{self.sector} - Sector Symbols Price Chart")
        target = self.base_output_dir / f"plot_{self.sector}.html"
        figure.write_html(target, config={"scrollZoom": True}, auto_open=False)
        return target

    def plot_draw(self, underlying: str | None = None) -> Path | None:
        symbol = underlying or self.underlying
        frame = self._read_symbol(symbol)
        if frame.empty:
            return None
        figure = go.Figure()
        if {"open", "high", "low", "close"}.issubset(frame.columns):
            figure.add_trace(
                go.Candlestick(
                    x=frame["datetime"],
                    open=frame["open"],
                    high=frame["high"],
                    low=frame["low"],
                    close=frame["close"],
                    name=symbol,
                )
            )
        else:
            figure.add_trace(go.Scatter(x=frame["datetime"], y=frame["close"], name=symbol))
        for indicator in self.plot_settings.get("indicators", []):
            column = indicator[0] if isinstance(indicator, list) else indicator
            if column in frame.columns:
                figure.add_trace(go.Scatter(x=frame["datetime"], y=frame[column], name=column))
        target = self.base_output_dir / f"plot_{symbol}.html"
        figure.write_html(target, config={"scrollZoom": True}, auto_open=False)
        return target
