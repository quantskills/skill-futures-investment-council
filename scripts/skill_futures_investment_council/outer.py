"""Standalone shared constants and utilities for market analysis.

This module deliberately contains no imports from the original trading framework or parent repository.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml


PACKAGE_DIR = Path(__file__).resolve().parent
workspace_dir = PACKAGE_DIR
OUTPATH = "data"


class Utils:
    """Small local replacements for the repository utilities used by this tool."""

    @staticmethod
    def read_yaml(path: str | Path) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    @staticmethod
    def write_yaml(path: str | Path, data: dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)


def get_logger() -> logging.Logger:
    logger = logging.getLogger("skill_futures_investment_council")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = get_logger()


SECTOR_MAP = {
    "B_GJS": ["AU", "AG"],
    "B_YSJS": ["CU", "AL", "ZN", "PB", "NI", "SN", "AO"],
    "B_HSJS": ["JM", "J", "I", "RB", "HC", "SM", "SF"],
    "B_MT": ["JM", "J"],
    "B_QG": ["FG", "SP", "LG"],
    "B_SY": ["SC", "FU", "PG", "BU", "LU"],
    "B_HG": ["RU", "L", "V", "TA", "MA", "PP", "EG", "UR", "EB", "NR", "SA", "PF", "BR", "PX", "SH"],
    "B_YZYL": ["Y", "P", "RM"],
    "B_GW": ["A", "C"],
    "B_RSP": ["CF", "SR"],
    "B_NF": ["JD", "LH", "AP", "CJ"],
    "B_HY": ["EC"],
}

EXCLUDE_SYMBOLS = ["ZC", "WR", "BB", "CY", "FB", "JR", "LR", "PM", "RI", "RR", "WH", "GN", "WS", "WT", "RO", "ER", "ME", "TC"]

TRADE_TIME_GROUPS = {
    "group1": [("9:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00"), ("21:00", "2:30")],
    "group2": [("9:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00"), ("21:00", "1:00")],
    "group3": [("9:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00"), ("21:00", "23:00")],
    "group4": [("9:15", "11:30"), ("13:00", "15:15")],
    "group5": [("9:15", "11:30"), ("13:00", "15:00")],
    "group6": [("9:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00")],
}

TRADE_TIME_GROUPS_MAPPPING = {
    "group1": ["AU", "AG", "SC"],
    "group2": ["CU", "PB", "AL", "ZN", "WR", "NI", "SN", "SS", "BC", "AO"],
    "group3": ["RU", "RB", "HC", "SP", "FU", "BU", "NR", "C", "CS", "LU", "PF", "BR", "TA", "JR", "OI", "RO", "PM", "WH", "CF", "SR", "FG", "MA", "RS", "RM", "RI", "ZC", "SA", "PR", "PX", "V", "L", "BB", "I", "FB", "PP", "A", "B", "M", "Y", "P", "JM", "J", "EG", "EB", "PG", "SH"],
    "group4": ["T", "TF", "TS", "TL"],
    "group5": ["IC", "IF", "IH", "IM"],
    "group6": ["EC", "CJ", "PK", "UR", "SI", "SM", "SF", "AP", "LC", "LH", "PS", "LG", "JD"],
}

INDEX_BASE_DATE = "2020-01-02"
INDEX_BASE_VALUE = 1000


class MACDSTATE:
    OUTPUT = "status"
    RED_REDUCE = "Shrinking Red Bar"
    RED = "Red Bar"
    GREEN_REDUCE = "Shrinking Green Bar"
    GREEN = "Green Bar"
    GOLDEN_CROSS = "Golden Cross"
    DEAD_CROSS = "Death Cross"
    DEFAULT = "Normal"


class RSISTATE:
    OUTPUT = "status"
    OVERBUY = "Overbought"
    OVERSELL = "Oversold"
    DEFAULT = "Normal"


class TANAME:
    MACD = "MACD"
    MACD_SIGNAL = "MACD_Signal"
    MACD_HIST = "MACD_Hist"
    RSI = "RSI"
