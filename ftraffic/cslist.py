from itertools import repeat
from typing import Iterable, Type, Union, Optional, TypeVar, Generic
from feasytools import RangeList
from flocale import Lang
from .geo import KDTree, Point
from .utils import readXML
from .params import *
from .evdict import EVDict
from .cs import CS, SCS, FCS

T_CS = TypeVar("T_CS", FCS, SCS)
CS_Type = Type[T_CS]


def _LoadCSList(filePath:str, csType:CS_Type) -> list:
    assert csType == FCS or csType == SCS
    _cs:list[CS] = []
    for cs_node in readXML(filePath).getroot():
        par_pbuy = ()
        par_psell = ()
        par_off = []
        for cfg in cs_node:
            if cfg.tag == "pbuy" or cfg.tag == "psell":
                tl = [int(itm.attrib["btime"]) for itm in cfg]
                pl = [float(itm.attrib["price"]) for itm in cfg]
                if cfg.tag == "pbuy":
                    par_pbuy = (tl, pl)
                else:
                    par_psell = (tl, pl)
            elif cfg.tag == "offline":
                par_off = RangeList(cfg)
            else:
                raise ValueError(Lang.CSLIST_INVALID_TAG.format(cfg.tag))
        if par_pbuy is None:
            raise ValueError(Lang.CSLIST_PBUY_NOT_SPECIFIED)
        _cs.append(
            csType(
                name = cs_node.attrib["edge"],
                slots = int(cs_node.attrib["slots"]),
                bus = cs_node.attrib.get("bus", "None"),
                max_pc = float(cs_node.attrib.get("max_pc", "inf")) / 3600,
                max_pd = float(cs_node.attrib.get("max_pd", "inf")) / 3600,
                x = float(cs_node.attrib.get("x", "inf")),
                y = float(cs_node.attrib.get("y", "inf")),
                offline = par_off, 
                price_buy = par_pbuy, 
                price_sell = par_psell,
                pc_alloc = cs_node.attrib.get("pcalloc", "Average"),
                pd_alloc = cs_node.attrib.get("pdalloc", "Average"),
            )
        )
    return _cs
            
