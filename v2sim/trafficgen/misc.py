from dataclasses import dataclass
import gzip, random
from typing import Any, List, Optional, Sequence, Union
from ..locale import Lang
from ..traffic import EV,Trip
from feasytools.pdf import (
    PDModel, PDBeta, PDDiscrete, PDExponential, 
    PDFunc, PDUniform, PDGamma, PDLogLogistic, 
    PDLogNormal, PDNormal, PDWeibull, PDTriangular,
    CDDiscrete, CreatePDFunc, CreatePDDiscretesFromCSVbyRow,
)

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

class _TripInner:
    def __init__(self, trip_id:str, depart_time:Union[str,int], from_node:str, from_type:str,
            to_node:str, to_type:str,):
        '''
        Initialize a trip object.
            trip_id: Unique trip ID
            depart_time: Departure time in seconds since midnight of the day.
                Can be a string or an integer. If it is a string, it should be convertible to an integer.
            from_node: Origin node ID
            from_type: The type of place where the trip starts.
            to_node: Destination node ID
            to_type: The type of place where the trip will end.
        '''
        self.id = trip_id
        self.DPTT = int(depart_time) # departure time in seconds since midnight
        self.frN = from_node
        self.toN = to_node
        self.frT = from_type
        self.toT = to_type
    
    def toXML(self, daynum:int) -> str:
        return (f'\n<trip id="{self.id}" depart="{self.DPTT + 86400 * daynum}" ' + 
            f'fromType="{self.frT}" toType="{self.toT}" ' + 
            f'fromNode="{self.frN}" toNode="{self.toN}" />')
    
    def toTrip(self, daynum:int) -> Trip:
        return Trip(self.id, self.DPTT + 86400 * daynum, self.frN, self.toN)

PDFuncLike = Union[None, float, PDFunc]
def _impl_PDFuncLike(x:PDFuncLike, default:PDFunc) -> float:
    if x is None:
        return default.sample()
    elif isinstance(x, float):
        return x
    elif isinstance(x, PDFunc):
        return x.sample()
    raise TypeError("x must be None, float or PDFunc")
    
class _EVInner:
    """
    EV class used to generate trips
    """

    def __init__(self, veh_id: str, vT:VehicleType, soc:float, v2g_prop:float = 1.0+1e-4, 
        omega:PDFuncLike = None, krel:PDFuncLike = None,
        ksc:PDFuncLike = None, kfc:PDFuncLike = None, 
        kv2g:PDFuncLike = None, cache_route:bool = False,
    ):
        '''
        Initialize EV object
            veh_id: Vehicle ID
            vT: Vehicle type
            soc: State of charge
            v2g_prop: Vehicle's probability of being able to V2G. Value >= 1.0 means always V2G.
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
        self.omega = _impl_PDFuncLike(omega, PDUniform(5.0, 10.0))
        self.krel = _impl_PDFuncLike(krel, PDUniform(1.0, 1.2))
        self.ksc = _impl_PDFuncLike(ksc, PDUniform(0.4, 0.6))
        self.kfc = _impl_PDFuncLike(kfc, PDUniform(0.2, 0.25))
        self.cache_route = cache_route
        if v2g_prop >= 1.0 or random.random() < v2g_prop:
            self.kv2g = _impl_PDFuncLike(kv2g, PDUniform(0.65, 0.75))
        else:
            self.kv2g = 1 + 1e-4
        self.trips:List[_TripInner] = []
        self.daynum:List[int] = []
    
    def _add_trip(self, daynum: int, trip_dict: _TripInner):
        self.daynum.append(daynum)
        self.trips.append(trip_dict)
    
    def addTrip(self, trip_id:str, depart_time:int, from_node:str, from_Type:str,
                to_node:str, to_Type:str, daynum:int = -1):
        '''
        Add a trip to the EV.
            trip_id: Unique trip ID
            depart_time: Departure time in seconds since midnight of the day.
                When it is less than 86400 and `daynum` >= 0, it is considered as in the day specified by `daynum`.
                Otherwise, it is considered as the exact time in seconds since simulation start.
            from_TAZ: Origin TAZ ID
            from_EDGE: Origin edge ID
            to_TAZ: Destination TAZ ID
            to_EDGE: Destination edge ID
            route: List of edge IDs representing the route, should have at least 2 elements.
                When the route has only 2 elements, it is considered only the start and end edges.
            fixed_route: Whether the route is fixed or not.
                True means the route is fixed.
                False means the route is not fixed and must be recalculated every time the trip is used.
                None means it is not specified. Whether the route is fixed or not will be determined by the simulation.
            daynum: Day number, starting from 0. -1 means the trip is not in a specific day and `depart_time` is the exact time since simulation start.
        Raises:
            AssertionError: If `daynum` is specified and `depart_time` is not less than 86400.
        '''
        if daynum < 0:
            daynum = depart_time // 86400
            depart_time = depart_time % 86400
        else:
            assert 0 <= depart_time and depart_time < 86400, "When daynum is specified, depart_time must be less than 86400."
        self.daynum.append(daynum)
        depart_time = int(depart_time) if isinstance(depart_time, str) else depart_time
        self.trips.append(_TripInner(trip_id, depart_time, from_node, from_Type, to_node, to_Type))

    def toXML(self) -> str:
        ret = (
            f'<vehicle id="{self.vehicle_id}" soc="{self.soc:.4f}" bcap="{self.bcap:.4f}" c="{self.consump_Whpm:.8f}"'
            + f' rf="{self.efc_rate_kW:.4f}" rs="{self.esc_rate_kW:.4f}" rv="{self.max_v2g_rate_kW:.4f}" omega="{self.omega:.6f}"'
            + f'\n  kf="{self.kfc:.4f}" ks="{self.ksc:.4f}" kv="{self.kv2g:.4f}" kr="{self.krel:.4f}"'
            + f' eta_c="0.9" eta_d="0.9" rmod="Linear" cache_route="{self.cache_route}">'
        )
        for d, tr in zip(self.daynum, self.trips):
            ret += tr.toXML(d)
        ret += "\n</vehicle>\n"
        return ret

    def toEV(self) -> EV:
        trips = [m.toTrip(daynum) for m, daynum in zip(self.trips, self.daynum)]
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

    def write(self, e: _EVInner):
        self.a.write(e.toXML())

    def close(self):
        self.a.write("</root>")
        self.a.close()