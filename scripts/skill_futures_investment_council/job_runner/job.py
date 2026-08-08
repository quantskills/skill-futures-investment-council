from typing import Dict, List, Tuple
from datetime import datetime
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..api.provider import MarketDataProvider
from ..calculators import Calculator, ChainCalculator
from ..util.util import get_symbols_by_daterange
from ..filters.filters import filter_handler
from ..outer import logger, EXCLUDE_SYMBOLS



class Job:
    def __init__(self, setting: Dict, data_provider: MarketDataProvider):
        self.setting = setting
        self.data_provider = data_provider
        self._idx = setting.get('_idx', 0) # 只是用来标记任务名
        self.calculators: List[Calculator] = []

    
    def run(self):
        workers = int(self.setting.get("workers", 1))
        workers = max(1, min(workers, os.cpu_count() or 1))
        futures = []
        results: List[str] = []
        if workers == 1:
            for calculator in self.calculators:
                try:
                    results.append(calculator.execute())
                except Exception as exc:
                    logger.error("Task generated an exception: %s", exc, exc_info=True)
            return results
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for calculator in self.calculators:
                futures.append(pool.submit(calculator.execute))
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                    logger.info(f"Task {future} completed.")
                except Exception as e:
                    logger.error(f"Task generated an exception: {e}")
        return results


class ChainJob(Job):
    def __init__(self, setting, data_provider: MarketDataProvider):
        super().__init__(setting, data_provider)
        md_freq = setting['md_freq']
        md_freq = md_freq.lower()
        if md_freq not in ('m', 'd'):
            raise ValueError(f'md_freq只能是m或d。m表示分钟线，d表示日线。而给的值是{md_freq}。')
        
        start_date, end_date = self.get_date_range()

        symbols = setting['symbols']
        if isinstance(symbols, list):
            # 品种列表
            input_symbols = symbols
        else:
            # 单个品种
            input_symbols = [symbols]
        
        calculate_symbols = get_symbols_by_daterange(
            input_symbols, start_date, end_date, provider=data_provider
        )
        for symbol, info in calculate_symbols.items():
            if symbol in EXCLUDE_SYMBOLS:
                continue
            try:
                self.calculators.append(ChainCalculator(symbol, info, setting, data_provider))
            except Exception as e:
                logger.error(f'{symbol}数据获取失败。{e}')
                continue
    
    def get_date_range(self) -> Tuple[datetime, datetime]:
        s_date = self.setting.get('start_date')
        if not s_date:
            start_date = None
        else:
            start_date = datetime.strptime(s_date, '%Y-%m-%d')
        e_date = self.setting.get('end_date')
        if not e_date:
            end_date = None
        else:
            end_date = datetime.strptime(e_date, '%Y-%m-%d')
        return start_date, end_date
    

class JobRunner:
    def __init__(self, setting: Dict, data_provider: MarketDataProvider):
        self.jobs: List[Job] = []

        for idx, job_setting in enumerate(setting.get('jobs', [])):
            job_setting['_idx'] = idx
            cls = job_setting.get('cls')
            if cls == 'ChainCalculator':
                self.jobs.append(ChainJob(job_setting, data_provider))
            else:
                raise ValueError(f"不支持的计算器类型: {cls}")
    def run(self):
        for job in self.jobs:
            job.run()


def work(setting: Dict, data_provider: MarketDataProvider):
    JobRunner(setting, data_provider).run()
    # 执行数据过滤与收集
    filter_handler(setting, data_provider)
