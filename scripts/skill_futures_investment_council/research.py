from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from .api.provider import create_provider
from .features import calculate_feature_set
from .investment_council import build_evidence_package, generate_council_report

Progress = Callable[[str], None]

_SYMBOL_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "AU_INDEX": ("沪金", "黄金", "黄金9999"),
    "AG_INDEX": ("沪银", "白银"),
    "CU_INDEX": ("沪铜", "铜", "上海铜"),
    "AL_INDEX": ("沪铝", "铝"),
    "ZN_INDEX": ("沪锌", "锌"),
    "NI_INDEX": ("沪镍", "镍"),
    "PB_INDEX": ("沪铅", "铅"),
    "SN_INDEX": ("沪锡", "锡"),
    "BC_INDEX": ("国际铜",),
    "AD_INDEX": ("氧化铝",),
    "SI_INDEX": ("工业硅", "硅工业"),
    "PS_INDEX": ("多晶硅", "光伏多晶硅"),
    "LC_INDEX": ("碳酸锂", "锂碳酸"),
    "SC_INDEX": ("原油", "上海原油", "沪油"),
    "BU_INDEX": ("沥青",),
    "FU_INDEX": ("燃料油", "燃油"),
    "LU_INDEX": ("低硫燃料油", "低硫燃油"),
    "RU_INDEX": ("橡胶", "天然橡胶", "沪胶"),
    "NR_INDEX": ("20号胶", "20号橡胶"),
    "PG_INDEX": ("液化石油气", "LPG", "液化气"),
    "A_INDEX": ("豆一", "大豆", "黄大豆1号"),
    "B_INDEX": ("豆二", "黄大豆2号"),
    "C_INDEX": ("玉米", "黄玉米"),
    "CS_INDEX": ("玉米淀粉",),
    "M_INDEX": ("豆粕",),
    "Y_INDEX": ("豆油",),
    "P_INDEX": ("棕榈油", "棕榈"),
    "OI_INDEX": ("菜油", "菜籽油"),
    "RM_INDEX": ("菜粕", "菜籽粕"),
    "JD_INDEX": ("鸡蛋",),
    "AP_INDEX": ("苹果",),
    "CF_INDEX": ("棉花", "郑棉"),
    "SR_INDEX": ("白糖",),
    "TA_INDEX": ("PTA", "精对苯二甲酸"),
    "CJ_INDEX": ("红枣",),
    "PK_INDEX": ("花生",),
    "CY_INDEX": ("棉纱",),
    "RR_INDEX": ("粳米",),
    "WH_INDEX": ("强麦", "强筋小麦"),
    "L_INDEX": ("聚乙烯", "塑料", "PE"),
    "V_INDEX": ("PVC", "聚氯乙烯"),
    "MA_INDEX": ("甲醇", "郑醇"),
    "EG_INDEX": ("乙二醇",),
    "UR_INDEX": ("尿素",),
    "SA_INDEX": ("纯碱",),
    "SP_INDEX": ("纸浆",),
    "EB_INDEX": ("苯乙烯",),
    "SH_INDEX": ("烧碱", "氢氧化钠"),
    "PX_INDEX": ("对二甲苯", "PX"),
    "PF_INDEX": ("短纤", "涤纶短纤"),
    "PR_INDEX": ("瓶片",),
    "LH_INDEX": ("生猪",),
    "FB_INDEX": ("纤维板",),
    "SS_INDEX": ("不锈钢",),
    "RB_INDEX": ("螺纹钢", "螺纹"),
    "HC_INDEX": ("热卷", "热轧卷板"),
    "I_INDEX": ("铁矿石", "铁矿"),
    "J_INDEX": ("焦炭",),
    "JM_INDEX": ("焦煤",),
    "SM_INDEX": ("锰硅", "硅锰"),
    "SF_INDEX": ("硅铁",),
    "WR_INDEX": ("线材",),
    "IF_INDEX": ("沪深300", "沪深300指数"),
    "IC_INDEX": ("中证500", "中证500指数"),
    "IH_INDEX": ("上证50", "上证50指数"),
    "IM_INDEX": ("中证1000", "中证1000指数"),
    "T_INDEX": ("5年国债", "五年国债", "5年期国债"),
    "TF_INDEX": ("10年国债", "十年国债", "10年期国债"),
    "TS_INDEX": ("2年国债", "两年国债", "2年期国债"),
    "TL_INDEX": ("30年国债", "三十年国债", "30年期国债"),
}