class CSList(Generic[T_CS]):
    """CS List. Index starts from 0."""
    _cs: list[T_CS]

    def __iter__(self):
        return self._cs.__iter__()

    def __init__(
        self,
        ev_dict_to_bind: EVDict,
        *,
        csList: Optional[list[T_CS]] = None,
        filePath: Optional[str] = None,
        csType: CS_Type = FCS,
    ):
        """
        Initialize
            ev_dict_to_bind: EVDict to bind
            csList: CS list
            filePath: file name of CS
            csType: CS type, must be FCS or SCS
        Provide csList, or provide filePath and csType together
        """
        self._evdict: EVDict = ev_dict_to_bind
        if csList is not None:
            flagF = False
            flagS = False
            for cs in csList:
                if isinstance(cs, FCS):
                    flagF = True
                elif isinstance(cs, SCS):
                    flagS = True
                else:
                    raise TypeError(Lang.CSLIST_INVALID_ELEMENT)
            if flagF and flagS and not ALLOW_MIXED_CSTYPE_IN_CSLIST:
                raise TypeError(Lang.CSLIST_MIXED_ELEMENT)
            self._cs = csList
        elif filePath is not None and csType is not None:
            self._cs = _LoadCSList(filePath, csType)
        else:
            raise TypeError(Lang.CSLIST_INVALID_INIT_PARAM)
        self._n = len(self._cs)
        self._remap: dict[str, int] = {}  # Number of a CS with a name
        self._veh: dict[str, int] = {}  # Number of the charging station to which a vehicle belongs
        self._cs_names = [cs.name for cs in self._cs]
        self._cs_slots = [cs.slots for cs in self._cs]
        self.__v2g_cap_res: list[float] = [0.0] * self._n
        self.__v2g_cap_res_time = -1
        self.__v2g_demand: list[float] = []
        for i, cs in enumerate(self._cs):
            self._remap[cs.name] = i
        self._kdtree = KDTree([Point(cs._x, cs._y) for cs in self._cs], range(self._n))
    
    def select_near(self, pos: Point, n: int = 2147483647) -> Iterable[int]:
        """
        Select the n nearest charging station numbers to (x, y).
            pos: coordinate
            n: Number of selections
        Return
            Selected number list
        """
        if n >= self._n:
            return range(self._n)
        return self._kdtree.k_nearest_mapped(pos, n)

    def index(self, name: str) -> int:
        """
        Get the index of the CS by its name. If the name does not exist, KeyError will be raised.
        """
        return self._remap[name]

    def get_CS_names(self) -> list[str]:
        """List of names of all charging stations"""
        return self._cs_names

    def get_online_CS_names(self, t: int) -> list[str]:
        """
        List of names of all available charging stations at t seconds
        """
        return [cs.name for cs in self._cs if cs.is_online(t)]

    def get_prices_at(self, t: int) -> list[float]:
        """
        List of prices of all charging stations at t seconds
        """
        return [cs.pbuy(t) for cs in self._cs]

    def get_online_prices_at(self, t: int) -> list[float]:
        """
        List of prices of all available charging stations at t seconds
        """
        return [cs.pbuy(t) for cs in self._cs if cs.is_online(t)]

    def get_veh_count(self, only_charging=False) -> list[int]:
        """
        List of the number of vehicles at all charging stations. When only_charging is True, only the number of vehicles being charged is returned.
        """
        return [cs.veh_count(only_charging) for cs in self._cs]

    def get_online_veh_count(self, t: int, only_charging=False) -> list[int]:
        """
        List of the number of vehicles at all available charging stations at t seconds. When only_charging is True, only the number of vehicles being charged is returned.
        """
        return [cs.veh_count(only_charging) for cs in self._cs if cs.is_online(t)]

    def get_slots_of(self) -> list[int]:
        """
        List of the number of charging piles at all charging stations
        """
        return self._cs_slots

    def get_online_slots_of(self, t: int) -> list[int]:
        """
        List of the number of charging piles at all available charging stations at t seconds
        """
        return [cs.slots for cs in self._cs if cs.is_online(t)]

    def get_Pd(self, k: float = 1) -> list[float]:
        """
        List of charging power of all charging stations, default unit kWh/s
            k: Unit conversion coefficient, default is 1, indicating no conversion;
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs.Pd * k for cs in self._cs]

    def get_online_Pd(self, t: int, k: float = 1) -> list[float]:
        """
        List of charging power of all available charging stations
            t: Determination time
            k: Unit conversion coefficient, default is 1, indicating no conversion;
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs.Pd * k for cs in self._cs if cs.is_online(t)]

    def get_Pc(self, k: float = 1) -> list[float]:
        """
        List of discharge power of all charging stations
            k: Unit conversion coefficient, default is 1, indicating no conversion;
            3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs.Pc * k for cs in self._cs]

    def get_online_Pc(self, t: int, k: float = 1) -> list[float]:
        """
        List of discharge power of all available charging stations
            t: Determination time
            sb: Unit conversion coefficient, default is 1, indicating no conversion; 
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs.Pc * k for cs in self._cs if cs.is_online(t)]

    def add_veh(self, veh_id: str, cs: Union[int, str]) -> bool:
        """
        Add vehicles to the specified charging station
            veh_id: Vehicle ID
            cs: Charging station name or string
        Return
            True if added successfully, False if the vehicle is already charging, KeyError if the charging station does not exist.
        """
        if not isinstance(cs, int):
            cs = self.index(cs)
        ret = self._cs[cs].add_veh(veh_id)
        if ret:
            self._veh[veh_id] = cs
        return ret

    def pop_veh(self, veh_id: str) -> bool:
        """
        Remove vehicles from the charging station
            veh_id: Vehicle ID
        Return:
            True if removed successfully, False if the vehicle does not exist.
        """
        try:
            cs = self._veh[veh_id]
        except KeyError:
            return False
        del self._veh[veh_id]
        self._cs[cs].pop_veh(veh_id)
        return True

    def has_veh(self, veh_id: str) -> bool:
        """
        Check if there is a vehicle with the specified ID
            veh_id: Vehicle ID
        Return
            True if exists, False if not.
        """
        return veh_id in self._veh

    def CS_index(self, cs_name: str) -> int:
        """
        Check the index (starting from 0) of the charging station with the specified name
            cs_name: Charging station name
        Return
            Index. If it does not exist, return -1.
        """
        try:
            return self._cs_names.index(cs_name)
        except ValueError:
            return -1

    def is_charging(self, veh_id: str) -> bool:
        """
        Get the charging status of the vehicle. If the vehicle does not exist, a ValueError will be raised.
            veh_id: Vehicle ID
        Return
            True if charging, False if waiting.
        """
        cs = self._veh[veh_id]
        return self._cs[cs].is_charging(veh_id)

    def __getitem__(self, indices: Union[str, int]) -> CS:
        """
        Get the index of given charging station. It can be either indices or a charging station name.
        """
        if isinstance(indices, str):
            indices = self._remap[indices]
        return self._cs[indices]

    def get_V2G_cap(self, t: int) -> list[float]:
        """
        Get the maximum V2G return power (considering losses) of each charging station at the current moment, in kWh/s
            t: Indicates the current moment
        """
        if t == self.__v2g_cap_res_time:
            return self.__v2g_cap_res
        self.__v2g_cap_res = [cs.get_V2G_cap(self._evdict,t) for cs in self._cs]
        self.__v2g_cap_res_time = t
        return self.__v2g_cap_res

    def set_V2G_demand(self, v2g_demand: list[float]):
        """Set V2G demand"""
        assert len(v2g_demand) == len(self._cs) or len(v2g_demand) == 0
        self.__v2g_demand = v2g_demand

    def update(self, sec: int, cur_time: int) -> list[str]:
        """
        Charge and V2G discharge the EV with the current parameters.
            sec: Charging duration is sec seconds
            cur_time: Current time (seconds)
        Return
            Vehicle list that has completed charging (power is calculated in kWh/s)
        """
        if len(self.__v2g_demand) > 0:  # Has V2G demand
            v2g_cap = self.get_V2G_cap(sec)
            # The ratio of the actual V2G return power of each CS to its maximum V2G return power
            v2g_k = [
                min(1, d / c) if c > 0.0 else 0.0
                for d, c in zip(self.__v2g_demand, v2g_cap)
            ]
        else:
            v2g_k = repeat(0)
        ret: list[str] = []
        for cs, k in zip(self._cs, v2g_k):
            lst = cs.update(self._evdict, sec, cur_time, k)
            for veh_id in lst:
                del self._veh[veh_id]
            ret.extend(lst)
        return ret

    def __len__(self):
        return len(self._cs)

    def __repr__(self):
        return f"CSList[{','.join(map(str,self._cs))}]"
    
    def __str__(self):
        return repr(self)
