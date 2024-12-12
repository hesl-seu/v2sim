from abc import abstractmethod
from typing import Any, Iterable
from fplugins import *

def cross_list(a:Iterable[str],b:Iterable[str])->list[str]:
    '''Generate cross table header'''
    return [f"{i}#{j}" for j in b for i in a]

class StaBase:
    '''Base class for statistics recorder'''
    @abstractmethod
    def __init__(self,name:str,path:str,items:list[str],tinst:TrafficInst,plugins:dict[str,PluginBase]):
        self._name=name
        self._inst=tinst
        self._plug=plugins
        self._cols=items
        self._vals=[None] * len(items)
        self._writer=open(str(Path(path)/(self._name+".csv")),"w")
        self._writer.write("Time,Item,Value\n")
        self._lastT = -1
    
    @property
    def Writer(self):
        return self._writer
    
    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]: 
        '''Get Data'''
        raise NotImplementedError
    
    def LogOnce(self):
        data = self.GetData(self._inst,self._plug)
        n = len(self._vals)
        cnt = 0
        for i,v in enumerate(data):
            cnt += 1
            if i >= n: raise ValueError(f"{self._name}: Data length ({cnt}) > Column count ({n}).")
            if self._vals[i] is None or abs(v-self._vals[i])>1e-6:
                if self._lastT != self._inst.current_time:
                    self._lastT = self._inst.current_time
                    self._writer.write(f"{self._lastT},{self._cols[i]},{v}\n")
                else:
                    self._writer.write(f",{self._cols[i]},{v}\n")
                self._vals[i] = v
        assert cnt == n, f"{self._name}: Data length ({cnt}) != Column count ({n})."

    def close(self):
        self._writer.close()
    
    def __exit__(self):
        self.close()