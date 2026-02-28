from itertools import chain
from typing import Dict, Optional
from feasytools import RangeList
from ..locale import Lang
from ..utils import *
from .params import *
from .veh import *
from .ev import *

EVDict = Dict[str, EV]
GVDict = Dict[str, GV]

def _get(d:dict, names: tuple[str, ...], default: Optional[str] = None) -> str:
    for name in names:
        if name in d: return d[name]
    if default is None: raise KeyError(names)
    return default

def _dget(d:dict, names: tuple[str, ...], default: float) -> float:
    for name in names:
        if name in d: return float(d[name])
    return default

def LoadVehicles(file_path: str, node_mode:bool = True):
    rt = ReadXML(file_path).getroot()
    if rt is None: raise RuntimeError(Lang.EV_LOAD_ERROR.format(file_path))
    
    evs:EVDict = {}; gvs:GVDict = {}
    
    for veh in rt:
        trips: list[Trip] = []; trip_info = {}  
        for trip in veh:
            if trip.tag == "info":
                trip_info = trip.attrib
                continue
            if trip.tag != "trip": continue
            
            route = trip.attrib.get("route_edges", "").split(' ')
            if len(route) == 1 and route[0] == '': route = None
            
            O = _get(trip.attrib, ("from", "origin", "o", "O", "fromNode", "from_node", "fromEdge", "from_edge"), "")
            D = _get(trip.attrib, ("to", "dest", "d", "D", "toNode", "to_node", "toEdge", "to_edge"), "")
            if node_mode:
                if O == "" or D == "":
                    raise ValueError(f"OD missing for vehicle {veh.attrib['id']}'s trip {trip.attrib['id']}")
            else: # Edge_mode
                if O == "": 
                    assert route is not None and len(route) > 0
                    O = route[0]
                if D == "": 
                    assert route is not None and len(route) > 0
                    D = route[-1]
            new_trip = Trip(
                trip.attrib.pop("id"),
                int(float(trip.attrib.pop("depart"))),
                O, D, route
            )
            if len(trips) > 0:
                if new_trip.depart_time <= trips[-1].depart_time:
                    raise ValueError(Lang.BAD_TRIP_DEPART_TIME.format(
                        new_trip.depart_time, trips[-1].depart_time, veh.attrib['id'], new_trip.id))
                if new_trip.O != trips[-1].D:
                    raise ValueError(Lang.BAD_TRIP_OD.format(
                        new_trip.O, trips[-1].D, veh.attrib['id'], new_trip.id))
            trips.append(new_trip)
        
        attr = veh.attrib
        args = {
            "name": veh.attrib["id"],
            "vtype": VehType(int(attr.get("type", DEFAULT_VEH_TYPE))),
            "cap": _dget(attr, ("cap", "bcap", "emax"), DEFAULT_FULL_BATTERY),
            "pct": _dget(attr, ("soc", "pct"), DEFAULT_INIT_SOC),
            "epm": _dget(attr, ("e", "c", "consumption", "epm"), DEFAULT_CONSUMPTION),
            "omega": _dget(attr, ("omega", "w"), DEFAULT_OMEGA),
            "kr": _dget(attr, ("kr", "krel"), DEFAULT_KREL),
            "kf": _dget(attr, ("kf", "kfc"), DEFAULT_FAST_CHARGE_THRESHOLD),
            "trips": trips,
            "trip_info": trip_info,
            "base": attr.get("base", None),
        }
        if veh.tag in ("ev", "vehicle"):
            args.update({
                "ecf": _dget(attr, ("ecf", "ec_fast", "eta_c", "ec"), DEFAULT_ETA_CHARGE),
                "ecs": _dget(attr, ("ecs", "ec_slow", "eta_c", "ec"), DEFAULT_ETA_CHARGE),
                "ed": _dget(attr, ("ed", "eta_d"), DEFAULT_ETA_DISCHARGE),
                "pcf": _dget(attr, ("pcf", "rf", "pcfast"), DEFAULT_FAST_CHARGE_RATE),
                "pcs": _dget(attr, ("pcs", "rs", "pcslow"), DEFAULT_SLOW_CHARGE_RATE),
                "pdv": _dget(attr, ("pd", "pdv", "rv", "pv2g"), DEFAULT_MAX_V2G_RATE),
                "ks": _dget(attr, ("ks", "ksc"), DEFAULT_SLOW_CHARGE_THRESHOLD),
                "kv": _dget(attr, ("kv", "kv2g"), DEFAULT_KV2G),
                "rmod": veh.attrib.get("rmod", DEFAULT_RMOD),
                "sc_time": RangeList(veh.find("sctime")),
                "max_sc_cost": _dget(attr, ("max_sc_cost",), DEFAULT_MAX_SC_COST),
                "v2g_time": RangeList(veh.find("v2gtime")),
                "min_v2g_earn": _dget(attr, ("min_v2g_earn",), DEFAULT_MIN_V2G_EARN),
            })
            evs[veh.attrib["id"]] = EV(**args)
        elif veh.tag == "gv":
            gvs[veh.attrib["id"]] = GV(**args)
    
    return evs, gvs


class VDict:
    def __init__(self, evs: EVDict, gvs: GVDict):
        self.evs = evs
        self.gvs = gvs
    
    def __getitem__(self, name: str):
        if name in self.evs:
            return self.evs[name]
        if name in self.gvs:
            return self.gvs[name]
        raise KeyError(name)
    
    def __setitem__(self, name: str, veh: Vehicle):
        if isinstance(veh, EV):
            self.evs[name] = veh
        elif isinstance(veh, GV):
            self.gvs[name] = veh
        else:
            raise TypeError("veh must be an instance of EV or GV")
    
    def __contains__(self, name: str):
        return name in self.evs or name in self.gvs
    
    def __len__(self):
        return len(self.evs) + len(self.gvs)
    
    def keys(self):
        return chain(self.evs.keys(), self.gvs.keys())
    
    def values(self):
        return chain(self.evs.values(), self.gvs.values())
    
    def items(self):
        return chain(self.evs.items(), self.gvs.items())
    
    @staticmethod
    def from_file(file_path: str, node_mode: bool = True):
        evs, gvs = LoadVehicles(file_path, node_mode)
        return VDict(evs, gvs)
    
    def save(self, fname:str):
        from xml.etree.ElementTree import Element, ElementTree
        rt = Element("root")
        for v in chain(self.evs.values(), self.gvs.values()):
            rt.append(v.to_xml())
        if fname.lower().endswith(".gz"):
            import gzip
            fh = gzip.open(fname, "wb")
        else: fh = open(fname, "wb")
        ElementTree(rt).write(fh, encoding="utf-8", xml_declaration=True)
        fh.close()
    
    def reset(self):
        for v in chain(self.evs.values(), self.gvs.values()):
            v.reset()
    

__all__ = ["EVDict", "GVDict", "LoadVehicles", "VDict"]