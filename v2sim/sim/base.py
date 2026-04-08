import random
from dataclasses import dataclass
from itertools import chain
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, TypeVar, List, Tuple, Union
from feasytools import TimeFunc, ConstFunc
from fpowerkit import Grid
from ..net import RoadNet
from ..locale import Lang
from ..utils import *
from ..veh import *
from ..hub import *
from .tlog import *
T_OD = TypeVar("T_OD")


TRAFFIC_INST_FILE_NAME = "inst.gz"
StepCallback = Callable[['TrafficInst'], None]


class StageLike(Protocol):
    edges: List[Any]
    travelTime: float
    length: float


class TrafficInst(ABC):
    def __init__(
        self, start_time: int, step_len: int, end_time: int, roadnet:RoadNet, 
        trip_logger: TripLogger, vehs: VDict, hubs: MixedHub, pdn: Grid,
        gasoline_price: TimeFunc, seed: int = 0, silent: bool = False, 
        dist_based_restoration: bool = False, step_callback:Optional[StepCallback] = None
    ):  
        self._st: int = start_time
        self._ct: int = start_time
        self._step: int = step_len
        self._et: int = end_time
        self._log = trip_logger
        self._vehs = vehs
        self._hubs = hubs
        self._rnet = roadnet
        self.silent = silent
        self._dist_based_restoration = dist_based_restoration
        self._pdn = pdn
        self._gp = gasoline_price
        self._step_cb = step_callback
        random.seed(seed)

    def _prepare_trips_and_scs(self):
        # Load vehicles
        from feasytools import PQueue
        self._fQ:PQueue[str] = PQueue()  # Fault queue
        self._que:PQueue[Tuple[str, Any]] = PQueue()  # Departure queue

        # Prepare for departure
        for veh in self._vehs.values():
            self._que.push(veh.trip.depart_time, (veh._name, None))
        
        for veh in self._vehs.evs.values():
            # There is a 20% chance of adding to a rechargeable parking point
            if veh.soc < veh._ks or random.random() <= 0.2:
                if len(self._hubs.atbind[veh.trip.O].scs) == 0: continue
                scs = random.choice(self._hubs.atbind[veh.trip.O].scs)
                self.scs.add_veh(veh, scs._name)
                # Do not directly add to a specific slow charging station here, or SCSHub will not be able to track the vehicle correctly
    
    @abstractmethod
    def get_veh_pos(self, veh_id: str) -> Tuple[float, float]: ...
    
    @property
    def pdn(self) -> Grid:
        """Power distribution network"""
        return self._pdn
    
    @property
    def start_time(self):
        """Simulation start time"""
        return self._st

    @property
    def end_time(self):
        """Simulation end time"""
        return self._et

    @property
    def step_len(self):
        """Simulation step length"""
        return self._step
    
    @property
    def cur_time(self):
        """Current time"""
        return self._ct
    
    @property
    def trip_logger(self) -> TripLogger:
        """Trip logger"""
        return self._log
    
    @property
    def gs(self) -> GSHub:
        """Gas station list"""
        return self._hubs.gs
    
    @property
    def fcs(self) -> FCSHub:
        """Fast charging station list"""
        return self._hubs.fcs

    @property
    def scs(self) -> SCSHub:
        """Slow charging station list"""
        return self._hubs.scs
    
    @property
    def stations(self) -> MixedHub:
        """All stations"""
        return self._hubs

    @property
    def vehs(self) -> VDict:
        """Vehicle dictionary, key is vehicle ID, value is EV instance"""
        return self._vehs
    
    @property
    def itertrips(self):
        """Get an iterator for all trips"""
        return chain(*(x.trips for x in self._vehs.values()))
    
    def get_sta_head(self) -> List[str]:
        """Get the names of all stations"""
        return self._hubs.fcs.get_names() + self._hubs.scs.get_names() + self._hubs.gs.get_names()

    def get_veh_count(self) -> List[int]:
        """Get the number of vehicles in all stations"""
        return self._hubs.fcs.get_veh_count() + self._hubs.scs.get_veh_count() + self._hubs.gs.get_veh_count()

    @property
    @abstractmethod
    def edges(self): 
        """Get all road instances"""
    
    @abstractmethod
    def get_edge_names(self) -> List[str]:
        """Get all road names"""
    
    # Backward compatibility
    current_time = cur_time  
    trips_logger = trip_logger
    GSList = gs
    FCSList = fcs
    SCSList = scs
    vehicles = vehs
    trips_iterator = itertrips
    
    @abstractmethod
    def simulation_start(self): ...

    @abstractmethod
    def simulation_step(self, step_len: int): ...

    def post_simulation_step(self, deltaT: int):
        # Process vehicles in charging stations and parked vehicles
        pb_g = self._gp(self._ct)
        Sb_kVA = self._pdn.Sb_kVA
        # Electricity price is $/puh. Convert to $/kWh
        pb_e = self._pdn._cp(self._ct) / Sb_kVA
        ps_e = self._pdn._dp(self._ct) / Sb_kVA
        gvs = self._hubs.gs.update(deltaT, self._ct, pb_g)
        for gv in gvs: self._end_restore(gv)
        evs = self._hubs.fcs.update(deltaT, self._ct, pb_e, ps_e)
        for ev in evs: self._end_restore(ev)
        evs = self._hubs.scs.update(deltaT, self._ct, pb_e, ps_e)
        assert len(evs) == 0, f"SCS should not release vehicles automatically, but got {len(evs)} vehicles."

        # Process faulty vehicles
        while not self._fQ.empty() and self._fQ.top[0] <= self._ct:
            _, v = self._fQ.pop()
            self._start_restore(self._vehs[v])
        
        if self._step_cb is not None:
            self._step_cb(self)
        
    def set_step_callback(self, callback: StepCallback):
        """
        Set a callback function to be called at each simulation step.
            callback: A function that takes the TrafficInst instance as an argument.
        """
        self._step_cb = callback
    
    def clear_step_callback(self):
        """Clear the step callback function."""
        self._step_cb = None

    @abstractmethod
    def simulation_stop(self): ...

    @abstractmethod
    def save(self, path: Union[str, Path]): ...

    @abstractmethod
    def _add_veh2(self, veh_id:str, O:str, D:str): ...

    def _start_restore(self, veh: Vehicle, dist: float = -1):
        veh.status = VehStatus.Charging
        assert isinstance(veh._cs, str)
        if isinstance(veh, EV):
            cs = self._hubs.fcs[veh._cs]
            if self._dist_based_restoration:
                ch_tar = veh._epm * self.find_route(cs._bind, veh.trip.D).length
                if ch_tar > veh._cap:
                    # Even if the battery is fully charged mid-way, the vehicle is still not able to reach the destination
                    self._log.warn_smallcap(self._ct, veh, ch_tar)
                veh._etar = min(veh._cap, max(veh._cap * 0.8, veh._kr * ch_tar))
            else:
                veh._etar = veh._cap  # Charge to full
            self._hubs.fcs.add_veh(veh, veh._cs)
            self._log.arrive_FCS(self._ct, veh, veh._cs, dist)
        elif isinstance(veh, GV):
            self._hubs.gs.add_veh(veh, veh._cs)
            self._log.arrive_GS(self._ct, veh, veh._cs, dist)
        else:
            raise RuntimeError(Lang.VEH_TYPE_NOT_SUPPORTED.format(veh._name, type(veh)))
    
    def _end_restore(self, veh: Vehicle):
        if veh._cs is None:
            raise RuntimeError(f"Runtime error: {self._ct}, {veh.brief()}, {veh.status}")
        trip = veh.trip
        if isinstance(veh, EV):
            self._log.depart_FCS(self._ct, veh, veh._cs)
            self._add_veh2(veh._name, self._hubs.fcs.get_bind_of(veh._cs), trip.D)
        elif isinstance(veh, GV):
            self._log.depart_GS(self._ct, veh, veh._cs)
            self._add_veh2(veh._name, self._hubs.gs.get_bind_of(veh._cs), trip.D)
        else:
            raise RuntimeError(Lang.VEH_TYPE_NOT_SUPPORTED.format(veh._name, type(veh)))
        
        veh._cs = None
        veh._etar = veh._cap # Reset the energy target
        veh.status = VehStatus.Pending
    
    def _start_charging_SCS(self, veh: EV, bind: str) -> bool:
        """
        Make a vehicle enter the charging state (slow charging station)
            veh: Vehicle instance
            bind: Node/edge where the vehicle is located
        """
        # Firstly, check if there is a private SCS at the destination
        target_scs:Optional[CS] = None
        scs_candidates:List[CS] = []
        for c in self._hubs.atbind[bind]:
            if isinstance(c, CS) and c._cs_type == CSType.SCS:
                scs_candidates.append(c)
                if c._owners is not None and veh._name in c._owners:
                    target_scs = c
                    break
        if target_scs is None:
            # No private SCS, choose the one with the shortest queue
            min_wt = float("inf")
            for scs in scs_candidates:
                wt = scs.wait_count()
                if wt < min_wt:
                    min_wt = wt
                    target_scs = scs
        if target_scs is None:
            # No available SCS at the location
            return False
        if self.scs.add_veh(veh, target_scs._name):
            # Do not directly add to a specific slow charging station here, or SCSHub will not be able to track the vehicle correctly
            self._log.join_SCS(self._ct, veh, target_scs._name)
            return True
        return False
    
    def _end_trip(self, veh: Vehicle, dist: float):
        """
        End the current trip of a vehicle and add its next trip to the departure queue.
        If the destination of the trip meets the charging conditions, try to charge.
            veh: Vehicle object
            dist: Distance traveled in this trip
        """
        veh.status = VehStatus.Parking
        arr_sta = TripLogger.ARRIVAL_NO_CHARGE
        if isinstance(veh, EV) and (veh.soc < veh._ks or veh._force_sc):
            # Add to the slow charge station
            veh._force_sc = False  # Clear the slow charge force flag
            if self._start_charging_SCS(veh, veh.trip.D):
                arr_sta = TripLogger.ARRIVAL_CHARGE_SUCCESSFULLY
            else:
                arr_sta = TripLogger.ARRIVAL_CHARGE_FAILED
        else:
            arr_sta = TripLogger.ARRIVAL_NO_CHARGE
        self._log.arrive(self._ct, veh, arr_sta, dist)
        tid = veh.next_trip()
        if tid != -1:
            ntrip = veh.trip
            self._que.push(ntrip.depart_time, (veh._name, None))
    
    def _prepare_stations(self, veh:Vehicle, to_stations: List[str], omega:float, to_charge: float, hub: StationHub):
        # Ds: bind(node/edge) -> station name
        # scores: bind(node/edge) -> score
        Ds:Dict[str, str] = {}; scores:Dict[str, float] = {}
        if len(to_stations) == 0:
            raise RuntimeError(Lang.NO_AVAILABLE_FCS if isinstance(veh, EV) else Lang.NO_AVAILABLE_GS)
        
        # Get station instances
        for name in to_stations:
            s: BaseStation = hub[name]; bind = s._bind
            score = omega * s.wait_count() * 30.0 + s.pbuy(self._ct, veh) * to_charge
            if bind in Ds: # Multiple stations at the same node/.edge, keep the one with smaller wt * omega + p
                if score < scores[bind]:
                    Ds[bind] = name; scores[bind] = score
            else: # New station
                Ds[bind] = name; scores[bind] = score
        return Ds, scores
    
    def get_queue_rate(self) -> float:
        """Calculate the average queue rate of all stations."""
        tot = 0; s_cnt = 0
        for s in self.stations:
            if not s._allow_que or s.slots == 0: continue
            tot += s.wait_count() / s.slots
            s_cnt += 1
        if s_cnt == 0:
            return 0.0
        return tot / s_cnt
    
    def get_total_queue_count(self) -> int:
        """Calculate the total number of vehicles in the queues of all stations."""
        return sum(s.wait_count() for s in self.stations if s._allow_que)
    
    @abstractmethod
    def get_average_vcr(self) -> float:
        """Calculate the smoothness of the traffic network."""
        raise NotImplementedError

    @abstractmethod
    def find_route(self, O: str, D: str) -> StageLike:
        """
        Find a route from O to D.
        
        :param O: Origin node/edge
        :param D: Destination node/edge
        :return: A route object (SUMO Stage or V2Sim Stage)
        """
        raise NotImplementedError
    
    @abstractmethod
    def find_best_station(self, veh: Vehicle, O: str, to_stations: List[str], omega:float,
            to_charge: float, max_dist: float, hub: StationHub) -> Tuple[str, StageLike]:
        """
        Find the best station to go from O.
        
        :param O: Origin node/edge
        :param to_stations: List of station names to choose from
        :param omega: Weight factor for waiting time
        :param to_charge: Amount of energy needed
        :param max_dist: Maximum distance allowed
        :param hub: Station hub containing stations
        :return: The best station name and the route to the selected station(SUMO Stage or V2Sim Stage)
        """
        raise NotImplementedError

    def add_trip(self, veh_id:str, trip:Trip, force_sc:bool = False, force_fc:bool = False, force_fcs:Optional[str] = None):
        """
        Add a new trip for a vehicle. The trip will be added to the departure queue, but not added to the vehicle's trip list.
            veh_id: Vehicle ID
            trip: Trip instance
            force_sc: Whether to force slow charging at the destination if needed
            force_fc: Whether to force fast charging on the way if needed
            force_fcs: If not None and force_fc is True, force fast charging at the specified fast charging station on the way
        Note: The force will not be set immediately. They will be set when the vehicle departs.
        """
        if veh_id not in self._vehs:
            raise RuntimeError(Lang.VEH_NOT_FOUND.format(veh_id))
        depart_time = trip.depart_time
        assert depart_time >= self._ct, Lang.DEPART_TIME_PASSED.format(veh_id, depart_time, self._ct)
        self._que.push(depart_time, (veh_id, (trip, force_sc, force_fc, force_fcs)))
    
    def add_veh(self, veh: Vehicle):
        """
        Add a new vehicle to the simulation. The vehicle will be added to the departure queue according to its first trip's departure time.
            veh: Vehicle instance
        """
        if veh._name in self._vehs:
            raise RuntimeError(Lang.VEH_ALREADY_EXISTS.format(veh._name))
        self._vehs[veh._name] = veh
        if len(veh.trips) > 0:
            tid = veh.trip_id
            while veh.trip.depart_time < self._ct:
                tid = veh.next_trip()
                if tid == -1: break
            if tid >= 0:
                self._que.push(veh.trip.depart_time, (veh._name, None))
    
    def add_station(self, station: Union[CS, GS]):
        """
        Add a new station to the simulation.
            station: Station instance
        """
        self._hubs.add_station(station)


@dataclass
class CommonConfig:
    routing_algorithm: str = "astar"
    gasoline_price: TimeFunc = ConstFunc(5.0)


@dataclass
class SUMOConfig:
    ignore_driving: bool = False
    suppress_route_not_found: bool = True
    gui: bool = False


@dataclass
class UXsimConfig:
    show_uxsim_info: bool = False
    randomize_uxsim: bool = False
    no_parallel: bool = False
