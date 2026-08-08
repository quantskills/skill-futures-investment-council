"""
提供访问csv的接口。有哪些csv文件取决于配置文件。
"""
import pandas as pd
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple
from ..outer import Utils, logger

class BModule:
    """
    根据配置文件，确认要找的文件的路径
    """
    def __init__(self, setting_file: str = "setting.yaml"):
        # setting_file如果包含目录，请传绝对路径；如果不包含目录，则会在settings文件夹里找这个文件
        if not setting_file:
            raise ValueError("BModule请指定配置文件")
        else:
            setting_file_path = Path(setting_file)
            if setting_file_path.parent != Path('.') or setting_file_path.is_absolute():
                # 绝对路径，直接用
                pass
            else:
                # 纯文件名
                settings_path = Path(__file__).parent.parent / 'settings'
                setting_file_path = settings_path / setting_file
        self.setting_file_path = setting_file_path
        self.inited = False
        
    
    def init(self):
        if not self.inited:
            settings = Utils.read_yaml(str(self.setting_file_path))
            self.file_index = {} # 存储文件路径
            self.df_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
            self.resolve_setting(settings)
            self.inited = True
    
    def resolve_setting(self, settings: Dict):
        # 解析jobs
        jobs_setting = settings.get('jobs', [])
        for job in jobs_setting:
            name = job['name']
            output_path = self.rearrange_path(job['output_path'])
            value = os.path.join(output_path, name)
            self.file_index[name] = value
        # 解析filter_handlers
        for filter_handler in settings.get('filter_handlers', []):
            name = filter_handler['name']
            output_path = self.rearrange_path(filter_handler['output_path'])
            self.file_index[name] = output_path
    
    def rearrange_path(self, path: str):
        p = Path(path)
        if p.parent != Path('.') or p.is_absolute():
            return path
        else:
            current_path = Path(__file__).parent.parent
            return os.path.join(current_path, path)

    def get_df(self, name: str, pattern: str=None, reload: bool=False):
        """
        name: 就是配置中的name。
        pattern: 被用作正则表达式
        reload: 为了避免重复读取，对象会根据name和pattern来缓存df。如果想要缓存失效，设置reload为True。
        由于文件的命名方式五花八门，这里就直接用正则表达式来匹配文件好了。
        只解析csv和csv.gz文件，其余文件不解析。并且这些文件会合成一个df返回。
        pattern选出来的文件，列名最好保持一致，不然最后拼出来的dataframe会奇形怪状。
        还要注意一点的是，pattern如果是A（本意是拿豆一相关的数据)，那会把所有包含A的文件都包含进去。使用前务必再做一次过滤。
        """
        self.init()
        if reload:
            self.df_cache = {}
        if (name, pattern) in self.df_cache:
            return self.df_cache[(name, pattern)]
        if name not in self.file_index:
            logger.error(f'未找到{name}任务')
        p = re.compile(pattern or ".*", re.I)
        output_path = self.file_index[name]
        # 遍历所有文件：
        matched_files: List[str] = []
        df_list: List[pd.DataFrame] = []
        for dirpath, dirnames, filenames in  os.walk(output_path):
            for filename in filenames:
                match = p.search(filename)
                if match:
                    file = os.path.join(dirpath, filename)
                    matched_files.append(file)
                    df_list.append(pd.read_csv(file))
        logger.info(f'get_df({name}, {pattern})匹配的文件有：{matched_files}')
        if not df_list:
            return pd.DataFrame()
        df = pd.concat(df_list, ignore_index=True)
        self.df_cache[(name, pattern)] = df
        return df


                

                




    
