import pandas as pd
import numpy as np
from typing import Dict, List, Union, Tuple
from pandas import DataFrame
import os
import traceback
from datetime import datetime, timedelta
import functools
import itertools
import re
import bisect
from ..api.provider import MarketDataProvider
from ..outer import logger, workspace_dir, OUTPATH, MACDSTATE, RSISTATE, TANAME
from ..util.util import add_trading_day, find_nearest_rows, find_optimal_boundary_line, get_symbol_group

# plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']  # 指定默认字体
# plt.rcParams['axes.unicode_minus'] = False  # 解决负号 '-' 显示为方块的问题

"""
name是函数名。即calculate_{name}
input表示输入列名称。output只是表示后缀。实际的output为 {input}_{output}。
input可以传正则表达式，来指定列名。
如果参数中存在windows，则output还要加上window值。即 {input}_{output}_{window}。
"""
sample_setting = {
    # key是任务名job_name。也是最终的文件名
    'jobs': {
        'calculate_AG': {
            'symbol': 'AG',
            'md_freq': 'd', # m表示分钟，d表示日线。
            'md_type': 'index', # 或者是main。index表示指数，main表示主连
            'tasks': [
                {
                    'name': 'change_rate',
                    'inputs': 'close',
                    'output': 'change_rate',
                },
                {
                    'name': 'moving_average',
                    'inputs': 'close_change_rate',
                    'output': 'MA',
                    'windows': [5, 10, 22, 126],
                },
                {
                    'name': 'exponential_moving_average',
                    'inputs': 'close_change_rate',
                    'output': 'EMA',
                    'windows': [5, 10, 22, 126],
                }
            ]
        }
    }
}

