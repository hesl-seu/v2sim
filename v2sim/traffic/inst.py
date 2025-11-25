import platform
import random
import pickle
import gzip
from itertools import chain
from pathlib import Path
from typing import Any, Sequence, List, Tuple, Dict, Iterable, Optional, Union
from sumolib.net import readNet, Net
from sumolib.net.edge import Edge
from feasytools import PQueue
from scipy.spatial import KDTree
from .evdict import EVDict
from .trip import TripsLogger
from .cslist import *
from .ev import *
from .cs import *
from .params import *
from .win_vis import WINDOWS_VISUALIZE
from .utils import random_string, TWeights
from ..locale import Lang
from .utils import PyVersion, CheckPyVersion

SUMO_FILE_NAME = "traffic.gz"
TRAFFIC_INST_FILE_NAME = "inst.gz"

if platform.system() == "Linux":
    import libsumo as traci
else:  # Windows & Mac
    if WINDOWS_VISUALIZE:
        import traci
    else:
        import libsumo as traci

from traci._simulation import Stage

TC = traci.constants

def _mean(x: Sequence[float]) -> float:
    """Calculate the mean of a list of floats."""
    return sum(x) / len(x) if x else 0.0

def _argmin(x: Iterable[float]) -> int:
    """Find the index of the minimum value in a list of floats."""
    minv_i = -1
    minv = float('inf')
    for i, v in enumerate(x):
        if v < minv:
            minv = v
            minv_i = i
    return minv_i

