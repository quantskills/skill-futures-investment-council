import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime
from ..api.provider import MarketDataProvider
from ..outer import TRADE_TIME_GROUPS_MAPPPING


def get_symbols_by_daterange(symbols: List[str]=None,
                             start_date: datetime=None, end_date: datetime=None,
                             provider: MarketDataProvider=None) -> Dict[str, Dict]:
    """
    找到symbols中在日期范围内有效的合约。
    symbols: 列表元素可以包含真实合约、_INDEX 指数、_DOMINANT 主连、品种或板块。
    比如列表中已经有AG，就表明要获取AG下的指数，主连，期货，期权。其余关于AG的元素都会被忽视。
    比如 AU_INDEX 表示黄金品种指数，AU_DOMINANT 表示黄金主连。
    最后，symbols如果为空，就会查找全库的合约。

    start_date和end_date可以都为空，表示没有任何时间范围限制。

    return: List[Dict[合约名，合约属性]]
    """
    if provider is None:
        raise ValueError("必须提供 MarketDataProvider 才能解析标的")
    return provider.resolve_symbols(symbols, start_date, end_date)


def add_trading_day(df: pd.DataFrame) -> pd.DataFrame:
        """
        _vectorized
        完全向量化版本
        """
        # 保存原始索引
        original_index = df.index
        
        # 重置索引
        df_work = df.reset_index()
        
        # 找到日期时间列
        datetime_cols = df_work.select_dtypes(include=["datetime64"]).columns
        if len(datetime_cols) == 0:
            raise ValueError("No datetime column found in the DataFrame")
        datetime_col = datetime_cols[0]
        
        # 确保是datetime类型
        df_work[datetime_col] = pd.to_datetime(df_work[datetime_col])
        
        # 提取时间信息
        times = df_work[datetime_col].dt.time
        dates_dt = df_work[datetime_col].dt.normalize()  # 获取日期部分（datetime格式）
        weekdays = df_work[datetime_col].dt.weekday
        
        # 创建时段掩码
        day_mask = (times >= pd.Timestamp("08:50:00").time()) & (times <= pd.Timestamp("15:30:00").time())
        night_mask = (times >= pd.Timestamp("20:50:00").time()) & (times <= pd.Timestamp("23:59:59").time())
        early_mask = (times >= pd.Timestamp("00:00:00").time()) & (times <= pd.Timestamp("03:00:00").time())
        
        # 初始化trading_day
        trading_day = pd.Series(index=df_work.index, dtype='datetime64[ns]')
        
        # 白天时段：当天日期
        trading_day[day_mask] = dates_dt[day_mask]
        
        # 夜盘时段：下一个工作日
        night_dates = dates_dt[night_mask] + pd.Timedelta(days=1)
        # 向量化处理周末：如果是周六，加2天；如果是周日，加1天
        night_weekdays = night_dates.dt.weekday
        weekend_adjustment = pd.Series(index=night_dates.index, data=0)
        weekend_adjustment[night_weekdays == 5] = 2  # 周六+2天=周一
        weekend_adjustment[night_weekdays == 6] = 1  # 周日+1天=周一
        
        trading_day[night_mask] = night_dates + pd.to_timedelta(weekend_adjustment[night_mask], unit='D')
        
        # 凌晨时段：工作日当天，周末下一个工作日
        early_dates = dates_dt[early_mask]
        early_weekdays = weekdays[early_mask]
        
        # 工作日直接使用当天
        workday_early_mask = early_mask & (weekdays < 5)
        trading_day[workday_early_mask] = dates_dt[workday_early_mask]
        
        # 周末计算下一个工作日
        weekend_early_mask = early_mask & (weekdays >= 5)
        weekend_early_dates = dates_dt[weekend_early_mask]
        weekend_early_weekdays = weekdays[weekend_early_mask]
        
        # 周六+2天=周一，周日+1天=周一
        weekend_adj = pd.Series(index=weekend_early_dates.index, data=0)
        weekend_adj[weekend_early_weekdays == 5] = 2
        weekend_adj[weekend_early_weekdays == 6] = 1
        
        trading_day[weekend_early_mask] = weekend_early_dates + pd.to_timedelta(weekend_adj, unit='D')
        
        # 转换为字符串格式
        df_work["trading_day"] = trading_day.dt.strftime("%Y-%m-%d")
        
        # 恢复原始索引
        #df_result = df_work.set_index(original_index.names)
        
        return df_work

def find_nearest_rows(df: pd.DataFrame, col: str, target_values: List[float]) -> List[int]:
    """
    在df中，找到列col中，最接近target_values的行
    """
    import bisect
    # 提取列并转为数组
    arr = df[col].values
    if len(arr) == 0:
        return []
    results = []
    for target in target_values:
        pos = bisect.bisect_left(arr, target)
        candidates = []
        if pos < len(arr):
            # 添加右边的
            candidates.append((abs(arr[pos] - target), pos))
        if pos > 0:
            # 添加左边的
            candidates.append((abs(arr[pos - 1] - target), pos - 1))
        
        if not candidates:
            best_index = len(arr) - 1
        else:
            candidates.sort(key=lambda x: x[0])
            best_index = candidates[0][1]
        
        results.append(best_index)
    return results

