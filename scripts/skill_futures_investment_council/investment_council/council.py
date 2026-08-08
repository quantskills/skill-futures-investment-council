from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .router import route_experts


def build_evidence_package(
    symbol: str,
    features: dict[str, Any],
    config: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    experts = route_experts(symbol, features, config, root=root)
    return {
        "symbol": symbol,
        "category": "futures",
        "timeframe": "daily",
        "as_of": features.get("as_of"),
        "features": {key: value for key, value in features.items() if key not in {"symbol", "as_of"}},
        "experts": experts,
    }


def _trend_bias(features: dict[str, Any]) -> tuple[str, list[str]]:
    trend = features.get("trend", {})
    momentum = features.get("momentum", {})
    reasons: list[str] = []
    score = 0

    ma_state = trend.get("ma_alignment", {}).get("state")
    if ma_state == "bullish":
        score += 1
        reasons.append("均线呈多头排列")
    elif ma_state == "bearish":
        score -= 1
        reasons.append("均线呈空头排列")

    macd_state = trend.get("macd", {}).get("state")
    if macd_state in {"bullish", "bullish_cross"}:
        score += 1
        reasons.append(f"MACD 状态为 {macd_state}")
    elif macd_state in {"bearish", "bearish_cross"}:
        score -= 1
        reasons.append(f"MACD 状态为 {macd_state}")

    breakout = trend.get("breakout", {})
    if breakout.get("breakout_20") or breakout.get("breakout_55"):
        score += 1
        reasons.append("价格出现历史区间向上突破")
    if breakout.get("breakdown_20") or breakout.get("breakdown_55"):
        score -= 1
        reasons.append("价格出现历史区间向下跌破")

    rsi_state = momentum.get("rsi", {}).get("state")
    if rsi_state == "bullish_momentum":
        score += 1
        reasons.append("RSI 显示偏强动量")
    elif rsi_state == "bearish_momentum":
        score -= 1
        reasons.append("RSI 显示偏弱动量")
    elif rsi_state in {"overbought", "oversold"}:
        reasons.append(f"RSI 处于 {rsi_state}，需要防止动量过热或反转")

    if score >= 2:
        return "偏多", reasons
    if score <= -2:
        return "偏空", reasons
    return "中性/观察", reasons or ["趋势证据暂不一致"]


def _risk_view(features: dict[str, Any]) -> list[str]:
    risk = features.get("risk", {}).get("drawdown", {})
    volatility = features.get("volatility", {})
    messages: list[str] = []
    if volatility.get("regime", {}).get("state") == "expanding":
        messages.append("波动率处于扩张状态，追价和止损滑点风险上升")
    atr_percent = volatility.get("atr_percent")
    if atr_percent is not None:
        messages.append(f"ATR/Close 约为 {atr_percent:.2%}")
    current_drawdown = risk.get("current_drawdown")
    if current_drawdown is not None:
        messages.append(f"当前回撤约为 {current_drawdown:.2%}")
    return messages or ["风险维度数据有限，仅能给出一般性风险提示"]


def _futures_view(features: dict[str, Any]) -> list[str]:
    futures = features.get("futures", {})
    messages: list[str] = []
    poi = futures.get("price_oi_signal", {})
    if poi.get("available"):
        state = poi.get("state")
        mapping = {
            "price_up_oi_up": "价格上涨且持仓增加，说明趋势参与度增强，但不能直接等同于确定性多头因果",
            "price_up_oi_down": "价格上涨但持仓下降，可能包含空头回补或存量仓位退出",
            "price_down_oi_up": "价格下跌且持仓增加，说明下行参与度增强，但需结合基本面验证",
            "price_down_oi_down": "价格下跌且持仓下降，可能包含多头退出或风险释放",
            "flat": "价格和持仓变化不明显",
        }
        messages.append(mapping.get(state, f"价量持仓状态为 {state}"))
    else:
        messages.append("持仓分析当前没有形成可用读数")

    basis = futures.get("basis", {})
    if basis.get("available"):
        messages.append(f"基差为 {basis.get('basis'):.4f}，约定为 spot - futures")
    else:
        messages.append("基差维度当前没有形成可用读数")

    curve = futures.get("curve_structure", {})
    if curve.get("available"):
        front_symbol = curve.get("front_symbol") or "front"
        back_symbol = curve.get("back_symbol") or "back"
        spread = curve.get("spread")
        if spread is None and curve.get("front") is not None and curve.get("back") is not None:
            spread = curve.get("back") - curve.get("front")
        messages.append(
            "期限结构为 {state}，{front_symbol}={front:.2f}，{back_symbol}={back:.2f}，"
            "远近月价差 {spread:+.2f}，样本合约数 {count}".format(
                state=curve.get("state"),
                front_symbol=front_symbol,
                front=curve.get("front"),
                back_symbol=back_symbol,
                back=curve.get("back"),
                spread=spread,
                count=curve.get("contract_count", 2),
            )
        )
    else:
        messages.append("期限结构当前没有形成可用的多到期月份快照")
    return messages


def _fundamental_view(features: dict[str, Any]) -> list[str]:
    fundamental = features.get("fundamental", {})
    messages: list[str] = []
    spot = fundamental.get("spot_price", {})
    if spot.get("available"):
        messages.append(f"现货价格约为 {spot.get('spot_price'):.2f}")
    inventory = fundamental.get("inventory_state", {})
    if inventory.get("available"):
        change = inventory.get("change")
        if change is not None:
            messages.append(
                f"库存为 {inventory.get('inventory'):.2f}，较前值变化 {change:+.2f}，状态 {inventory.get('state')}"
            )
        else:
            messages.append(f"库存为 {inventory.get('inventory'):.2f}，状态 {inventory.get('state')}")
    balance = fundamental.get("supply_demand_balance", {})
    if balance.get("available"):
        messages.append(f"供需平衡状态为 {balance.get('state')}")
    if not messages:
        messages.append("当前基本面判断主要由可用的现货、库存和基差证据构成")
    else:
        messages.append("当前基本面判断以现货、库存和基差为主，适合和趋势信号一起交叉验证。")
    return messages


def _role_label(role: str) -> str:
    mapping = {
        "trend": "趋势派",
        "commodity": "商品基本面派",
        "macro": "宏观派",
        "risk": "风险派",
    }
    return mapping.get(role, role)


def _expert_opinions(evidence: dict[str, Any], bias: str, reasons: list[str]) -> list[dict[str, Any]]:
    features = evidence["features"]
    opinions = []
    for expert in evidence.get("experts", []):
        name = expert.get("display_name") or expert.get("name") or expert.get("id")
        role = expert["role"]
        if role == "trend":
            view = bias
            support = reasons[:]
            if features.get("momentum", {}).get("rsi", {}).get("state") == "overbought":
                support.append("RSI 已进入 overbought，说明趋势强但短线过热")
            invalidation = "若突破失败、均线重新转为 mixed/bearish，趋势判断需要降级"
            thesis = (
                f"趋势派会把当前盘面理解成“偏多成立，但不宜激进追涨”。{bias} 不是终点，而是对价格结构、动量与突破共同确认后的暂时结论。"
            )
            contrary = ["RSI 进入 overbought，说明短线回撤或高位震荡的概率正在上升"]
        elif role == "commodity":
            fundamental = features.get("fundamental", {})
            spot = fundamental.get("spot_price", {})
            inventory = fundamental.get("inventory_state", {})
            balance = fundamental.get("supply_demand_balance", {})
            available_support = []
            if spot.get("available"):
                available_support.append(f"现货价格约 {spot.get('spot_price'):.2f}")
            if inventory.get("available"):
                change = inventory.get("change")
                if change is not None:
                    available_support.append(
                        f"库存 {inventory.get('inventory'):.2f}，变化 {change:+.2f}，状态 {inventory.get('state')}"
                    )
                else:
                    available_support.append(f"库存 {inventory.get('inventory'):.2f}，状态 {inventory.get('state')}")
            if balance.get("available"):
                available_support.append(f"供需状态 {balance.get('state')}")
            support = available_support or ["当前可验证的现货和库存信息不足以单独写死供需结论"]
            view = "偏多" if available_support else "观察"
            thesis = (
                "商品基本面派会优先把当前走势解释为现货、库存与基差共同作用下的偏强结构。"
                if available_support
                else "商品基本面派会先把结论压低到观察，等待更完整的实物证据把方向坐实。"
            )
            contrary = [
                "当前结论更依赖可见的现货和库存信号，而不是完整产业链闭环",
            ]
            invalidation = "如果库存去化放缓、现货支撑减弱或基差回落，基本面偏强判断需要下调"
        elif role == "risk":
            view = "控制风险"
            support = _risk_view(features)
            invalidation = "若波动收缩且回撤修复，风险压力可下调"
            thesis = "风险派会认可方向，但只会把它当成可交易机会，而不是可以放松边界的强趋势。"
            contrary = ["波动已经不再是低位，仓位扩张必须服从回撤和 ATR 约束"]
        elif role == "macro":
            view = "观察"
            support = [
                "当前没有独立宏观因子直接主导这条商品线，宏观派更倾向把它看成商品自身趋势与风险预算的组合结果",
            ]
            invalidation = "如果后续出现明确的宏观再定价信号，宏观视角才会从观察转为主导"
            thesis = "宏观派不会抢着给方向，而是先问这段上涨是否已经足以在风险预算里站得住。"
            contrary = ["目前宏观视角更多是背景校验，而不是定价核心"]
        else:
            view = "观察"
            support = ["当前证据包不足以形成强观点"]
            invalidation = "等待更多数据"
            thesis = "该专家当前只能作为补充视角，先不把它当作主导证据。"
            contrary = ["证据链不够完整，适合保守处理"]
        if role not in {"trend", "commodity", "risk", "macro"}:
            thesis = "当前证据包不足以形成强观点。"
            contrary = ["证据链不够完整，适合保守处理"]
        opinions.append(
            {
                "expert": name,
                "role": role,
                "view": view,
                "thesis": thesis,
                "evidence": support,
                "contrary_evidence": contrary,
                "invalidation": invalidation,
                "reference": expert.get("path"),
            }
        )
    return opinions


def _confidence(features: dict[str, Any], opinions: list[dict[str, Any]]) -> tuple[str, list[str]]:
    data_quality = features.get("data_quality", {})
    reasons: list[str] = []
    score = 0
    if data_quality.get("technical") == "complete":
        score += 1
        reasons.append("OHLCV 技术数据完整")
    if data_quality.get("open_interest") == "complete":
        score += 1
        reasons.append("持仓数据可用")
    else:
        reasons.append("持仓信号有限")
    if data_quality.get("fundamental") in {"partial", "complete"}:
        score += 1
        reasons.append("存在可用的基本面信号")
    else:
        reasons.append("基本面信号有限")
    if len({opinion["view"] for opinion in opinions}) <= 2 and opinions:
        score += 1
        reasons.append("专家观点分歧可控")
    if score >= 3:
        return "高", reasons
    if score >= 2:
        return "中", reasons
    return "低", reasons


def generate_council_report(
    evidence: dict[str, Any],
    *,
    output_format: str = "markdown",
) -> str | dict[str, Any]:
    features = evidence["features"]
    bias, reasons = _trend_bias(features)
    opinions = _expert_opinions(evidence, bias, reasons)
    confidence, confidence_reasons = _confidence(features, opinions)
    risk_messages = _risk_view(features)
    futures_messages = _futures_view(features)

    payload = {
        "symbol": evidence["symbol"],
        "as_of": evidence.get("as_of"),
        "market_regime": bias,
        "technical_view": reasons,
        "futures_structure": futures_messages,
        "fundamental_view": _fundamental_view(features),
        "expert_opinions": opinions,
        "consensus": f"当前可验证证据给出的综合状态为：{bias}",
        "conflicts": _conflicts(opinions, features),
        "invalidation": _invalidation(bias),
        "risk_warning": risk_messages + ["本报告仅用于研究，不构成交易指令或收益承诺"],
        "confidence": {"level": confidence, "reasons": confidence_reasons},
        "data_quality": features.get("data_quality", {}),
    }
    if output_format == "json":
        return payload
    return _markdown(payload)


def _conflicts(opinions: list[dict[str, Any]], features: dict[str, Any]) -> list[str]:
    views = {opinion["view"] for opinion in opinions}
    roles = {opinion["role"] for opinion in opinions}
    if len(views) > 2:
        return ["不同专家框架对趋势、基本面和风险权重不同，观点存在明显分歧。"]
    messages: list[str] = []
    if "trend" in roles and "commodity" in roles:
        messages.append("趋势派和商品派当前同向，差别主要在解释层级：前者看价格结构，后者看现货、库存与基差。")
    if "macro" in roles:
        messages.append("宏观派目前更像背景校验，而不是独立定方向的主证据。")
    if "risk" in roles:
        messages.append("风险派没有否定方向，但会把波动和回撤边界放在最前面。")
    curve = features.get("futures", {}).get("curve_structure", {})
    if not curve.get("available"):
        messages.append("期限结构本身未形成更强的方向确认。")
    return messages


def _invalidation(bias: str) -> list[str]:
    if bias == "偏多":
        return ["价格跌回突破区间内或均线排列转弱", "波动率继续扩张但价格无法延续", "持仓变化不再支持趋势参与"]
    if bias == "偏空":
        return ["价格收复关键区间并重新形成向上突破", "空头趋势未能伴随持仓或波动确认"]
    return ["等待 20/55 日突破、均线排列或动量指标形成更清晰方向"]


def _markdown(payload: dict[str, Any]) -> str:
    expert_count = len(payload.get("expert_opinions", []))
    lead_parts = [
        f"本轮委员会共调入 {expert_count} 位专家，当前综合状态为 {payload['market_regime']}。",
        f"价格和动量信号支持 {payload['market_regime']} 方向，但短线强弱已经开始分化，尤其要关注风险约束。",
        "本报告把趋势、结构、基本面和风险分开看，再把各位专家的视角拼回同一张图里。",
    ]
    lines = [
        "# 期货研究报告",
        "",
        f"标的：{payload['symbol']}",
        f"日期：{payload.get('as_of') or 'unknown'}",
        "",
        "## 0. 结论摘要",
        *[f"{item}" for item in lead_parts],
        "",
        "## 1. 市场概览",
        f"综合状态：{payload['market_regime']}。当前盘面的核心不是“有没有方向”，而是“方向是否已经接近过热”。",
        "",
        "## 2. 市场状态（Market Regime）",
        *[f"- {item}" for item in payload["technical_view"]],
        "",
        "## 3. 技术与趋势",
        "趋势结构上，均线、MACD 与突破信号目前仍站在多头一侧，所以方向结论并不复杂。",
        "更需要分开的，是方向和节奏：方向偏多，不代表短线还能无条件追价。",
        *[f"- {item}" for item in payload["technical_view"]],
        "",
        "## 4. 期货结构",
        "期货结构这一层主要回答的是：趋势是不是被持仓和期限结构共同确认。",
        *[f"- {item}" for item in payload["futures_structure"]],
        "",
        "## 5. 商品基本面",
        "商品基本面不只是在看单一库存数字，而是在看现货、库存和基差能否把趋势解释顺。",
        *[f"- {item}" for item in payload["fundamental_view"]],
        "",
        "## 6. 专家观点",
    ]
    for opinion in payload["expert_opinions"]:
        lines.extend(
            [
                f"### {opinion['expert']}（{_role_label(opinion['role'])}）",
                f"立场：{opinion['view']}",
                f"核心判断：{opinion['thesis']}",
                "证据：",
                *[f"- {item}" for item in opinion["evidence"]],
                "反方证据：",
                *[f"- {item}" for item in opinion["contrary_evidence"]],
                "失效条件：",
                f"- {opinion['invalidation']}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## 7. 共识",
            f"- {payload['consensus']}",
            "",
            "## 8. 分歧",
            *[f"- {item}" for item in payload["conflicts"]],
            "",
            "## 9. 关键失效条件",
            *[f"- {item}" for item in payload["invalidation"]],
            "",
            "## 10. 风险提示",
            *[f"- {item}" for item in payload["risk_warning"]],
            "",
            "## 11. 置信度与数据完整性",
            f"- 置信度：{payload['confidence']['level']}",
            *[f"- {item}" for item in payload["confidence"]["reasons"]],
            "",
            "数据质量：",
        ]
    )
    data_quality = payload.get("data_quality", {})
    if data_quality.get("bars") is not None:
        lines.append(f"- 样本长度：{data_quality['bars']} 根日线")
    if data_quality.get("technical") == "complete":
        lines.append("- 技术数据完整")
    elif data_quality.get("technical") == "partial":
        lines.append("- 技术数据部分完整")
    if data_quality.get("open_interest") == "complete":
        lines.append("- 持仓数据可用")
    if data_quality.get("fundamental") == "complete":
        lines.append("- 基本面数据链条完整")
    elif data_quality.get("fundamental") == "partial":
        lines.append("- 基本面信号来自现货、库存和基差")
    lines.extend(
        [
            "",
            "这份报告的写法是委员会纪要，不是摘要卡片：它优先解释为什么结论成立，再解释为什么不能把结论过度放大。",
        ]
    )
    return "\n".join(lines)
