from feasytools import LangLib
from ..sim import *
from .base import *


FILE_EV = "ev"
EV_ATTRIB = ["soc", "status", "cost", "earn", "x", "y"]
_L = LangLib(["en", "zh_CN"])
_L.SetLangLib("en", 
    EV = "EV",
    UTN = "UTN"
)
_L.SetLangLib("zh_CN", 
    EV = "电动车", 
    UTN = "交通网"
)


class StaEV(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        super().__init__(FILE_EV, path, cross_list(tinst.vehicles.keys(), EV_ATTRIB), tinst, plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("EV")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        for veh in inst.vehicles.values():
            yield veh.soc
            yield veh._sta
            yield veh._cost
            yield veh._earn if isinstance(veh, EV) else 0.0
            if veh.status == VehStatus.Driving:
                pos = inst.get_veh_pos(veh._name)
                yield pos[0]; yield pos[1]
                # Do not use yield from due to performance issue
            else:
                yield 0; yield 0

class StaUTN(StaBase):
    def __init__(self, path:str, tinst:TrafficInst, plugins:Dict[str, PluginBase]):
        super().__init__("utn", path, ["avg_speed"], tinst, plugins)
        if not hasattr(tinst, 'W'):
            raise RuntimeError("Traffic network statistics require TrafficUX instance")

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("UTN")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self, inst:TrafficInst, plugins:Dict[str, PluginBase]) -> Iterable[Any]:
        # inst is guaranteed to be TrafficUX due to check in __init__
        yield inst.W.get_average_speed() # type: ignore