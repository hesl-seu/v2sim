from .utils import readXML
from .params import *
from .trip import Trip
from .ev import EV


class EVDict(dict[str, EV]):
    def __init__(self, file_path=None):
        super().__init__()
        if file_path is None:
            return
        for veh in readXML(file_path).getroot():
            trips: list[Trip] = []
            for trip in veh:
                route = trip.attrib["route_edges"].split(" ")
                trips.append(
                    Trip(
                        trip.attrib["id"],
                        int(float(trip.attrib["depart"])),
                        trip.attrib["fromTaz"],
                        trip.attrib["toTaz"],
                        route,
                    )
                )
            params = {
                "id": veh.attrib["id"],
                "trips": trips,
                "bcap": DEFAULT_FULL_BATTERY,
                "soc": DEFAULT_INIT_SOC,
                "c": DEFAULT_CONSUMPTION,
                "rf": DEFAULT_FAST_CHARGE_RATE,
                "rs": DEFAULT_SLOW_CHARGE_RATE,
                "rv": DEFAULT_MAX_V2G_RATE,
                "omega": DEFAULT_OMEGA,
                "kr": DEFAULT_KREL,
                "kf": DEFAULT_FAST_CHARGE_THRESHOLD,
                "ks": DEFAULT_SLOW_CHARGE_THRESHOLD,
                "kv": DEFAULT_KV2G,
                "eta_c": DEFAULT_ETA_CHARGE,
                "eta_d": DEFAULT_ETA_DISCHARGE,
            }
            params2 = veh.attrib
            params2.pop("id")
            rmod = params2.pop("rmod", DEFAULT_RMOD)
            params.update({k: float(v) for k, v in params2.items()})
            assert params["id"] is not None
            params["rmod"] = rmod
            self.add(EV(**params))

    def add(self, ev: EV):
        """Add a vehicle"""
        super().__setitem__(ev.ID, ev)

    def pop(self, veh_id: str) -> EV:
        """
        Remove a vehicle by ID, return: the removed value
        """
        return super().pop(veh_id)
