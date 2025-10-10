from collections import deque
from itertools import chain
from pathlib import Path
import random
import heapq
import pickle
import gzip
from typing import Sequence, List, Tuple, Dict
from sumolib.net import readNet, Net
from sumolib.net.edge import Edge
from sumolib.net.node import Node
from feasytools import PQueue, Point
from uxsim import World, Link, Vehicle

from .trip import TripsLogger
from .cslist import *
from .ev import *
from .utils import TWeights



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

@dataclass
class Stage:
    nodes: List[str]
    travelTime: float
    length: float

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
        """
        random.seed(seed)
        self.__logger = TripsLogger(clogfile)
        
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
        
        # Create uxsim world
        self.W = World(tmax = self.__etime, deltan = self.__step_len, name = Path(road_net_file).stem, random_seed=seed)
        self._uvi:Dict[str, Vehicle] = {}

        self.nodes:Dict[str, Node] = {n.getID(): n for n in self.__rnet.getNodes()}
        for u in self.nodes.values():
            x, y = u.getCoord()
            self.W.addNode(name = u.getID(), x = x, y = y)
        
        self.gl:Dict[str, List[Tuple[str, str, Link]]] = {nid: [] for nid in self.nodes}
        self.edges_dict:Dict[str, Edge] = {e.getID(): e for e in self.__rnet.getEdges()}
        for e in self.edges_dict.values():
            en:str = e.getID()
            fr:Node = e.getFromNode()
            frn:str = fr.getID()
            to:Node = e.getToNode()
            ton:str = to.getID()
            link = self.W.addLink(name = en, start_node = frn, end_node = ton,
                length = e.getLength(), free_flow_speed = e.getSpeed(), number_of_lanes = e.getLaneNumber())
            self.gl[frn].append((ton, en, link))
        
        # Load vehicles to charging stations and prepare to depart
        for veh in self._VEHs.values():
            self._que.push(veh.trip.depart_time, veh.ID)
            if veh.trip.from_node not in self.__names_scs:
                continue  # Only vehicles with slow charging stations can be added to the slow charging station
            # There is a 20% chance of adding to a rechargeable parking point
            if veh.SOC < veh.ksc or random.random() <= 0.2:
                self._scs.add_veh(veh.ID, veh.trip.from_node)

    def find_route(self, from_node: str, to_node: str) -> Stage:
        """
        Use heap-optimized Dijkstra algorithm to find the shortest time route from from_node to to_node.
        """
        heap = [(0, 0, from_node, [from_node])]
        visited = set()
        min_time = {from_node: 0}
        while heap:
            cur_time, cur_len, cur_node, path = heapq.heappop(heap)
            if cur_node in visited:
                continue
            visited.add(cur_node)
            if cur_node == to_node:
                return Stage(path, cur_time, cur_len)
            for neighbor, _, link in self.gl[cur_node]:
                if neighbor in visited:
                    continue
                next_time = cur_time + link.instant_travel_time(self.__ctime)
                next_len = cur_len + link.length
                if neighbor not in min_time or next_time < min_time[neighbor]:
                    min_time[neighbor] = next_time
                    heapq.heappush(heap, (next_time, next_len, neighbor, path + [neighbor]))
        return Stage([], float('inf'), float('inf'))
    
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
        tn = self.W.get_node(to_node)
        v = self.W.addVehicle(orig=from_node, dest=to_node, departure_time=self.__ctime, name=veh_id)
        def __add_to_arrQ():
            self._aQ.append(veh_id)
        v.node_event[tn] = __add_to_arrQ
        self._uvi[veh_id] = v


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
        self, veh: EV, omega: float, current_node: Optional[str] = None, 
        current_edge: Optional[str] = None, cur_pos: Optional[Point] = None
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
        
        if current_node is None:
            if veh.ID not in self._uvi:
                raise RuntimeError(f"Vehicle {veh.ID} not found in simulator")
            if current_edge is None:
                link:Optional[Link] = self._uvi[veh.ID].link
            else:
                link = self.W.get_link(current_edge)
            if link is None:
                raise RuntimeError(f"Vehicle {veh.ID} has no current link")
            current_node = link.end_node.name
        assert isinstance(current_node, str)
        
        if cur_pos is None:
            if veh.ID not in self._uvi:
                raise RuntimeError(f"Vehicle {veh.ID} not found in simulator")
            x, y = self._uvi[veh.ID].get_xy_coords()
            cur_pos = Point(x, y)

        # Distance check
        cs_names: List[str] = []
        veh_cnt: List[int] = []
        slots: List[int] = []
        prices: List[float] = []
        stages: List[Stage] = []
        for cs_i in self._fcs.select_near(cur_pos,10):
            cs = self._fcs[cs_i]
            if not cs.is_online(self.__ctime): continue
            stage = self.find_route(current_node, cs.name)
            if veh.is_batt_enough(stage.length):
                cs_names.append(cs.name)
                veh_cnt.append(cs.veh_count())
                slots.append(cs.slots)
                prices.append(cs.pbuy(self.__ctime))
                stages.append(stage)

        if len(cs_names) == 0:
            return [], (-1, -1, -1)

        t_drive = [t.travelTime/60 for t in stages]  # Convert travel time to minutes
        t_wait = [max((t-lim)*30, 0) for t, lim in zip(veh_cnt, slots)]  # Queue time: 30 minutes per vehicle

        # Total weight
        weight = [
            omega * (td + tw) + to_charge * p for td, tw, p in zip(t_drive, t_wait, prices)
        ]

        wret = (_mean(t_drive), _mean(t_wait), _mean(prices))
        # Return the path and weight to the charging station with the minimum weight
        return stages[_argmin(weight)].nodes, wret
    
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
            x, y = self.__rnet.getNode(trip.from_node).getCoord()
            route, weights = self.__sel_best_CS(veh, veh.omega, 
                current_node = trip.from_node, cur_pos = Point(x, y))
            if len(route) == 0:
                # The power is not enough to drive to any charging station, you need to charge for a while
                veh.target_CS = None
                return False, None
            else: # Found a charging station
                veh.target_CS = route[-1]
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
            route = self.find_route(cur_edge, cs)
            if route.length < min_cs_dist:
                min_cs_dist = route.length
                min_cs_name = cs
                min_cs_stage = route
        return min_cs_name, min_cs_dist, min_cs_stage

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
                cs_name, cs_dist, cs_stage = self.__get_nearest_CS(trip.from_node)
                batt_req = cs_dist * veh.consumption * veh.krel
                if self._scs.has_veh(veh.ID):
                    # Plugged in the charging pile, you can wait
                    delay = int(1 + (batt_req - veh.battery) / veh.rate)
                    self.__logger.depart_delay(self.__ctime, veh, batt_req, delay)
                    self._que.push(depart_time + delay, veh_id)
                else:
                    # Not plugged in the charging pile, sent to the nearest fast charging station (consume 2 times of the running time)
                    veh.status = VehStatus.Depleted
                    assert cs_name is not None and cs_stage is not None, "No FCS found, please check the configuration"
                    veh.target_CS = cs_name
                    trT = int(self.__ctime + 2 * cs_stage.travelTime)
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

    def simulation_start(
        self,
        sumocfg_file: str,
        net_file: str,
        start_time: Optional[int] = None,
        gui: bool = False,
    ):
        """
        Start simulation
            sumocfg_file: SUMO configuration file path
            start_time: Start time (seconds), if not specified, provided by the SUMO configuration file
            gui: Whether to display the graphical interface
        """
        
        self.__ctime = self.__stime if start_time is None else start_time
        self.W.exec_simulation(until_t=self.__ctime)
        
        self.__batch_depart()

        for cs in chain(self.FCSList, self.SCSList):
            if cs._x == float('inf') or cs._y == float('inf'):
                cs._x, cs._y = self.__rnet.getNode(cs.name).getCoord()
        
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
        while self._aQ:
            v = self._aQ.popleft()
            veh = self._VEHs[v]
            v0 = self._uvi[v]
            v0.node_event.clear() # Trigger only once
            route, timepoint = v0.traveled_route()
            dist = sum(link.length for link in route.links)
            veh.drive(dist)
            if veh.target_CS is None:
                self.__end_trip(v)
            else:
                self.__start_charging_FCS(self._VEHs[v])
            self.W.VEHICLES.pop(v)
            self._uvi.pop(v)

        # Process vehicles in charging stations and parked vehicles
        self.__FCS_update(deltaT)
        self.__SCS_update(deltaT)

        # Process faulty vehicles
        while not self._fQ.empty() and self._fQ.top[0] <= self.__ctime:
            _, v = self._fQ.pop()
            self.__start_charging_FCS(self._VEHs[v])

    def simulation_stop(self):
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
        