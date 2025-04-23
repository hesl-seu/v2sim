from feasytools import CreateRangeList
from .utils import readXML
from .params import *
from .ev import EV, Trip

class FloatDictWrapper:
    def __init__(self, d: dict[str, str]):
        self.__d = d
    
    def get(self, key: str, default: float) -> float:
        return float(self.__d.get(key, default))
    
class EVDict(dict[str, EV]):
    def __init__(self, file_path=None):
        super().__init__()
        if file_path is None:
            return
        rt = readXML(file_path).getroot()
        if rt is None:
            raise RuntimeError(f"Failed to load EV file {file_path}")
        for veh in rt:
            trips: list[Trip] = []
            for trip in veh:
                route = trip.attrib["route_edges"].split(" ")
                fixed_route = trip.attrib.get("fixed_route", "none")
                if fixed_route.lower() == "true": fixed_route = True
                elif fixed_route.lower() == "false": fixed_route = False
                else: fixed_route = None
                trips.append(
                    Trip(
                        trip.attrib["id"],
                        int(float(trip.attrib["depart"])),
                        trip.attrib["fromTaz"],
                        trip.attrib["toTaz"],
                        route,
                        fixed_route
                    )
                )
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
                CreateRangeList(elem_sctime),
                attr.get("max_sc_cost", DEFAULT_MAX_SC_COST),
                CreateRangeList(elem_v2gtime),
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
