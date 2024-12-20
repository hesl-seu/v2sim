import gzip, random
from typing import Union
from ..locale import Lang
from ..traffic import EV,Trip

def random_diff(seq, exclude):
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
            to_TAZ:str, to_EDGE:str, route:list[str], next_type_place:str):
        self.id = trip_id
        self.DPTT = int(depart_time)
        self.frE = from_EDGE
        self.frTAZ = from_TAZ
        self.toE = to_EDGE
        self.toTAZ = to_TAZ
        assert isinstance(route, list) and len(route) >= 2, "Route should be a list with at least 2 elements"
        self.route = route
        self.NTP = next_type_place
    
    def to_xml(self, daynum:int) -> str:
        return "".join(
            [
                f'\n<trip id="{self.id}" depart="{(self.DPTT)*60+86400*daynum}" ',
                f'fromTaz="{self.frTAZ}" toTaz="{self.toTAZ}" route_edges="{" ".join(self.route)}" />',
            ]
        )
    
    def to_Trip(self, daynum:int) -> Trip:
        return Trip(self.id, self.DPTT * 60 + 86400 * daynum, self.frTAZ, self.toTAZ, self.route)

class _EV:
    """
    EV class used to generate trips
    """

    def __init__(self, veh_id: str, vT, soc, v2g_prop: float):
        self.vehicle_id = veh_id
        self.bcap = vT["bcap_kWh"]
        self.soc = soc
        self.consump_Whpm = vT["bcap_kWh"] / vT["range_km"]  # kWh/km = Wh/m
        self.efc_rate_kW = vT["efc_rate_kW"]
        self.esc_rate_kW = vT["esc_rate_kW"]
        self.max_v2g_rate_kW = vT["max_V2G_kW"]
        self.omega = random.uniform(5.0, 10.0)
        self.krel = random.uniform(1.0, 1.2)
        self.ksc = random.uniform(0.4, 0.6)
        self.kfc = random.uniform(0.2, 0.25)
        self.kv2g = (
            random.uniform(0.65, 0.75) if random.random() < v2g_prop else 1 + 1e-4
        )
        self.trips:list[TripInner] = []
        self.daynum:list[int] = []

    def add_trip(self, daynum: int, trip_dict: TripInner):
        self.daynum.append(daynum)
        self.trips.append(trip_dict)

    def to_xml(self) -> str:
        ret = (
            f'<vehicle id="{self.vehicle_id}" soc="{self.soc:.4f}" bcap="{self.bcap:.2f}" c="{self.consump_Whpm:.6f}"'
            + f' rf="{self.efc_rate_kW:.2f}" rs="{self.esc_rate_kW:.2f}" rv="{self.max_v2g_rate_kW:.2f}" omega="{self.omega:.2f}"'
            + f'\n  kf="{self.kfc:.2f}" ks="{self.ksc:.2f}" kv="{self.kv2g:.2f}" kr="{self.krel:.2f}"'
            + f' eta_c="0.9" eta_d="0.9" rmod="Linear">'
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
            "Linear"
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