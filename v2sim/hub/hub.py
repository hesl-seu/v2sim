from typing import Dict, Iterable, Sequence, Tuple, Union, TypeVar, Generic, List, Literal
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from feasytools import RangeList
from xml.etree.ElementTree import Element, ElementTree
from abc import ABC, abstractmethod
from itertools import repeat
from ..veh import *
from ..locale import Lang
from ..utils import ReadXML, PathLike
from .cs import *
from .s import *


def _parse_station_params(cs_node: Element) -> Dict:
    par_pbuy = (); par_psell = (); par_off = []; par_owners = None
    for cfg in cs_node:
        if cfg.tag == "pbuy":
            if par_pbuy: raise ValueError(Lang.STATIONHUB_DUPLICATE_PBUY)
            par_pbuy = PriceGetterPool.from_elem(cfg)
        elif cfg.tag == "psell":
            if par_psell: raise ValueError(Lang.STATIONHUB_DUPLICATE_PSELL)
            par_psell = PriceGetterPool.from_elem(cfg)
        elif cfg.tag == "offline":
            if par_off: raise ValueError(Lang.STATIONHUB_DUPLICATE_OFFLINE)
            par_off = RangeList(cfg)
        elif cfg.tag == "owners":
            if par_owners != "": raise ValueError(Lang.STATIONHUB_DUPLICATE_OWNERS)
            par_owners = OwnerGroup(cfg)
        else:
            raise ValueError(Lang.STATIONHUB_INVALID_TAG.format(cfg.tag))
    if par_pbuy is None:
        raise ValueError(Lang.STATIONHUB_PBUY_NOT_SPECIFIED)
    if "bind" in cs_node.attrib:
        bind = cs_node.attrib["bind"]
    elif "edge" in cs_node.attrib:
        bind = cs_node.attrib["edge"]
    elif "node" in cs_node.attrib:
        bind = cs_node.attrib["node"]
    else:
        raise ValueError(Lang.STATIONHUB_BIND_NOT_SPECIFIED)
    args = {
        "name": cs_node.attrib["name"],
        "bind": bind,
        "slots": int(cs_node.attrib["slots"]),
        "x": float(cs_node.attrib.get("x", "inf")),
        "y": float(cs_node.attrib.get("y", "inf")),
        "offline": par_off,
        "price_buy": par_pbuy,
        "price_buy_is_service_fee": cs_node.attrib.get("pbuy_is_service_fee", "False").lower() == "true",
    }
    if cs_node.tag == "fcs":
        cs_type = CSType.FCS
        cs_extra = True
    elif cs_node.tag == "scs":
        cs_type = CSType.SCS
        cs_extra = True
    elif cs_node.tag in ["gs", "gas"]:
        cs_extra = False
    else:
        raise ValueError(Lang.STATIONHUB_INVALID_TYPE.format(cs_node.tag))
    if cs_extra: # FCS/SCS
        args.update({
            "bus": cs_node.attrib.get("bus"),
            "owners": par_owners,
            "cs_type": cs_type,
            "price_sell": par_psell,
            "price_sell_is_service_fee": cs_node.attrib.get("psell_is_service_fee", "False").lower() == "true",
            "max_pc": float(cs_node.attrib.get("max_pc", "inf")) / 3600,
            "max_pd": float(cs_node.attrib.get("max_pd", "inf")) / 3600,
            "pc_alloc": cs_node.attrib.get("pcalloc", "Average"),
            "pd_alloc": cs_node.attrib.get("pdalloc", "Average"),
            "allow_queuing": cs_node.attrib.get("allow_queuing", "True").lower() == "true",
        })
    return args


def LoadStationList(filePath:str):
    _fcs:List[CS] = []; _scs:List[CS] = []; _gs:List[GS] = []
    root = ReadXML(filePath).getroot()
    if root is None: raise ValueError("Invalid station file")
    for station in root:
        if station.tag == "fcs":
            args = _parse_station_params(station)
            _fcs.append(BiCS(**args) if args["price_sell"] else UniCS(**args))
        elif station.tag == "scs":
            args = _parse_station_params(station)
            _scs.append(BiCS(**args) if args["price_sell"] else UniCS(**args))
        elif station.tag in ["gs", "gas"]:
            args = _parse_station_params(station)
            _gs.append(GS(**args))
        else:
            raise ValueError(Lang.STATIONHUB_INVALID_TYPE.format(station.tag))
    return _fcs, _scs, _gs


