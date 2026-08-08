from datetime import datetime
import re
import os
from typing import List, Dict
import pandas as pd
import traceback
import sys
from pathlib import Path
from ..api.provider import MarketDataProvider
from ..util.util import get_symbols_by_daterange
from ..outer import MACDSTATE, RSISTATE, TANAME, workspace_dir, OUTPATH, logger


def filter_handler(setting: Dict, data_provider: MarketDataProvider):
    for handler in setting.get('filter_handlers', []):
        # 根据字符串找到本文件对应的函数
        handler_func = getattr(sys.modules[__name__], handler.get('name'))
        if handler_func:
            handler_func(handler, data_provider)


def get_ouput_path(output_path) -> str:
    if not output_path:
        current_day = datetime.now().strftime('%Y%m%d')
        output_path = str(workspace_dir/OUTPATH/current_day)
    if output_path != '.':
        os.makedirs(output_path, exist_ok=True)
    return output_path

def filter_by_macd_and_rsi(setting: Dict, data_provider: MarketDataProvider):
    """
    筛选macd状态和rsi状态满足条件的数据
    """
    try:
        # 从src_path获取文件
        src_path = setting.get('src_path')
        if not src_path:
            return
        output_path = get_ouput_path(setting.get('output_path'))
        # 解析要收集的品种
        symbols = setting.get('symbols')
        if isinstance(symbols, list):
            # 品种列表
            input_symbols = symbols
        else:
            # 单个品种
            input_symbols = [symbols]
        # 要提取的最后天数
        days = setting.get('extract_days', -1)
        to_collect_symbols = get_symbols_by_daterange(
            input_symbols, provider=data_provider
        )
        df_list: List[pd.DataFrame] = []
        for file in os.listdir(src_path):
            p = Path(file)
            symbol_name = p.stem
            if symbol_name in to_collect_symbols:
                df = pd.read_csv(os.path.join(src_path, file))
                # 提取最近N天的数据
                df['datetime'] = pd.to_datetime(df['datetime'])
                df_sorted = df.sort_values('datetime').reset_index(drop=True)
                if days == -1:
                    df_list.append(df_sorted)
                else:
                    df_recent_N = df_sorted.tail(days)
                    df_list.append(df_recent_N)
        if not df_list:
            logger.warning("没有找到符合筛选范围的结果文件")
            return
        combined_df = pd.concat(df_list, ignore_index=True)
        f_name = f'{filter_by_macd_and_rsi.__name__}_{days}days.csv'
        if days == -1:
            f_name = 'filter_by_macd_and_rsi.csv'
        target_file = os.path.join(output_path, f_name)
        combined_df.to_csv(target_file, index=False)


        # 要过滤的状态
        macd_filter_states = [MACDSTATE.GOLDEN_CROSS, MACDSTATE.DEAD_CROSS]  # MACD 需要筛选的状态
        rsi_normal_state = RSISTATE.DEFAULT  # RSI 正常状态

        # 获取包含{Calculator.NAME_MACD_HIST}_{MACDSTATE.OUTPUT}的列
        # 以及包含{Calculator.NAME_RSI}_{RSISTATE.OUTPUT}的列
        macd_columns = [
            col for col in combined_df.columns 
            if f'{TANAME.MACD_HIST}_{MACDSTATE.OUTPUT}' in col
        ]
        rsi_columns = [
            col for col in combined_df.columns 
            if f'{TANAME.RSI}_{RSISTATE.OUTPUT}' in col
        ]

        if not macd_columns or not rsi_columns:
            logger.warning("Warning: No matching columns found.")
            return
        
        # 筛选出每个symbol日期最早的那一天的数据

        # 筛选出符合条件的symbol
        condition = (
            combined_df[macd_columns].apply(lambda x: any(item in macd_filter_states for item in x), axis=1) |
            combined_df[rsi_columns].apply(lambda x: any(item != rsi_normal_state for item in x), axis=1)
        )
        result_symbols = combined_df[condition]['symbol'].unique().tolist()

        if not result_symbols:
            logger.info("No matching symbols found on the earliest date.")
            return
        
        # 使用这些symbol筛选出combined_df中的所有数据
        result_df = combined_df[combined_df['symbol'].isin(result_symbols)]

        # 写入文件
        output_file = os.path.join(output_path, 'macd_and_rsi.csv')
        result_df.to_csv(output_file, index=False)
        result_df['symbol'] = result_df['symbol'].astype(str)
        result_df.sort_values('symbol', inplace=True)
        # 合并两个dataframe到一个excel中 
        # 定义 Excel 文件路径
        combined_file = os.path.join(output_path, 'current_day_analysis.xlsx')

        # 保存两个 DataFrame 到 Excel 的不同 sheet
        with pd.ExcelWriter(combined_file, engine='xlsxwriter') as writer:
            combined_df.to_excel(writer, sheet_name='全部数据', index=False)
            result_df.to_excel(writer, sheet_name='筛选数据', index=False)

        logger.info(f"Filtered data written to {combined_file}")

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}, {traceback.format_exc()}")


def filter_ratio(setting: Dict, data_provider: MarketDataProvider):
    """
    计算品种成交金额和沉淀资金在板块中的占比。
    计算板块成交金额和沉淀资金在全市场的占比。
    结果保存到sector_ratio.csv
    """
    def calculate_ratio_rank(df: pd.DataFrame):
        df['money_ratio'] = df['money'] / df.groupby('datetime')['money'].transform('sum')
        df['money_rank'] = df.groupby('datetime')['money'].rank(method='first', ascending=False)

        df['open_interest_money_ratio'] = df['open_interest_money'] / df.groupby('datetime')['open_interest_money'].transform('sum')
        df['open_interest_money_rank'] = df.groupby('datetime')['open_interest_money'].rank(method='first', ascending=False)


    src_path = setting.get("src_path")
    if not src_path:
        raise ValueError("filter_ratio 需要 src_path")
    files = [
        path for path in Path(src_path).iterdir()
        if path.is_file() and path.name.lower().endswith((".csv", ".csv.gz"))
    ]
    if not files:
        raise ValueError(f"src_path 中没有 CSV 文件: {src_path}")
    final_df = pd.concat((pd.read_csv(path) for path in files), ignore_index=True)
    required = {"datetime", "symbol", "money", "open_interest_money"}
    missing = required.difference(final_df.columns)
    if missing:
        raise ValueError(f"filter_ratio 输入缺少列: {', '.join(sorted(missing))}")
    calculate_ratio_rank(final_df)
    final_df.sort_values(["datetime", "symbol"], inplace=True)
    output_path = get_ouput_path(setting.get("output_path"))
    final_df.to_csv(os.path.join(output_path, "sector_ratio.csv"), index=False)

