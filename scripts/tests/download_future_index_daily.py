"""手工验证并下载期货指数合约日线行情。

运行前请先设置 PANDA_DATA_USERNAME、PANDA_DATA_PASSWORD。
默认测试本地合成的黄金指数 AU_INDEX。
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

import pandas as pd

import panda_data
from panda_data.exceptions import ServiceError

from skill_futures_investment_council.api.provider import PandadataMarketDataProvider

# 如需测试其他指数合约，可修改以下非认证参数。
FUTURE_INDEX_SYMBOL = "AU_INDEX"
START_DATE = "20250101"
END_DATE = "20251231"

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "future_index"


def validate_config() -> tuple[str, str]:
    username = os.getenv("PANDA_DATA_USERNAME", "").strip()
    password = os.getenv("PANDA_DATA_PASSWORD", "").strip()
    missing = [
        name
        for name, value in (("PANDA_DATA_USERNAME", username), ("PANDA_DATA_PASSWORD", password))
        if not value
    ]
    if missing:
        raise ValueError(f"请先设置环境变量: {', '.join(missing)}")

    return username, password


def download_future_index_daily() -> Path:
    """登录、下载指数合约日线并返回保存路径。"""
    username, password = validate_config()

    panda_data.init_token(
        username=username,
        password=password,
    )

    start_date = datetime.strptime(START_DATE, "%Y%m%d")
    end_date = datetime.strptime(END_DATE, "%Y%m%d")
    provider = PandadataMarketDataProvider(sdk=panda_data)
    symbol_info = provider.resolve_symbols(
        [FUTURE_INDEX_SYMBOL], start_date, end_date
    )[FUTURE_INDEX_SYMBOL]
    frame = provider.get_bars(
        FUTURE_INDEX_SYMBOL,
        symbol_info,
        start_date,
        end_date,
        "d",
    )
    if frame.empty:
        raise RuntimeError(
            f"没有足够的真实合约行情用于合成 {FUTURE_INDEX_SYMBOL}。"
            "请确认合约目录、持仓量及所选日期范围。"
        )

    required_columns = {"symbol", "datetime", "open", "high", "low", "close"}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise RuntimeError(f"行情结果缺少字段: {', '.join(sorted(missing_columns))}")

    result = frame.copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="raise")
    result = result.sort_values(["symbol", "datetime"]).reset_index(drop=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_symbol = FUTURE_INDEX_SYMBOL.replace(".", "_")
    output_path = OUTPUT_DIR / f"{safe_symbol}_{START_DATE}_{END_DATE}.csv"
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"下载成功: {FUTURE_INDEX_SYMBOL}")
    print(f"数据行数: {len(result)}")
    print(f"日期范围: {result['datetime'].min().date()} -> {result['datetime'].max().date()}")
    print(f"保存位置: {output_path}")
    print(result.head())
    return output_path


def main() -> None:
    try:
        download_future_index_daily()
    except ServiceError as exc:
        print(f"Panda Data 请求失败: {exc}")
        print(f"错误码: {getattr(exc, 'code', None)}")
        print(f"解决方案: {getattr(exc, 'solution', None)}")
        raise SystemExit(1) from exc
    except (ValueError, RuntimeError) as exc:
        print(f"测试失败: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
