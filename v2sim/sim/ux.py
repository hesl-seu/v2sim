import cloudpickle as pickle
import gzip, math
from fpowerkit import Grid
from feasytools import TimeFunc
from dataclasses import asdict
from itertools import chain
from warnings import warn
from pathlib import Path
from typing import List, Optional, Union
from ..utils import *
from ..hub import *
from ..veh import *
from ..locale import Lang
from ..net import RoadNet
from .routing import *
from .uxsim import Link
from .tlog import TripLogger
from .utils import CaseData
from .base import CommonConfig, TrafficInst, TRAFFIC_INST_FILE_NAME, UXsimConfig

WORLD_FILE_NAME = "world.gz"
ATTR_UX_DEST_SCS = "_ux_dest_scs"
UX_SCS_SEARCH_RADIUS_M = 200.0


class TrafficUX(TrafficInst):
    def __init__(
        self, start_time: int, step_len: int, end_time: int, 
        roadnet:RoadNet, trip_logger: TripLogger, vehs: VDict, 
        hubs: MixedHub, pdn: Grid, gasoline_price: TimeFunc, 
        seed: int = 0, silent: bool = False, *,
        add_veh_to_scs: bool = False,
        allow_scs_redirect: bool = False,
        routing_algorithm: str = "dijkstra",  # or "astar"
        show_uxsim_info: bool = False,
        randomize_uxsim: bool = True,
        no_parallel: bool = False,
        internal_step_len: Optional[int] = None
    ):  
        super().__init__(start_time, step_len, end_time, roadnet, trip_logger, vehs, hubs, pdn, gasoline_price, seed, silent)
        self.__stall_warned = False
        self.__stall_count = 0
        self.__stall_last_check = 0
        
        assert routing_algorithm in ("dijkstra", "astar"), Lang.ROUTE_ALGO_NOT_SUPPORTED
        self.__use_astar = routing_algorithm == "astar"
        self.__allow_scs_redirect = allow_scs_redirect
        self.__instant_arrivals = set()
        self.__speed_upper_bound = max(
            (float(edge.speed_limit) for edge in self._rnet.edges.values() if edge.speed_limit > 0),
            default=0.0,
        )
        
        # Get all road names
        self.__names: List[str] = list(self._rnet.edges.keys())
        
        # Check if all CS are in the largest SCC
        bad_s = set(s._bind for s in self._hubs if not self._rnet.is_node_in_largest_scc(s._bind))
        if len(bad_s) > 0 and not self.silent:
            warn(Lang.WARN_CS_NOT_IN_SCC.format(','.join(bad_s)))
        
        # Create uxsim world
        create_func = self._rnet.create_singleworld if no_parallel else self._rnet.create_world
        self.__show_uxsim_info = show_uxsim_info
        self.W = create_func(
            tmax=end_time,
            deltan=1,
            reaction_time=1 if internal_step_len is None else internal_step_len,
            random_seed=seed,
            hard_deterministic_mode=not randomize_uxsim,
            reduce_memory_delete_vehicle_route_pref=True,
            print_mode=1 if self.__show_uxsim_info else 0,
            silent=self.silent,
        )
        if not self.silent:
            from .uxworld import ParaWorlds
            if isinstance(self.W, ParaWorlds):
                print(Lang.PARA_WORLDS.format(len(self.W.worlds)))
            else:
                print(Lang.SINGLE_WORLD)

        super()._prepare_trips_and_scs(add_veh_to_scs)

    def get_veh_pos(self, veh_id: str) -> Tuple[float, float]:
        return self.W.get_vehicle(veh_id).get_xy_coords()
    
    def get_average_vcr(self) -> float:
        speed_prop_sum = 0.0
        link_cnt = 0
        for link in self.W.links():
            speed_prop_sum += float(link.speed / link.free_flow_speed)
            link_cnt += 1
        speed_prop = 1.0 if link_cnt == 0 else speed_prop_sum / link_cnt
        return speed_prop
    
    def find_route(self, O: str, D: str, fastest:bool = True) -> Stage:
        """
        Find the best route from node O to node D.
        
        :param fastest: True = fastest route, False = shortest route
        """
        if O == D:
            return Stage([O], [], 0.0, 0.0)
        if self.__use_astar:
            if fastest:
                return astarF(
                    self.W.get_gl(), self.W.get_coords(), self._ct, O, D,
                    self.__speed_upper_bound,
                )
            else:
                return astarS(self.W.get_gl(), self.W.get_coords(), self._ct, O, D)
        else:
            if fastest:
                return dijMF(self.W.get_gl(), self._ct, O, {D})
            else:
                return dijMS(self.W.get_gl(), self._ct, O, {D})
        
    def find_best_route(self, O:str, Ds:Iterable[str], fastest:bool = True):
        """
        Find the best route from O to one of Ds.
        
        :param O: Origin node/edge
        :param Ds: Destination nodes/edges
        :param fastest: Whether to find the fastest route (True) or the shortest route (False)
        """
        if self.__use_astar:
            if fastest:
                return astarMF(self.W.get_gl(), self.W.get_coords(), self._ct,
                    O, Ds, self.__speed_upper_bound)
            else:
                return astarMS(self.W.get_gl(), self.W.get_coords(), self._ct, O, Ds)
        else:
            if fastest:
                return dijMF(self.W.get_gl(), self._ct, O, Ds)
            else:
                return dijMS(self.W.get_gl(), self._ct, O, Ds)
    
    def find_best_station(self, veh: Vehicle, O:str, to_stations: List[str], omega:float, 
            to_charge:float, max_dist:float, hub: StationHub) -> Tuple[str, Stage]:
        """
        Find the best station to go from O.
        
        :param O: Origin node/edge
        :param to_stations: List of station names to choose from
        :param omega: Weight factor for waiting time
        :param to_charge: Amount of energy needed
        :param max_dist: Maximum distance allowed
        :param hub: Station hub containing stations
        :return: The best station name and the route to the selected station
        """
        Ds, scores = self._prepare_stations(veh, to_stations, omega, to_charge, hub)

        if self.__use_astar:
            ret = astarMC(self.W.get_gl(), self.W.get_coords(), self._ct, O, omega, Ds.keys(),
                scores, max_dist, self.__speed_upper_bound)
        else:
            ret = dijMC(self.W.get_gl(), self._ct, O, omega, Ds.keys(), scores, max_dist)
        
        if len(ret.nodes) == 0:  # No available station within range
            return "", ret
        return Ds[ret.nodes[-1]], ret
    
    @property
    def routing_algo(self) -> str:
        """Routing algorithm, can be "dijkstra" or "astar" """
        return "astar" if self.__use_astar else "dijkstra"
    
    @property
    def show_uxsim_info(self) -> bool:
        """Whether to display uxsim information"""
        return self.__show_uxsim_info

    def __route_length(self, route: Union[Stage, List[str]]) -> float:
        """Return a V2Sim-planned route length for canonical energy accounting."""
        if isinstance(route, Stage):
            return max(0.0, float(route.length))
        length = 0.0
        for edge_id in route:
            try:
                length += float(self._rnet.get_edge(edge_id).length)
            except Exception:
                pass
        return max(0.0, length)

    def __node_xy(self, node_id: str) -> Tuple[float, float]:
        """Return node coordinates in the same metre-based plane as UXsim."""
        return self._rnet.get_node(node_id).get_coord()

    @staticmethod
    def __estimated_soc_after(veh: EV, distance: float) -> float:
        return (veh._energy - distance * veh._epm) / veh._cap

    def __select_scs_near_destination(
        self, veh: EV, trip: Trip
    ) -> Tuple[Optional[CS], Optional[Stage], float]:
        """Select an online SCS near the destination in the node-based network."""
        try:
            dx, dy = self.__node_xy(trip.D)
        except Exception:
            return None, None, 0.0

        best_scs: Optional[CS] = None
        best_stage: Optional[Stage] = None
        best_length = 0.0
        best_score = (1, float("inf"), float("inf"))

        for scs in self.SCSList:
            if not scs.is_online(self._ct):
                continue
            try:
                if math.isfinite(scs._x) and math.isfinite(scs._y):
                    sx, sy = float(scs._x), float(scs._y)
                else:
                    sx, sy = self.__node_xy(scs._bind)
            except Exception:
                continue

            dist = math.hypot(sx - dx, sy - dy)
            if dist > UX_SCS_SEARCH_RADIUS_M:
                continue

            try:
                stage = self.find_route(trip.O, scs._bind)
            except Exception:
                continue
            if len(stage.nodes) == 0:
                continue

            owner_rank = 0 if scs._owners is not None and veh._name in scs._owners else 1
            score = (owner_rank, scs.wait_count(), dist)
            if score < best_score:
                best_score = score
                best_scs = scs
                best_stage = stage
                best_length = stage.length

        return best_scs, best_stage, best_length

    def __maybe_redirect_trip_to_scs(
        self, veh: Vehicle, base_stage: Stage, base_length: float
    ) -> Tuple[Stage, float]:
        if not isinstance(veh, EV):
            return base_stage, base_length

        trip = veh.trip
        estimated_soc = self.__estimated_soc_after(veh, base_length)
        if estimated_soc > veh._ks:
            return base_stage, base_length

        scs, scs_stage, scs_length = self.__select_scs_near_destination(veh, trip)
        if scs is None or scs_stage is None:
            return base_stage, base_length

        trip.D = scs._bind
        trip.DPos = None
        trip.edges = None
        veh._force_sc = True
        setattr(veh, ATTR_UX_DEST_SCS, scs._name)

        next_idx = veh.trip_id + 1
        if next_idx < len(veh.trips):
            next_trip = veh.trips[next_idx]
            next_trip.O = scs._bind
            next_trip.OPos = None
            next_trip.edges = None

        return scs_stage, scs_length

    def __start_charging_SCS_by_name(self, veh: EV, scs_name: str) -> bool:
        if scs_name not in self._hubs.scs:
            return False
        scs = self._hubs.scs[scs_name]
        if not scs.is_online(self._ct):
            return False
        if self.scs.add_veh(veh, scs_name):
            self._log.join_SCS(self._ct, veh, scs_name)
            return True
        return False

    def _end_trip(self, veh: Vehicle, dist: float):
        """End a UXsim trip, honoring an explicit SCS redirect target when set."""
        veh.status = VehStatus.Parking
        arr_sta = TripLogger.ARRIVAL_NO_CHARGE
        if isinstance(veh, EV):
            target_scs = getattr(veh, ATTR_UX_DEST_SCS, None)
            if target_scs is not None:
                veh._force_sc = False
                if self.__start_charging_SCS_by_name(veh, target_scs):
                    arr_sta = TripLogger.ARRIVAL_CHARGE_SUCCESSFULLY
                else:
                    arr_sta = TripLogger.ARRIVAL_CHARGE_FAILED
                delattr(veh, ATTR_UX_DEST_SCS)
            elif veh.soc < veh._ks or veh._force_sc:
                veh._force_sc = False
                if self._start_charging_SCS(veh, veh.trip.D):
                    arr_sta = TripLogger.ARRIVAL_CHARGE_SUCCESSFULLY
                else:
                    arr_sta = TripLogger.ARRIVAL_CHARGE_FAILED
        self._log.arrive(self._ct, veh, arr_sta, dist)
        tid = veh.next_trip()
        if tid != -1:
            ntrip = veh.trip
            self._que.push(ntrip.depart_time, (veh._name, None))

    @staticmethod
    def __ctpl_or(measured_distance: float, veh: Vehicle) -> float:
        ctpl = getattr(veh, "current_trip_planned_length", 0.0)
        return ctpl if ctpl > EPS else measured_distance

    def _add_veh(
        self,
        veh_id: str,
        from_node: str,
        to_node: str,
        route: Union[Stage, List[str]],
        planned_length: Optional[float] = None,
    ):
        veh = self._vehs[veh_id]
        veh.clear_odometer()
        veh.current_trip_planned_length = (
            self.__route_length(route) if planned_length is None else planned_length
        )
        self.W.add_vehicle(veh_id, from_node, to_node, route)

    def _add_veh2(
        self,
        veh_id: str,
        O: str,
        D: str,
        planned_length: Optional[float] = None,
    ):
        stage = self.find_route(O, D)

        if planned_length is None:
            planned_length = stage.length

        self._add_veh(
            veh_id,
            O,
            D,
            stage,
            planned_length=planned_length,
        )

    @property
    def edges(self):
        """Get all roads"""
        return list(self._rnet.edges.values())

    def get_edge_names(self) -> List[str]:
        """Get the names of all roads"""
        return self.__names
    
    def __sel_best_station(
        self, veh: Vehicle, cur_node: Optional[str] = None, cur_edge: Optional[str] = None
    ) -> Tuple[str, Stage]:
        """
        Select the best available station (FCS/GS) based on the edge where the car is currently located, and return the path and average weight
        
        :param veh: Vehicle instance
        :param cur_node: Current node, if None, it will be automatically obtained
        :param cur_edge: Current road, if None, it will be automatically obtained
        :return: The best station name and the route to the selected station
        """
        to_charge = veh._etar - veh._energy
        
        if cur_node is None:
            if not self.W.has_vehicle(veh._name):
                raise RuntimeError(Lang.VEH_NOT_FOUND.format(veh._name))
            if cur_edge is None:
                link:Optional[Link] = self.W.get_vehicle(veh._name).link
            else:
                link = self.W.get_link(cur_edge)
            if link is None:
                raise RuntimeError(Lang.VEH_HAS_NO_LINK.format(veh._name))
            cur_node = link.end_node.name
        assert isinstance(cur_node, str)
        
        if isinstance(veh, EV): hub = self._hubs.fcs
        elif isinstance(veh, GV): hub = self._hubs.gs
        else: raise RuntimeError(Lang.VEH_TYPE_NOT_SUPPORTED.format(veh._name, type(veh)))
        
        return self.find_best_station(veh, cur_node, hub.get_online_names(self._ct),
            veh._w, to_charge, veh.range / veh._kr, hub)
    
    def __start_trip(self, veh: Vehicle) -> bool:
        """
        Start the current trip of a vehicle
        
        :param veh: Vehicle instance
        :return: whether departed successfully. If False, it means the vehicle cannot reach any FCS/GS on the way
        """
        trip = veh.trip
        stage = self.find_route(trip.O, trip.D)
        planned_length = stage.length
        if self.__allow_scs_redirect:
            stage, planned_length = self.__maybe_redirect_trip_to_scs(veh, stage, planned_length)
        trip = veh.trip

        # Edge-to-node conversion can collapse a SUMO trip to O == D.  Do not
        # inject such a vehicle into UXsim: UXsim may otherwise make it traverse
        # a cycle before it can finish.  This is a genuine zero-distance trip.
        instant_arrival = trip.O == trip.D

        if instant_arrival:
            direct_depart = True
        elif self._dist_based_restoration:
            # Determine whether the battery is sufficient
            direct_depart = (not veh._fr_on_dpt) and veh.is_energy_enough(planned_length)
        else:
            # Determine whether the EV needs to be fast charged
            direct_depart = (not veh._fr_on_dpt) and veh.soc >= veh._kf
        if direct_depart:  # Direct departure
            veh._cs = None
            veh._etar = veh._cap  # Reset the energy target
            if instant_arrival:
                veh.clear_odometer()
                veh.current_trip_planned_length = 0.0
                self.__instant_arrivals.add(veh._name)
            else:
                self._add_veh(
                    veh._name, trip.O, trip.D, stage,
                    planned_length=planned_length,
                )
        else:  # Charge/Refuel once on the way
            if veh._fr_on_dpt is not None and veh._dpt_rs is not None:
                # Forced to a specified FCS/GS
                veh._cs = veh._dpt_rs # Assume the type of _dpt_rs is correct
                self._add_veh2(veh._name, trip.O, self._hubs.get_bind_of(veh._dpt_rs))
            else:
                # Find a suitable FCS / GS
                station, route = self.__sel_best_station(veh, trip.O)
                if len(route.nodes) == 0:
                    # The power is not enough to drive to any FCS or GS
                    veh._cs = None
                    veh._fr_on_dpt = False  # Clear the fast charge force flag
                    veh._dpt_rs = None  # Clear the fast charge target flag
                    return False
                else: # Found a station
                    veh._cs = station
                    self._add_veh(veh._name, trip.O, self._hubs.get_bind_of(station), route)
        if isinstance(veh, EV):
            # Stop slow charging of the vehicle and add it to the waiting to depart set
            if self._hubs.scs.pop_veh(veh):
                self._log.leave_SCS(self._ct, veh, trip.O)
        veh.status = VehStatus.Pending
        veh._fr_on_dpt = False  # Clear the fast charge force flag
        veh._dpt_rs = None  # Clear the fast charge target flag
        return True

    def __batch_depart(self):
        """Sent out all vehicles that reaching the departure time"""
        while not self._que.empty() and self._que.top[0] <= self._ct:
            depart_time, (veh_id, extras) = self._que.pop()
            veh = self._vehs[veh_id]
            if extras is not None:
                trip, force_sc, force_fc, force_fcs = extras
                if isinstance(veh, EV): veh._force_sc = force_sc
                veh._fr_on_dpt = force_fc
                veh._dpt_rs = force_fcs
                assert isinstance(trip, Trip)
            else:
                trip = veh.trip
            if self.__start_trip(veh):
                depart_delay = max(0, self._ct - depart_time)
                self._log.depart(self._ct, veh, depart_delay, veh._cs)
                if veh_id in self.__instant_arrivals:
                    self.__instant_arrivals.discard(veh_id)
                    veh.drive(0.0)
                    self._end_trip(veh, 0.0)
            else:
                if isinstance(veh, GV):
                    available_s = self._hubs.gs.get_online_names(self._ct)
                else:
                    available_s = self._hubs.fcs.get_online_names(self._ct)
                if len(available_s) == 0: raise RuntimeError(Lang.NO_AVAILABLE_FCS)
                
                nodes = {} # bind(node/edge) -> station name
                for s in available_s:
                    bind = self._hubs.get_bind_of(s)
                    if bind not in nodes:
                        nodes[bind] = s
                    elif self._hubs[nodes[bind]].wait_count() > veh._w * self._hubs[s].wait_count():
                        nodes[bind] = s
                
                # Find the nearest FCS
                best_route = self.find_best_route(trip.O, nodes.keys(), False)
                if len(best_route.nodes) == 0:
                    # No FCS/GS available
                    trT = self._ct + self._step
                    self._fQ.push(trT, veh_id)  # Teleport in the next step
                    self._log.depart_failed(self._ct, veh, -1, "", trT)
                    continue

                best_s = nodes[best_route.nodes[-1]]

                batt_req = best_route.length * veh._epm * veh._kr
                if isinstance(veh, EV) and self._hubs.scs.has_veh(veh._name):
                    # Plugged in an SCS charger, wait for a moment
                    delay = int(1 + (batt_req - veh._energy) / veh._pcr)
                    self._log.depart_delay(self._ct, veh, batt_req, delay)
                    self._que.push(depart_time + delay, (veh_id, None))
                else:
                    # Not plugged in an SCS charger, teleport to the nearest FCS (consume 2 times of the running time)
                    veh.status = VehStatus.Depleted
                    veh._cs = best_s
                    trT = int(self._ct + 2 * best_route.travelTime)
                    self._fQ.push(trT, veh._name)
                    self._log.depart_failed(self._ct, veh, batt_req, best_s, trT)
    
    def simulation_start(self):
        """Start simulation"""
        # Do not set _ct here, it may be loaded from the state
        self.__batch_depart()

        for s in chain(self._hubs):
            if s._x == float('inf') or s._y == float('inf'):
                s._x, s._y = self._rnet.get_node(s._bind).get_coord()
        
        self._hubs.check_kdtree()

    def simulation_step(self, step_len: int):
        """
        Simulation step.
            step_len: Step length (seconds)
            v2g_demand: V2G demand list (kWh/s)
        """
        new_time = self._ct + step_len
        self.W.exec_simulation(new_time)
        deltaT = new_time - self._ct
        self._ct = new_time

        if self.__stall_count > 0 or self._ct - self.__stall_last_check >= 3600:
            # Check for simulation stall every hour or if already detected. Not running every step to reduce overhead.
            # The first hour is skipped to allow the simulation to warm up.
            self.__stall_last_check = self._ct
            if self.W.get_running_vehicle_count() > 1 and self.W.get_average_speed() < 1e-3:
                # If the average speed is too low, we can consider the simulation to be stalled
                self.__stall_count += 1
                if self.__stall_count >= 5 and not self.__stall_warned:
                    if not self.silent:
                        warn(Warning(Lang.SIMULATION_MAY_STALL.format(self._ct)))
                    self.__stall_warned = True
            else:
                self.__stall_count = 0

        # Depart vehicles before processing arrivals
        # If a vehicle arrives and departs in the same step, performing departure after arrival immediately will cause the vehicle to be unable to depart
        # Therefore, all departures are processed first can delay the departure to the next step and cause no problem
        self.__batch_depart()

        # Process arrived vehicles
        for v, v0 in self.W.get_arrived_vehicles():
            veh = self._vehs[v]
            dist = veh.current_trip_planned_length
            if dist <= EPS:
                route, timepoint = v0.traveled_route()
                dist = sum(link.length for link in route.links)
            dist = self.__ctpl_or(dist, veh)
            veh.drive(dist)
            if veh._cs is None:
                self._end_trip(veh, dist)
            else:
                self._start_restore(veh, dist)

        super().post_simulation_step(deltaT)

    def simulation_stop(self):
        if not self.silent:
            print(self.W.shutdown())
        self._log.close()
    
    def save(self, folder: Union[str, Path]):
        """
        Save the current state of the simulation
            folder: Folder path
        """
        f = Path(folder) if isinstance(folder, str) else folder
        f.mkdir(parents=True, exist_ok=True)
        self.W.save(str(f / WORLD_FILE_NAME))
        tmpW = self.W
        tmpTL = self._log
        del self._log
        del self.W
        with gzip.open(f / TRAFFIC_INST_FILE_NAME, "wb") as f:
            pickle.dump({
                "obj": self,
                "version": PyVersion(),
                "pickler": pickle.__name__,
            }, f)
        self.W = tmpW
        self._log = tmpTL

    def _save_obj(self):
        tmpW = self.W
        tmpTL = self._log
        del self._log
        del self.W
        ret = pickle.dumps({
            "obj": self,
            "version": PyVersion(),
            "pickler": pickle.__name__,
        })
        self.W = tmpW
        self._log = tmpTL
        return ret
    
    @staticmethod
    def _partial_load_unsafe(d:dict, tlogger:TripLogger) -> 'TrafficUX':
        """
        Load a TrafficUX from a saved_state object (unsafe, for advanced users only, at your own risk!)
            object: Saved_state object
            triplogger_save_path: If not None, change the trip logger save path to this path
        Return:
            TrafficUX instance, without world loaded!
        """
        assert isinstance(d, dict) and "obj" in d and "pickler" in d and "version" in d, "Invalid TrafficUX state file."
        if not CheckPyVersion(d["version"]):
            raise RuntimeError(Lang.PY_VERSION_MISMATCH_TI.format(PyVersion(), d["version"]))
        if d["pickler"] != pickle.__name__:
            raise RuntimeError(Lang.PICKLER_MISMATCH_TI.format(pickle.__name__, d["pickler"]))

        ti = d["obj"]
        assert isinstance(ti, TrafficUX)
        if not hasattr(ti, "_TrafficUX__allow_scs_redirect"):
            ti.__allow_scs_redirect = False
        if not hasattr(ti, "_TrafficUX__instant_arrivals"):
            ti.__instant_arrivals = set()
        if not hasattr(ti, "_TrafficUX__speed_upper_bound"):
            ti.__speed_upper_bound = max(
                (float(edge.speed_limit) for edge in ti._rnet.edges.values() if edge.speed_limit > 0),
                default=0.0,
            )
        ti._log = tlogger
        return ti
    
    @staticmethod
    def load(folder: Union[str, Path], tlogger:TripLogger) -> 'TrafficUX':
        """
        Load a TrafficUX from a saved_state folder
            folder: Folder path
            tlogger: TripLogger instance to use
        Return:
            TrafficUX instance
        """
        folder = Path(folder) if isinstance(folder, str) else folder
        inst = folder / TRAFFIC_INST_FILE_NAME
        if not inst.exists():
            raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(inst))
        
        with gzip.open(str(inst), "rb") as f:
            d = pickle.load(f)
        
        ti = TrafficUX._partial_load_unsafe(d, tlogger)
        from .uxworld import load_world
        ti.W = load_world(str(Path(folder) / WORLD_FILE_NAME))
        return ti
    
    @staticmethod
    def create(
        case: CaseData,
        tlogger: TripLogger,
        vscfg: CommonConfig,
        config: UXsimConfig,
        seed:int = 0,
        silent:bool = False,
    ):
        tc = case.time_config
        return TrafficUX(
            tc.start_time, tc.step_length, tc.end_time,
            case.road_network, tlogger, case.vehicles,
            case.mixed_hub, case.power_network, 
            seed = seed, silent = silent, 
            **asdict(vscfg),
            **asdict(config)
        )
        

__all__ = ["TrafficUX", "WORLD_FILE_NAME"]