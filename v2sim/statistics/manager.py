from collections import defaultdict
import os
from pathlib import Path
from feasytools import SegFunc
from typing import Type, Optional
from ..plugins import *
from .logcs import *
from .logev import *
from .loggr import *
from ..locale import Lang


class StaPool:
    def __init__(self, load_internal_logger: bool = True):
        self.__ava_logger: Dict[str, type] = {}
        if load_internal_logger:
            self.__ava_logger = {
                FILE_FCS: StaFCS,
                FILE_SCS: StaSCS,
                FILE_EV: StaEV,
                FILE_GEN: StaGen,
                FILE_BUS: StaBus,
                FILE_LINE: StaLine,
                FILE_PVW: StaPVWind,
                FILE_ESS: StaESS,
            }

    def Register(self, name: str, base: Type) -> None:
        """Register a statistic item"""
        if name in self.__ava_logger:
            raise ValueError(Lang.ERROR_STA_REGISTERED.format(name))
        assert issubclass(base, StaBase)
        self.__ava_logger[name] = base

    def Get(self, name: str) -> Type:
        """Get a statistic item"""
        return self.__ava_logger[name]

    def GetAllLogItem(self) -> List[str]:
        """Get all statistic items"""
        return list(self.__ava_logger.keys())


class StaWriter:
    """Statistic data recorder"""
    __items: Dict[str, StaBase]

    def Writer(self, name: str):
        return self.__items[name].Writer

    def __init__(
        self,
        path: str,
        tinst: TrafficInst,
        plugins: Dict[str, PluginBase],
        staPool: StaPool,
    ):
        self.__path = path
        self.__items = {}
        self.__inst = tinst
        self.__plug = plugins
        self.__pool = staPool

    def Add(self, sta_name: str) -> None:
        """Add a statistic item, select from the registered items of StaMan"""
        sta_type = self.__pool.Get(sta_name)
        if sta_name in self.__items:
            raise ValueError(Lang.ERROR_STA_ADDED.format(sta_name))
        self.__items[sta_name] = sta_type(
            self.__path, self.__inst, self.__plug
        )

    #@FEasyTimer
    def Log(self, time: int):
        for item in self.__items.values():
            try:
                item.LogOnce()
            except Exception as e:
                print(Lang.ERROR_STA_LOG_ITEM.format(item._name, e))
                raise e

    def close(self):
        for item in self.__items.values():
            try:
                item.close()
            except Exception as e:
                print(Lang.ERROR_STA_CLOSE_ITEM.format(item._name, e))
                raise e

class _CSVTable:
    def force_load(self):
        lastTime:Dict[str,int] = defaultdict(lambda:-1)
        data = self.__f.readlines()
        lt = -1
        for i, line in enumerate(data,2):
            time, item, value = line.strip().split(",")
            if self._mp is not None: item = self._mp[item]
            time = int(time) if time != "" else lt
            assert time > lastTime[item], f"Item {item} @ line {i}: Time must be increasing, but value to add ({time}) is smaller or equal to the last time ({lastTime[item]})"
            lastTime[item] = time
            lt = time
            self.__data[item].add(time, float(value))
        if self.__head is None: self.__head = list(self.__data.keys())
        self.__lt = lt
        self.__f.close()
        self.__loaded = True

    def __init__(self, filename:str, preload:bool=False):
        self.__data:Dict[str, SegFunc] = defaultdict(SegFunc)
        self.__loaded = False
        self.__f = open(filename, "r")
        head = self.__f.readline().strip()
        self._mp = None
        if head == "C":
            head = self.__f.readline().strip().split(",")
            self.__head = head
            self._mp = {to_base62(i):item for i, item in enumerate(head)}
            head = self.__f.readline().strip()
        else:
            self.__head = None
        header = head.split(",")
        assert len(header) == 3 and header[0] == "Time" and header[1] == "Item" and header[2] == "Value"
        self.__lt = -1
        if preload: self.force_load()
    
    def __getitem__(self, key:str)->SegFunc:
        if not self.__loaded: self.force_load()
        return self.__data[key]
    
    def __contains__(self, key:str)->bool:
        if not self.__loaded: self.force_load()
        return key in self.__data
    
    def keys(self) -> List[str]:
        if self.__head is None: self.force_load()
        return self.__head # type: ignore
    
    @property
    def LastTime(self)->int:
        if not self.__loaded: self.force_load()
        return self.__lt
    
class StaReader:
    """
    Generic purpose readonly statistics reader, created from a folder.
    If you are reading results from a standard V2Sim simulation, using ReadOnlyStatistics is better than using this class, for it supports detailed API.
    """
    def __init__(
        self,
        path: str,
        sta_pool: Optional[StaPool] = None,
    ):
        """
        Initialize
            path: Path to the results folder
            sta_pool: Statistics items' pool, for checking whether an item exists. None for not checking.
        """
        work_dir = Path(path)
        dir_con = os.listdir(path)
        self.__items: Dict[str, _CSVTable] = {}
        for file in dir_con:
            if file.endswith(".csv"):
                fname = file[:-4]  # Remove .csv suffix
                if sta_pool is None or sta_pool.Get(fname) is not None:
                    self.__items[fname] = _CSVTable(str(work_dir / file))
            else:
                continue

    def __contains__(self, table_name: str) -> bool:
        return table_name in self.__items

    def __getitem__(self, table_name: str) -> _CSVTable:
        return self.__items[table_name]
    
    def GetColumn(self, table_name:str, item:str)->SegFunc:
        if table_name not in self.__items:
            raise ValueError(f"Table '{table_name}' not found")
        if item not in self.__items[table_name]:
            return SegFunc([(0, 0.0)])
            #raise ValueError(f"Item '{item}' not found in table '{table_name}'")
        return self.__items[table_name][item]
    
    def GetTable(self, table_name:str)->_CSVTable:
        if table_name not in self.__items:
            raise ValueError(f"Table '{table_name}' not found")
        return self.__items[table_name]
    
    @property
    def LastTime(self)->int:
        t = 0
        for table in self.__items.values():
            t = max(t, table.LastTime)
        return t