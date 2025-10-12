from collections import deque
from itertools import chain
from warnings import warn
from pathlib import Path
import random
import pickle
import gzip
from typing import List, Tuple, Dict
from feasytools import PQueue, Point, FEasyTimer
from uxsim import Link
from .routing import *
from .trip import TripsLogger
from .cslist import *
from .ev import *
from .utils import TWeights
from .paraworlds import ParaWorlds
from .net import RoadNet


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
        initial_state_folder: str = "",
        routing_algo: str = "dijkstra",  # or "astar"
        show_uxsim_info: bool = False,
        no_parallel: bool = False
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
        """
        random.seed(seed)
        self.__logger = TripsLogger(clogfile)
        assert routing_algo in ("dijkstra", "astar"), "Unsupported routing algorithm"
        self.__use_astar = routing_algo == "astar"
        
        self.__vehfile = vehfile
        self.__fcsfile = fcsfile
        self.__scsfile = scsfile
        self.__ctime: int = start_time
        self.__stime: int = start_time
        self.__step_len: int = step_len
        self.__etime: int = end_time
        
        # Read road network
        self.__rnet: RoadNet = RoadNet.load(road_net_file)
        # Get all road names
        self.__names: List[str] = list(self.__rnet.edges.keys())

        self.__istate_folder = initial_state_folder

        if self.__istate_folder != "":
            self.load_state(self.__istate_folder)
            return
        
        # Load vehicles
        self._fQ = PQueue()  # Fault queue
        self._que = PQueue()  # Departure queue
        self._aQ = deque()  # Arrival queue
        self._VEHs = veh_obj if veh_obj else EVDict(vehfile)

        # Load charging stations
        self._fcs:CSList[FCS] = fcs_obj if fcs_obj else CSList(self._VEHs, filePath=fcsfile, csType=FCS)
        self._scs:CSList[SCS] = scs_obj if scs_obj else CSList(self._VEHs, filePath=scsfile, csType=SCS)
        self.__names_fcs: List[str] = [cs.name for cs in self._fcs]
        self.__names_scs: List[str] = [cs.name for cs in self._scs]

        # Check if all CS are in the largest SCC
        bad_cs = set(cs.name for cs in chain(self._fcs, self._scs) if not self.__rnet.is_node_in_largest_scc(cs.name))
        if len(bad_cs) > 0:
            warn(Lang.WARN_CS_NOT_IN_SCC.format(','.join(bad_cs)))
        
        # Create uxsim world
        create_func = self.__rnet.create_singleworld if no_parallel else self.__rnet.create_world
        self.W = create_func(
            tmax=end_time,
            deltan=1,
            reaction_time=step_len,
            random_seed=seed,
            hard_deterministic_mode=True,
            reduce_memory_delete_vehicle_route_pref=True,
            vehicle_logging_timestep_interval=-1,
            print_mode=1 if show_uxsim_info else 0
        )
        print(f"World created: {type(self.W).__name__}")
        if isinstance(self.W, ParaWorlds):
            print(f"Number of sub-worlds: {len(self.W.worlds)}")

        # Load vehicles to charging stations and prepare to depart
        for veh in self._VEHs.values():
            self._que.push(veh.trip.depart_time, veh.ID)
            if veh.trip.from_node not in self.__names_scs:
                continue  # Only vehicles with slow charging stations can be added to the slow charging station
            # There is a 20% chance of adding to a rechargeable parking point
            if veh.SOC < veh.ksc or random.random() <= 0.2:
                self._scs.add_veh(veh.ID, veh.trip.from_node)

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
    ) -> Tuple[Stage, TWeights]:
        """
        Select the nearest available charging station based on the edge where the car is currently located, and return the path and average weight
            veh: Vehicle instance
            cur_node: Current node, if None, it will be automatically obtained
            cur_edge: Current road, if None, it will be automatically obtained
            cur_pos: Current position, if None, it will be automatically obtained
        Return:
            Stage, Weight(Tuple[float,float,float])
            If no charging station is found, return [],(-1,-1,-1)
        """
        to_charge = veh.charge_target - veh.battery
        
        if cur_node is None:
            if not self.W.has_vehicle(veh.ID):
                raise RuntimeError(f"Vehicle {veh.ID} not found in simulator")
            if cur_edge is None:
                link:Optional[Link] = self.W.get_vehicle(veh.ID).link
            else:
                link = self.W.get_link(cur_edge)
            if link is None:
                raise RuntimeError(f"Vehicle {veh.ID} has no current link")
            cur_node = link.end_node.name
        assert isinstance(cur_node, str)
        
        if cur_pos is None:
            if not self.W.has_vehicle(veh.ID):
                raise RuntimeError(f"Vehicle {veh.ID} not found in simulator")
            x, y = self.W.get_vehicle(veh.ID).get_xy_coords()
            cur_pos = Point(x, y)
        
        best = self.find_best_fcs(cur_node, self._fcs.get_online_CS_names(self.__ctime),
            veh._w, to_charge, veh.max_mileage/veh._krel)

        return best, (-1, -1, -1)
    
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
            route, weights = self.__sel_best_CS(veh, trip.from_node, cur_pos = Point(x, y))
            if len(route.nodes) == 0:
                # The power is not enough to drive to any charging station, you need to charge for a while
                veh.target_CS = None
                return False, None
            else: # Found a charging station
                veh.target_CS = route.nodes[-1]
                self.__add_veh2(veh_id, trip.from_node, trip.to_node)
        # Stop slow charging of the vehicle and add it to the waiting to depart set
        if self._scs.pop_veh(veh_id):
            self.__logger.leave_SCS(self.__ctime, veh, trip.from_node)
        veh.stop_charging()
        veh.status = VehStatus.Pending
        return True, weights

    def __end_trip(self, veh_id: str):
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
        self.__logger.arrive(self.__ctime, veh, arr_sta)
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
            self._scs.add_veh(veh.ID, veh.trip.to_node)
            ret = True
        except:
            pass
        if ret:
            self.__logger.join_SCS(self.__ctime, veh, veh.trip.to_node)
        return ret

    def __start_charging_FCS(self, veh: EV):
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
        self._fcs.add_veh(veh.ID, veh.target_CS)
        self.__logger.arrive_CS(self.__ctime, veh, veh.target_CS)

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

    #@FEasyTimer
    def __batch_depart(self) -> Dict[str, Optional[TWeights]]:
        """
        All vehicles that arrive at the departure queue are sent out
            self.__ctime: Current time, in seconds
        Return:
            Departure dictionary, the key is the vehicle ID, and the value is the fast charging station selection parameter (if there is no need to go to the fast charging station, it is None)
        """
        ret = {}
        while not self._que.empty() and self._que.top[0] <= self.__ctime:
            depart_time, veh_id = self._que.pop()
            veh = self._VEHs[veh_id]
            trip = veh.trip
            success, weights = self.__start_trip(veh_id)
            if success:
                depart_delay = max(0, self.__ctime - depart_time)
                self.__logger.depart(self.__ctime, veh, depart_delay, veh.target_CS, weights)
                ret[veh_id] = weights
            else:
                available_cs = self._fcs.get_online_CS_names(self.__ctime)
                if len(available_cs) == 0:
                    raise RuntimeError("No FCS is available at this time, please check the configuration")
                
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
        return ret

    #@FEasyTimer
    def __FCS_update(self, sec: int):
        """
        Charging station update: Charge all vehicles in the charging station, and send out the vehicles that have completed charging
            sec: Simulation seconds
        """
        veh_ids = self._fcs.update(sec, self.__ctime)
        #veh_ids.sort()
        for i in veh_ids:
            self.__end_charging_FCS(self._VEHs[i])

    #@FEasyTimer
    def __SCS_update(self, sec: int):
        """
        Parking vehicle update: Charge and V2G all parked vehicles in the charging station
            sec: Simulation seconds
        """
        self._scs.update(sec, self.__ctime)

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

    # @FEasyTimer
    def simulation_start(self, start_time: Optional[int] = None):
        """
        Start simulation
            sumocfg_file: SUMO configuration file path
            start_time: Start time (seconds), if not specified, provided by the SUMO configuration file
            gui: Whether to display the graphical interface
        """
        
        self.__ctime = self.__stime if start_time is None else start_time
        self.W.exec_simulation(self.__ctime)
        
        self.__batch_depart()

        for cs in chain(self.FCSList, self.SCSList):
            if cs._x == float('inf') or cs._y == float('inf'):
                cs._x, cs._y = self.__rnet.get_node(cs.name).get_coord()
        
        if self.FCSList._kdtree == None:
            self.FCSList._kdtree = KDTree(
                (Point(cs._x, cs._y) for cs in self.FCSList),
                range(self.FCSList._n)
            )
        
        if self.SCSList._kdtree == None:
            self.SCSList._kdtree = KDTree(
                (Point(cs._x, cs._y) for cs in self.SCSList),
                range(self.SCSList._n)
            )

    # @FEasyTimer
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
                self.__end_trip(v)
            else:
                self.__start_charging_FCS(self._VEHs[v])

        # Process vehicles in charging stations and parked vehicles
        self.__FCS_update(deltaT)
        self.__SCS_update(deltaT)

        # Process faulty vehicles
        while not self._fQ.empty() and self._fQ.top[0] <= self.__ctime:
            _, v = self._fQ.pop()
            self.__start_charging_FCS(self._VEHs[v])

    def simulation_stop(self):
        print(self.W.shutdown())
        self.__logger.close()
    
    def save_state(self, folder: str):
        """
        Save the current state of the simulation
            folder: Folder path
        """
        f = Path(folder)
        f.mkdir(parents=True, exist_ok=True)
        with gzip.open(str(f / "inst.gz"), "wb") as f:
            pickle.dump({
                "ctime":self.__ctime,
                "fQ":self._fQ,
                "aQ":self._aQ,
                "que":self._que,
                "VEHs":self._VEHs,
                "fcs":self._fcs,
                "scs":self._scs,
                "names_fcs":self.__names_fcs,
                "names_scs":self.__names_scs,
                "W":self.W,
            }, f)
        
    def load_state(self, folder: str):
        """
        Load the state of the simulation
            folder: Folder path
        """
        inst = Path(folder) / "inst.gz"
        if not inst.exists():
            raise FileNotFoundError(Lang.ERROR_STATE_FILE_NOT_FOUND.format(inst))
        with gzip.open(str(inst), "rb") as f:
            d = pickle.load(f)
        self.__ctime = d["ctime"]
        self._fQ = d["fQ"]
        self._aQ = d["aQ"]
        self._que = d["que"]
        self._VEHs = d["VEHs"]
        self._fcs = d["fcs"]
        self._scs = d["scs"]
        self.__names_fcs = d["names_fcs"]
        self.__names_scs = d["names_scs"]
        self.W = d["W"]
        