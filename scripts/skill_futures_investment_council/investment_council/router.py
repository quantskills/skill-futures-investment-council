from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROUTER_FILENAME = "expert_router.yaml"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def product_code(symbol: str) -> str:
    prefix = []
    for char in str(symbol).upper():
        if char.isalpha():
            prefix.append(char)
        else:
            break
    code = "".join(prefix)
    return code.removesuffix("_INDEX").removesuffix("_DOMINANT")


def _base_expert_id(stem: str) -> str:
    if stem.endswith("_zh") or stem.endswith("_en"):
        return stem[:-3]
    return stem


def _language_score(language: str | None) -> int:
    value = (language or "").lower()
    if value.startswith("zh"):
        return 3
    if value.startswith("en"):
        return 2
    return 1


def _directory_score(path: Path) -> int:
    parts = {part.lower() for part in path.parts}
    if "references" in parts and "experts" in parts:
        return 2
    if "experts" in parts:
        return 1
    return 0


def _candidate_score(path: Path, meta: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _directory_score(path),
        _language_score(meta.get("language")),
        1 if meta.get("display_name") else 0,
    )


def _parse_expert_meta(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return meta
    if not text.startswith("---"):
        return meta
    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta
    try:
        loaded = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return meta
    if isinstance(loaded, dict):
        meta = loaded
    return meta


@lru_cache(maxsize=4)
def _router_config(root: str) -> dict[str, Any]:
    root_path = Path(root)
    path = root_path / "references" / ROUTER_FILENAME
    if not path.exists():
        path = Path(__file__).resolve().parent / ROUTER_FILENAME
        if not path.exists():
            return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=4)
def _available_experts(root: str) -> dict[str, dict[str, Any]]:
    root_path = Path(root)
    search_dirs = [root_path / "references" / "experts", root_path / "experts"]
    result: dict[str, dict[str, Any]] = {}
    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name.lower() in {"readme.md", "index.md"}:
                continue
            meta = _parse_expert_meta(path)
            expert_id = str(meta.get("id") or _base_expert_id(path.stem))
            display_name = str(meta.get("display_name") or expert_id)
            candidate = {
                "id": expert_id,
                "name": display_name,
                "display_name": display_name,
                "language": meta.get("language"),
                "archetype": meta.get("archetype"),
                "scope": meta.get("scope", "futures"),
                "path": str(path),
                "_score": _candidate_score(path, meta),
            }
            existing = result.get(expert_id)
            if existing is None or candidate["_score"] > existing["_score"]:
                result[expert_id] = candidate
    return result


PRECIOUS_METALS = {"AU", "AG"}
BASE_METALS = {"CU", "AL", "ZN", "NI", "PB", "SN", "BC", "AD", "SI", "LC", "PS"}
ENERGY = {"SC", "BU", "FU", "LU", "NR", "PG"}
AGRICULTURE = {
    "A",
    "B",
    "C",
    "CS",
    "M",
    "Y",
    "P",
    "OI",
    "RM",
    "JD",
    "AP",
    "CF",
    "SR",
    "TA",
    "CJ",
    "PK",
    "CY",
    "RR",
    "WH",
    "L",
    "V",
    "MA",
    "EG",
    "SP",
    "BR",
    "RU",
    "J",
    "JM",
}
BLACK_INDUSTRIALS = {"RB", "HC", "I", "J", "JM", "SM", "SF", "SS", "WR"}
FINANCIAL_FUTURES = {"IF", "IC", "IH", "IM", "T", "TF", "TS", "TL"}


def _market_hint_key(symbol: str) -> str | None:
    code = product_code(symbol)
    if code in PRECIOUS_METALS:
        return "precious_metals"
    if code in BASE_METALS:
        return "base_metals"
    if code in ENERGY:
        return "energy"
    if code in AGRICULTURE:
        return "agriculture"
    if code in BLACK_INDUSTRIALS:
        return "black_industrials"
    if code in FINANCIAL_FUTURES:
        return "financial_futures"
    return None


