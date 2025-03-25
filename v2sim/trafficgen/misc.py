from dataclasses import dataclass
import gzip, random
from typing import Any, Optional, Sequence, Union
from feasytools.pdf import *
from ..locale import Lang
from ..traffic import EV,Trip

@dataclass
class VehicleType:
    id:int
    bcap_kWh:float
    range_km:float
    efc_rate_kW:float
    esc_rate_kW:float
    max_V2G_kW:float
    
def random_diff(seq:Sequence[Any], exclude:Any):
    """
    Choose a random element from `seq` that is not equal to `exclude`
    """
    ret = exclude
    if len(seq) == 1 and seq[0] == exclude:
        raise RuntimeError(Lang.ERROR_RANDOM_CANNOT_EXCLUDE)
    while ret == exclude:
        ret = random.choice(seq)
    return ret

class TripInner:
    def __init__(self, trip_id:str, depart_time:Union[str,int], from_TAZ:str, from_EDGE:str,
            to_TAZ:str, to_EDGE:str, route:list[str], next_type_place:str, fixed_route:Optional[bool]=None):
        self.id = trip_id
        self.DPTT = int(depart_time)
        self.frE = from_EDGE
        self.frTAZ = from_TAZ
        self.toE = to_EDGE
        self.toTAZ = to_TAZ
        assert isinstance(route, list) and len(route) >= 2, "Route should be a list with at least 2 elements"
        self.route = route
        self.NTP = next_type_place
        self.fixed_route = fixed_route
    
    def to_xml(self, daynum:int) -> str:
        return (f'\n<trip id="{self.id}" depart="{(self.DPTT)*60+86400*daynum}" ' + 
            f'fromTaz="{self.frTAZ}" toTaz="{self.toTAZ}" route_edges="{" ".join(self.route)}" ' + 
            f'fixed_route="{self.fixed_route}" />')
    
    def to_Trip(self, daynum:int) -> Trip:
        return Trip(self.id, self.DPTT * 60 + 86400 * daynum, self.frTAZ, self.toTAZ, self.route)
    
    
class _EV:
    """
    EV class used to generate trips
    """

    def __init__(self, veh_id: str, vT:VehicleType, soc:float, v2g_prop:float, 
        omega:Optional[PDFunc] = None, krel:Optional[PDFunc] = None,
        ksc:Optional[PDFunc] = None, kfc:Optional[PDFunc] = None, 
        kv2g:Optional[PDFunc] = None, cache_route:bool = False,
    ):
        '''
        Initialize EV object
            veh_id: Vehicle ID
            vT: Vehicle type
            soc: State of charge
            v2g_prop: Proportion of V2G capable vehicles
            omega: PDF for omega. None for random uniform between 5 and 10.
                omega indicates the user's sensitivity to the cost of charging. Bigger omega means less sensitive.
            krel: PDF for krel. None for random uniform between 1 and 1.2.
                krel indicates the user's estimation of the distance. Bigger krel means the user underestimates the distance.
            ksc: PDF for ksc. None for random uniform between 0.4 and 0.6.
                ksc indicates the SoC threshold for slow charging.
            kfc: PDF for kfc. None for random uniform between 0.2 and 0.25.
                kfc indicates the SoC threshold for fast charging halfway.
            kv2g: PDF for kv2g. None for random uniform between 0.65 and 0.75.
                kv2g indicates the SoC threshold of the battery that can be used for V2G.'
            cache_route: Wheter remember route for further use.
        '''
        self.vehicle_id = veh_id
        self.bcap = vT.bcap_kWh
        self.soc = soc
        self.consump_Whpm = vT.bcap_kWh / vT.range_km  # kWh/km = Wh/m
        self.efc_rate_kW = vT.efc_rate_kW
        self.esc_rate_kW = vT.esc_rate_kW
        self.max_v2g_rate_kW = vT.max_V2G_kW
        self.omega = omega.sample() if omega else random.uniform(5.0, 10.0)
        self.krel = krel.sample() if krel else random.uniform(1.0, 1.2)
        self.ksc = ksc.sample() if ksc else random.uniform(0.4, 0.6)
        self.kfc = kfc.sample() if kfc else random.uniform(0.2, 0.25)
        self.cache_route = cache_route
        if random.random() < v2g_prop:
            self.kv2g = kv2g.sample() if kv2g else random.uniform(0.65, 0.75)
        else:
            self.kv2g = 1 + 1e-4
        self.trips:list[TripInner] = []
        self.daynum:list[int] = []

    def add_trip(self, daynum: int, trip_dict: TripInner):
        self.daynum.append(daynum)
        self.trips.append(trip_dict)

    def to_xml(self) -> str:
        ret = (
            f'<vehicle id="{self.vehicle_id}" soc="{self.soc:.4f}" bcap="{self.bcap:.4f}" c="{self.consump_Whpm:.8f}"'
            + f' rf="{self.efc_rate_kW:.4f}" rs="{self.esc_rate_kW:.4f}" rv="{self.max_v2g_rate_kW:.4f}" omega="{self.omega:.6f}"'
            + f'\n  kf="{self.kfc:.4f}" ks="{self.ksc:.4f}" kv="{self.kv2g:.4f}" kr="{self.krel:.4f}"'
            + f' eta_c="0.9" eta_d="0.9" rmod="Linear" cache_route="{self.cache_route}">'
        )
        for d, tr in zip(self.daynum, self.trips):
            ret += tr.to_xml(d)
        ret += "\n</vehicle>\n"
        return ret

    def to_EV(self) -> EV:
        trips = [m.to_Trip(daynum) for m, daynum in zip(self.trips, self.daynum)]
        return EV(
            self.vehicle_id,
            trips,
            0.9,
            0.9,
            self.bcap,
            self.soc,
            self.consump_Whpm,
            self.efc_rate_kW,
            self.esc_rate_kW,
            self.max_v2g_rate_kW,
            self.omega,
            self.krel,
            self.kfc,
            self.ksc,
            self.kv2g,
            "Linear",
            cache_route=self.cache_route,
        )


class _xmlSaver:
    """Class used to save XML files"""

    def __init__(self, path: str):
        if path.endswith(".gz"):
            self.a = gzip.open(path, "wt")
        else:
            self.a = open(path, "w")
        self.a.write("<root>\n")

    def write(self, e: _EV):
        self.a.write(e.to_xml())

    def close(self):
        self.a.write("</root>")
        self.a.close()