def find_optimal_boundary_line(points, mode='upper'):
    """
    统一函数：寻找最优边界线（上界或下界）
    最优边界线：1、所有点要么在线上，要么在线的上方或下方。2、所有符合的线中，到所有点的垂直距离之和最小的线

    参数:
        points: list of tuples, [(0, y0), (1, y1), ...]
        mode: 'upper' -> 所有点在直线下方
              'lower' -> 所有点在直线上方

    返回:
        (i, j, total_distance, line_function) 或 None
    """
    from scipy.spatial import ConvexHull

    valid_modes = {'upper', 'lower'}
    if mode not in valid_modes:
        raise ValueError(f"mode must be one of {valid_modes}")

    n = len(points)
    if n < 2:
        return None

    x_coords = np.array([p[0] for p in points])
    y_coords = np.array([p[1] for p in points])

    # === 确定方向性逻辑 ===
    if mode == 'upper':
        # 上界线：要求 y <= line，最小化 line - y
        condition_func = lambda y_data, line_vals: np.all(y_data <= line_vals + 1e-10)
        distance_func = lambda y_data, line_vals: line_vals - y_data
        sign = +1
    else:  # mode == 'lower'
        # 下界线：要求 y >= line，最小化 y - line
        condition_func = lambda y_data, line_vals: np.all(y_data >= line_vals - 1e-10)
        distance_func = lambda y_data, line_vals: y_data - line_vals
        sign = -1

    # === 构建凸包，提取候选点 ===
    try:
        hull = ConvexHull(np.column_stack((x_coords, y_coords)))
        hull_indices = hull.vertices
        # 按 x 排序凸包点
        hull_points_sorted = sorted([(x_coords[i], y_coords[i], i) for i in hull_indices], key=lambda x: x[0])
    except:
        # 凸包失败，使用全枚举回退
        return _find_boundary_fallback(points, mode)

    # === 根据 mode 选择候选点：上包络 or 下包络 ===
    candidate_indices = []
    prev_y = sign * float('inf')  # 初始化为极大或极小

    # 简单贪心策略：提取单调方向的包络点（上：y 递增后递减，下：y 递减后递增）
    # 这里简化：直接使用所有凸包点，后续通过 condition 过滤
    candidate_indices = [idx for _, _, idx in hull_points_sorted]

    best_i, best_j = 0, 1
    best_distance = float('inf')
    best_line = None

    # === 枚举候选点对 ===
    for idx_i, i in enumerate(candidate_indices):
        for j in candidate_indices[idx_i + 1:]:
            xi, yi = points[i]
            xj, yj = points[j]

            # 构造直线
            a = (yj - yi) / (xj - xi)
            b = yi - a * xi
            line_ys = a * x_coords + b

            # 检查条件
            if not condition_func(y_coords, line_ys):
                continue

            # 计算距离和
            distances = distance_func(y_coords, line_ys)
            total_distance = np.sum(distances)

            if total_distance < best_distance:
                best_distance = total_distance
                best_i, best_j = i, j
                best_line = lambda x, a=a, b=b: a * x + b

    return best_i, best_j, best_distance, best_line

# === 回退函数（全枚举）===
def _find_boundary_fallback(points, mode):
    """回退版本，用于凸包失败时"""
    n = len(points)
    x_coords = np.array([p[0] for p in points])
    y_coords = np.array([p[1] for p in points])

    if mode == 'upper':
        condition = lambda y_data, line_vals: np.all(y_data <= line_vals + 1e-10)
        distance = lambda y_data, line_vals: line_vals - y_data
    else:
        condition = lambda y_data, line_vals: np.all(y_data >= line_vals - 1e-10)
        distance = lambda y_data, line_vals: y_data - line_vals

    best_distance = float('inf')
    best_i, best_j = 0, 1
    best_line = None

    for i in range(n):
        for j in range(i + 1, n):
            xi, yi = points[i]
            xj, yj = points[j]
            a = (yj - yi) / (xj - xi)
            b = yi - a * xi
            line_ys = a * x_coords + b

            if condition(y_coords, line_ys):
                total_distance = np.sum(distance(y_coords, line_ys))
                if total_distance < best_distance:
                    best_distance = total_distance
                    best_i, best_j = i, j
                    best_line = lambda x, a=a, b=b: a * x + b

    return best_i, best_j, best_distance, best_line

def get_symbol_group(symbol: str) -> str:
    group_name = None
    for group, symbols in TRADE_TIME_GROUPS_MAPPPING.items():
        if symbol in symbols:
            group_name = group
            break
    return group_name
