from __future__ import annotations

from skill_futures_investment_council.research import analyze_symbol


def main() -> None:
    report = analyze_symbol("DEMO_INDEX", config_path="settings/smoke.yaml")
    required = [
        "市场概览",
        "市场状态",
        "期货结构",
        "专家观点",
        "置信度",
    ]
    missing = [section for section in required if section not in report]
    if missing:
        raise SystemExit(f"smoke test failed; missing sections: {missing}")
    print("smoke_test_ok")


if __name__ == "__main__":
    main()