def _build_symbol_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    suffix_map = {
        "期货": "",
        "指数": "",
        "主连": "_DOMINANT",
        "连续": "_DOMINANT",
        "主力": "_DOMINANT",
        "主力合约": "_DOMINANT",
    }
    for code, names in _SYMBOL_ALIAS_GROUPS.items():
        dominant_code = code.removesuffix("_INDEX") + "_DOMINANT"
        for name in names:
            variants = {
                name: code,
                f"{name}期货": code,
                f"{name}指数": code,
                f"{name}主连": dominant_code,
                f"{name}连续": dominant_code,
                f"{name}主力": dominant_code,
                f"{name}主力合约": dominant_code,
            }
            for alias, target in variants.items():
                aliases[alias] = target
    return aliases


SYMBOL_ALIASES = _build_symbol_aliases()


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_research_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else repo_root() / "settings.yaml"
    if not config_path.is_absolute():
        config_path = repo_root() / config_path
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config["_config_path"] = str(config_path)
    return config


def _provider_config(config: dict[str, Any]) -> dict[str, Any]:
    if "data_source" in config:
        return config
    data = config.get("data", {})
    provider = data.get("provider", {})
    if provider:
        next_config = dict(config)
        next_config["data_source"] = provider
        return next_config
    return config


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def _normalise_symbol(symbol: str) -> str:
    stripped = symbol.strip()
    for candidate in (stripped, stripped.upper(), stripped.lower()):
        if candidate in SYMBOL_ALIASES:
            return SYMBOL_ALIASES[candidate]
    return stripped


def _progress(enabled: bool) -> Progress:
    def emit(message: str) -> None:
        if enabled:
            print(message, file=sys.stderr)

    return emit


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def default_markdown_output_path(symbol: str, *, end_date: str | None = None) -> Path:
    stamp = end_date or datetime.now().strftime("%Y-%m-%d")
    downloads = Path.home() / "Downloads"
    target_dir = downloads if downloads.exists() else Path.home()
    safe_symbol = re.sub(r'[<>:"/\\|?*]+', "_", symbol.strip()) or "futures_report"
    return target_dir / f"{safe_symbol}_{stamp}.md"


@contextmanager
def _timed_step(emit: Progress, label: str):
    start = time.perf_counter()
    emit(f"{label}（开始）")
    try:
        yield
    finally:
        emit(f"{label}（完成 {_format_elapsed(time.perf_counter() - start)}）")


def _date_range(
    data_cfg: dict[str, Any],
    provider_config: dict[str, Any],
    start_date: str | None,
    end_date: str | None,
) -> tuple[datetime | None, datetime | None]:
    start = _date(start_date or data_cfg.get("start_date"))
    end = _date(end_date or data_cfg.get("end_date"))
    provider_type = str((provider_config.get("data_source") or {}).get("type", "")).lower()
    if provider_type in {"pandadata", "panda_data"}:
        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=int(data_cfg.get("lookback_days", 420)))
    return start, end


def resolve_symbol(
    provider: Any,
    symbol: str,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    progress: Progress | None = None,
) -> tuple[str, dict[str, Any]]:
    symbol = _normalise_symbol(symbol)
    try:
        resolved = provider.resolve_symbols([symbol], start_date=start_date, end_date=end_date, progress=progress)
    except ValueError:
        aliases = [f"{symbol}_INDEX", f"{symbol}_DOMINANT"]
        for alias in aliases:
            try:
                if progress is not None:
                    progress(f"正在尝试别名解析：{alias}")
                resolved = provider.resolve_symbols(
                    [alias],
                    start_date=start_date,
                    end_date=end_date,
                    progress=progress,
                )
                break
            except ValueError:
                continue
        else:
            raise
    key = next(iter(resolved))
    return key, resolved[key]


def analyze_symbol(
    symbol: str,
    *,
    config_path: str | Path | None = None,
    output_format: str = "markdown",
    start_date: str | None = None,
    end_date: str | None = None,
    verbose: bool = True,
) -> str | dict[str, Any]:
    emit = _progress(verbose)
    with _timed_step(emit, "[1/5] 读取研究配置 settings.yaml"):
        config = load_research_config(config_path)
    provider_config = _provider_config(config)
    base_dir = Path(provider_config.get("_config_path", repo_root() / "settings.yaml")).parent
    provider = create_provider(provider_config, base_dir=base_dir)
    data_cfg = config.get("data", {})
    start, end = _date_range(data_cfg, provider_config, start_date, end_date)

    with _timed_step(emit, f"[2/5] 解析标的：{symbol}"):
        resolved_symbol, info = resolve_symbol(
            provider,
            symbol,
            start_date=start,
            end_date=end,
            progress=emit,
        )

    source_type = (provider_config.get("data_source") or {}).get("type", "unknown")
    start_label = start.strftime("%Y-%m-%d") if start else "provider default"
    end_label = end.strftime("%Y-%m-%d") if end else "provider default"
    with _timed_step(
        emit,
        f"[3/5] 拉取行情：source={source_type}, symbol={resolved_symbol}, range={start_label}..{end_label}",
    ):
        bars = provider.get_bars(
            resolved_symbol,
            info,
            start,
            end,
            data_cfg.get("frequency", "d"),
            progress=emit,
        )

    with _timed_step(emit, f"[4/5] 内存计算特征：bars={len(bars)}，不生成中间 CSV"):
        features = calculate_feature_set(bars, config)

    with _timed_step(emit, "[5/5] 路由专家、生成证据包并生成研究报告"):
        evidence = build_evidence_package(resolved_symbol, features, config, root=skill_root())
        report = generate_council_report(evidence, output_format=output_format)
    return report


