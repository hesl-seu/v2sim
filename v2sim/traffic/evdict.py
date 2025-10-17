from typing import Dict
from feasytools import RangeList
from ..locale.lang import Lang
from .utils import ReadXML
from .params import *
from .ev import EV, Trip

class FloatDictWrapper:
    def __init__(self, d: Dict[str, str]):
        self.__d = d
    
    def get(self, key: str, default: float) -> float:
        return float(self.__d.get(key, default))
    
class EVDict(Dict[str, EV]):
    def __init__(self, file_path=None):
        super().__init__()
        if file_path is None:
            return
        rt = ReadXML(file_path).getroot()
        if rt is None:
            raise RuntimeError(Lang.EV_LOAD_ERROR.format(file_path))
        for veh in rt:
            trips: list[Trip] = []            
            for trip in veh:
                new_trip = Trip(
                    trip.attrib.pop("id"),
                    int(float(trip.attrib.pop("depart"))),
                    trip.attrib.pop("fromNode"),
                    trip.attrib.pop("toNode"),
                )
                if len(trips) > 0:
                    if new_trip.depart_time <= trips[-1].depart_time:
                        raise ValueError(Lang.BAD_TRIP_DEPART_TIME.format(
                            new_trip.depart_time, trips[-1].depart_time, veh.attrib['id'], new_trip.id))
                    if new_trip.from_node != trips[-1].to_node:
                        raise ValueError(Lang.BAD_TRIP_OD.format(
                            new_trip.from_node, trips[-1].to_node, veh.attrib['id'], new_trip.id))
                trips.append(new_trip)
            attr = FloatDictWrapper(veh.attrib)
            elem_sctime = veh.find("sctime")
            elem_v2gtime = veh.find("v2gtime")
            self.add(EV(
                veh.attrib["id"],
                trips,
                attr.get("eta_c", DEFAULT_ETA_CHARGE),
                attr.get("eta_d", DEFAULT_ETA_DISCHARGE),
                attr.get("bcap", DEFAULT_FULL_BATTERY),
                attr.get("soc", DEFAULT_INIT_SOC),
                attr.get("c", DEFAULT_CONSUMPTION),
                attr.get("rf", DEFAULT_FAST_CHARGE_RATE),
                attr.get("rs", DEFAULT_SLOW_CHARGE_RATE),
                attr.get("rv", DEFAULT_MAX_V2G_RATE),
                attr.get("omega", DEFAULT_OMEGA),
                attr.get("kr", DEFAULT_KREL),
                attr.get("kf", DEFAULT_FAST_CHARGE_THRESHOLD),
                attr.get("ks", DEFAULT_SLOW_CHARGE_THRESHOLD),
                attr.get("kv", DEFAULT_KV2G),
                veh.attrib.get("rmod", DEFAULT_RMOD),
                RangeList(elem_sctime),
                attr.get("max_sc_cost", DEFAULT_MAX_SC_COST),
                RangeList(elem_v2gtime),
                attr.get("min_v2g_earn", DEFAULT_MIN_V2G_EARN),
                veh.attrib.get("cache_route", "false").lower() == "true",
            ))

    def add(self, ev: EV):
        """Add a vehicle"""
        super().__setitem__(ev.ID, ev)

    def pop(self, veh_id: str) -> EV:
        """
        Remove a vehicle by ID, return the removed value
        """
        return super().pop(veh_id)

__all__ = ["EVDict"]