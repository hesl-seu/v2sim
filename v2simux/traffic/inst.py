import random
import cloudpickle as pickle
import gzip
from collections import deque
from itertools import chain
from warnings import warn
from pathlib import Path
from typing import List, Optional
from feasytools import PQueue, Point
from .uxsim import Link
from .routing import *
from ..locale import Lang
from .trip import TripsLogger
from .cs import *
from .cslist import *
from .evdict import *
from .ev import *
from .paraworlds import ParaWorlds, load_world
from .net import RoadNet
from .params import *
from .utils import PyVersion, CheckPyVersion

WORLD_FILE_NAME = "world.gz"
TRAFFIC_INST_FILE_NAME = "inst.gz"

class TrafficInst:
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
        routing_algo: str = "dijkstra",  # or "astar"
        show_uxsim_info: bool = False,
        no_parallel: bool = False,
        silent: bool = False,
    ):
        """
        TrafficInst initialization
            road_net_file: Road network file
            start_time: Simulation start time
            step_len: Simulation step length
            end_time: Simulation end time
            clogfile: Log file path
            seed: Randomization seed
            vehfile: Vehicle information and itinerary file
            fcsfile: Fast charging station list file
            scsfile: Slow charging station list file
            routing_algo: Routing algorithm, can be "dijkstra" or "astar"
            show_uxsim_info: Whether to display uxsim information
            no_parallel: Whether to disable parallel worlds
        """
        random.seed(seed)
        self.__stall_warned = False
        self.__stall_count = 0
        self.__triplogger_path = clogfile
        self.__logger = TripsLogger(self.__triplogger_path)
        assert routing_algo in ("dijkstra", "astar"), Lang.ROUTE_ALGO_NOT_SUPPORTED
        self.__use_astar = routing_algo == "astar"
        self.silent = silent
        self.__vehfile = vehfile
        self.__fcsfile = fcsfile
        self.__scsfile = scsfile
        self.__ctime: int = start_time
        self.__stime: int = start_time
        self.__step_len: int = step_len
        self.__etime: int = end_time
        
        # Read road network
        self.__net_file = road_net_file
        self.__rnet: RoadNet = RoadNet.load(road_net_file)
        # Get all road names
        self.__names: List[str] = list(self.__rnet.edges.keys())
        
        # Load vehicles
        self._fQ = PQueue()  # Fault queue
        self._que = PQueue()  # Departure queue
        self._aQ = deque()  # Arrival queue
        self._VEHs = veh_obj if veh_obj else EVDict(vehfile)

        # Load charging stations
        self._fcs:CSList[FCS] = fcs_obj if fcs_obj else CSList(filePath=fcsfile, csType=FCS)
        self._scs:CSList[SCS] = scs_obj if scs_obj else CSList(filePath=scsfile, csType=SCS)
        self.__names_fcs: List[str] = [cs.name for cs in self._fcs]
        self.__names_scs: List[str] = [cs.name for cs in self._scs]

        for cs in self._fcs:
            if cs.name not in self.__rnet.nodes:
                raise RuntimeError(Lang.ERROR_CS_NODE_NOT_EXIST.format(cs.name))
            
        for cs in self._scs:
            if cs.name not in self.__rnet.nodes:
                raise RuntimeError(Lang.ERROR_CS_NODE_NOT_EXIST.format(cs.name))

        # Check if all CS are in the largest SCC
        bad_cs = set(cs.name for cs in chain(self._fcs, self._scs) if not self.__rnet.is_node_in_largest_scc(cs.name))
        if len(bad_cs) > 0 and not self.silent:
            warn(Lang.WARN_CS_NOT_IN_SCC.format(','.join(bad_cs)))
        
        # Create uxsim world
        create_func = self.__rnet.create_singleworld if no_parallel else self.__rnet.create_world
        self.__show_uxsim_info = show_uxsim_info
        self.W = create_func(
            tmax=end_time,
            deltan=1,
            reaction_time=step_len,
            random_seed=seed,
            hard_deterministic_mode=True,
            reduce_memory_delete_vehicle_route_pref=True,
            vehicle_logging_timestep_interval=-1,
            print_mode=1 if self.__show_uxsim_info else 0
        )
        if not self.silent:
            if isinstance(self.W, ParaWorlds):
                print(Lang.PARA_WORLDS.format(len(self.W.worlds)))
            else:
                print(Lang.SINGLE_WORLD)

        # Load vehicles to charging stations and prepare to depart
        for veh in self._VEHs.values():
            self._que.push(veh.trip.depart_time, veh.ID)
            if veh.trip.from_node not in self.__names_scs:
                continue  # Only vehicles with slow charging stations can be added to the slow charging station
            # There is a 20% chance of adding to a rechargeable parking point
            if veh.SOC < veh.ksc or random.random() <= 0.2:
                self._scs.add_veh(veh, veh.trip.from_node)

    def find_route(self, from_node: str, to_node: str, fastest:bool = True) -> Stage:
        """
        Find the best route from from_node to to_node.
            fastest: True = fastest route, False = shortest route
        """
        if self.__use_astar:
            if fastest:
                return astarF(self.W.get_gl(), self.W.get_coords(), self.__ctime, from_node, to_node)
            else:
                return astarS(self.W.get_gl(), self.W.get_coords(), self.__ctime, from_node, to_node)
        else:
            if fastest:
                return dijMF(self.W.get_gl(), self.__ctime, from_node, {to_node})
            else:
                return dijMS(self.W.get_gl(), self.__ctime, from_node, {to_node})
        
    def find_best_route(self, from_node:str, to_nodes: set[str], fastest:bool = True):
        if self.__use_astar:
            if fastest:
                return astarMF(self.W.get_gl(), self.W.get_coords(), self.__ctime,
                    from_node, to_nodes, max(0.1, self.W.get_average_speed()))
            else:
                return astarMS(self.W.get_gl(), self.W.get_coords(), self.__ctime, from_node, to_nodes)
        else:
            if fastest:
                return dijMF(self.W.get_gl(), self.__ctime, from_node, to_nodes)
            else:
                return dijMS(self.W.get_gl(), self.__ctime, from_node, to_nodes)
    
    def find_best_fcs(self, from_node:str, to_fcs: List[str], omega:float, to_charge:float, max_dist:float):
        wt = {c: self._fcs[c].wait_count() * 30.0 for c in to_fcs}
        p = {c: self._fcs[c].pbuy(self.__ctime) for c in to_fcs}
        if self.__use_astar:
            return astarMC(self.W.get_gl(), self.W.get_coords(), self.__ctime, from_node, set(to_fcs),
                omega, to_charge, wt, p, max_dist,  max(0.1, self.W.get_average_speed()))
        else:
            return dijMC(self.W.get_gl(), self.__ctime, from_node, set(to_fcs), omega, to_charge, wt, p, max_dist)

    @property
    def trips_logger(self) -> TripsLogger:
        """Trip logger"""
        return self.__logger
    
    @property
    def net_file(self):
        """Road network file"""
        return self.__net_file

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
    def triplogger_path(self):
        """Trip logger file path"""
        return self.__triplogger_path
    
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
    def FCSList(self)->CSList[FCS]:
        """Fast charging station list"""
        return self._fcs

    @property
    def SCSList(self)->CSList[SCS]:
        """Slow charging station list"""
        return self._scs

    @property
    def vehicles(self) -> EVDict:
        """Vehicle dictionary, key is vehicle ID, value is EV instance"""
        return self._VEHs
    
    @property
    def routing_algo(self) -> str:
        """Routing algorithm, can be "dijkstra" or "astar" """
        return "astar" if self.__use_astar else "dijkstra"
    
    @property
    def show_uxsim_info(self) -> bool:
        """Whether to display uxsim information"""
        return self.__show_uxsim_info

    def __add_veh2(self, veh_id:str, from_node:str, to_node:str):
        self._VEHs[veh_id].clear_odometer()
        self.W.add_vehicle(veh_id, from_node, to_node)

    @property
    def edges(self):
        """Get all roads"""
        return list(self.__rnet.edges.values())

    @property
    def trips_iterator(self):
        """Get an iterator for all trips"""
        return chain(*(x.trips for x in self._VEHs.values()))

    def get_edge_names(self) -> List[str]:
        """Get the names of all roads"""
        return self.__names
    
    def __sel_best_CS(
        self, veh: EV, cur_node: Optional[str] = None, 
        cur_edge: Optional[str] = None, cur_pos: Optional[Point] = None
    ) -> Stage:
        """
        Select the nearest available charging station based on the edge where the car is currently located, and return the path and average weight
            veh: Vehicle instance
            cur_node: Current node, if None, it will be automatically obtained
            cur_edge: Current road, if None, it will be automatically obtained
            cur_pos: Current position, if None, it will be automatically obtained
        Return:
            Stage
        """
        to_charge = veh.charge_target - veh.battery
        
        if cur_node is None:
            if not self.W.has_vehicle(veh.ID):
                raise RuntimeError(Lang.VEH_NOT_FOUND.format(veh.ID))
            if cur_edge is None:
                link:Optional[Link] = self.W.get_vehicle(veh.ID).link
            else:
                link = self.W.get_link(cur_edge)
            if link is None:
                raise RuntimeError(Lang.VEH_HAS_NO_LINK.format(veh.ID))
            cur_node = link.end_node.name
        assert isinstance(cur_node, str)
        
        if cur_pos is None:
            if not self.W.has_vehicle(veh.ID):
                raise RuntimeError(Lang.VEH_NOT_FOUND.format(veh.ID))
            x, y = self.W.get_vehicle(veh.ID).get_xy_coords()
            cur_pos = Point(x, y)
        
        best = self.find_best_fcs(cur_node, self._fcs.get_online_CS_names(self.__ctime),
            veh._w, to_charge, veh.max_mileage/veh._krel)

        return best
    
    def __start_trip(self, veh_id: str) -> bool:
        """
        Start the current trip of a vehicle
            veh_id: Vehicle ID
        Return:
            Departure succeeded: True
            Departure failed: False
        """
        veh = self._VEHs[veh_id]
        trip = veh.trip
        direct_depart = True

        if ENABLE_DIST_BASED_CHARGING_DECISION:
            stage = self.find_route(trip.from_node, trip.to_node)
            # Determine whether the battery is sufficient
            direct_depart = veh.is_batt_enough(stage.length)
        else:
            # Determine whether the EV needs to be fast charged
            stage = None
            direct_depart = veh.SOC >= veh.kfc
        if direct_depart:  # Direct departure
            veh.target_CS = None
            veh.charge_target = veh.full_battery
            self.__add_veh2(veh_id, trip.from_node, trip.to_node)
        else:  # Charge once on the way
            x, y = self.__rnet.get_node(trip.from_node).get_coord()
            route = self.__sel_best_CS(veh, trip.from_node, cur_pos = Point(x, y))
            if len(route.nodes) == 0:
                # The power is not enough to drive to any charging station, you need to charge for a while
                veh.target_CS = None
                return False
            else: # Found a charging station
                veh.target_CS = route.nodes[-1]
                self.__add_veh2(veh_id, trip.from_node, trip.to_node)
        # Stop slow charging of the vehicle and add it to the waiting to depart set
        if self._scs.pop_veh(veh):
            self.__logger.leave_SCS(self.__ctime, veh, trip.from_node)
        veh.stop_charging()
        veh.status = VehStatus.Pending
        return True

    def __end_trip(self, veh_id: str, dist: float):
        """
        End the current trip of a vehicle and add its next trip to the departure queue.
        If the destination of the trip meets the charging conditions, try to charge.
            veh_id: Vehicle ID
        """
        veh = self._VEHs[veh_id]
        veh.status = VehStatus.Parking
        arr_sta = TripsLogger.ARRIVAL_NO_CHARGE
        if veh.SOC < veh.ksc:
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
            self._que.push(ntrip.depart_time, veh_id)

    def __start_charging_SCS(self, veh: EV) -> bool:
        """
        Make a vehicle enter the charging state (slow charging station)
            veh: Vehicle instance
        """
        ret = False
        try:
            self._scs.add_veh(veh, veh.trip.to_node)
            ret = True
        except:
            pass
        if ret:
            self.__logger.join_SCS(self.__ctime, veh, veh.trip.to_node)
        return ret

    def __start_charging_FCS(self, veh: EV, dist: float = -1):
        """
        Make a vehicle enter the charging state (fast charging station)
            veh: Vehicle instance
        """
        veh.status = VehStatus.Charging
        assert isinstance(veh.target_CS, str)
        if ENABLE_DIST_BASED_CHARGING_QUANTITY:
            ch_tar = (
                veh.consumption
                * self.find_route(veh.target_CS, veh.trip.to_node).length
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
        self.__logger.arrive_FCS(self.__ctime, veh, veh.target_CS, dist)

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
        
        self.__add_veh2(veh.ID, veh.target_CS, trip.to_node)
        veh.target_CS = None
        veh.charge_target = veh.full_battery
        veh.status = VehStatus.Pending
        veh.stop_charging()

    def __batch_depart(self):
        """
        All vehicles that arrive at the departure queue are sent out
            self.__ctime: Current time, in seconds
        """
        while not self._que.empty() and self._que.top[0] <= self.__ctime:
            depart_time, veh_id = self._que.pop()
            veh = self._VEHs[veh_id]
            trip = veh.trip
            if self.__start_trip(veh_id):
                depart_delay = max(0, self.__ctime - depart_time)
                self.__logger.depart(self.__ctime, veh, depart_delay, veh.target_CS)
            else:
                available_cs = self._fcs.get_online_CS_names(self.__ctime)
                if len(available_cs) == 0:
                    raise RuntimeError(Lang.NO_AVAILABLE_FCS)
                
                # Find the nearest FCS
                best_cs = self.find_best_route(trip.from_node, set(available_cs), False)

                if len(best_cs.nodes) == 0:
                    # No FCS available
                    trT = self.__ctime + self.__step_len
                    self._fQ.push(trT, veh_id)  # Teleport in the next step
                    self.__logger.depart_failed(self.__ctime, veh, -1, "", trT)
                    continue

                cs_name = best_cs.nodes[-1]
                batt_req = best_cs.length * veh.consumption * veh.krel
                if self._scs.has_veh(veh.ID):
                    # Plugged in an SCS charger, wait for a moment
                    delay = int(1 + (batt_req - veh.battery) / veh.rate)
                    self.__logger.depart_delay(self.__ctime, veh, batt_req, delay)
                    self._que.push(depart_time + delay, veh_id)
                else:
                    # Not plugged in an SCS charger, teleport to the nearest FCS (consume 2 times of the running time)
                    veh.status = VehStatus.Depleted
                    veh.target_CS = cs_name
                    trT = int(self.__ctime + 2 * best_cs.travelTime)
                    self._fQ.push(trT, veh.ID)
                    self.__logger.depart_failed(self.__ctime, veh, batt_req, cs_name, trT)        

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

    def simulation_start(self):
        """
        Start simulation
        """
        # Do not set __ctime here, it may be loaded from the state
        self.__batch_depart()

        for cs in chain(self.FCSList, self.SCSList):
            if cs._x == float('inf') or cs._y == float('inf'):
                cs._x, cs._y = self.__rnet.get_node(cs.name).get_coord()
        
        if self.FCSList._kdtree == None:
            self.FCSList.create_kdtree()
        
        if self.SCSList._kdtree == None:
            self.SCSList.create_kdtree()

    def simulation_step(self, step_len: int):
        """
        Simulation step.
            step_len: Step length (seconds)
            v2g_demand: V2G demand list (kWh/s)
        """
        new_time = self.__ctime + step_len
        self.W.exec_simulation(new_time)
        deltaT = new_time - self.__ctime
        self.__ctime = new_time

        if self.W.get_running_vehicle_count() > 0 and self.W.get_average_speed() < 1e-3:
            # If the average speed is too low, we can consider the simulation to be stalled
            self.__stall_count += 1
            if self.__stall_count >= 50 and not self.__stall_warned:
                if not self.silent:
                    warn(Warning(Lang.SIMULATION_MAY_STALL.format(self.__ctime)))
                self.__stall_warned = True
        else:
            self.__stall_count = 0
            

        # Depart vehicles before processing arrivals
        # If a vehicle arrives and departs in the same step, performing departure after arrival immediately will cause the vehicle to be unable to depart
        # Therefore, all departures are processed first can delay the departure to the next step and cause no problem
        self.__batch_depart()

        # Process arrived vehicles
        for v, v0 in self.W.get_arrived_vehicles():
            veh = self._VEHs[v]
            route, timepoint = v0.traveled_route()
            dist = sum(link.length for link in route.links)
            veh.drive(dist)
            if veh.target_CS is None:
                self.__end_trip(v, dist)
            else:
                self.__start_charging_FCS(self._VEHs[v], dist)

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
        if not self.silent:
            print(self.W.shutdown())
        self.__logger.close()
    
    def save(self, folder: Union[str, Path]):
        """
        Save the current state of the simulation
            folder: Folder path
        """
        f = Path(folder) if isinstance(folder, str) else folder
        f.mkdir(parents=True, exist_ok=True)
        self.W.save(str(f / WORLD_FILE_NAME))
        self._fcs.shutdown_pool()
        self._scs.shutdown_pool()
        tmpW = self.W
        tmpTL = self.__logger
        delattr(self, "_TrafficInst__logger")
        delattr(self, "W")
        with gzip.open(str(f / TRAFFIC_INST_FILE_NAME), "wb") as f:
            pickle.dump({
                "obj": self,
                "version": PyVersion(),
                "pickler": pickle.__name__,
            }, f)
        self.W = tmpW
        self.__logger = tmpTL
        self._fcs.create_pool()
        self._scs.create_pool()
    
    @staticmethod
    def load(folder: Union[str, Path], triplogger_save_path:Union[None, str, Path] = None) -> 'TrafficInst':
        """
        Load a TrafficInst from a saved_state folder
            folder: Folder path
            triplogger_save_path: If not None, change the trip logger save path to this path
        Return:
            TrafficInst instance
        """
        folder = Path(folder) if isinstance(folder, str) else folder
        inst = folder / TRAFFIC_INST_FILE_NAME
        if not inst.exists():
            raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(inst))
        
        with gzip.open(str(inst), "rb") as f:
            d = pickle.load(f)
            assert isinstance(d, dict) and "obj" in d and "pickler" in d and "version" in d, "Invalid TrafficInst state file."
        if not CheckPyVersion(d["version"]):
            raise RuntimeError(Lang.PY_VERSION_MISMATCH_TI.format(PyVersion(), d["version"]))
        if d["pickler"] != pickle.__name__:
            raise RuntimeError(Lang.PICKLER_MISMATCH_TI.format(pickle.__name__, d["pickler"]))

        ti = d["obj"]
        assert isinstance(ti, TrafficInst)
        ti.W = load_world(str(Path(folder) / WORLD_FILE_NAME))
        if triplogger_save_path is not None:
            ti.__triplogger_path = str(triplogger_save_path)
        ti.__logger = TripsLogger(ti.__triplogger_path, append=True)
        ti._fcs.create_pool()
        ti._scs.create_pool()
        return ti

__all__ = ["TrafficInst"]