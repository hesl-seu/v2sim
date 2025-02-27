from collections import defaultdict
import heapq
import math
import os
import bisect
from pathlib import Path
#from feasytools import FEasyTimer
from typing import Type, Optional
from ..plugins import *
from .logcs import *
from .logev import *
from .loggr import *


class StaPool:
    def __init__(self, load_internal_logger: bool = True):
        self.__ava_logger: dict[str, type] = {}
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

    def GetAllLogItem(self) -> list[str]:
        """Get all statistic items"""
        return list(self.__ava_logger.keys())


class StaWriter:
    """Statistic data recorder"""
    __items: dict[str, StaBase]

    def Writer(self, name: str):
        return self.__items[name].Writer

    def __init__(
        self,
        path: str,
        tinst: TrafficInst,
        plugins: dict[str, PluginBase],
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

T = TypeVar('T')
class _PQ(Generic[T]):
    def __init__(self):
        self.__data: list[T] = []
    
    def push(self, val:T):
        heapq.heappush(self.__data, val)
    
    def pop(self)->T:
        return heapq.heappop(self.__data)
    
    def top(self)->T:
        return self.__data[0]
    
    def empty(self)->bool:
        return len(self.__data) == 0
    
    def __len__(self)->int:
        return len(self.__data)
    
    def clear(self):
        self.__data.clear()

class TimeSeg:
    def __init__(self):
        self.time:list[int] = []
        self.vals:list[Any] = []
    
    def add(self, time:int, val:Any):
        assert len(self.time) == 0 or time > self.time[-1]
        self.time.append(time)
        self.vals.append(val)
    
    def __len__(self)->int:
        return len(self.time)
    
    def __call__(self):
        return self.time, self.vals
    
    def __add__(self, rv:'TimeSeg')->'TimeSeg':
        return TimeSeg.quicksum(self, rv)
    
    def __neg__(self)->"TimeSeg":
        ret = TimeSeg()
        for i in range(len(self)):
            ret.add(self.time[i], -self.vals[i])
        return ret
    
    def __sub__(self, rv:'TimeSeg')->'TimeSeg':
        return self + (-rv)
    
    def slice(self, start=-math.inf, end=math.inf)->'TimeSeg':
        if end == -1: end = math.inf
        if start > end: start, end = end, start
        assert len(self.time) > 0, "Cannot slice an empty TimeSeg"
        if self.time[0] >= start and self.time[-1] <= end: return self
        ret = TimeSeg()
        l = 0 
        while l < len(self.time) and self.time[l] < start:
            l += 1
        if l >= len(self.time):
            ret.add(int(start), self.vals[-1])
            return ret
        if l > 0 and self.time[l] != start:
            ret.add(int(start), self.vals[l - 1])
        r = len(self.time) - 1
        while r >= 0 and self.time[r] > end:
            r -= 1
        if r < 0: return ret
        if l <= r:
            ret.time.extend(self.time[l:r+1])
            ret.vals.extend(self.vals[l:r+1])
        return ret
    
    @staticmethod
    def quicksum(*v:'TimeSeg')->'TimeSeg':
        ret = TimeSeg()
        pq:_PQ[tuple[int, Any, int]] = _PQ()
        sum = 0
        n = len(v)
        for i in range(n):
            if len(v[i]) > 0: pq.push((v[i].time[0], i, 0))
        ctime = -1
        while not pq.empty():
            htime, idx, prog = pq.top()
            pq.pop()
            if ctime != htime:
                if ctime >= 0:
                    ret.add(ctime, sum)
                ctime = htime
            if prog > 0:
                sum = sum - v[idx].vals[prog - 1] + v[idx].vals[prog]
            else:
                sum += v[idx].vals[prog]
            if prog < len(v[idx]) - 1:
                pq.push((v[idx].time[prog + 1], idx, prog + 1))
        if len(ret.time) == 0:
            ret.add(0, sum)
        elif ctime >= 0 and ctime != ret.time[-1]:
            ret.add(ctime, sum)
        return ret
    
    def interpolate(self,tl:int,tr:int) -> 'TimeSeg':
        ret = TimeSeg()
        if len(self.time) == 0:
            ret.add(tl, 0)
            return ret
        #assert self.time[0] == tl, f"TimeSeg must start at {tl}, but starts at {self.time[0]}"
        for i in range(len(self)):
            if len(ret) > 0 and self.time[i] - ret.time[-1] > 1:
                ret.add(self.time[i] - 1, self.vals[i-1])
            ret.add(self.time[i], self.vals[i])
        if tr!=-1 and len(self.vals) > 0 and ret.time[-1] < tr: 
            ret.add(tr,self.vals[-1])
        return ret
    
    def values_at(self,times:'list[int]')->list[Any]:
        ret = []
        i = 0
        for time in times:
            while i < len(self.time) and self.time[i] < time:
                i += 1
            if i == len(self.time):
                if len(self.vals) > 0:ret.append(self.vals[-1])
                else: ret.append(0)
            elif self.time[i] == time:
                if len(self.vals) > 0:ret.append(self.vals[i])
                else: ret.append(0)
            else:
                if i == 0:
                    ret.append(self.vals[0])
                else:
                    ret.append(self.vals[i-1])
        return ret
    
    def value_at(self,time:int)->Any:
        if len(self.vals) == 0: return 0
        i = bisect.bisect_left(self.time, time)
        if i == len(self.time):
            return self.vals[-1]
        return self.vals[i]

    def min(self)->tuple[int,Any]:
        if len(self.vals) == 0:
            return 0, 0
        return min(zip(self.time, self.vals), key=lambda x:x[1])
    
    def max(self)->tuple[int,Any]:
        if len(self.vals) == 0:
            return 0, 0
        return max(zip(self.time, self.vals), key=lambda x:x[1])
    
    def mean(self,tl:int,tr:int)->Any:
        if len(self.vals) == 0:
            return 0
        if tl == tr:
            return self.value_at(tl)
        lp = bisect.bisect_left(self.time, tl)
        rp = bisect.bisect_right(self.time, tr)
        if lp == len(self.time):
            return 0
        if rp == 0:
            return 0
        if lp == rp:
            return self.vals[lp]
        if self.time[lp] > tl and lp > 0:
            s = self.vals[lp - 1] * (self.time[lp] - tl)
        for i in range(lp,rp):
            if len(self.time) <= i+1:
                s += self.vals[i] * (tr - self.time[i])
            else:
                s += self.vals[i] * (self.time[i+1] - self.time[i])
        s/=(tr-tl)
        return s
    
    @staticmethod
    def cross_interpolate(segs:'list[TimeSeg]')->tuple[list[int],list[list[Any]]]:
        times = set()
        for seg in segs:
            times.update(seg.time)
        times = sorted(list(times))
        return times, [seg.values_at(times) for seg in segs]

class _CSVTable:
    def __init__(self, filename:str):
        self.__data:dict[str,TimeSeg] = defaultdict(TimeSeg)
        lastTime:dict[str,int] = defaultdict(lambda:-1)
        lt = -1
        with open(filename, "r") as f:
            head = f.readline().strip()
            _mp = None
            if head == "C":
                head = f.readline().strip().split(",")
                _mp = {to_base62(i):item for i, item in enumerate(head)}
                head = f.readline().strip()
            header = head.split(",")
            assert len(header) == 3 and header[0] == "Time" and header[1] == "Item" and header[2] == "Value"
            data = f.readlines()
            for i, line in enumerate(data,2):
                time, item, value = line.strip().split(",")
                if _mp is not None: item = _mp[item]
                time = int(time) if time != "" else lt
                assert time > lastTime[item], f"Item {item} @ line {i}: Time must be increasing, but value to add ({time}) is smaller or equal to the last time ({lastTime[item]})"
                lastTime[item] = time
                lt = time
                self.__data[item].add(time, float(value))
        self.lastTime = lt
    
    def __getitem__(self, key:str)->TimeSeg:
        return self.__data[key]
    
    def __contains__(self, key:str)->bool:
        return key in self.__data
    
    def keys(self):
        return self.__data.keys()
    
    @property
    def LastTime(self)->int:
        return self.lastTime
    
class StaReader:
    """Readonly statistics reader, created from a folder"""
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
        self.__items: dict[str, _CSVTable] = {}
        for file in dir_con:
            if file.endswith(".csv"):
                fname = file.removesuffix(".csv")
                if sta_pool is None or sta_pool.Get(fname) is not None:
                    self.__items[fname] = _CSVTable(str(work_dir / file))
            else:
                continue

    def __contains__(self, table_name: str) -> bool:
        return table_name in self.__items

    def __getitem__(self, table_name: str) -> _CSVTable:
        return self.__items[table_name]
    
    def GetColumn(self, table_name:str, item:str)->TimeSeg:
        if table_name not in self.__items:
            raise ValueError(f"Table '{table_name}' not found")
        if item not in self.__items[table_name]:
            ts = TimeSeg()
            ts.add(0,0)
            return ts
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