def _LoadCSList(filePath:PathLike, tag:Literal["fcs", "scs", ""]) -> List[CS]:
    _cs = []
    root = ReadXML(filePath).getroot()
    if root is None: raise ValueError(f"Invalid {tag.upper()} file")
    for station in root:
        if tag != "": assert station.tag == tag, Lang.STATIONHUB_INVALID_TYPE.format(station.tag)
        args = _parse_station_params(station)
        _cs.append(BiCS(**args) if args["price_sell"] else UniCS(**args))
    return _cs

def LoadCSList(filePath:PathLike): return _LoadCSList(filePath, "")
def LoadSCSList(filePath:PathLike): return _LoadCSList(filePath, "scs")
def LoadFCSList(filePath:PathLike): return _LoadCSList(filePath, "fcs")


def LoadGSList(filePath:PathLike) -> List[GS]:
    _gs = []
    root = ReadXML(filePath).getroot()
    if root is None: raise ValueError("Invalid GS file")
    for station in root:
        assert station.tag in ["gs", "gas"], Lang.STATIONHUB_INVALID_TYPE.format(station.tag)
        args = _parse_station_params(station)
        _gs.append(GS(**args))
    return _gs


T_Station = TypeVar("T_Station", bound=BaseStation)


def _create_kdt(s: Sequence[BaseStation]):
    from scipy.spatial import KDTree
    pts = []
    for cs in s:
        if cs._x == float("inf") or cs._y == float("inf"):
            return None
        pts.append((cs._x, cs._y))
    return KDTree(pts) if pts else None


class StationHub(Generic[T_Station, T_Vehicle], ABC):
    """List of Stations(GS/CS). Index starts from 0."""
    def __init__(self, par:List[T_Station]):
        self._s = par
        # Station index of a vehicle
        self._veh: Dict[str, int] = {}
        # Station name to index mapping
        self._remap: Dict[str, int] = {s._name: i for i, s in enumerate(self._s)} 
        self.create_kdtree()
    
    def save(self, filePath:Union[str, Path]):
        """Save station hub to XML file."""
        root = Element("root")
        for s in self._s:
            root.append(s.to_xml())
        ElementTree(root).write(filePath, encoding="utf-8", xml_declaration=True)
    
    def reset(self):
        """Reset station hub to initial state."""
        for s in self._s: s.reset()
        self._veh.clear()
    
    def __iter__(self):
        return self._s.__iter__()
    
    def __len__(self):
        return len(self._s)
    
    def _append(self, s: T_Station):
        """Append a charging station without updating the KDTree. Internal use only."""
        if s._name in self._remap:
            raise ValueError(f"Station {s._name} already exists.")
        self._s.append(s)
        self._remap[s._name] = len(self._s) - 1
    
    def append(self, cs: T_Station):
        """Append a charging station. If you want to add multiple charging stations, use extend() instead."""
        self._append(cs)
        self.create_kdtree()
    
    def extend(self, cs_list: Iterable[T_Station]):
        """Extend the charging station list."""
        for cs in cs_list: self._append(cs)
        self.create_kdtree()
    
    def create_kdtree(self):
        # Create KDTree for gas stations and fast charging stations
        self._kdtree = _create_kdt(self._s)
    
    def select_near(self, pos: Tuple[float, float], n: int = 1) -> Iterable[int]:
        """
        Select the n nearest charging station numbers to (x, y).

        :param pos: coordinate
        :param n: Number of selections
        :return: Selected indices. If n >= len(all CSs), all CSs will be returned.
        """
        if n >= len(self._s) or self._kdtree is None:
            return range(len(self._s))
        dist, idx = self._kdtree.query([pos], k=n)
        return idx.reshape(-1)

    def index(self, cs_name: str) -> int:
        """
        Get the index (starting from 0) of the CS by its name
        
        :param cs_name: Charging station name
        :return: Index. If it does not exist, return -1.
        """
        return self._remap.get(cs_name, -1)
    
    def get_names(self) -> List[str]:
        """List of names of all stations"""
        return [s._name for s in self._s]

    def get_online_names(self, t: int) -> List[str]:
        """List of names of all available stations at t second"""
        return [s._name for s in self._s if s.is_online(t)]

    def get_slots_of(self) -> List[int]:
        """List of the number of chargers/oil pumps at all stations"""
        return [s._slots for s in self._s]

    def get_online_slots_of(self, t: int) -> List[int]:
        """List of the number of chargers/oil pumps at all available stations at t second"""
        return [s._slots for s in self._s if s.is_online(t)]
    
    def get_bind_of(self, name:str) -> str:
        """
        Get the bind node/edge of the specified station

        :param name: Station name
        :return: Bind node/edge name
        """
        idx = self._remap.get(name, -1)
        if idx == -1: raise KeyError(f"{name} not found in station hub.")
        return self._s[idx]._bind
    
    def __getitem__(self, index: Union[str, int]) -> T_Station:
        """
        Get the index of given station. It can be either indices or a charging station name.
        """
        if isinstance(index, str): index = self._remap[index]
        return self._s[index]

    def __contains__(self, cs_name: str) -> bool:
        """
        Check if a charging station with the specified name exists

        :param cs_name: Station name
        :return: True if exists, False if not.
        """
        return cs_name in self._remap
    
    @abstractmethod
    def update(self, sec: int, cur_time: int, *args, **kwargs) -> List[T_Vehicle]: 
        """
        Update the station state for sec seconds.

        :param sec: duration in seconds
        :param cur_time: current time in seconds
        :return: Vehicle list that has completed charging/refueling
        """
        ...

    def add_veh(self, veh:T_Vehicle, cs: Union[int, str]) -> bool:
        """
        Add vehicles to the specified station

        :param veh: Vehicle object
        :param cs: Station name or index
        :return: True if added successfully, False if the vehicle is already charging/refueling, KeyError if the station does not exist.
        """
        if not isinstance(cs, int): cs = self._remap[cs]
        ret = self._s[cs].add_veh(veh)
        if ret: self._veh[veh._name] = cs
        return ret

    def pop_veh(self, veh: T_Vehicle) -> bool:
        """
        Remove vehicles from the charging station

        :param veh: Vehicle object
        :return: True if removed successfully, False if the vehicle does not exist.
        """
        try:
            cs = self._veh[veh._name]
        except KeyError:
            return False
        del self._veh[veh._name]
        self._s[cs].pop_veh(veh)
        return True

    def has_veh(self, veh_id: str) -> bool:
        """
        Check if there is a vehicle with the specified ID

        :param veh_id: Vehicle ID
        :return: True if exists, False if not.
        """
        return veh_id in self._veh


