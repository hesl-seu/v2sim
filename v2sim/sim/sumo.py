import pickle, gzip, heapq, math
from dataclasses import asdict
from feasytools import TimeFunc
from fpowerkit import Grid
from itertools import chain
from pathlib import Path
from typing import Callable, List, Tuple, Dict, Optional, Union, Iterable
from sumolib.net import Net
from sumolib.net.edge import Edge
from ..net import RoadNet
from ..veh import *
from ..hub import *
from ..utils import *
from ..locale import Lang
from .utils import CaseData
from .tlog import TripLogger
from .base import CommonConfig, SUMOConfig, TrafficInst, TRAFFIC_INST_FILE_NAME

from .sumo_backend import (
    Stage, SUMO_FILE_NAME, SUMOSingleBackend, SUMOParallelBackend,
    SUMOStepResult, detect_sumo_partition,
)

ATTR_SUMO_DEST_SCS = "_sumo_dest_scs"
SUMO_SCS_SEARCH_RADIUS_M = 200.0


def dijMC(
    gl: Net, from_edge: str, omega: float, to_edges: Iterable[str],
    node_scores: Dict[str, float], travel_time: Callable[[str], float],
    max_length: float = float('inf')
) -> Stage:
    """
    Find the BEST route based on score = omega * (time + waiting) + charging_cost.
    Uses time as primary key, length as secondary key.
    """
    # (time, length, edge, path, path_edges)

    heap = [(0., 0, from_edge, [from_edge], [])]
    visited = set()
    min_time = {from_edge: 0.}
    best_score = float('inf')
    best_stage = Stage(edges = [], travelTime=float('inf'), length=float('inf'))

    while heap:
        cur_time, cur_len, cur_edge, path, path_edges = heapq.heappop(heap)

        if cur_edge in visited: continue
        visited.add(cur_edge)

        if cur_edge in to_edges:
            score = omega * cur_time + node_scores.get(cur_edge, 0)
            if score < best_score:
                best_score = score
                best_stage = Stage(edges=path_edges + [cur_edge], travelTime=cur_time, length=cur_len)

        e:Edge = gl.getEdge(cur_edge)
        try:
            outgoing = e.getAllowedOutgoing("passenger").keys()
        except Exception:
            outgoing = e.getOutgoing().keys()
        for edge_obj in outgoing:
            edge_obj:Edge
            neighbor:str = edge_obj.getID()
            if neighbor in visited: continue
            new_time = cur_time + travel_time(neighbor)
            new_len = cur_len + edge_obj.getLength()
            if new_len > max_length:
                continue
            if neighbor not in min_time or new_time < min_time[neighbor]:
                min_time[neighbor] = new_time
                heapq.heappush(heap, (new_time, new_len, neighbor, path + [neighbor], path_edges + [cur_edge]))

    return best_stage

