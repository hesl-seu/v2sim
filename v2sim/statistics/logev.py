from itertools import chain
from ..traffic import VehStatus
from .base import *
try:
    import libsumo as traci
except:
    import traci

FILE_EV = "ev"
EV_ATTRIB = ["soc","status","cost","earn","x","y"]

class StaEV(StaBase):
    def __init__(self,path:str,tinst:TrafficInst,plugins:dict[str,PluginBase]):
        super().__init__(FILE_EV,path,cross_list(tinst.vehicles.keys(),EV_ATTRIB),tinst,plugins)

    def GetData(self,inst:TrafficInst,plugins:dict[str,PluginBase])->Iterable[Any]:
        vehs = inst.vehicles.values()
        soc = map(lambda veh:veh.SOC, vehs)
        status = map(lambda veh:veh.status, vehs)
        cost = map(lambda veh:veh._cost, vehs)
        earn = map(lambda veh:veh._earn, vehs)
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