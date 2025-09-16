from itertools import chain
import operator
from ..locale import CustomLocaleLib
from ..traffic import VehStatus
from .base import *
try:
    import libsumo as traci
except:
    import traci

FILE_EV = "ev"
EV_ATTRIB = ["soc","status","cost","earn","x","y"]

_L = CustomLocaleLib(["en", "zh_CN"])
_L.SetLanguageLib("en",
    EV = "EV",
)
_L.SetLanguageLib("zh_CN",
    EV = "电动车",
)

class StaEV(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:Dict[str,PluginBase]):
        super().__init__(FILE_EV,path,cross_list(tinst.vehicles.keys(),EV_ATTRIB),tinst,plugins)

    @staticmethod
    def GetLocalizedName() -> str:
        return _L("EV")
    
    @staticmethod
    def GetPluginDependency() -> List[str]:
        '''Get Plugin Dependency'''
        return []
    
    def GetData(self,inst:TrafficInst,plugins:Dict[str,PluginBase])->Iterable[Any]:
        vehs = inst.vehicles.values()
        soc = (veh.SOC for veh in vehs)
        status = map(operator.attrgetter("_sta"), vehs)
        cost = map(operator.attrgetter("_cost"), vehs)
        earn = map(operator.attrgetter("_earn"), vehs)
        x = []
        y = []
        for veh in inst.vehicles.values():
            if veh.status == VehStatus.Driving:
                pos = traci.vehicle.getPosition(veh.ID)
            else:
                pos = (0,0)
            x.append(pos[0])
            y.append(pos[1])
        return chain(soc,status,cost,earn,x,y)