class TrafficSUMO(TrafficInst):
    def __init__(
        self, start_time: int, step_len: int, end_time: int, roadnet:RoadNet, 
        trip_logger: TripLogger, vehs: VDict, hubs: MixedHub, pdn: Grid, 
        gasoline_price:TimeFunc, seed: int = 0, silent: bool = False, *,
        road_net_file: str,
        initial_state_folder: str = "",
        routing_algo:str = "CH",
        ignore_driving:bool = False,
        suppress_route_not_found:bool = True,
        gui: bool = False,
        sumocfg_file: str = "",
        mesosim: bool = False,
        case_dir: str = "",
    ):
        super().__init__(start_time, step_len, end_time, roadnet, trip_logger, vehs, hubs, pdn, gasoline_price, seed, silent)
        self.__seed = seed
        self.__gui = gui
        self.__sumocfg_file = sumocfg_file
        self.__ralgo = routing_algo
        self.__ignore_driving = ignore_driving
        assert self.__ralgo in ["CH", "dijkstra", "astar", "CHWrapper"], f"Invalid routing algorithm: {self.__ralgo}"
        self.__suppress_route_not_found = suppress_route_not_found
        self.__mesosim = mesosim
        
        # Read road network
        self.__snet_file = road_net_file
        self.__snet: Net = self._rnet.sumo
        self.__edges: List[Edge] = self.__snet.getEdges()
        # Get all road names
        self.__names: List[str] = [e.getID() for e in self.__edges]

        # Create SUMO backend.  A case is partitioned when its case folder
        # contains partition/partition.json (also accepts legacy
        # partitions/partitions.json used by the provided sample case).
        case_folder = case_dir or str(Path(sumocfg_file).parent)
        partition = detect_sumo_partition(case_folder, default_meso=mesosim)
        if partition is not None:
            # Partitioned SUMO no longer reports every running vehicle distance
            # each step.  Force the existing end-of-trip energy accounting mode
            # so worker processes only need to query distance for arrivals.
            self.__ignore_driving = True
        if partition is None:
            self.__sumo = SUMOSingleBackend(
                snet=self.__snet,
                sumocfg_file=sumocfg_file,
                net_file=road_net_file,
                start_time=start_time,
                end_time=end_time,
                step_length=step_len,
                routing_algo=routing_algo,
                seed=seed,
                gui=gui,
                mesosim=mesosim,
            )
        else:
            if gui and not silent:
                print("SUMO partition mode uses headless libsumo worker processes; GUI is disabled.")
            self.__sumo = SUMOParallelBackend(
                snet=self.__snet,
                partition=partition,
                start_time=start_time,
                end_time=end_time,
                step_length=step_len,
                routing_algo=routing_algo,
                seed=seed,
                gui=False,
            )
            if not silent:
                micro = sum(1 for pid, meso in partition.meso.items() if not meso)
                meso = sum(1 for pid, meso in partition.meso.items() if meso)
                print(f"SUMO partition mode: {partition.part_count} libsumo processes ({micro} micro, {meso} meso).")

        # Load static shortest paths
        self.__shortest_paths: Dict[Tuple[str,str], Stage] = {}
        self.__backend_state_meta = None

        self.__istate_folder = initial_state_folder

        if self.__istate_folder != "":
            self.__load_v2sim_state(self.__istate_folder)
            return
        
        super()._prepare_trips_and_scs()

    def get_veh_pos(self, veh_id: str) -> Tuple[float, float]:
        return self.__sumo.get_vehicle_position(veh_id)
    
    def get_average_vcr(self) -> float:
        return self.__sumo.get_average_vcr(self.__edges)
    
    def find_route(self, O: str, D: str, use_cache:bool = False) -> Stage:
        """
        Fin the best route from O to D

        :param O: Start edge
        :param D: End edge
        :param use_cache: Whether to use cached results
        """
        if use_cache and (O, D) in self.__shortest_paths:
            return self.__shortest_paths[(O, D)]
        ret:Stage = self.__sumo.find_route(O, D)
        if len(ret.edges) == 0:
            if self.__suppress_route_not_found:
                ret = Stage(edges=[O, D], length=1e9, travelTime=1e9)
                print(Lang.ERROR_ROUTE_NOT_FOUND.format(O, D))
            else:
                raise RuntimeError(Lang.ERROR_ROUTE_NOT_FOUND.format(O, D))
        else:
            self.__shortest_paths[(O, D)] = ret
        return ret
    
    def find_best_station(self, veh: Vehicle, O: str, to_stations: List[str], omega:float,
            to_charge: float, max_dist: float, hub: StationHub) -> Tuple[str, Stage]:
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
        
        ret = dijMC(self.__snet, O, omega, Ds.keys(), scores, self.__sumo.get_traveltime, max_length=max_dist)
        
        if len(ret.edges) == 0:  # No available station within range
            return "", ret
        return Ds[ret.edges[-1]], ret
    
    @property
    def routing_algo(self) -> str:
        """Get the current routing algorithm"""
        return self.__ralgo
    
    def __route_length(
        self,
        route: Iterable[str],
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
    ) -> float:
        """Return a V2Sim-planned route length for canonical energy accounting.

        SUMO's vehicle.getDistance() may have different semantics in micro and
        meso modes, and partition workers may only know segment-local distance.
        We therefore use the route planned by V2Sim as the canonical trip length
        for vehicle energy accounting.
        """
        edges = list(route)
        if not edges:
            return 0.0
        length = 0.0
        for edge_id in edges:
            try:
                length += float(self.__snet.getEdge(edge_id).getLength())
            except Exception:
                pass
        try:
            first_len = float(self.__snet.getEdge(edges[0]).getLength())
            if depart_pos is not None:
                length -= max(0.0, min(first_len, float(depart_pos)))
            last_len = float(self.__snet.getEdge(edges[-1]).getLength())
            if arrival_pos is not None:
                length -= max(0.0, last_len - max(0.0, min(last_len, float(arrival_pos))))
        except Exception:
            pass
        return max(0.0, length)

    @staticmethod
    def __ctpl_or(measured_distance: float, veh: Vehicle) -> float:
        ctpl = getattr(veh, "current_trip_planned_length", 0.0)
        return ctpl if ctpl > EPS else measured_distance

    def _add_veh(
        self,
        veh_id: str,
        route: List[str],
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
        planned_length: Optional[float] = None,
    ):
        veh = self._vehs[veh_id]
        veh.clear_odometer()
        veh.current_trip_planned_length = (
            self.__route_length(route, depart_pos, arrival_pos)
            if planned_length is None else planned_length
        )
        self.__sumo.add_vehicle_route(veh_id, route, depart_pos=depart_pos, arrival_pos=arrival_pos)
    
    def _add_veh2(
        self,
        veh_id: str,
        st_edge: str,
        ed_edge: str,
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
        planned_length: Optional[float] = None,
    ):
        veh = self._vehs[veh_id]
        veh.clear_odometer()
        if planned_length is None:
            stage = self.find_route(st_edge, ed_edge)
            planned_length = self.__route_length(stage.edges, depart_pos, arrival_pos)
        veh.current_trip_planned_length = planned_length
        try:
            self.__sumo.add_vehicle_od(
                veh_id, st_edge, ed_edge, agg_routing,
                depart_pos=depart_pos, arrival_pos=arrival_pos,
            )
        except Exception as e:
            raise RuntimeError(f"(Time = {self._ct})Fail to add vehicle '{veh_id}' into SUMO: {st_edge}->{ed_edge}") from e

    def _end_restore(self, veh: Vehicle):
        if veh._cs is None:
            raise RuntimeError(f"Runtime error: {self._ct}, {veh.brief()}, {veh.status}")
        trip = veh.trip
        if isinstance(veh, EV):
            self._log.depart_FCS(self._ct, veh, veh._cs)
            self._add_veh2(
                veh._name,
                self._hubs.fcs.get_bind_of(veh._cs),
                trip.D,
                depart_pos=self.__station_pos(veh._cs),
                arrival_pos=trip.DPos,
            )
        elif isinstance(veh, GV):
            self._log.depart_GS(self._ct, veh, veh._cs)
            self._add_veh2(
                veh._name,
                self._hubs.gs.get_bind_of(veh._cs),
                trip.D,
                depart_pos=self.__station_pos(veh._cs),
                arrival_pos=trip.DPos,
            )
        else:
            raise RuntimeError(Lang.VEH_TYPE_NOT_SUPPORTED.format(veh._name, type(veh)))

        veh._cs = None
        veh._etar = veh._cap
        veh.status = VehStatus.Pending

    @property
    def edges(self):
        """Get all roads"""
        return self.__edges

    def get_edge_names(self) -> List[str]:
        """Get the names of all roads"""
        return self.__names
    
    def __sel_best_station(
        self, veh: Vehicle, cur_edge: Optional[str] = None, cur_pos: Optional[Tuple[float, float]] = None
    ) -> Tuple[str, Stage]:
        """
        Select the nearest available charging station based on the edge where the car is currently located, and return the path and average weight
        
        :param veh: Vehicle instance
        :param cur_edge: Current road, if None, it will be automatically obtained
        :return: The best station name and the route to the selected station
        """
        to_charge = veh._etar - veh._energy
        cur_edge = self.__sumo.get_vehicle_road(veh._name) if cur_edge is None else cur_edge
        cur_pos = self.__sumo.get_vehicle_position(veh._name) if cur_pos is None else cur_pos

        # Distance check
        if isinstance(veh, EV): hub = self._hubs.fcs
        elif isinstance(veh, GV): hub = self._hubs.gs
        else: raise RuntimeError(Lang.VEH_TYPE_NOT_SUPPORTED.format(veh._name, type(veh)))
        
        return self.find_best_station(veh, cur_edge, hub.get_online_names(self._ct),
            veh._w, to_charge, veh.range / veh._kr, hub)


    def __get_edge_pos(self, eid:str) -> Tuple[float, float]:
        e:Edge = self.__snet.getEdge(eid)
        sp = e.getShape()
        assert isinstance(sp, list) and len(sp) > 0
        return sp[0][0], sp[0][1]

    def __station_pos(self, station_name: Optional[str]) -> Optional[float]:
        """Return SUMO longitudinal position for a station, if available."""
        if station_name is None:
            return None
        try:
            pos = self._hubs.get_pos_of(station_name)
        except Exception:
            return None
        if not math.isfinite(pos):
            return None
        return float(pos)

    def __fix_sumo_station_location(self, station: BaseStation):
        """
        Normalize a SUMO station location.

        New station XML may provide bind + pos + x/y. Old files may only have
        bind or bind + x/y. This method fills the missing representation and
        snaps x/y onto the bound edge in SUMO mode.
        """
        try:
            edge = self.__snet.getEdge(station._bind)
        except Exception:
            return

        if math.isfinite(station._pos):
            station._pos = max(0.0, min(float(edge.getLength()), station._pos))
            if not (math.isfinite(station._x) and math.isfinite(station._y)):
                station._x, station._y = self._rnet.get_edge_xy_from_pos(station._bind, station._pos)
            return

        if math.isfinite(station._x) and math.isfinite(station._y):
            station._pos, _, closest = self._rnet.get_edge_pos_from_point(station._bind, station._x, station._y)
            station._x, station._y = closest
        else:
            station._pos = float(edge.getLength()) * 0.5
            station._x, station._y = self._rnet.get_edge_xy_from_pos(station._bind, station._pos)

    def __arrival_xy(self, edge_id: str, pos: Optional[float]) -> Tuple[float, float]:
        if pos is None or not math.isfinite(float(pos)):
            return self._rnet.get_edge_pos(edge_id)
        return self._rnet.get_edge_xy_from_pos(edge_id, float(pos))

    def __planned_stage_and_length(
        self,
        O: str,
        D: str,
        OPos: Optional[float],
        DPos: Optional[float],
    ) -> Tuple[Stage, float]:
        stage = self.find_route(O, D)
        planned_length = self.__route_length(stage.edges, OPos, DPos)
        return stage, planned_length

    @staticmethod
    def __estimated_soc_after(veh: EV, distance: float) -> float:
        return (veh._energy - distance * veh._epm) / veh._cap

    def __select_scs_near_destination(
        self, veh: EV, trip: Trip
    ) -> Tuple[Optional[CS], Optional[Stage], float]:
        dx, dy = self.__arrival_xy(trip.D, trip.DPos)
        best_scs: Optional[CS] = None
        best_stage: Optional[Stage] = None
        best_length = 0.0
        best_score = (1, float("inf"), float("inf"))

        for scs in self.SCSList:
            if not scs.is_online(self._ct):
                continue
            if not (math.isfinite(scs._x) and math.isfinite(scs._y) and math.isfinite(scs._pos)):
                continue
            dist = math.hypot(scs._x - dx, scs._y - dy)
            if dist > SUMO_SCS_SEARCH_RADIUS_M:
                continue
            try:
                stage, planned_length = self.__planned_stage_and_length(
                    trip.O, scs._bind, trip.OPos, scs._pos
                )
            except Exception:
                continue
            if len(stage.edges) == 0:
                continue
            owner_rank = 0 if scs._owners is not None and veh._name in scs._owners else 1
            score = (owner_rank, scs.wait_count(), dist)
            if score < best_score:
                best_score = score
                best_scs = scs
                best_stage = stage
                best_length = planned_length
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
        trip.DPos = scs._pos
        trip.edges = None
        veh._force_sc = True
        setattr(veh, ATTR_SUMO_DEST_SCS, scs._name)

        next_idx = veh.trip_id + 1
        if next_idx < len(veh.trips):
            next_trip = veh.trips[next_idx]
            next_trip.O = scs._bind
            next_trip.OPos = scs._pos
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
        veh.status = VehStatus.Parking
        arr_sta = TripLogger.ARRIVAL_NO_CHARGE
        if isinstance(veh, EV):
            target_scs = getattr(veh, ATTR_SUMO_DEST_SCS, None)
            if target_scs is not None:
                veh._force_sc = False
                if self.__start_charging_SCS_by_name(veh, target_scs):
                    arr_sta = TripLogger.ARRIVAL_CHARGE_SUCCESSFULLY
                else:
                    arr_sta = TripLogger.ARRIVAL_CHARGE_FAILED
                delattr(veh, ATTR_SUMO_DEST_SCS)
            elif veh.soc < veh._ks or veh._force_sc:
                veh._force_sc = False
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
    
    def __start_trip(self, veh:Vehicle) -> bool:
        """
        Start the current trip of a vehicle
            veh_id: Vehicle ID
        Return:
            Departure succeeded: True, Fast charging station selection weight (if fast charging is required)
            Departure failed: False, None
        """
        trip = veh.trip
        direct_depart = True
        base_stage, base_length = self.__planned_stage_and_length(
            trip.O, trip.D, trip.OPos, trip.DPos
        )
        stage, planned_length = self.__maybe_redirect_trip_to_scs(veh, base_stage, base_length)
        trip = veh.trip

        if self._dist_based_restoration:
            # Determine whether the battery is sufficient for the actual destination.
            direct_depart = (not veh._fr_on_dpt) and veh.is_energy_enough(planned_length)
        else:
            # Determine whether the EV needs to be fast charged.
            direct_depart = (not veh._fr_on_dpt) and veh.soc >= veh._kf
        if direct_depart:  # Direct departure
            veh._cs = None
            veh._etar = veh._cap
            self._add_veh(
                veh._name, stage.edges, trip.OPos, trip.DPos,
                planned_length=planned_length,
            )
        else:  # Charge once on the way
            if veh._fr_on_dpt is not None and veh._dpt_rs is not None:
                # Forced to a specified fast charging station
                veh._cs = veh._dpt_rs
                self._add_veh2(
                    veh._name, trip.O, self._hubs.get_bind_of(veh._dpt_rs),
                    depart_pos=trip.OPos, arrival_pos=self.__station_pos(veh._dpt_rs),
                )
            else:
                x, y = self.__get_edge_pos(trip.O)
                station, route = self.__sel_best_station(veh, trip.O, (x, y))
                if len(route.edges) == 0:
                    # The power is not enough to drive to any charging station, you need to charge for a while
                    veh._cs = None
                    veh._fr_on_dpt = False  # Clear the fast charge force flag
                    veh._dpt_rs = None  # Clear the fast charge target flag
                    return False
                else: # Found a charging station
                    veh.target_CS = station
                    self._add_veh(veh._name, route.edges, trip.OPos, self.__station_pos(station))
        if isinstance(veh, EV):
            # Stop slow charging of the vehicle and add it to the waiting to depart set
            if self._hubs.scs.pop_veh(veh):
                self._log.leave_SCS(self._ct, veh, trip.O)
        veh.status = VehStatus.Pending
        veh._fr_on_dpt = False  # Clear the fast charge force flag
        veh._dpt_rs = None  # Clear the fast charge target flag
        return True

    def __get_nearest_station(
        self, cur_edge: str, hub: StationHub
    ) -> Tuple[Optional[str], float, Optional[Stage]]:
        """
        Find the nearest charging station
            cur_edge: Current road
        """
        min_s_name = None
        min_s_dist = 1e400
        min_s_stage = None
        for s in hub.get_online_names(self._ct):
            route = self.find_route(cur_edge, hub.get_bind_of(s))
            if route.length < min_s_dist:
                min_s_dist = route.length
                min_s_name = s
                min_s_stage = route
        return min_s_name, min_s_dist, min_s_stage

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

                cs_name, cs_dist, cs_stage = self.__get_nearest_station(trip.O, self._hubs.fcs if isinstance(veh, EV) else self._hubs.gs)
                batt_req = cs_dist * veh._epm * veh._kr
                if isinstance(veh, EV) and  self._hubs.scs.has_veh(veh._name):
                    # Plugged in the charging pile, you can wait
                    delay = int(1 + (batt_req - veh._energy) / veh._pcr)
                    self._log.depart_delay(self._ct, veh, batt_req, delay)
                    self._que.push(depart_time + delay, (veh_id, None))
                else:
                    # Not plugged in the charging pile, sent to the nearest fast charging station (consume 2 times of the running time)
                    veh.status = VehStatus.Depleted
                    assert cs_name is not None and cs_stage is not None, "No FCS found, please check the configuration"
                    veh.target_CS = cs_name
                    trT = int(self._ct + 2 * cs_stage.travelTime)
                    self._fQ.push(trT, veh._name)
                    self._log.depart_failed(self._ct, veh, batt_req, cs_name, trT)
    
    def simulation_start(self):
        """
        Start simulation.
        """
        self.__sumo.start()

        if self.__istate_folder:
            self.__load_sumo_state(self.__istate_folder)
            self.__istate_folder = ""

        self._ct = int(self.__sumo.get_time())

        for cs in chain(self.FCSList, self.SCSList, self.GSList):
            self.__fix_sumo_station_location(cs)

        from scipy.spatial import KDTree
        if self.FCSList._kdtree == None:
            self.FCSList._kdtree = KDTree([(cs._x, cs._y) for cs in self.FCSList])

        if self.SCSList._kdtree == None:
            self.SCSList._kdtree = KDTree([(cs._x, cs._y) for cs in self.SCSList])

        self.__batch_depart()

    def simulation_step(self, step_len: int):
        """
        Simulation step.
            step_len: Step length (seconds)
            v2g_demand: V2G demand list (kWh/s)
        """
        step_result: SUMOStepResult = self.__sumo.simulation_step(self._ct + step_len)
        new_time = int(step_result.time)
        deltaT = new_time - self._ct
        self._ct = new_time

        # Depart vehicles before processing arrivals.
        # If a vehicle arrives and departs in the same step, performing departure after arrival immediately will cause the vehicle to be unable to depart.
        # Therefore, all departures are processed first and can be delayed to the next step without changing the V2Sim state semantics.
        self.__batch_depart()

        # Process arrived vehicles.  In partitioned SUMO this list only contains
        # vehicles that have completed the whole V2Sim trip; arrivals at
        # partition boundaries are transferred internally by the backend.
        for v, snap in step_result.arrived.items():
            if v not in self._vehs:
                continue
            veh = self._vehs[v]
            dist = self.__ctpl_or(snap.distance, veh)
            veh.drive(dist)
            if veh._cs is None: self._end_trip(veh, dist)
            else: self._start_restore(veh, dist)

        if self.__ignore_driving:
            # Process departed vehicles
            for v in step_result.departed:
                if v not in self._vehs:
                    continue
                veh = self._vehs[v]
                if veh._sta == VehStatus.Pending:
                    veh._sta = VehStatus.Driving
        else:
            # Process driving vehicles
            for veh_id, snap in step_result.running.items():
                if veh_id not in self._vehs:
                    continue
                veh = self._vehs[veh_id]
                running_dist = snap.distance
                if veh.current_trip_planned_length > EPS:
                    running_dist = min(running_dist, veh.current_trip_planned_length)
                veh.drive(running_dist)
                if veh._energy <= 0:
                    # Vehicles with depleted batteries will be sent to the nearest fast charging station (time * 2)
                    veh._sta = VehStatus.Depleted
                    cur_edge = snap.road or self.__sumo.get_vehicle_road(veh_id)
                    veh._cs, _, cs_stage = self.__get_nearest_station(cur_edge, self._hubs.fcs if isinstance(veh, EV) else self._hubs.gs)
                    assert cs_stage is not None and veh._cs is not None
                    trT = int(self._ct + 2 * cs_stage.travelTime)
                    self._fQ.push(trT, veh_id)
                    self.__sumo.remove_vehicle(veh_id)
                    self._log.fault_deplete(self._ct, veh, veh._cs, trT)
                    continue
                if veh._sta == VehStatus.Pending:
                    veh._sta = VehStatus.Driving
                if veh._sta == VehStatus.Driving:
                    if veh._cs is not None and self._hubs[veh._cs].is_offline(self._ct):
                        # Target FCS is offline, redirected to the nearest FCS
                        station, route = self.__sel_best_station(veh)
                        if len(route.edges) == 0:
                            # The power is not enough to drive to any charging station, remove from the network
                            veh._sta = VehStatus.Depleted
                            self.__sumo.remove_vehicle(veh_id)
                            self._fQ.push(self._ct, veh_id)
                            self._log.fault_nocharge(self._ct, veh, veh._cs)
                            veh.target_CS = None
                        else:  # Found the charging station
                            new_cs = station
                            old_cs = veh._cs
                            new_pos = self.__station_pos(new_cs)
                            # setRoute can only change the remaining edge list.
                            # It cannot set an arrivalPos, so use a managed SUMO
                            # stop at the station's exact bind+pos.  The backend
                            # removes the vehicle immediately when the stop starts
                            # and reports it as an arrival to V2Sim.
                            self.__sumo.set_station_stop(
                                veh_id, route, self._hubs.get_bind_of(new_cs), new_pos
                            )
                            veh.current_trip_planned_length = veh.odometer + self.__route_length(
                                route.edges, arrival_pos=new_pos
                            )
                            self._log.fault_redirect(self._ct, veh, old_cs, new_cs)
                            veh.target_CS = new_cs
                else:
                    print(f"Error: {veh.brief()}, {veh._sta}")

        super().post_simulation_step(deltaT)

    def simulation_stop(self):
        self.__sumo.close()
        self._log.close()

    def save(self, folder: Union[str, Path]):
        """Save the current state of the simulation to a folder"""
        f = Path(folder) if isinstance(folder, str) else folder
        f.mkdir(parents=True, exist_ok=True)
        backend_meta = self.__sumo.save_state(f)
        obj = {
            "ctime":self._ct,
            "fQ":self._fQ,
            "que":self._que,
            "VEHs":self._vehs,
            "hubs":self._hubs,
            "sumo_backend": backend_meta,
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
            raise RuntimeError(f"Python version mismatch for TrafficInst: Expect {PyVersion()}, got {d['version']}")
        if d["pickler"] != pickle.__name__:
            raise RuntimeError(f"Pickler mismatch for TrafficInst: Expect {pickle.__name__}, got {d['pickler']}")
        d = d["obj"]
        self._ct = d["ctime"]
        self._fQ = d["fQ"]
        self._que = d["que"]
        self._vehs: VDict = d["VEHs"]
        self._hubs: MixedHub = d["hubs"]
        self.__backend_state_meta = d.get("sumo_backend")

    def __load_sumo_state(self, folder: str):
        self.__sumo.load_state(folder, self.__backend_state_meta)

    def load_state(self, folder: str):
        """
        Load the state of the simulation
            folder: Folder path
        """
        self.__load_v2sim_state(folder)
        self.__load_sumo_state(folder)

    @staticmethod
    def create(
        case: CaseData,
        tlogger: TripLogger,
        vscfg: CommonConfig,
        config: SUMOConfig,
        seed:int = 0,
        silent:bool = False,
    ):
        tc = case.time_config
        sumo = case.files.sumo
        assert sumo is not None, "Internal error: SUMO configuration file is None"
        net = case.files.net
        assert net is not None, "Internal error: Network file is None"
        return TrafficSUMO(
            tc.start_time, tc.step_length, tc.end_time,
            case.road_network, tlogger, case.vehicles,
            case.mixed_hub, case.power_network, 
            vscfg.gasoline_price, seed, silent,
            road_net_file = net,
            sumocfg_file = sumo,
            routing_algo = vscfg.routing_algorithm,
            case_dir = case.case_dir,
            **asdict(config)
        )
    
    @staticmethod
    def load(
        case: CaseData,
        folder: str,
        tlogger: TripLogger,
        vscfg: CommonConfig,
        config: SUMOConfig,
        seed:int = 0,
        silent:bool = False,
    ):
        tc = case.time_config
        sumo = case.files.sumo
        assert sumo is not None, "Internal error: SUMO configuration file is None"
        net = case.files.net
        assert net is not None, "Internal error: Network file is None"
        return TrafficSUMO(
            tc.start_time, tc.step_length, tc.end_time,
            case.road_network, tlogger, case.vehicles,
            case.mixed_hub, case.power_network,
            vscfg.gasoline_price, seed, silent,
            road_net_file = net,
            sumocfg_file = sumo,
            initial_state_folder = folder,
            routing_algo = vscfg.routing_algorithm,
            case_dir = case.case_dir,
            **asdict(config)
        )


__all__ = ["TrafficInst", "TRAFFIC_INST_FILE_NAME", "SUMO_FILE_NAME"]