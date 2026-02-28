import cloudpickle as pickle
import gzip
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


class TrafficUX(TrafficInst):
    def __init__(
        self, start_time: int, step_len: int, end_time: int, 
        roadnet:RoadNet, trip_logger: TripLogger, vehs: VDict, 
        hubs: MixedHub, pdn: Grid, gasoline_price: TimeFunc, 
        seed: int = 0, silent: bool = False, *,
        routing_algo: str = "dijkstra",  # or "astar"
        show_uxsim_info: bool = False,
        randomize_uxsim: bool = True,
        no_parallel: bool = False,
    ):  
        super().__init__(start_time, step_len, end_time, roadnet, trip_logger, vehs, hubs, pdn, gasoline_price, seed, silent)
        self.__stall_warned = False
        self.__stall_count = 0
        self.__stall_last_check = 0
        
        assert routing_algo in ("dijkstra", "astar"), Lang.ROUTE_ALGO_NOT_SUPPORTED
        self.__use_astar = routing_algo == "astar"
        
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
            reaction_time=step_len,
            random_seed=seed,
            hard_deterministic_mode=not randomize_uxsim,
            reduce_memory_delete_vehicle_route_pref=True,
            vehicle_logging_timestep_interval=-1,
            print_mode=1 if self.__show_uxsim_info else 0,
            silent=self.silent,
        )
        if not self.silent:
            from .uxworld import ParaWorlds
            if isinstance(self.W, ParaWorlds):
                print(Lang.PARA_WORLDS.format(len(self.W.worlds)))
            else:
                print(Lang.SINGLE_WORLD)

        super()._prepare_trips_and_scs()

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
        if self.__use_astar:
            if fastest:
                return astarF(self.W.get_gl(), self.W.get_coords(), self._ct, O, D)
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
                    O, Ds, max(0.1, self.W.get_average_speed()))
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
                scores, max_dist, max(0.1, self.W.get_average_speed()))
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

    def _add_veh(self, veh_id:str, from_node:str, to_node:str, route:Union[Stage, List[str]]):
        self._vehs[veh_id].clear_odometer()
        self.W.add_vehicle(veh_id, from_node, to_node, route)

    def _add_veh2(self, veh_id:str, O:str, D:str):
        self._vehs[veh_id].clear_odometer()
        self.W.add_vehicle(veh_id, O, D)

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
        direct_depart = True

        if self._dist_based_restoration:
            stage = self.find_route(trip.O, trip.D)
            # Determine whether the battery is sufficient
            direct_depart = (not veh._fr_on_dpt) and veh.is_energy_enough(stage.length)
        else:
            # Determine whether the EV needs to be fast charged
            stage = None
            direct_depart = (not veh._fr_on_dpt) and veh.soc >= veh._kf
        if direct_depart:  # Direct departure
            veh._cs = None
            veh._etar = veh._cap  # Reset the energy target
            if stage:
                self._add_veh(veh._name, trip.O, trip.D, stage)
            else:
                self._add_veh2(veh._name, trip.O, trip.D)
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
                best_s = nodes[best_route.nodes[-1]]

                if len(best_route.nodes) == 0:
                    # No FCS/GS available
                    trT = self._ct + self._step
                    self._fQ.push(trT, veh_id)  # Teleport in the next step
                    self._log.depart_failed(self._ct, veh, -1, "", trT)
                    continue

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
            route, timepoint = v0.traveled_route()
            dist = sum(link.length for link in route.links)
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
            vscfg.gasoline_price, seed, silent, 
            routing_algo=vscfg.routing_algorithm,
            **asdict(config)
        )
        

__all__ = ["TrafficUX", "WORLD_FILE_NAME"]