class ChainCalculator:
    """
    该类做统计计算。
    该类中的函数的特征就是：给定一个dataframe，指定输入列以及处理函数，在dataframe中创建新列存储结果。
    如果计算任务满足这一特征，就可以在类中定义新方法。
    该类参数中的tasks强调了链式处理逻辑。比如指标C依赖于指标B，指标B依赖于指标A。
    tasks中就要定义两个任务：A -> B, B -> C。而且要按序定义。这样才能确保任务开始执行时，输入列已经准备好了。
    """

    def __init__(
        self,
        symbol: str,
        symbol_info: Dict,
        setting: Dict,
        data_provider: MarketDataProvider,
    ):
        self.symbol = symbol
        self.symbol_info = symbol_info
        self.setting = setting
        self.md_freq = setting['md_freq']
        self.save_path = setting['name']
        self.display_name = f'{self.save_path}_{symbol}'
        self.output_path = setting.get('output_path', 'data')
        self.data_provider = data_provider
        self.data: pd.DataFrame = None

    def resolve_input(self, inputs: Union[str, List[str]]) -> List[str]:
        """
        解析输入。如果输入是正则表达式，需要匹配上具体列名。
        """
        if not inputs:
            # 不需要指定输入列，直接返回
            return []

        def is_regex(s: str) -> bool:
            # 检查字符串中是否包含正则表达式的特殊字符
            regex_chars = set('.*+?[](){}^$|\\')
            return any(char in regex_chars for char in s)
    
        if isinstance(inputs, str):
            if not is_regex(inputs):
                # 不是正则表达式
                if inputs not in self.data.columns:
                    logger.error(f"{self.symbol}数据中，列名'{inputs}'不存在.")
                    return []
                return [inputs]
            else:
                # 可能是正则表达式
                try:
                    columns = self.data.filter(regex=inputs).columns.tolist()
                    if not columns:
                        logger.error(f"{self.symbol}数据中，正则表达式 '{inputs}' 没有匹配到任何列名.")
                        return []
                    return columns
                except Exception as e:
                    raise ValueError(f"正则表达式解析失败: {traceback.format_exc()}") from e
        elif isinstance(inputs, list):
            # 处理输入为列表的情况
            result = []
            for item in inputs:
                if isinstance(item, str):
                    if not is_regex(item):
                        if item not in self.data.columns:
                            logger.error(f"{self.symbol}数据中，列名'{item}'不存在.")
                            continue
                        result.append(item)
                    else:
                        try:
                            columns = self.data.filter(regex=item).columns.tolist()
                            if not columns:
                                logger.error(f"{self.symbol}数据中，正则表达式 '{item}' 没有匹配到任何列名.")
                                continue
                            result.extend(columns)
                        except Exception as e:
                            raise ValueError(f"正则表达式解析失败: {traceback.format_exc()}") from e
                else:
                    raise TypeError("列表中的每个元素必须是字符串.")
            return result
        else:
            raise TypeError("输入必须是字符串或字符串列表.")

    def fetch_data(self):
        start_date = self.setting.get('start_date')
        end_date = self.setting.get('end_date')
        if end_date:
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_datetime = datetime.now()
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start_datetime = datetime(year=2000, month=1, day=1)
        return self.data_provider.get_bars(
            self.symbol,
            self.symbol_info,
            start_datetime,
            end_datetime,
            self.md_freq,
        )

    def get_output_path(self):
        output_path = self.output_path
        if not output_path:
            current_day = datetime.now().strftime('%Y%m%d')
            output_path = str(workspace_dir/OUTPATH/current_day)
        if output_path != '.':
            output_path = os.path.join(output_path, self.save_path)
        else:
            output_path = self.save_path
        return output_path

    def to_csv(self):
        output_path = self.get_output_path()
        filename = f'{self.symbol}.csv'
        compression = self.setting.get('compression', True)
        if compression:
            # 默认压缩
            filename = f'{filename}.gz'
        os.makedirs(output_path, exist_ok=True)
        file = os.path.join(output_path, filename)

        if compression:
            self.data.to_csv(file, index=False, encoding='utf-8', compression='gzip')
        else:
            self.data.to_csv(file, index=False, encoding='utf-8')
        logger.info(f'{self.display_name}保存计算结果到{file}')
        return file

    def to_db(self):
        pass

    def output(self):
        if self.output_path == 'DB':
            return self.to_db()
        else:
            return self.to_csv()

    def execute(self) -> str:
        """根据配置文件执行计算任务"""
        self.data = self.fetch_data()
        if self.data is None or self.data.empty:
            logger.info(f'未找到{self.symbol}的数据')
            return None
        self.data['datetime'] = pd.to_datetime(self.data['datetime'])
        for task in self.setting["tasks"]:
            func_name = f'calculate_{task["name"]}'
            # 这里的inputs支持字符串，列表，正则表达式。
            input_cols = task.get("inputs", [])
            output_col = task.get("output", '')
            func = getattr(self, func_name)

            # 如果函数需要额外参数，从配置中获取
            task_params = set(list(task.keys()))
            other_params = task_params - {'name', 'inputs', 'output'}
            kwargs = {}
            for param in other_params:
                kwargs[param] = task[param]
            try:
                func(input_cols, output_col, **kwargs)
            except Exception as e:
                logger.error(traceback.format_exc())
        result = self.output()
        return result

    @staticmethod
    def pre_check(func):
        @functools.wraps(func)
        def inner(self, *args, **kwargs):
            input_cols = self.resolve_input(args[0])
            _, *other_args = args
            new_args = (input_cols, *other_args)
            logger.info(f'{self.display_name}运行{func.__name__}')
            return func(self, *new_args, **kwargs)
        return inner

    # --------------------- 在如下区域中加上计算函数 -----------------------
    @pre_check
    def calculate_change_rate(self, input_cols: List[str], output: str):
        """计算变化率. input_cols是计算用的列名，output是新列的后缀。
        新列的命名规则可以自定义，只要确保使用到该列的后续计算中的input值没有填错
        """
        for input_col in input_cols:
            self.data[f"{input_col}_{output}"] = self.data[input_col].pct_change()

    @pre_check
    def calculate_next_day_trend(self, inputs, output_suffix: str, *, shadow_ratio: float):
        """
        根据前一天最高点、最低点以及收盘价判断第二天日线涨跌.
        price_cols是包含['high', 'low', 'close', 'open']列名的列表，output_suffix是输出新列的后缀。
        看涨：
        当前收盘价高于前一天的high（突破前高） and 当前收盘价高于前一天的close
        看跌：
        当前收盘价低于前一天的low（突破前低） and 当前收盘价低于前一天的close
        下跌：
        当前收盘价在前一天的high和low之间 (未突破前高或前低)
        上影线较长(upper_shadow > kline_length * shadow_ratio)
        当前收盘价低于前一天的close
        上涨：
        当前收盘价在前一天的high和low之间(未突破前高或前低)
        下影线较长 （lower_shadow > kline_length * shadow_ratio）
        当前收盘价高于前一天的close
        """
        # 确保数据按日期排序
        self.data.sort_index(inplace=True)

        # 计算前一日的high和low
        prev_high = self.data['high'].shift(1)
        prev_low = self.data['low'].shift(1)
        prev_close = self.data['close'].shift(1)
        # 当日k线实体长度
        kline_length = abs(self.data['high'] - self.data['low'])

        # 上下影线长度
        upper_shadow = self.data['high'] - np.maximum(self.data['open'], self.data['close'])
        lower_shadow = np.minimum(self.data['open'], self.data['close']) - self.data['low']

        # 判断条件
        conditions = [
            (self.data['close'] > prev_high) & (self.data.index > 0) & (self.data['close'] > prev_close),  # 看涨
            (self.data['close'] < prev_low) & (self.data.index > 0) & (self.data['close'] < prev_close),  # 看跌

        ]
        # 此部分为通过判断影线来推算第二天的涨跌情况
        # (self.data['close'] < prev_high) & (self.data['close'] > prev_low) & (
        #         upper_shadow > kline_length * shadow_ratio) & (self.data.index > 0) & (
        #             self.data['close'] < prev_close),  # 下跌
        # (self.data['close'] > prev_low) & (self.data['close'] < prev_high) & (
        #         lower_shadow > kline_length * shadow_ratio) & (self.data.index > 0) & (
        #             self.data['close'] > prev_close),  # 上涨
        #
        choices = ['UP', 'DOWN']

        # 应用条件选择结果
        self.data[f'next_day_trend'] = np.select(conditions, choices, default='Sideways')

        return self.data


    @pre_check
    def calculate_plot_volume_oi(self, input_cols: List[str], output: str):
        import plotly.graph_objects as go
        """绘制成交金额和持仓量的柱状图（严格按照数据中的日期绘制）
        参数:
            input_cols: 不需要使用的输入列(保留参数)
            output: 输出文件后缀(保留参数)
        """
        try:
            # 导入plotly相关模块
            import plotly.graph_objects as go

            # 创建plot文件夹路径
            plot_dir = os.path.join(self.output_path, 'plot')
            os.makedirs(plot_dir, exist_ok=True)

            # 获取calculate_all文件夹路径
            calculate_all_dir = os.path.join(self.output_path, 'calculate_all')

            # 检查文件夹是否存在
            if not os.path.exists(calculate_all_dir):
                logger.error(f"calculate_all文件夹不存在: {calculate_all_dir}")
                return

            # 读取所有CSV文件
            all_files = [f for f in os.listdir(calculate_all_dir) if f.endswith('.csv') or f.endswith('.csv.gz')]
            if not all_files:
                logger.error(f"calculate_all文件夹中没有CSV文件")
                return

            # 合并所有数据
            dfs = []
            for file in all_files:
                file_path = os.path.join(calculate_all_dir, file)
                try:
                    if file.endswith('.gz'):
                        df = pd.read_csv(file_path, compression='gzip')
                    else:
                        df = pd.read_csv(file_path)
                    dfs.append(df)
                except Exception as e:
                    logger.error(f"读取文件{file}失败: {e}")
                    continue

            if not dfs:
                logger.error("没有成功读取任何CSV文件")
                return

            combined_df = pd.concat(dfs, ignore_index=True)

            # 确保有必要的列
            required_cols = ['symbol', 'datetime', 'money', 'open_interest']
            missing_cols = [col for col in required_cols if col not in combined_df.columns]
            if missing_cols:
                logger.error(f"数据中缺少必要的列: {missing_cols}")
                return

            # 转换datetime为datetime类型
            combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])

            # 按symbol分组
            grouped = combined_df.groupby('symbol')

            # 创建成交金额柱状图（严格按照数据中的日期）
            fig_money = go.Figure()
            for name, group in grouped:
                fig_money.add_trace(go.Bar(
                    x=group['datetime'],
                    y=group['money'],
                    name=name,
                    hovertemplate='%{x|%Y-%m-%d}<br>金额: %{y:.2f}',
                    opacity=0.7
                ))

            fig_money.update_layout(
                title='各品种成交金额走势(柱状图)',
                xaxis_title='日期',
                yaxis_title='成交金额',
                hovermode='x unified',
                legend_title='品种',
                barmode='group',
                bargap=0.15,
                bargroupgap=0.1,
                xaxis=dict(
                    type='category',  # 将x轴设为分类轴，严格按照数据中的日期显示
                    tickangle=45,  # 倾斜45度避免重叠
                    tickformat='%Y-%m-%d'  # 日期格式
                )
            )

            # 保存成交金额图表
            money_plot_path = os.path.join(plot_dir, 'money_plot.html')
            fig_money.write_html(money_plot_path)
            logger.info(f"成交金额柱状图已保存到: {money_plot_path}")

            # 创建持仓量柱状图（严格按照数据中的日期）
            fig_oi = go.Figure()
            for name, group in grouped:
                fig_oi.add_trace(go.Bar(
                    x=group['datetime'],
                    y=group['open_interest'],
                    name=name,
                    hovertemplate='%{x|%Y-%m-%d}<br>持仓量: %{y:.0f}',
                    opacity=0.7
                ))

            fig_oi.update_layout(
                title='各品种持仓量走势(柱状图)',
                xaxis_title='日期',
                yaxis_title='持仓量',
                hovermode='x unified',
                legend_title='品种',
                barmode='group',
                bargap=0.15,
                bargroupgap=0.1,
                xaxis=dict(
                    type='category',  # 将x轴设为分类轴，严格按照数据中的日期显示
                    tickangle=45,  # 倾斜45度避免重叠
                    tickformat='%Y-%m-%d'  # 日期格式
                )
            )

            # 保存持仓量图表
            oi_plot_path = os.path.join(plot_dir, 'oi_plot.html')
            fig_oi.write_html(oi_plot_path)
            logger.info(f"持仓量柱状图已保存到: {oi_plot_path}")

        except ImportError as e:
            logger.error(f"无法导入plotly.graph_objects，请确保已安装plotly库: {e}")
            logger.error("可以使用命令安装: pip install plotly")
        except Exception as e:
            logger.error(f"绘制成交金额和持仓量柱状图时出错: {e}")
            logger.error(traceback.format_exc())

    @pre_check
    def calculate_macd(self, input_cols: List[str], output: str, *, fastperiod=12, slowperiod=26, signalperiod=9):
        """计算MACD状态. input_cols是计算用的列名，output是新列的后缀。
        """
        # 写死output
        output = MACDSTATE.OUTPUT
        def parse_macd_status(macd_hist_col: pd.Series) -> pd.Series:
            """解析MACD柱子状态"""
            prev_hist = macd_hist_col.shift(1)
            curr_hist = macd_hist_col
            
            conditions = [
                (curr_hist > 0) & (prev_hist > 0) & (curr_hist < prev_hist),  # 红柱缩柱
                (curr_hist > 0) & (prev_hist > 0) & (curr_hist >= prev_hist),  # 红柱
                (curr_hist < 0) & (prev_hist < 0) & (curr_hist > prev_hist),  # 绿柱缩柱
                (curr_hist < 0) & (prev_hist < 0) & (curr_hist <= prev_hist),  # 绿柱
                (curr_hist < 0) & (prev_hist > 0),  # 死叉
                (curr_hist > 0) & (prev_hist < 0)  # 金叉
            ]
            choices = [MACDSTATE.RED_REDUCE, MACDSTATE.RED, MACDSTATE.GREEN_REDUCE, MACDSTATE.GREEN, MACDSTATE.DEAD_CROSS, MACDSTATE.GOLDEN_CROSS]
            
            return pd.Series(np.select(conditions, choices, default=RSISTATE.DEFAULT), index=macd_hist_col.index)

        try:
            for input_col in input_cols:
                if input_col not in self.data.columns:
                    raise KeyError(f"列名 {input_col} 不存在于数据中")

                values = pd.to_numeric(self.data[input_col], errors="coerce")
                fast_ema = values.ewm(span=fastperiod, adjust=False, min_periods=fastperiod).mean()
                slow_ema = values.ewm(span=slowperiod, adjust=False, min_periods=slowperiod).mean()
                macd = fast_ema - slow_ema
                macdsignal = macd.ewm(span=signalperiod, adjust=False, min_periods=signalperiod).mean()
                macdhist = macd - macdsignal

                # 将结果添加到DataFrame中
                self.data[f'{input_col}_{TANAME.MACD}'] = np.round(macd, 2)
                self.data[f'{input_col}_{TANAME.MACD_SIGNAL}'] = np.round(macdsignal, 2)
                self.data[f'{input_col}_{TANAME.MACD_HIST}'] = np.round(macdhist, 2)
                
                # 解析MACD柱子状态
                one_input_col = f'{input_col}_{TANAME.MACD_HIST}'
                status_col = parse_macd_status(self.data[one_input_col])
                self.data[f'{one_input_col}_{output}'] = status_col

        except Exception as e:
            raise RuntimeError(f"计算MACD时发生错误: {e}")

    @pre_check
    def calculate_predict_next_day_trend(
            self,
            input_cols: List[str],
            output: str = "macd_vol_TREND",
            *,
            fastperiod: int = 12,
            slowperiod: int = 26,
            signalperiod: int = 9,
            threshold: float = 0.005
    ) -> None:
        """预测每日的次日涨跌状态，输出三分类结果（上涨/下跌/震荡）

        参数：
            input_cols: 用于计算的收盘价列名列表
            output: 预测结果列后缀
            fastperiod: MACD快线周期
            slowperiod: MACD慢线周期
            signalperiod: 信号线周期
            threshold: 价格波动阈值（默认0.5%）

        输出列：
            {input_col}_PRED_TREND: 每日的预测结果（UP/DOWN/SIDEWAYS）
            {input_col}_PROB: 每日的预测置信度（0-1）
        """

        def _calculate_trend_probability(
                close_series: pd.Series,
                macd_hist: pd.Series
        ) -> Tuple[pd.Series, pd.Series]:
            """计算每日趋势概率（核心逻辑）"""
            # 价格动量因子（3日收益率）
            price_change = close_series.pct_change(3)

            # Wilder ATR（14日周期）
            previous_close = close_series.shift(1)
            true_range = pd.concat(
                [
                    self.data["high"] - self.data["low"],
                    (self.data["high"] - previous_close).abs(),
                    (self.data["low"] - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

            # MACD状态因子（标准化处理）
            with np.errstate(divide='ignore', invalid='ignore'):
                macd_strength = macd_hist / atr
                macd_strength.replace([np.inf, -np.inf], np.nan, inplace=True)

            # 多因子合成（60% MACD强度 + 40% 价格动量）
            trend_strength = 0.6 * macd_strength + 0.4 * price_change

            # Sigmoid压缩得到概率
            prob = 1 / (1 + np.exp(-3 * trend_strength))

            # 三分类逻辑
            conditions = [
                trend_strength > threshold,
                trend_strength < -threshold
            ]
            choices = ["UP", "DOWN"]
            trend = np.select(conditions, choices, default="SIDEWAYS")

            return pd.Series(trend, index=close_series.index), pd.Series(prob, index=close_series.index)

        try:
            for input_col in input_cols:
                if input_col not in self.data.columns:
                    raise KeyError(f"列名 {input_col} 不存在于数据中")

                values = pd.to_numeric(self.data[input_col], errors="coerce")
                fast_ema = values.ewm(span=fastperiod, adjust=False, min_periods=fastperiod).mean()
                slow_ema = values.ewm(span=slowperiod, adjust=False, min_periods=slowperiod).mean()
                macd = fast_ema - slow_ema
                signal = macd.ewm(span=signalperiod, adjust=False, min_periods=signalperiod).mean()
                macdhist = macd - signal

                # 预测每日趋势（全历史数据）
                trend, prob = _calculate_trend_probability(
                    close_series=self.data[input_col],
                    macd_hist=macdhist
                )

                # 存储结果
                self.data[f'{input_col}_{output}'] = trend
                self.data[f'{input_col}_PROB'] = prob

        except Exception as e:
            raise RuntimeError(f"每日趋势预测失败: {e}")

    @pre_check
    def calculate_rsi(self, input_cols: List[str], output: str, *, timeperiod=14, overbuy_threshold=70, oversell_threshold=40):
        """计算rsi状态. input_cols是计算用的列名，output是新列的后缀。"""
        # 写死output
        output = RSISTATE.OUTPUT
        for input_col in input_cols:
            logger.info(f"Calculating RSI for column: {input_col}")
            delta = pd.to_numeric(self.data[input_col], errors="coerce").diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            average_gain = gain.ewm(alpha=1 / timeperiod, adjust=False, min_periods=timeperiod).mean()
            average_loss = loss.ewm(alpha=1 / timeperiod, adjust=False, min_periods=timeperiod).mean()
            relative_strength = average_gain / average_loss
            rsi = 100 - (100 / (1 + relative_strength))
            rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100)
            self.data[f'{input_col}_{TANAME.RSI}'] = np.round(rsi, 2)

            output_col = f'{input_col}_{TANAME.RSI}_{output}'
            self.data[output_col] = self.data[f'{input_col}_{TANAME.RSI}'].apply(
                lambda x: RSISTATE.OVERBUY if x > overbuy_threshold else RSISTATE.OVERSELL if x < oversell_threshold else RSISTATE.DEFAULT,
            )

    @pre_check
    def calculate_price_relation(self, input_cols: List[str], output: str, *, comparisons: List[str]):
        """
        计算input_cols中的列的值与comparsions中的列的值相对大小关系。
        """
        for input_col in input_cols:
            for comparison in comparisons:
                # 创建新列名
                new_col_name = f'{input_col}_{output}_{comparison}'
                # 使用 pandas 的向量化操作来比较列
                self.data[new_col_name] = self.data.apply(
                    lambda row: '大于' if row[input_col] < row[comparison] else
                            ('等于' if row[input_col] == row[comparison] else '小于'),
                    axis=1
                )

    @pre_check
    def calculate_moving_average(self, input_cols: List[str], output: str, *, windows: List[int]):
        """计算移动平均，input_cols是计算用的列名，output以及window是会作为新列的后缀"""
        for input_col in input_cols:
            for window in windows:
                self.data[f"{input_col}_{output}_{window}"] = self.data[input_col].rolling(window=window).mean()

    @pre_check
    def calculate_exponential_moving_average(self, input_cols: List[str], output: str, *, windows: List[int]):
        """计算指数移动平均"""
        for input_col in input_cols:
            for window in windows:
                self.data[f"{input_col}_{output}_{window}"] = self.data[input_col].ewm(span=window, adjust=False).mean()
    
    @pre_check
    def calculate_rolling_zscore(self, input_cols: List[str], output: str, *, windows: List[int]):
        """计算滚动zscore"""
        def rolling_zscore(series):
            mean = series.mean()
            std = series.std(ddof=0)  # 使用 ddof=0 来匹配样本标准差
            return (series.iloc[-1] - mean) / std  # 返回最后一个元素的 Z-Score
        
        for input_col in input_cols:
            for window in windows:
                self.data[f"{input_col}_{output}_{window}"] = self.data[input_col].rolling(window=window).apply(rolling_zscore, raw=False)
    
    @pre_check
    def calculate_rolling_percentile(self, input_cols: List[str], output: str, *, windows: List[int], percentiles: List[float]):
        """计算滚动百分位数"""
        def calculate_quantile(series, value):
            # 计算series中所有值的分位数
            sorted_series = series.sort_values()
            position = sorted_series.searchsorted(value, side='left')
            quantile = (position + 1) / (len(sorted_series) + 1)
            return quantile

        for input_col, window in itertools.product(input_cols, windows):
            self.data[f"{input_col}_{output}_{window}"] = self.data[input_col].rolling(window=window, min_periods=1).apply(
                lambda x: calculate_quantile(x, x.iloc[-1]), raw=False)
    
    @pre_check
    def calculate_vwap(self, input_cols: List[str], output: str):
        """计算vwap"""
        # vwap不用区分输入
        contract_size = self.symbol_info.get('contract_size')
        if not contract_size:
            # 没有合约乘数，不计算vwap
            return
        # 获取symbol的合约乘数
        self.data['contract_size'] = contract_size
        self.data[output] = self.data['money'] / (self.data['volume'] * self.data['contract_size'])

    @pre_check
    def calculate_daily_amplitude(self, input_cols: List[str], output: str):
        """计算每日最大振幅"""
        for input_col in input_cols:
            self.data[f"{input_col}_{output}"] = (self.data['high'] - self.data['low']) / self.data[input_col]
    
    @pre_check
    def calculate_volume_change(self, input_cols: List[str], output: str, *, target_ratios: List[float]):
        """
        统计每一天指定百分比的成交量完成时的价格，时长，以及价格变化比率，持仓量的变化量，变化率
        只适用于分钟数据
        """
        # 给分钟线加交易日
        self.data = add_trading_day(self.data)
        df_list: List[pd.DataFrame] = []
        # 按照时间分组
        for label, df_group in self.data.groupby("trading_day"):
            # 先算出累计的成交量
            df_group['volume_cumsum'] = df_group['volume'].cumsum()
            total_volume = df_group['volume_cumsum'].max()
            # 计算成交量比重
            df_group['volume_ratio'] = df_group['volume_cumsum'] / total_volume
            # 提取符合成交量比重的行
            result_idx = find_nearest_rows(df_group, 'volume_ratio', target_ratios)
            result_indices = df_group.index[result_idx]
            df = df_group.loc[result_indices].copy()


            # 计算相邻两行之间的datetime相差的分钟数
            df['minutes_diff'] = df.index.to_series().diff()
            df['close_diff'] = df['close'].diff()
            df['close_diff_cumsum'] = df['close_diff'].cumsum()
            df['close_pct'] = df['close'].pct_change()
            df['open_interest_diff'] = df['open_interest'].diff()
            df['open_interest_pct'] = df['open_interest'].pct_change()
            

            df['minutes_diff'] = df['minutes_diff'].fillna(0)  # 首行时间差设为0
            df['close_diff'] = df['close_diff'].fillna(0)      # 首行价格差设为0
            df['close_pct'] = df['close_pct'].fillna(0)      # 首行变化率设为0%
            df['open_interest_diff'] = df['open_interest_diff'].fillna(0)
            df['open_interest_pct'] = df['open_interest_pct'].fillna(0)


            df_list.append(df)
        self.data = pd.concat(df_list, ignore_index=True)
        self.data.drop(columns=['index'], inplace=True)
    
    @pre_check
    def calculate_binseg(self, input_cols: List[str], output_cols: List[str]):
        import matplotlib.pyplot as plt
        import ruptures as rpt
        from sklearn.metrics import silhouette_score
        # 1. 构建时间序列 V - 假设 df 已经包含按 time_window_index 计算好的 median_volume
        # 不需要再次 groupby，直接排序并提取值
        self.data = add_trading_day(self.data)
        self.data['time'] = self.data['datetime'].dt.time
        df_sorted = self.data.groupby('time')['volume'].median().reset_index()
        V = df_sorted['volume'].values
        print(f"时间序列长度: {len(V)}")

        # 2. 使用 BinSeg 算法检测变点 (关注均值变化 'l2' 损失)
        model = "l2"  # 检测均值变点
        algo = rpt.Binseg(model=model).fit(V)  # 使用 BinSeg 替代 Pelt

        # 3. 选择变点数量 - 方法1：根据惩罚项pen选择 (需要调参)
        # 注意：BinSeg 不支持 pen 参数，所以这里只展示轮廓系数方法

        # 3. 选择变点数量 - 方法2：根据轮廓系数选择K (n_bkps = K-1)
        min_k = 2  # 最少时间段数
        max_k = 10  # 最多时间段数
        results = []

        for n_bkps in range(min_k - 1, max_k):  # n_bkps = 变点数 = K(段数) - 1
            try:
                # 使用 n_bkps 参数预测变点
                bkps = algo.predict(n_bkps=n_bkps)
                
                # 为轮廓系数准备标签：为每个时间窗口分配它所属的时段标签
                labels = np.zeros(len(V))
                start = 0
                for i, bkp in enumerate(bkps[:-1]):  # 最后一个bkps是序列结尾
                    end = bkp
                    labels[start:end] = i
                    start = end
                # 添加最后一段的标签
                labels[start:] = len(bkps) - 1
                
                # 计算轮廓系数 (X是时间窗口索引本身，因为我们关心成交量在时间上的聚集)
                X = np.arange(len(V)).reshape(-1, 1)  # 时间索引作为唯一"特征"
                
                # 确保有多个聚类
                if len(np.unique(labels)) < 2:
                    score = -1  # 无效分数
                else:
                    score = silhouette_score(X, labels, metric='euclidean')
                
                results.append((n_bkps + 1, bkps, score))  # n_bkps+1 = 段数K
                
                print(f"尝试 K={n_bkps+1}, 轮廓系数: {score:.4f}, 变点位置: {bkps}")
            except Exception as e:
                print(f"K={n_bkps+1} 时出错: {str(e)}")
                results.append((n_bkps + 1, [], -1))

        # 找到轮廓系数最大的K
        if results:
            best_result = max(results, key=lambda x: x[2])
            best_K, best_bkps, best_score = best_result
            
            if best_score > 0:  # 确保有有效分割
                print(f"\n最佳时间段数: {best_K}, 轮廓系数: {best_score:.4f}")
                print(f"变点位置(索引): {best_bkps}")
                
                # 4. 可视化 (使用最佳分割结果)
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(V, label='成交量中位数')
                
                # 绘制变点线
                for bkp in best_bkps[:-1]:
                    ax.axvline(x=bkp, color='red', linestyle='--', alpha=0.7)
                
                ax.set_title('日内成交量与检测到的变点')
                ax.set_ylabel('成交量中位数')
                ax.set_xlabel('时间窗口索引')
                ax.legend()
                
                plt.show()
                
                # 5. 根据 best_bkps 划分时间段
                # 生成时间窗口列表（假设5分钟窗口，从09:00开始）
                start_time = datetime.strptime("09:00", "%H:%M")
                time_windows = []
                for i in range(len(V)):
                    time_str = (start_time + datetime.timedelta(minutes=5*i)).strftime("%H:%M")
                    time_windows.append(time_str)
                
                # 划分时间段
                periods = []
                start_idx = 0
                
                # 处理所有变点（不包括最后一个，因为它是序列结束）
                for i, bkp in enumerate(best_bkps[:-1]):
                    end_idx = bkp  # 变点位置是当前段的结束索引
                    start_time_str = time_windows[start_idx]
                    
                    # 当前段的结束时间是变点位置对应的时间
                    # 注意：变点位置对应的时间是下一段的开始
                    end_time_str = time_windows[bkp] if bkp < len(time_windows) else time_windows[-1]
                    
                    periods.append((f"时段 {i+1}", start_time_str, end_time_str))
                    start_idx = bkp  # 下一段从当前变点开始
                
                # 添加最后一段
                start_time_str = time_windows[start_idx]
                # 最后一段的结束时间：最后一个时间窗口结束时间 + 5分钟
                last_window_end = datetime.strptime(time_windows[-1], "%H:%M") + timedelta(minutes=5)
                end_time_str = last_window_end.strftime("%H:%M")
                periods.append((f"时段 {len(periods)+1}", start_time_str, end_time_str))
                
                print("\n定义的时间段:")
                for i, (name, start, end) in enumerate(periods):
                    print(f"{name}: {start} - {end}")
                    
                # 6. 验证 - 计算各时间段统计量
                # 首先为每个时间窗口分配时间段标签
                window_labels = np.zeros(len(V))
                start = 0
                for i, bkp in enumerate(best_bkps[:-1]):
                    end = bkp
                    window_labels[start:end] = i
                    start = end
                window_labels[start:] = len(best_bkps) - 1
                
                # 添加到DataFrame
                df_labeled = df_sorted.copy()
                df_labeled['period_label'] = window_labels
                
                # 计算各时间段统计量
                period_stats = df_labeled.groupby('period_label')['median_volume'].agg(
                    ['mean', 'median', 'std', 'min', 'max', 'count'])
                period_stats['cv'] = period_stats['std'] / period_stats['mean']  # 变异系数
                
                print("\n各时间段统计量:")
                print(period_stats)
                
                # 7. 可选：进行统计检验验证时段间差异
                from scipy import stats
                
                # 准备分组数据
                groups = []
                for label in range(len(periods)):
                    group_data = df_labeled[df_labeled['period_label'] == label]['median_volume'].values
                    groups.append(group_data)
                
                # Kruskal-Wallis检验（非参数ANOVA）
                h_stat, p_value = stats.kruskal(*groups)
                print(f"\n时段间差异显著性检验(p-value): {p_value:.6f}")
                if p_value < 0.05:
                    print("时段间成交量存在显著差异")
                else:
                    print("时段间成交量无显著差异")
                
            else:
                print("未找到有效的分割方案，轮廓系数均小于0")
        else:
            print("没有有效的结果")

    @pre_check
    def calculate_trend_line(self, input_cols: List[str], output: str, *, sample_end: str):
        """
        1、首先基于sample_end计算出当天的趋势线。
        2、根据趋势线，找到突破柱。
        3、计算突破时的累计成交量占当天总成交量的比重。
        """
        # 添加交易日
        self.data = add_trading_day(self.data)
        ret = {
            'trading_day': [],
            'volume': [], # 交易日的成交量
            'slope': [],
            'intercept': [],
            'point1': [],
            'point2': [],
            'break_time': [],
            'break_price': [],
            'break_volume': [],
            'break_cumvolume': [],
            'break_point': [],
            'break_volume_rank': [],
            'max_price_after_break': [],
            'min_price_after_break': [],
            "profit_loss_ratio": [],
            "all_loss": [], # 定义最大收益和最大亏损是否都是负数
            "close_profit": [],
        }
        for trading_day, df in self.data.groupby('trading_day'):
            df = df.reset_index(drop=True)
            df['volume_cumsum'] = df['volume'].cumsum()
            
            td_sample_end = datetime.strptime(f'{trading_day} {sample_end}', '%Y-%m-%d %H:%M')
            df_sample = df[df['datetime'] <= td_sample_end]

            high_points = df_sample['high'].tolist()
            high_points = list(zip(range(len(high_points)), high_points))
            hpointA_idx, hpointB_idx, _, hline_function = find_optimal_boundary_line(high_points, mode='upper')
            xi, yi = high_points[hpointA_idx]
            xj, yj = high_points[hpointB_idx]
            h_slope = (yj - yi) / (xj - xi)
            h_intercept = yi - h_slope * xi

            low_points = df_sample['low'].tolist()
            low_points = list(zip(range(len(low_points)), low_points))
            lpointA_idx, lpointB_idx, _, lline_function = find_optimal_boundary_line(low_points, mode='lower')
            xi, yi = low_points[lpointA_idx]
            xj, yj = low_points[lpointB_idx]
            l_slope = (yj - yi) / (xj - xi)
            l_intercept = yi - l_slope * xi

            ret['trading_day'].append(trading_day)
            ret['volume'].append(df['volume_cumsum'].max())

            # h_slope要求为负数，l_slope要求为正数。但是又不能同时满足
            if h_slope < 0 and l_slope <= 0:
                # 使用hline
                line_function = hline_function
                slope = h_slope
                intercept = h_intercept
                point_a = hpointA_idx
                point_b = hpointB_idx
            elif h_slope >= 0 and l_slope > 0:
                # 使用lline
                line_function = lline_function
                slope = l_slope
                intercept = l_intercept
                point_a = lpointA_idx
                point_b = lpointB_idx
            else:
                ret['slope'].append(None)
                ret['intercept'].append(None)
                ret['point1'].append(None)
                ret['point2'].append(None)
                ret['break_time'].append(None)
                ret['break_price'].append(None)
                ret['break_volume'].append(None)
                ret['break_cumvolume'].append(None)
                ret['break_point'].append(None)
                ret['break_volume_rank'].append(None)
                ret['max_price_after_break'].append(None)
                ret['min_price_after_break'].append(None)
                ret['profit_loss_ratio'].append(None)
                ret['all_loss'].append(None)
                ret['close_profit'].append(None)
                continue
            
            ret['slope'].append(slope)
            ret['intercept'].append(intercept)
            ret['point1'].append(point_a)
            ret['point2'].append(point_b)

            df_out_sample = df[df['datetime'] > td_sample_end]

            volume_list = df_sample['volume'].to_list()
            volume_list.sort()
            
            has_break = False
            for index, row in df_out_sample.iterrows():
                line_value = line_function(index)
                if slope < 0 and line_value < row['close']:
                    # 价格在line_value上方，做多
                    ret['break_point'].append(index)
                    ret['break_cumvolume'].append(row['volume_cumsum'])
                    ret['break_time'].append(row['datetime'])
                    ret['break_price'].append(row['close'])
                    ret['break_volume'].append(row['volume'])
                    rank = bisect.bisect_right(volume_list, row['volume'])
                    ret['break_volume_rank'].append(rank)
                    max_price = df_out_sample.iloc[index + 1:]['close'].max()
                    ret['max_price_after_break'].append(max_price)
                    min_price = df_out_sample.iloc[index + 1:]['close'].min()
                    ret['min_price_after_break'].append(min_price)
                    profit = max_price - row['close']
                    loss = min_price - row['close']
                    profit_ratio = profit / loss if loss != 0 else 0
                    ret['profit_loss_ratio'].append(profit_ratio)
                    if profit < 0 and loss < 0:
                        ret['all_loss'].append(True)
                    else:
                        ret['all_loss'].append(False)

                    last_price = df_out_sample.iloc[-1]['close']
                    close_profit = last_price - row['close']
                    ret['close_profit'].append(close_profit)
                    has_break = True
                    break
                elif slope > 0 and line_value > row['close']:
                    # 价格在line_value下方，做空
                    ret['break_point'].append(index)
                    ret['break_cumvolume'].append(row['volume_cumsum'])
                    ret['break_time'].append(row['datetime'])
                    ret['break_price'].append(row['close'])
                    ret['break_volume'].append(row['volume'])
                    rank = bisect.bisect_right(volume_list, row['volume'])
                    ret['break_volume_rank'].append(rank)
                    max_price = df_out_sample.iloc[index + 1:]['close'].max()
                    ret['max_price_after_break'].append(max_price)
                    min_price = df_out_sample.iloc[index + 1:]['close'].min()
                    ret['min_price_after_break'].append(min_price)
                    profit = row['close'] - min_price
                    loss = row['close'] - max_price
                    profit_ratio = profit / loss if loss != 0 else 0
                    ret['profit_loss_ratio'].append(profit_ratio)
                    if profit < 0 and loss < 0:
                        ret['all_loss'].append(True)
                    else:
                        ret['all_loss'].append(False)
                    last_price = df_out_sample.iloc[-1]['close']
                    close_profit = row['close'] - last_price
                    ret['close_profit'].append(close_profit)
                    has_break = True
                    break
                bisect.insort(volume_list, row['volume'])

            if not has_break:
                ret['break_point'].append(None)
                ret['break_cumvolume'].append(None)
                ret['break_time'].append(None)
                ret['break_price'].append(None)
                ret['break_volume'].append(None)
                ret['break_volume_rank'].append(None)
                ret['max_price_after_break'].append(None)
                ret['min_price_after_break'].append(None)
                ret['profit_loss_ratio'].append(None)
                ret['all_loss'].append(None)
                ret['close_profit'].append(None)
        
        self.data = pd.DataFrame(ret)
        self.data['break_volume_ratio'] = self.data['break_cumvolume'] / self.data['volume']
        self.data['close_profit_cumsum'] = self.data['close_profit'].cumsum()

    @pre_check
    def calculate_segment_statis(self, input_cols: List[str], output: str, *, segments: List[int]):
        from scipy import stats
        self.data = add_trading_day(self.data)

        results = []

        for trading_day, group in self.data.groupby("trading_day"):
            group = group.reset_index(drop=True)
            prices = group['close'].values

            # 遍历区间
            for i in range(len(segments) - 1):
                start, end = segments[i], segments[i + 1]
                if end > len(prices):  # 超出当天长度则跳过
                    continue
                seg_prices = prices[start:end]
                seg_returns = np.diff(np.log(seg_prices))  # log return

                if len(seg_returns) < 2:
                    continue

                # --- 趋势性检验 ---
                X = np.arange(len(seg_prices))
                slope, _, r_value, p_value, _ = stats.linregress(X, seg_prices)

                trend = 1 if (slope > 0 and p_value < 0.05) else (-1 if (slope < 0 and p_value < 0.05) else 0)

                # --- 均值回归检验 ---
                acf1 = np.corrcoef(seg_returns[:-1], seg_returns[1:])[0, 1] if len(seg_returns) > 1 else np.nan
                meanrev = 1 if acf1 < 0 else 0

                results.append({
                    "trading_day": trading_day,
                    "segment": f"{start:03d}_{end:03d}",
                    "trend": trend,       # 1=上升趋势，-1=下降趋势，0=无显著趋势
                    "meanrev": meanrev,   # 1=有均值回归迹象，0=无
                    "slope": slope,
                    "r2": r_value**2,
                    "acf1": acf1
                })

        res_df = pd.DataFrame(results)
        self.data = res_df

        # 汇总统计：每个区间在所有交易日中的趋势/均值回归比例
        summary = res_df.groupby("segment").agg(
            trend_up_ratio = ("trend", lambda x: np.mean(np.array(x) == 1)),
            trend_down_ratio = ("trend", lambda x: np.mean(np.array(x) == -1)),
            meanrev_ratio = ("meanrev", "mean"),
            avg_slope = ("slope", "mean"),
            avg_r2 = ("r2", "mean"),
            avg_acf1 = ("acf1", "mean")
        ).reset_index()

        output_path = self.get_output_path()
        file_name = os.path.join(output_path, f'{self.symbol}_segment_statis_summary.csv')
        summary.to_csv(file_name, index=False)


    @pre_check
    def calculate_daily_reversal(self, input_cols: List[str], output: str, *,
                                 tag_dts: List[str], threshold: float = 0.01):
        """
        统计每天每个品种超过threshold的反转情况。
        注意：反转时间点附带的数字，表示该反转点到下一个反转点所产生的行情最大变化幅度。
        """
        if self.symbol.startswith('B_'):
            return

        # 给分钟线加交易日
        self.data = add_trading_day(self.data)
        
        def find_reversal(df: pd.DataFrame, tag_dt: str, threshold: float):
            # 一个交易日内的行情。出现threshold级别的变化才标记
            open_price = df.iloc[0]['close']
            pre_low = (df.iloc[0]['datetime'], df.iloc[0]['close'])
            pre_high = (df.iloc[0]['datetime'], df.iloc[0]['close'])
            open_to_first_reversal = None # 开盘到反转点的变化率
            open_to_tag_dt = 0 # 开盘到指定时间
            tag_dt_price = None # 标记点的价格
            tag_dt_to_reversal = None # 指定时间到右边最近的反转点的变化率
            reversal_to_tag_dt = None
            last_reversal_to_close = None
            tag_dt_idx = None # tag_dt在reversal_dt中的位置
            reversal_dt: List[Tuple[datetime, float, float]] = [] # 
            for index, row in df.iterrows():
                if row['datetime'].strftime('%H:%M:%S') == tag_dt:
                    open_to_tag_dt = (row['close'] - open_price) / open_price
                    tag_dt_price = row['close']
                # dd = row['datetime'].strftime('%Y-%m-%d %H:%M:%S')
                # if dd > '2024-04-22 09:59:00':
                #     print('hi')
                if pre_low[0] == pre_high[0]:
                    # 初始阶段
                    if row['close'] < pre_low[1]:
                        pre_low = (row['datetime'], row['close'])
                    elif row['close'] > pre_high[1]:
                        pre_high = (row['datetime'], row['close'])
                elif pre_low[0] > pre_high[0]:
                    # ！！！如果最近的是极低点，意味着最新的reversal_dt是反转点-高点。
                    # 和最近的极低点比较
                    if row['close'] < pre_low[1]:
                        pre_low = (row['datetime'], row['close'])
                        if reversal_dt:
                            # last_extreme为反转点-高点。现在价格继续下跌，更新下跌幅度。
                            last_extreme = reversal_dt[-1][1]
                            change_rate = (row['close'] - last_extreme) / last_extreme # 负数change_rate表示下跌
                            reversal_dt[-1] = (reversal_dt[-1][0], reversal_dt[-1][1], change_rate)
                    else:
                        change_rate = (row['close'] - pre_low[1]) / pre_low[1]
                        if change_rate > threshold:
                            # 出现反转点-低点。
                            if not reversal_dt:
                                open_to_first_reversal = (pre_low[1] - open_price) / open_price
                            reversal_dt.append((pre_low[0], pre_low[1], change_rate))
                            pre_high = (row['datetime'], row['close'])
                else:
                    # 和最近的极高点比较
                    if row['close'] > pre_high[1]:
                        pre_high = (row['datetime'], row['close'])
                        if reversal_dt:
                            # last_extreme为反转点-低点。现在价格继续上升，更新上涨幅度。
                            last_extreme = reversal_dt[-1][1]
                            change_rate = (row['close'] - last_extreme) / last_extreme
                            reversal_dt[-1] = (reversal_dt[-1][0], reversal_dt[-1][1], change_rate)
                    else:
                        change_rate = (row['close'] - pre_high[1]) / pre_high[1]
                        if abs(change_rate) > threshold:
                            # 出现反转点-高点。
                            if not reversal_dt:
                                open_to_first_reversal = (pre_high[1] - open_price) / open_price
                            reversal_dt.append((pre_high[0], pre_high[1], change_rate))
                            pre_low = (row['datetime'], row['close'])

            if '00:00:00' < tag_dt < '17:00:00':
                # 如果是白天部分，加上24小时。
                h, m, s = tag_dt.split(':')
                new_h = int(h) + 24
                tag_dt = f'{new_h}:{m}:{s}'
            for idx, item in enumerate(reversal_dt):
                dt, price, *rest = item
                dt_time_str = dt.strftime('%H:%M:%S')
                if '00:00:00' < dt_time_str < '17:00:00':
                    h, m, s = dt_time_str.split(':')
                    new_h = int(h) + 24
                    dt_time_str = f'{new_h}:{m}:{s}'
                if dt_time_str > tag_dt and tag_dt_price:
                    # 节假日没夜盘
                    tag_dt_to_reversal = (price - tag_dt_price) / tag_dt_price
                    tag_dt_idx = idx
                    if idx > 0:
                        previous_reversal = reversal_dt[idx - 1]
                        dt, price, *rest = previous_reversal
                        reversal_to_tag_dt = (tag_dt_price - price) / price
                    break
            close_price = df.iloc[-1]['close']
            open_to_close = (close_price - open_price) / open_price

            if reversal_dt:
                last_reversal = reversal_dt[-1]
                dt, price, *rest = last_reversal
                last_reversal_to_close = (close_price - price) / price
            return (reversal_dt, open_to_first_reversal, open_to_tag_dt, 
                    tag_dt_to_reversal, open_to_close, reversal_to_tag_dt, last_reversal_to_close, tag_dt_idx)
        
        result = {
            'trading_day': [],
            'open_to_tag_dt': [], # 开盘价到标记时间点的变化率
            'open_to_close': [], # 开盘价到收盘价的变化率
            'open_to_first_reversal': [], # 标记开盘价到第一个反转点的变化率，如果没有反转点，则为None
            'reversal_to_tag_dt': [], # 标记时间左边的反转点到标记时间的变化率，如果左边没有反转点，则是None
            'tag_dt_to_reversal': [], # 标记时间到右边最近的反转点的变化率，如果没有则是None
            'last_reversal_to_close': [], # 最后一个反转点到收盘价的变化率。如果没有反转点，为None
            'tag_dt_idx': [], # tag_dt在第几个reversal_dt之前
            'reversal_dt': [],
        }

        match = re.match(r'([a-zA-Z]+)\d+', self.symbol)
        symbol = match.groups()[0]
        symbol_group = get_symbol_group(symbol)
        for tag_dt in tag_dts:
            if '17:00:00' < tag_dt < '23:59:00':
                # 夜盘的时间点
                if symbol_group not in ('group1', 'group2', 'group3'):
                    # 品种没有夜盘
                    continue

            for trading_day, group in self.data.groupby("trading_day"):
                result['trading_day'].append(trading_day)
                reversal_dt, open_to_first_reversal, open_to_tag_dt, tag_dt_to_reversal, open_to_close, reversal_to_tag_dt, last_reversal_to_close, tag_dt_idx = find_reversal(group, tag_dt, threshold)
                reversal_dt = [f"{item[0].strftime('%Y-%m-%d %H:%M:%S')}_{item[2]:.5f}" for item in reversal_dt]
                result['open_to_tag_dt'].append(f'{open_to_tag_dt:.5f}')
                result['open_to_close'].append(f'{open_to_close:.5f}')
                result['open_to_first_reversal'].append(f'{open_to_first_reversal:.5f}' if open_to_first_reversal else open_to_first_reversal)
                result['reversal_to_tag_dt'].append(f'{reversal_to_tag_dt:.5f}' if reversal_to_tag_dt else reversal_to_tag_dt)
                result['tag_dt_to_reversal'].append(f'{tag_dt_to_reversal:.5f}' if tag_dt_to_reversal else tag_dt_to_reversal)
                result['last_reversal_to_close'].append(f'{last_reversal_to_close:.5f}' if last_reversal_to_close else last_reversal_to_close)
                result['reversal_dt'].append(';'.join(reversal_dt))
                result['tag_dt_idx'].append(tag_dt_idx)
            
            df = pd.DataFrame(result)
            output_path = self.get_output_path()
            tag_dt = re.sub(':', '', tag_dt)
            file_name = os.path.join(output_path, f'{self.symbol}_daily_reversal_{tag_dt}.csv')
            df.to_csv(file_name, index=False)

        self.data = None



            







        