class CSHub(StationHub[CS, EV]):
    """List of CS(UniCS/BiCS). Index starts from 0."""
    def __init__(self, par:List[CS], auto_leave_at_etar: bool):
        super().__init__(par)
        self.__pd_cap: List[float] = [0.0] * len(self._s)
        self.__T_pd_cap:int = -1
        self.__pd_dem: List[float] = []
        self.__auto_leave_at_etar = auto_leave_at_etar
    
    def reset(self):
        """Reset station hub to initial state."""
        super().reset()
        self.__pd_cap = [0.0] * len(self._s)
        self.__T_pd_cap = -1
        self.__pd_dem = []
    
    def add_veh(self, veh: EV, cs: Union[int, str]) -> bool:
        """Add vehicles to the specified station"""
        veh.set_leave_at_etar(self.__auto_leave_at_etar)
        return super().add_veh(veh, cs)
    
    def _append(self, cs: CS):
        """Append a charging station. If you want to add multiple charging stations, use extend() instead."""
        super()._append(cs)
        self.__pd_cap.append(0.0)
        if len(self.__pd_dem) > 0:
            self.__pd_dem.append(0.0)
            assert len(self.__pd_dem) == len(self._s)
    
    def append(self, cs: CS):
        """Append a charging station. If you want to add multiple charging stations, use extend() instead."""
        self._append(cs)
        self.create_kdtree()
    
    def extend(self, cs_list: Iterable[CS]):
        """Extend the charging station list."""
        for cs in cs_list: self._append(cs)
        self.create_kdtree()
        
    def get_veh_count(self, only_charging: bool = False) -> List[int]:
        """
        List of the number of vehicles at all charging stations. When only_charging is True, only the number of vehicles being charged is returned.
        """
        return [cs.veh_count(only_charging) for cs in self._s]

    def get_online_veh_count(self, t: int, only_charging=False) -> List[int]:
        """
        List of the number of vehicles at all available charging stations at t seconds. When only_charging is True, only the number of vehicles being charged is returned.
        """
        return [cs.veh_count(only_charging) for cs in self._s if cs.is_online(t)]
    
    def get_Pd(self, k: float = 1) -> List[float]:
        """
        List of charging power of all charging stations, default unit kWh/s

        :param k: Unit conversion coefficient, default is 1, indicating no conversion;
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs._dload * k for cs in self._s]

    def get_online_Pd(self, t: int, k: float = 1) -> List[float]:
        """
        List of charging power of all available charging stations
            t: Determination time
            k: Unit conversion coefficient, default is 1, indicating no conversion;
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs._dload * k for cs in self._s if cs.is_online(t)]

    def get_Pc(self, k: float = 1) -> List[float]:
        """
        List of discharge power of all charging stations

        :param k: Unit conversion coefficient, default is 1, indicating no conversion;
            3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs._cload * k for cs in self._s]

    def get_online_Pc(self, t: int, k: float = 1) -> List[float]:
        """
        List of discharge power of all available charging stations
        
        :param t: Determination time
        :param k: Unit conversion coefficient, default is 1, indicating no conversion; 
               3600 indicates conversion to kW; 3600/Sb_kVA indicates conversion to per unit value
        """
        return [cs._cload * k for cs in self._s if cs.is_online(t)]

    def is_charging(self, veh: EV) -> bool:
        """
        Check if the given EV is charging
        """
        cs = self._veh[veh.name]
        return self._s[cs].is_charging(veh)
    
    def get_V2G_cap(self, t: int) -> List[float]:
        """
        Get the maximum V2G power (considering losses) of each CS at the current time t, in kWh/s
        """
        if t == self.__T_pd_cap:
            return self.__pd_cap
        self.__pd_cap = [cs.get_V2G_cap(t) for cs in self._s]
        self.__T_pd_cap = t
        return self.__pd_cap

    def set_V2G_demand(self, v2g_demand: List[float]):
        """Set V2G demand"""
        assert len(v2g_demand) == len(self._s) or len(v2g_demand) == 0
        self.__pd_dem = v2g_demand
    
    def clear_V2G_demand(self):
        """Clear V2G demand"""
        self.__pd_dem = []
    
    def update(self, sec: int, cur_time: int, pb_e:float, ps_e:float) -> List[EV]:
        """
        Charge and V2G discharge the EV with the current parameters.
        
        :param sec: Charging duration is sec seconds
        :param cur_time: Current time (seconds)
        :param pb_e: The cost for CS buying electricity from the grid, $/kWh
        :param ps_e: The revenue for CS selling electricity to the grid, $/kWh
        :return: Vehicle list that has completed charging (power is calculated in kWh/s)
        """
        if len(self.__pd_dem) > 0:  # Has V2G demand
            # assert len(self.__pd_dem) == len(self._s)
            # No need to check length since it is guaranteed by set_V2G_demand() method
            v2g_demand = self.__pd_dem
        else:
            v2g_demand = repeat(0.0)
        
        # Do not use multithreading since the overhead is too large for small number of CSs
        ret:List[EV] = []       
        for cs, pd in zip(self._s, v2g_demand):
            lst = cs.update(sec, cur_time, pd, pb_e, ps_e)
            for ev in lst:
                del self._veh[ev._name]
            ret.extend(lst)
        return ret

    def __repr__(self):
        return f"CSHub[{','.join(map(str,self._s))}]"
    
    def __str__(self):
        return repr(self)
    

class GSHub(StationHub[GS, GV]):
    """List of GS. Index starts from 0."""
    def __init__(self, par:Union[str, List[GS]]):
        if isinstance(par, str): par = LoadGSList(par)
        super().__init__(par)
    
    def update(self, sec: int, cur_time: int, pb_g:float) -> List[GV]:
        """
        Refuel the GV with the current parameters.

        :param sec: Refueling duration is sec seconds
        :param cur_time: Current time (seconds)
        :param pb_g: The cost for GS buying gasoline, $/L
        """
        ret:List[GV] = []
        for gs in self._s:
            ret.extend(gs.update(sec, cur_time, pb_g))
        return ret
    
    def get_veh_count(self) -> List[int]:
        """List of the number of vehicles at all gas stations at the current time."""
        return [len(s) for s in self._s]

    def get_online_veh_count(self, t: int) -> List[int]:
        """List of the number of vehicles at all available gas stations at t seconds."""
        return [len(s) for s in self._s if s.is_online(t)]

    def __repr__(self):
        return f"GSHub[{','.join(map(str,self._s))}]"
    
    def __str__(self):
        return repr(self)


class FCSHub(CSHub):
    """List of FCS(UniCS/BiCS). Index starts from 0."""
    def __init__(self, par:Union[str, List[CS]]):
        if isinstance(par, str): par = LoadFCSList(par)
        super().__init__(par, True)


class SCSHub(CSHub):
    """List of SCS(UniCS/BiCS). Index starts from 0."""
    def __init__(self, par:Union[str, List[CS]]):
        if isinstance(par, str): par = LoadSCSList(par)
        super().__init__(par, False)


@dataclass
class _MixedSList:
    fcs:List[CS]
    scs:List[CS]
    gs:List[GS]

    def __iter__(self):
        for cs in self.fcs: yield cs
        for cs in self.scs: yield cs
        for g in self.gs: yield g

def create_empty_mixed_slist() -> _MixedSList:
    return _MixedSList([], [], [])

class MixedHub:
    def __init__(self, fcs:Union[str, List[CS]], scs:Union[str, List[CS]], gs:Union[str, List[GS]]):
        self.fcs:FCSHub = FCSHub(fcs)
        self.scs:SCSHub = SCSHub(scs)
        self.gs:GSHub = GSHub(gs)
        # Don't use lambda function, since it cannot be pickled.
        self.atbind:Dict[str, _MixedSList] = defaultdict(create_empty_mixed_slist)
        for s in self.fcs._s: self.atbind[s._bind].fcs.append(s)
        for s in self.scs._s: self.atbind[s._bind].scs.append(s)
        for s in self.gs._s: self.atbind[s._bind].gs.append(s)
    
    def reset(self):
        """Reset mixed hub to initial state."""
        self.fcs.reset()
        self.scs.reset()
        self.gs.reset()

    def get_bind_of(self, name:str) -> str:
        if name in self.fcs._remap:
            return self.fcs._s[self.fcs._remap[name]]._bind
        elif name in self.scs._remap:
            return self.scs._s[self.scs._remap[name]]._bind
        elif name in self.gs._remap:
            return self.gs._s[self.gs._remap[name]]._bind
        else:
            raise KeyError(name)
    
    @staticmethod
    def from_file(filepath:Union[str, Iterable[str]]):
        if isinstance(filepath, str): filepath = [filepath]
        fcs:List[CS] = []; scs:List[CS] = []; gs:List[GS] = []
        for fn in filepath:
            if not isinstance(fn, str): raise ValueError("Invalid file path")
            f, s, g = LoadStationList(fn)
            fcs.extend(f)
            scs.extend(s)
            gs.extend(g)
        return MixedHub(fcs, scs, gs)
    
    def __contains__(self, key:str) -> bool:
        return key in self.fcs._remap or key in self.scs._remap or key in self.gs._remap
    
    def __len__(self):
        return len(self.fcs) + len(self.scs) + len(self.gs)
    
    @property
    def counts(self) -> Tuple[int, int, int]:
        """Number of FCS, SCS and GS"""
        return len(self.fcs), len(self.scs), len(self.gs)
    
    def __getitem__(self, key:str):
        if key in self.fcs._remap:
            return self.fcs._s[self.fcs._remap[key]]
        elif key in self.scs._remap:
            return self.scs._s[self.scs._remap[key]]
        elif key in self.gs._remap:
            return self.gs._s[self.gs._remap[key]]
        else:
            raise KeyError(Lang.HUB_CS_NOT_EXIST.format(key))
    
    def __iter__(self):
        for cs in self.fcs._s: yield cs
        for cs in self.scs._s: yield cs
        for g in self.gs._s: yield g
    
    def keys(self):
        """List of all station names."""
        yield from self.fcs._remap.keys()
        yield from self.scs._remap.keys()
        yield from self.gs._remap.keys()
    
    def values(self):
        """List of all station objects."""
        yield from self.fcs._s
        yield from self.scs._s
        yield from self.gs._s
    
    def items(self):
        """List of all station name and object pairs."""
        for cs in self.fcs._s:
            yield cs._name, cs
        for cs in self.scs._s:
            yield cs._name, cs
        for g in self.gs._s:
            yield g._name, g

    def check_kdtree(self):
        if self.fcs._kdtree is None:
            self.fcs.create_kdtree()
        if self.scs._kdtree is None:
            self.scs.create_kdtree()
        if self.gs._kdtree is None:
            self.gs.create_kdtree()
    
    def add_station(self, station:Union[CS, GS]):
        """Add a station to the hub."""
        if isinstance(station, GS):
            self.gs.append(station)
            self.atbind[station._bind].gs.append(station)
        elif isinstance(station, CS):
            if station._cs_type == CSType.FCS:
                self.fcs.append(station)
                self.atbind[station._bind].fcs.append(station)
            elif station._cs_type == CSType.SCS:
                self.scs.append(station)
                self.atbind[station._bind].scs.append(station)
            else:
                raise ValueError(f"Invalid CS type: {station._cs_type}")
        else:
            raise ValueError(f"Invalid station type: {type(station)}")
    
    def __repr__(self):
        return f"MixedHub[FCS={self.fcs} SCS={self.scs} GS={self.gs}]"

__all__ = [
    "LoadStationList", "LoadGSList", "LoadFCSList", "LoadSCSList", "LoadCSList",
    "GSHub", "FCSHub", "SCSHub", "MixedHub", "StationHub", "CSHub"
]