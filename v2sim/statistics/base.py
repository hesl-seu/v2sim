from abc import abstractmethod
from typing import Any, Iterable, Optional
from pathlib import Path
from ..plugins import *
from ..traffic import TrafficInst

def cross_list(a:Iterable[str],b:Iterable[str])->list[str]:
    '''Generate cross table header'''
    return [f"{i}#{j}" for j in b for i in a]

_DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
def to_base62(num:int):
    if num == 0: return '0'
    result = ''
    while num:
        num, remainder = divmod(num, 62)
        result += _DIGITS[remainder]
    return result

class StaBase:
    '''Base class for statistics recorder'''
    @abstractmethod
    def __init__(self, name:str, path:str, items:list[str], tinst:TrafficInst, plugins:dict[str,PluginBase], 
            precision:Optional[dict[str, int]]=None, compress:bool=True):
        self._name=name
        self._inst=tinst
        self._plug=plugins
        self._cols=items
        self._vals=[None] * len(items)
        self._writer=open(str(Path(path)/(self._name+".csv")),"w",buffering=1024*1024)
        self._mp = None
        self._pre = precision if precision is not None else {}
        if compress:
            self._mp = {i:to_base62(j) for j,i in enumerate(items)}
            self._writer.write("C\n")
            self._writer.write(','.join(items)+"\n")        
        self._writer.write("Time,Item,Value\n")
        self._lastT = -1
    
    @property
    def Writer(self):
        return self._writer
    
    def GetData(self, inst:TrafficInst, plugins:dict[str,PluginBase]) -> Iterable[Any]: 
        '''Get Data'''
        raise NotImplementedError
    
    def LogOnce(self):
        data = self.GetData(self._inst, self._plug)
        n = len(self._vals)
        for i, v in enumerate(data):
            if i >= n: raise ValueError(f"{self._name}: Data length ({i+1}) > Column count ({n}).")
            if self._vals[i] is None or abs(v-self._vals[i])>1e-6:
                v = round(v, self._pre.get(self._cols[i], 6))
                if self._mp is not None:
                    col = self._mp[self._cols[i]]
                else:
                    col = self._cols[i]
                if self._lastT != self._inst.current_time:
                    self._lastT = self._inst.current_time
                    self._writer.write(f"{self._lastT},{col},{v}\n")
                else:
                    self._writer.write(f",{col},{v}\n")
                self._vals[i] = v
        if n > 0 and i != n - 1: f"{self._name}: Data length ({i+1}) != Column count ({n})."

    def close(self):
        self._writer.close()
    
    def __exit__(self):
        self.close()