def _has_feature(features: dict[str, Any], section: str, names: tuple[str, ...]) -> bool:
    payload = features.get(section, {})
    if not isinstance(payload, dict):
        return False
    for name in names:
        value = payload.get(name)
        if isinstance(value, dict) and value.get("available"):
            return True
    return False


def _role_for(name: str, router_groups: dict[str, list[str]], metadata: dict[str, Any]) -> str:
    for role, names in router_groups.items():
        if name in names:
            return role
    archetype = str(metadata.get("archetype") or "").lower()
    if "trend" in archetype:
        return "trend"
    if "macro" in archetype:
        return "macro"
    if "risk" in archetype:
        return "risk"
    if "commodity" in archetype or "supply" in archetype:
        return "commodity"
    return "general"


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _fallback_candidates(router_cfg: dict[str, Any], features: dict[str, Any], symbol: str) -> list[str]:
    groups = router_cfg.get("groups", {}) or {}
    code = product_code(symbol)
    hints = router_cfg.get("market_hints", {}) or {}
    hint_key = _market_hint_key(symbol)

    candidates: list[str] = []
    if hint_key and hint_key in hints:
        candidates.extend(hints[hint_key].get("prefer", []))

    has_trend = _has_feature(features, "trend", ("ma_alignment", "adx", "breakout", "macd"))
    has_physical = _has_feature(features, "fundamental", ("inventory_state", "supply_demand_balance", "spot_price")) or _has_feature(
        features,
        "futures",
        ("basis", "curve_structure"),
    )

    if not candidates:
        candidates.extend(groups.get("trend", []))
        if has_physical or code in BASE_METALS | PRECIOUS_METALS | ENERGY | BLACK_INDUSTRIALS:
            candidates.extend(groups.get("commodity", []))
        else:
            candidates.extend(groups.get("macro", []))
    elif has_trend:
        candidates.extend(groups.get("trend", []))
    if has_physical:
        candidates.extend(groups.get("commodity", []))
    candidates.extend(groups.get("macro", []))
    candidates.extend(groups.get("risk", []))
    return _dedupe(candidates)


def route_experts(
    symbol: str,
    features: dict[str, Any],
    config: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    config = config or {}
    root_path = root or _repo_root()
    router_cfg = _router_config(str(root_path))
    available = _available_experts(str(root_path))

    groups = router_cfg.get("groups", {}) or {}
    defaults = router_cfg.get("defaults", {}) or {}
    min_experts = int(defaults.get("min_experts", 4))
    max_experts = int(defaults.get("max_experts", 7))
    require_risk = bool(defaults.get("require_risk_expert", True))

    candidates = _fallback_candidates(router_cfg, features, symbol)
    if not candidates:
        candidates = list(available)

    if require_risk and groups.get("risk"):
        candidates.extend(groups["risk"][:1])

    selected: list[str] = []
    for name in _dedupe(candidates):
        if name in available:
            selected.append(name)
        if len(selected) >= max_experts:
            break

    if len(selected) < min_experts:
        for pool in (groups.get("trend", []), groups.get("commodity", []), groups.get("macro", []), groups.get("risk", [])):
            for name in pool or []:
                if name in available and name not in selected:
                    selected.append(name)
                if len(selected) >= min_experts:
                    break
            if len(selected) >= min_experts:
                break

    if require_risk and groups.get("risk") and not any(name in groups["risk"] for name in selected):
        for name in groups["risk"]:
            if name in available:
                selected.append(name)
                break

    selected = selected[:max_experts]
    routed = []
    for name in selected:
        metadata = available[name]
        routed.append(
            {
                "id": metadata["id"],
                "name": metadata["display_name"],
                "display_name": metadata["display_name"],
                "role": _role_for(name, groups, metadata),
                "path": metadata["path"],
                "language": metadata.get("language"),
                "archetype": metadata.get("archetype"),
            }
        )
    return routed