class TrafficInst:
    def __find_route(self, e1: str, e2: str) -> Stage:
        if self.__force_static_routing: return self.__find_route_static(e1, e2)
        ret:Stage = traci.simulation.findRoute(
            e1, e2, routingMode=TC.ROUTING_MODE_AGGREGATED
        )
        if len(ret.edges) == 0:
            if SUPPRESS_ROUTE_NOT_FOUND:
                ret = Stage(edges=[e1, e2], length=1e9, travelTime=1e9)
                print(Lang.ERROR_ROUTE_NOT_FOUND.format(e1, e2))
            else:
                raise RuntimeError(Lang.ERROR_ROUTE_NOT_FOUND.format(e1, e2))
        return ret

    def __find_route_trip(self, t: Trip, cache_route:bool = False) -> Stage:
        if t.fixed_route:
            einst:List[Edge] = [self.__rnet.getEdge(e) for e in t.route]
            k = (t.route[0], t.route[-1])
            st = Stage(
                edges = t.route,
                length = sum(e.getLength() for e in einst),
                travelTime = sum(e.getLength() / e.getSpeed() for e in einst),
            )
            self.__shortest_paths[k] = st
            return st
        else:
            st = self.__find_route(t.route[0], t.route[-1])
            if cache_route:
                t.route = st.edges
            return st
    
    def __find_route_static(self, e1: str, e2: str) -> Stage:
        k = (e1, e2)
        if k not in self.__shortest_paths:
            stage:Stage = traci.simulation.findRoute(
                e1, e2, routingMode=TC.ROUTING_MODE_DEFAULT
            )
            if len(stage.edges) == 0:
                if SUPPRESS_ROUTE_NOT_FOUND:
                    stage = Stage(edges=[e1,e2], length=1e9, travelTime=1e9)
                    print(Lang.ERROR_ROUTE_NOT_FOUND.format(e1, e2))
                else:
                    raise RuntimeError(Lang.ERROR_ROUTE_NOT_FOUND.format(e1, e2))
            else:
                self.__shortest_paths[k] = stage
        return self.__shortest_paths[k]

    def __init__(
        self,
        road_net_file: str,
        start_time: int,
        step_len: int,
        end_time: int,
        clogfile: str,
        seed: int = 0, *,
        vehfile: str, veh_obj:Optional[EVDict] = None,
        fcsfile: str, fcs_obj:Optional[CSList] = None,
        scsfile: str, scs_obj:Optional[CSList] = None,
        initial_state_folder: str = "",
        routing_algo:str = "CH",
        force_static_routing:bool = False,
        ignore_driving:bool = False,
    ):
        """
        TrafficInst initialization
            road_net_file: SUMO road network configuration file
            start_time: Simulation start time
            end_time: Simulation end time
            clogfile: Log file path
            seed: Randomization seed
            vehfile: Vehicle information and itinerary file
            fcsfile: Fast charging station list file
            scsfile: Slow charging station list file
            initial_state_folder: Initial state folder path]
            routing_algo: Routing algorithm
            force_static_routing: Always use static routing to accelerate
            ignore_driving: Skip the battery update during driving, 
                only update the battery at origin and destination of a trip
        """
        random.seed(seed)
        self.__gui = None
        self.__logger = TripsLogger(clogfile)
        self.__ralgo = routing_algo
        self.__ignore_driving = ignore_driving
        assert self.__ralgo in ["CH", "dijkstra", "astar", "CHWrapper"], f"Invalid routing algorithm: {self.__ralgo}"
        
        self.__force_static_routing = force_static_routing
        self.__vehfile = vehfile
        self.__fcsfile = fcsfile
        self.__scsfile = scsfile
        self.__ctime: int = start_time
        self.__stime: int = start_time
        self.__step_len: int = step_len
        self.__etime: int = end_time
        
        # Read road network
        self.__rnet: Net = readNet(road_net_file)
        self.__edges: List[Edge] = self.__rnet.getEdges()
        # Get all road names
        self.__names: List[str] = [e.getID() for e in self.__edges]

        # Load static shortest paths
        self.__shortest_paths: Dict[Tuple[str,str], Stage] = {}

        self.__istate_folder = initial_state_folder

        if self.__istate_folder != "":
            self.__load_v2sim_state(self.__istate_folder)
            return
        
        # Load vehicles
        self._fQ:PQueue[str] = PQueue()  # Fault queue
        self._que:PQueue[Tuple[str, Any]] = PQueue()  # Departure queue
        self._VEHs = veh_obj if veh_obj else EVDict(vehfile)

        # Load charging stations
        self._fcs:CSList[FCS] = fcs_obj if fcs_obj else CSList(filePath=fcsfile, csType=FCS)
        self._scs:CSList[SCS] = scs_obj if scs_obj else CSList(filePath=scsfile, csType=SCS)
        self.__names_fcs: List[str] = [cs.name for cs in self._fcs]
        self.__names_scs: List[str] = [cs.name for cs in self._scs]

        # Load vehicles to charging stations and prepare to depart
        for veh in self._VEHs.values():
            self._que.push(veh.trip.depart_time, (veh.ID, None))
            if veh.trip.depart_edge not in self.__names_scs:
                continue  # Only vehicles with slow charging stations can be added to the slow charging station
            # There is a 20% chance of adding to a rechargeable parking point
            if veh.SOC < veh.ksc or random.random() <= 0.2:
                self._scs.add_veh(veh, veh.trip.depart_edge)

    @property
    def trips_logger(self) -> TripsLogger:
        """Trip logger"""
        return self.__logger
    
    @property
    def veh_file(self):
        """Vehicle information and itinerary file"""
        return self.__vehfile

    @property
    def fcs_file(self):
        """Fast charging station list file"""
        return self.__fcsfile
    
    @property
    def scs_file(self):
        """Slow charging station list file"""
        return self.__scsfile
    
    @property
    def start_time(self):
        """Simulation start time"""
        return self.__stime

    @property
    def end_time(self):
        """Simulation end time"""
        return self.__etime

    @property
    def step_len(self):
        """Simulation step length"""
        return self.__step_len
    
    @property
    def current_time(self):
        """Current time"""
        return self.__ctime

    @property
    def FCSList(self) -> CSList[FCS]:
        """Fast charging station list"""
        return self._fcs

    @property
    def SCSList(self) -> CSList[SCS]:
        """Slow charging station list"""
        return self._scs

    @property
    def vehicles(self) -> EVDict:
        """Vehicle dictionary, key is vehicle ID, value is EV instance"""
        return self._VEHs

    def __add_veh(self, veh_id: str, route: List[str]):
        self._VEHs[veh_id].clear_odometer()
        rou_id = random_string(16)
        traci.route.add(rou_id, route)
        traci.vehicle.add(veh_id, rou_id)
    
    def __add_veh2(self, veh_id:str, st_edge:str, ed_edge:str, agg_routing:bool = False):
        self._VEHs[veh_id].clear_odometer()
        try:
            traci.vehicle.add(veh_id, "")
            traci.vehicle.setRoute(veh_id, [st_edge])
            if agg_routing:
                traci.vehicle.setRoutingMode(veh_id, TC.ROUTING_MODE_AGGREGATED)
            traci.vehicle.changeTarget(veh_id, ed_edge)
        except Exception as e:
            raise RuntimeError(f"(Time = {self.__ctime})Fail to add vehicle '{veh_id}' into SUMO: {st_edge}->{ed_edge}") from e

    @property
    def edges(self) -> List[Edge]:
        """Get all roads"""
        return self.__edges

    @property
    def trips_iterator(self):
        """Get an iterator for all trips"""
        return chain(*(x.trips for x in self._VEHs.values()))

    def get_edge_names(self) -> List[str]:
        """Get the names of all roads"""
        return self.__names
    
    def __sel_best_CS(
        self, veh: EV, omega: float, current_edge: Optional[str] = None, cur_pos: Optional[Tuple[float, float]] = None
    ) -> Tuple[List[str], TWeights]:
        """
        Select the nearest available charging station based on the edge where the car is currently located, and return the path and average weight
            veh: Vehicle instance
            omega: Weight
            current_edge: Current road, if None, it will be automatically obtained
        Return:
            Path(List[str]), Weight(Tuple[float,float,float])
            If no charging station is found, return [],(-1,-1,-1)
        """
        to_charge = veh.charge_target - veh.battery
        c_edge = (
            traci.vehicle.getRoadID(veh.ID) if current_edge is None else current_edge
        )

        cur_pos = (traci.vehicle.getPosition(veh.ID) if cur_pos is None else cur_pos)

        # Distance check
        cs_names: List[str] = []
        wait_cnt: List[int] = []
        prices: List[float] = []
        stages: List[Stage] = []
        for cs_i in self._fcs.select_near(cur_pos,10):
            cs = self._fcs[cs_i]
            if cs.is_offline(self.__ctime): continue
            stage = self.__find_route(c_edge, cs.name)
            if veh.is_batt_enough(stage.length):
                cs_names.append(cs.name)
                wait_cnt.append(cs.wait_count())
                prices.append(cs.pbuy(self.__ctime))
                stages.append(stage)

        if len(cs_names) == 0:
            return [], (-1, -1, -1)

        t_drive = [t.travelTime / 60 for t in stages]  # Convert travel time to minutes
        t_wait = [wait_cnt * 30 for wait_cnt in wait_cnt]  # Queue time: 30 minutes per vehicle

        # Total weight
        weight = [
            omega * (td + tw) + to_charge * p for td, tw, p in zip(t_drive, t_wait, prices)
        ]

        wret = (_mean(t_drive), _mean(t_wait), _mean(prices))
        # Return the path and weight to the charging station with the minimum weight
        return stages[_argmin(weight)].edges, wret

    def __get_edge_pos(self, eid:str) -> Tuple[float, float]:
        e:Edge = self.__rnet.getEdge(eid)
        sp = e.getShape()
        assert isinstance(sp, list) and len(sp) > 0
        return sp[0][0], sp[0][1]
    
    def __start_trip(self, veh_id: str) -> Tuple[bool, Optional[TWeights]]:
        """
        Start the current trip of a vehicle
            veh_id: Vehicle ID
        Return:
            Departure succeeded: True, Fast charging station selection weight (if fast charging is required)
            Departure failed: False, None
        """
        weights = None
        veh = self._VEHs[veh_id]
        trip = veh.trip
        direct_depart = True

        if ENABLE_DIST_BASED_CHARGING_DECISION:
            stage = self.__find_route_trip(trip, veh._cache_route)
            # Determine whether the battery is sufficient
            direct_depart = (not veh._force_fc) and veh.is_batt_enough(stage.length)
        else:
            # Determine whether the EV needs to be fast charged
            stage = None
            direct_depart = (not veh._force_fc) and veh.SOC >= veh.kfc
        if direct_depart:  # Direct departure
            veh.target_CS = None
            veh.charge_target = veh.full_battery
            if stage:
                self.__add_veh(veh_id, stage.edges)
            else:
                self.__add_veh2(veh_id, trip.depart_edge, trip.arrive_edge)
        else:  # Charge once on the way
            if veh._force_fc is not None and veh._force_fcs is not None:
                # Forced to a specified fast charging station
                veh.target_CS = veh._force_fcs
                self.__add_veh2(veh_id, trip.depart_edge, veh._force_fcs)
            else:
                x, y = self.__get_edge_pos(trip.depart_edge)
                route, weights = self.__sel_best_CS(veh, veh.omega, trip.depart_edge, (x, y))
                if len(route) == 0:
                    # The power is not enough to drive to any charging station, you need to charge for a while
                    veh.target_CS = None
                    veh._force_fc = False  # Clear the fast charge force flag
                    veh._force_fcs = None  # Clear the fast charge target flag
                    return False, None
                else: # Found a charging station
                    veh.target_CS = route[-1]
                    self.__add_veh(veh_id, route)
        # Stop slow charging of the vehicle and add it to the waiting to depart set
        if self._scs.pop_veh(veh):
            self.__logger.leave_SCS(self.__ctime, veh, trip.depart_edge)
        veh.stop_charging()
        veh.status = VehStatus.Pending
        veh._force_fc = False  # Clear the fast charge force flag
        veh._force_fcs = None  # Clear the fast charge target flag
        return True, weights

    def __end_trip(self, veh_id: str, dist:float = -1):
        """
        End the current trip of a vehicle and add its next trip to the departure queue.
        If the destination of the trip meets the charging conditions, try to charge.
            veh: Vehicle object
        """
        veh = self._VEHs[veh_id]
        veh.status = VehStatus.Parking
        arr_sta = TripsLogger.ARRIVAL_NO_CHARGE
        if veh.SOC < veh.ksc or veh._force_sc:
            # Add to the slow charge station
            if self.__start_charging_SCS(veh):
                arr_sta = TripsLogger.ARRIVAL_CHARGE_SUCCESSFULLY
            else:
                arr_sta = TripsLogger.ARRIVAL_CHARGE_FAILED
        else:
            arr_sta = TripsLogger.ARRIVAL_NO_CHARGE
        self.__logger.arrive(self.__ctime, veh, arr_sta, dist)
        tid = veh.next_trip()
        if tid != -1:
            ntrip = veh.trip
            self._que.push(ntrip.depart_time, (veh.ID, None))

    def __start_charging_SCS(self, veh: EV) -> bool:
        """
        Make a vehicle enter the charging state (slow charging station)
            veh: Vehicle instance
        """
        ret = False
        try:
            self._scs.add_veh(veh, veh.trip.arrive_edge)
            ret = True
        except:
            pass
        if ret:
            self.__logger.join_SCS(self.__ctime, veh, veh.trip.arrive_edge)
        return ret

    def __start_charging_FCS(self, veh: EV, dist:float = -1):
        """
        Make a vehicle enter the charging state (fast charging station)
            veh: Vehicle instance
        """
        veh.status = VehStatus.Charging
        assert isinstance(veh.target_CS, str)
        if ENABLE_DIST_BASED_CHARGING_QUANTITY:
            ch_tar = (
                veh.consumption
                * self.__find_route_static(veh.target_CS, veh.trip.arrive_edge).length
            )
            if ch_tar > veh.full_battery:
                # Even if the battery is fully charged mid-way, the vehicle is still not able to reach the destination
                self.__logger.warn_smallcap(self.__ctime, veh, ch_tar)
            veh.charge_target = min(
                veh.full_battery, max(veh.full_battery * 0.8, veh.krel * ch_tar)
            )
        else:
            veh.charge_target = veh.full_battery
        self._fcs.add_veh(veh, veh.target_CS)
        self.__logger.arrive_CS(self.__ctime, veh, veh.target_CS, dist)

    def __end_charging_FCS(self, veh: EV):
        """
        Make a vehicle end charging and depart (fast charging station)
            veh: Vehicle instance
        """
        if veh.target_CS is None:
            raise RuntimeError(
                f"Runtime error: {self.__ctime}, {veh.brief()}, {veh.status}"
            )
        trip = veh.trip
        self.__logger.depart_CS(self.__ctime, veh, veh.target_CS)
        
        self.__add_veh2(veh.ID, veh.target_CS, trip.arrive_edge)
        veh.target_CS = None
        veh.charge_target = veh.full_battery
        veh.status = VehStatus.Pending
        veh.stop_charging()

    def __get_nearest_CS(
        self, cur_edge: str
    ) -> Tuple[Optional[str], float, Optional[Stage]]:
        """
        Find the nearest charging station
            cur_edge: Current road
        """
        min_cs_name = None
        min_cs_dist = 1e400
        min_cs_stage = None
        for cs in self._fcs.get_online_CS_names(self.__ctime):
            route = self.__find_route(cur_edge, cs)
            if route.length < min_cs_dist:
                min_cs_dist = route.length
                min_cs_name = cs
                min_cs_stage = route
        return min_cs_name, min_cs_dist, min_cs_stage

    def __batch_depart(self) -> Dict[str, Optional[TWeights]]:
        """
        All vehicles that arrive at the departure queue are sent out
            self.__ctime: Current time, in seconds
        Return:
            Departure dictionary, the key is the vehicle ID, and the value is the fast charging station selection parameter (if there is no need to go to the fast charging station, it is None)
        """
        ret = {}
        while not self._que.empty() and self._que.top[0] <= self.__ctime:
            depart_time, (veh_id, extras) = self._que.pop()
            veh = self._VEHs[veh_id]
            if extras is not None:
                trip, force_sc, force_fc, force_fcs = extras
                veh._force_sc = force_sc
                veh._force_fc = force_fc
                veh._force_fcs = force_fcs
                assert isinstance(trip, Trip)
            else:
                trip = veh.trip
            success, weights = self.__start_trip(veh_id)
            if success:
                depart_delay = max(0, self.__ctime - depart_time)
                self.__logger.depart(self.__ctime, veh, depart_delay, veh.target_CS)
                ret[veh_id] = weights
            else:
                cs_name, cs_dist, cs_stage = self.__get_nearest_CS(trip.depart_edge)
                batt_req = cs_dist * veh.consumption * veh.krel
                if self._scs.has_veh(veh.ID):
                    # Plugged in the charging pile, you can wait
                    delay = int(1 + (batt_req - veh.battery) / veh.rate)
                    self.__logger.depart_delay(self.__ctime, veh, batt_req, delay)
                    self._que.push(depart_time + delay, (veh_id, None))
                else:
                    # Not plugged in the charging pile, sent to the nearest fast charging station (consume 2 times of the running time)
                    veh.status = VehStatus.Depleted
                    assert cs_name is not None and cs_stage is not None, "No FCS found, please check the configuration"
                    veh.target_CS = cs_name
                    trT = int(self.__ctime + 2 * cs_stage.travelTime)
                    self._fQ.push(trT, veh.ID)
                    self.__logger.depart_failed(self.__ctime, veh, batt_req, cs_name, trT)
        return ret

    def get_sta_head(self) -> List[str]:
        """
        Get the edge name corresponding to the return value of get_veh_count and CS_PK_update
        """
        return self.__names_fcs + self.__names_scs

    def get_veh_count(self) -> List[int]:
        """
        Get the number of parked vehicles in all charging station and non-charging station edges
        """
        return self._fcs.get_veh_count() + self._scs.get_veh_count()
    
    def add_trip(self, veh_id:str, trip:Trip, force_sc:bool = False, force_fc:bool = False, force_fcs:Optional[str] = None):
        """
        Add a new trip for a vehicle
            veh_id: Vehicle ID
            trip: Trip instance
            force_sc: Whether to force slow charging at the destination if needed
            force_fc: Whether to force fast charging on the way if needed
            force_fcs: If not None and force_fc is True, force fast charging at the specified fast charging station on the way
        Note: The force will not be set immediately. They will be set when the vehicle departs.
        """
        if veh_id not in self._VEHs:
            raise RuntimeError(Lang.VEH_NOT_FOUND.format(veh_id))
        depart_time = trip.depart_time
        assert depart_time >= self.__ctime, Lang.DEPART_TIME_PASSED.format(veh_id, depart_time, self.__ctime)
        self._que.push(depart_time, (veh_id, (trip, force_sc, force_fc, force_fcs)))
    
    def simulation_start(
        self,
        sumocfg_file: str,
        net_file: str,
        start_time: Optional[int] = None,
        gui: bool = True,
    ):
        """
        Start simulation
            sumocfg_file: SUMO configuration file path
            start_time: Start time (seconds), if not specified, provided by the SUMO configuration file
            gui: Whether to display the graphical interface
        """
        self.__gui = gui
        sumoCmd = [
            "sumo-gui" if self.__gui else "sumo",
            "-c", sumocfg_file,
            "-n", net_file,
            "--no-warnings",
            "--routing-algorithm", self.__ralgo,
            # Keep the vehicle in the network for a exactly one step after arriving at the destination
            "--keep-after-arrival", str(self.__step_len),
        ]
        if start_time is not None:
            sumoCmd.extend(["-b", str(start_time)])
        traci.start(sumoCmd)

        if self.__istate_folder:
            self.__load_sumo_state(self.__istate_folder)
            self.__istate_folder = ""
        
        self.__ctime = int(traci.simulation.getTime())
        self.__batch_depart()

        for cs in chain(self.FCSList, self.SCSList):
            if cs._x == float('inf') or cs._y == float('inf'):
                cs._x, cs._y = self.__get_edge_pos(cs.name)
        
        if self.FCSList._kdtree == None:
            self.FCSList._kdtree = KDTree(
                [(cs._x, cs._y) for cs in self.FCSList],
            )
        
        if self.SCSList._kdtree == None:
            self.SCSList._kdtree = KDTree(
                [(cs._x, cs._y) for cs in self.SCSList],
            )

    def simulation_step(self, step_len: int):
        """
        Simulation step.
            step_len: Step length (seconds)
            v2g_demand: V2G demand list (kWh/s)
        """
        traci.simulationStep(float(self.__ctime + step_len))
        new_time = int(traci.simulation.getTime())
        deltaT = new_time - self.__ctime
        self.__ctime = new_time
        
        # Depart vehicles before processing arrivals
        # If a vehicle arrives and departs in the same step, performing departure after arrival immediately will cause the vehicle to be unable to depart
        # Therefore, all departures are processed first can delay the departure to the next step and cause no problem
        self.__batch_depart()

        # Process arrived vehicles
        arr_vehs: List[str] = traci.simulation.getArrivedIDList()
        for v in arr_vehs:
            veh = self._VEHs[v]
            dist = traci.vehicle.getDistance(v)
            veh.drive(dist)
            if veh.target_CS is None:
                self.__end_trip(v, dist)
            else:
                self.__start_charging_FCS(self._VEHs[v], dist)

        if self.__ignore_driving:
            # Process departed vehicles
            dep_vehs: List[str] = traci.simulation.getDepartedIDList()
            for v in dep_vehs:
                veh = self._VEHs[v]
                if veh._sta == VehStatus.Pending:
                    veh._sta = VehStatus.Driving
        else:
            # Process driving vehicles
            cur_vehs: List[str] = traci.vehicle.getIDList()
            for veh_id in cur_vehs:
                veh = self._VEHs[veh_id]
                veh.drive(traci.vehicle.getDistance(veh_id))
                if veh._elec <= 0:
                    # Vehicles with depleted batteries will be sent to the nearest fast charging station (time * 2)
                    veh._sta = VehStatus.Depleted
                    cur_edge = traci.vehicle.getRoadID(veh_id)
                    veh._cs, _, cs_stage = self.__get_nearest_CS(cur_edge)
                    assert cs_stage is not None and veh.target_CS is not None
                    trT = int(self.__ctime + 2 * cs_stage.travelTime)
                    self._fQ.push(trT, veh_id)
                    traci.vehicle.remove(veh_id)
                    self.__logger.fault_deplete(self.__ctime, veh, veh.target_CS, trT)
                    continue
                if veh._sta == VehStatus.Pending:
                    veh._sta = VehStatus.Driving
                if veh._sta == VehStatus.Driving:
                    if veh.target_CS is not None and self._fcs[veh.target_CS].is_offline(self.__ctime):
                        # Target FCS is offline, redirected to the nearest FCS
                        route, weights = self.__sel_best_CS(veh, veh.omega)
                        if len(route) == 0:  
                            # The power is not enough to drive to any charging station, remove from the network
                            veh._sta = VehStatus.Depleted
                            traci.vehicle.remove(veh_id)
                            self._fQ.push(self.__ctime, veh_id)
                            self.__logger.fault_nocharge(self.__ctime, veh, veh.target_CS)
                            veh.target_CS = None
                        else:  # Found the charging station
                            new_cs = route[-1]
                            traci.vehicle.setRoute(veh_id, route)
                            self.__logger.fault_redirect(self.__ctime, veh, veh.target_CS, new_cs)
                            veh.target_CS = new_cs
                else:
                    print(f"Error: {veh.brief()}, {veh._sta}")

        # Process vehicles in charging stations and parked vehicles
        evs = self._fcs.update(deltaT, self.__ctime)
        for ev in evs:
            self.__end_charging_FCS(ev)
        self._scs.update(deltaT, self.__ctime)

        # Process faulty vehicles
        while not self._fQ.empty() and self._fQ.top[0] <= self.__ctime:
            _, v = self._fQ.pop()
            self.__start_charging_FCS(self._VEHs[v])

    def simulation_stop(self):
        if self.__gui is None:
            raise RuntimeError("Simulation has not started. Call 'simulation_start' first.")
        traci.close()
        self.__logger.close()

    def save(self, folder: Union[str, Path]):
        """
        Save the current state of the simulation
            folder: Folder path
        """
        f = Path(folder) if isinstance(folder, str) else folder
        f.mkdir(parents=True, exist_ok=True)
        traci.simulation.saveState(str(f / SUMO_FILE_NAME))
        obj = {
            "ctime":self.__ctime,
            "fQ":self._fQ,
            "que":self._que,
            "VEHs":self._VEHs,
            "fcs":self._fcs,
            "scs":self._scs,
            "names_fcs":self.__names_fcs,
            "names_scs":self.__names_scs,
        }
        with gzip.open(str(f / TRAFFIC_INST_FILE_NAME), "wb") as f:
            pickle.dump({
                "obj": obj,
                "version": PyVersion(),
                "pickler": pickle.__name__,
            }, f)
    
    save_state = save  # Alias        
    
    def __load_v2sim_state(self, folder: str):
        inst = Path(folder) / TRAFFIC_INST_FILE_NAME
        if not inst.exists():
            raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(inst))
        with gzip.open(str(inst), "rb") as f:
            d = pickle.load(f)
        assert isinstance(d, dict) and "obj" in d and "pickler" in d and "version" in d, "Invalid TrafficInst state file."
        if not CheckPyVersion(d["version"]):
            raise RuntimeError(f"Python version mismatch for TrafficInst: Expect {PyVersion()}, got {d["version"]}")
        if d["pickler"] != pickle.__name__:
            raise RuntimeError(f"Pickler mismatch for TrafficInst: Expect {pickle.__name__}, got {d["pickler"]}")
        d = d["obj"]
        self.__ctime = d["ctime"]
        self._fQ = d["fQ"]
        self._que = d["que"]
        self._VEHs = d["VEHs"]
        self._fcs = d["fcs"]
        self._scs = d["scs"]
        self.__names_fcs = d["names_fcs"]
        self.__names_scs = d["names_scs"]
    
    def __load_sumo_state(self, folder: str):
        traffic = Path(folder) / SUMO_FILE_NAME
        if not traffic.exists():
            raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(traffic))
        traci.simulation.loadState(str(traffic))

    def load_state(self, folder: str):
        """
        Load the state of the simulation
            folder: Folder path
        """
        self.__load_v2sim_state(folder)
        self.__load_sumo_state(folder)

__all__ = ["TrafficInst", "TRAFFIC_INST_FILE_NAME", "SUMO_FILE_NAME"]