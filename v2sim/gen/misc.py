import random
from dataclasses import dataclass
from typing import Any, List, Sequence, Union, overload
from feasytools.pdf import *
from ..utils import ReadXML
from ..locale import Lang
from ..veh import EV, GV, Trip, VehType, Vehicle

@dataclass
class EVType:
    vtype:VehType
    bcap_kWh:float
    range_km:float
    pcf_kW:float
    pcs_kW:float
    pdv_kW:float

@dataclass
class GVType:
    vtype:VehType
    cap_L:float
    range_km:float

def parse_val(s:str, unit:str) -> float:
    if not s.lower().endswith(unit.lower()):
        raise ValueError(f"Expected string to end with {unit}, got {s}")
    return float(s[:-len(unit)])

class VehicleTypePool:
    def __init__(self, desc_file:str):
        self.__evtypes:List[EVType] = []
        self.__evt_weights:List[float] = []
        self.__gvtypes:List[GVType] = []
        self.__gvt_weights:List[float] = []

        root = ReadXML(desc_file).getroot()
        assert root is not None, Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(desc_file)
        for vt in root:
            if vt.tag == "ev":
                self.__evtypes.append(EVType(
                    vtype=VehType.from_str(vt.attrib["vtype"]),
                    bcap_kWh=parse_val(vt.attrib["cap"], "kWh"),
                    range_km=parse_val(vt.attrib["range"], "km"),
                    pcf_kW=parse_val(vt.attrib["pcf"], "kW"),
                    pcs_kW=parse_val(vt.attrib["pcs"], "kW"),
                    pdv_kW=parse_val(vt.attrib["pdv"], "kW"),
                ))
                self.__evt_weights.append(float(vt.attrib["weight"]))
            elif vt.tag == "gv":
                self.__gvtypes.append(GVType(
                    vtype=VehType.from_str(vt.attrib["vtype"]),
                    cap_L=parse_val(vt.attrib["cap"], "L"),
                    range_km=parse_val(vt.attrib["range"], "km"),
                ))
                self.__gvt_weights.append(float(vt.attrib["weight"]))
            else:
                raise ValueError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(desc_file))
        
        self.__total_ev_weight = sum(self.__evt_weights)
        self.__total_gv_weight = sum(self.__gvt_weights)
    
    def sample_evtype(self) -> EVType:
        return random.choices(self.__evtypes, weights=self.__evt_weights, k=1)[0]
    
    def sample_gvtype(self) -> GVType:
        return random.choices(self.__gvtypes, weights=self.__gvt_weights, k=1)[0]
    
    def sample(self) -> Union[EVType, GVType]:
        if random.uniform(0, self.__total_ev_weight + self.__total_gv_weight) < self.__total_ev_weight:
            return self.sample_evtype()
        else:
            return self.sample_gvtype()

    
def random_diff(seq:Sequence[Any], exclude:Any):
    """Choose a random element from `seq` that is not equal to `exclude`"""
    ret = exclude
    if len(seq) == 1 and seq[0] == exclude:
        raise RuntimeError(Lang.ERROR_RANDOM_CANNOT_EXCLUDE)
    while ret == exclude:
        ret = random.choice(seq)
    return ret

PDFuncLike = Union[None, float, PDFunc]
def _impl_PDFuncLike(x:PDFuncLike, default:PDFunc) -> float:
    if x is None:
        return default.sample()
    elif isinstance(x, float):
        return x
    elif isinstance(x, PDFunc):
        return x.sample()
    raise TypeError("x must be None, float or PDFunc")

@overload
def create_veh(veh_id: str, vT:EVType, soc:float, 
        omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None,
        v2g_prop:float = 1.0+1e-4, ksc:PDFuncLike = None, kv2g:PDFuncLike = None) -> EV: ...

@overload
def create_veh(veh_id: str, vT:GVType, soc:float,
        omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None) -> GV: ...

def create_veh(veh_id: str, vT:Union[GVType, EVType], soc:float, 
        omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None,
        v2g_prop:float = 1.0+1e-4, ksc:PDFuncLike = None, kv2g:PDFuncLike = None):
    '''Initialize EV object

    :param veh_id: Vehicle ID
    :param vT: Vehicle type
    :param soc: State of charge
    :param v2g_prop: Vehicle's probability of being able to V2G. Value >= 1.0 means always V2G.
    :param omega: PDF for omega. None for random uniform between 5 and 10.
        omega indicates the user's sensitivity to the cost of charging. Bigger omega means less sensitive.
    :param krel: PDF for krel. None for random uniform between 1 and 1.2.
        krel indicates the user's estimation of the distance. Bigger krel means the user underestimates the distance.
    :param ksc: PDF for ksc. None for random uniform between 0.4 and 0.6.
        ksc indicates the SoC threshold for slow charging.
    :param kfc: PDF for kfc. None for random uniform between 0.2 and 0.25.
        kfc indicates the SoC threshold for fast charging halfway.
    :param kv2g: PDF for kv2g. None for random uniform between 0.65 and 0.75.
            kv2g indicates the SoC threshold of the battery that can be used for V2G.
    '''
    if isinstance(vT, EVType):
        if v2g_prop >= 1.0 or random.random() < v2g_prop:
            kv2g = _impl_PDFuncLike(kv2g, PDUniform(0.65, 0.75))
        else:
            kv2g = 1 + 1e-4
        ret = EV(veh_id, vT.vtype, vT.bcap_kWh, soc,
            vT.bcap_kWh / vT.range_km, 0.88, 0.9, 0.85,
            vT.pcf_kW, vT.pcs_kW, vT.pdv_kW,
            _impl_PDFuncLike(omega, PDUniform(5.0, 10.0)),
            _impl_PDFuncLike(krel, PDUniform(0.9, 1.0)),
            _impl_PDFuncLike(kfc, PDUniform(0.2, 0.25)),
            _impl_PDFuncLike(ksc, PDUniform(0.4, 0.6)),
             kv2g, [], {})
    elif isinstance(vT, GVType):
        ret = GV(veh_id, vT.vtype, vT.cap_L, soc,
            vT.cap_L / vT.range_km / 1000, 
            _impl_PDFuncLike(omega, PDUniform(5.0, 10.0)),
            _impl_PDFuncLike(krel, PDUniform(0.9, 1.0)),
            _impl_PDFuncLike(kfc, PDUniform(0.2, 0.25)),
            [], {})
    else:
        raise TypeError("vT must be EVType or GVType")
    return ret


def add_trip_to_veh(veh:Vehicle, trip:Trip, day:int = -1):
    '''
    Add a trip to the vehicle.
        veh: Vehicle object
        trip_id: Unique trip ID
        depart_time: Departure time in seconds since midnight of the day.
        from_bind: Origin node/edge ID
        from_type: The type of place where the trip starts.
        to_bind: Destination node/edge ID
        to_type: The type of place where the trip will end.
        day: The day of the trip. -1 means the depart_time is absolute time in seconds.
             otherwise, depart_time is in seconds since midnight of the day.
    '''
    if not hasattr(veh, 'trips'): raise TypeError("veh must be EV or GV")
    if day >= 0:
        assert 0 <= trip.depart_time < 86400, "When day is specified, depart_time must be less than 86400."
        trip.depart_time += day * 86400
    veh.trips.append(trip)