def compare_symbols(
    symbols: list[str],
    *,
    config_path: str | Path | None = None,
    output_format: str = "markdown",
    verbose: bool = True,
) -> str | dict[str, Any]:
    reports = []
    for symbol in symbols:
        report = analyze_symbol(symbol, config_path=config_path, output_format="json", verbose=verbose)
        reports.append(report)
    if output_format == "json":
        return {"symbols": symbols, "reports": reports}

    lines = ["# 期货比较报告", ""]
    for report in reports:
        lines.extend(
            [
                f"## {report['symbol']}",
                f"- 综合状态：{report['market_regime']}",
                f"- 置信度：{report['confidence']['level']}",
                f"- 共识：{report['consensus']}",
                f"- 主要风险：{'；'.join(report['risk_warning'][:2])}",
                "",
            ]
        )
    return "\n".join(lines)


def screen_symbols(
    symbols: list[str] | None = None,
    *,
    config_path: str | Path | None = None,
    limit: int = 10,
    output_format: str = "markdown",
    verbose: bool = True,
) -> str | dict[str, Any]:
    emit = _progress(verbose)
    with _timed_step(emit, "[1/4] 读取扫描配置 settings.yaml"):
        config = load_research_config(config_path)
    provider_config = _provider_config(config)
    base_dir = Path(provider_config.get("_config_path", repo_root() / "settings.yaml")).parent
    provider = create_provider(provider_config, base_dir=base_dir)
    data_cfg = config.get("data", {})
    start, end = _date_range(data_cfg, provider_config, None, None)
    if symbols:
        with _timed_step(emit, "[2/4] 解析指定期货标的"):
            resolved = dict(
                resolve_symbol(provider, symbol, start_date=start, end_date=end, progress=emit)
                for symbol in symbols
            )
    else:
        with _timed_step(emit, "[2/4] 解析期货扫描 universe"):
            resolved = provider.resolve_symbols(["all.all"], progress=emit)

    rows = []
    with _timed_step(emit, "[3/4] 拉取行情并在内存中计算特征"):
        for symbol, info in resolved.items():
            try:
                bars = provider.get_bars(
                    symbol,
                    info,
                    start,
                    end,
                    data_cfg.get("frequency", "d"),
                    progress=emit,
                )
                features = calculate_feature_set(bars, config)
            except Exception as exc:
                rows.append({"symbol": symbol, "score": -999, "error": str(exc)})
                continue
            trend = features.get("trend", {})
            momentum = features.get("momentum", {})
            score = 0
            if trend.get("ma_alignment", {}).get("state") == "bullish":
                score += 2
            if trend.get("adx", {}).get("trend_strength") == "strong_trend":
                score += 1
            if trend.get("breakout", {}).get("breakout_20"):
                score += 2
            if trend.get("breakout", {}).get("breakout_55"):
                score += 3
            if momentum.get("rsi", {}).get("state") == "bullish_momentum":
                score += 1
            rows.append({"symbol": symbol, "score": score, "features": features})

    rows = sorted(rows, key=lambda row: row["score"], reverse=True)[:limit]
    with _timed_step(emit, "[4/4] 输出扫描摘要"):
        if output_format == "json":
            return {"results": rows}
        lines = ["# 期货趋势扫描", ""]
        for row in rows:
            if "error" in row:
                lines.append(f"- {row['symbol']}: 无法分析（{row['error']}）")
                continue
            features = row["features"]
            lines.append(
                "- {symbol}: score={score}, ma={ma}, adx={adx}, breakout20={breakout}".format(
                    symbol=row["symbol"],
                    score=row["score"],
                    ma=features["trend"]["ma_alignment"]["state"],
                    adx=features["trend"]["adx"]["trend_strength"],
                    breakout=features["trend"]["breakout"].get("breakout_20"),
                )
            )
        return "\n".join(lines)


def write_output(content: str | dict[str, Any], output: str | Path | None) -> Path | None:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
    if not output:
        print(text)
        return None
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
