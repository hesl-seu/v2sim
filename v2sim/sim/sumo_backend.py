"""SUMO backends used by :mod:`v2sim.sim.sumo`.

The ordinary backend wraps one SUMO/libsumo instance.  The partitioned
backend runs one libsumo instance per road-network partition in separate
Python processes.  libsumo is intentionally imported inside worker processes
for the partitioned backend so every process owns exactly one SUMO simulation.
"""

from __future__ import annotations

import heapq
import json
import math
import multiprocessing as mp
import platform
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

@dataclass
class Stage:
    """Small route-stage object compatible with the fields V2Sim uses.

    libsumo may return its own Stage object from ``simulation.findRoute`` in
    single-SUMO mode.  V2Sim only needs ``edges``, ``travelTime`` and
    ``length``, so the custom routers in this module use this lightweight
    object instead of importing traci.
    """

    edges: List[str]
    travelTime: float = 0.0
    length: float = 0.0
    cost: float = 0.0
    depart: float = -1.0
    departPos: float = 0.0
    arrivalPos: float = 0.0
    description: str = ""
    intended: str = ""
    type: str = "driving"


SUMO_FILE_NAME = "traffic.gz"


def _sumo_pos(pos: Optional[float], default: str) -> str:
    """Convert an optional edge position to the string values expected by TraCI."""
    return default if pos is None else f"{float(pos):g}"


def _route_id_for_vehicle(veh_id: str) -> str:
    """Return the per-vehicle temporary route id used for dynamic insertion."""
    return f"__v2sim_route_{veh_id}"


def _add_vehicle_with_route(
    api: Any,
    veh_id: str,
    route_edges: Sequence[str],
    depart_pos: Optional[float] = None,
    arrival_pos: Optional[float] = None,
):
    """Add a vehicle on an explicit route so depart/arrival positions are meaningful.

    SUMO interprets ``departPos`` on the first edge of ``routeID`` and
    ``arrivalPos`` on the last edge of ``routeID``.  Adding a vehicle with an
    empty route id asks SUMO to place it on a random edge, so positions cannot
    describe the requested OD pair.
    """
    edges = list(route_edges)
    if len(edges) == 0:
        raise RuntimeError(f"Cannot add vehicle {veh_id}: empty route")
    route_id = _route_id_for_vehicle(veh_id)
    try:
        api.route.remove(route_id)
    except Exception:
        pass
    api.route.add(route_id, edges)
    api.vehicle.add(
        veh_id,
        route_id,
        departPos=_sumo_pos(depart_pos, "base"),
        arrivalPos=_sumo_pos(arrival_pos, "max"),
    )


@dataclass
class SUMOVehicleSnapshot:
    """Cached vehicle state returned by a SUMO backend after a step."""

    veh_id: str
    distance: float
    road: str = ""
    position: Tuple[float, float] = (math.nan, math.nan)


@dataclass
class SUMOStepResult:
    """Aggregated result of one traffic step."""

    time: int
    arrived: Dict[str, SUMOVehicleSnapshot]
    departed: List[str]
    running: Dict[str, SUMOVehicleSnapshot]


@dataclass
class SUMOPartitionSpec:
    folder: Path
    config_file: Path
    edges: Dict[int, List[str]]
    edge_to_part: Dict[str, int]
    meso: Dict[int, bool]
    net_files: Dict[int, Path]

    @property
    def part_count(self) -> int:
        return len(self.edges)


@dataclass
class _RouteSegment:
    part_id: int
    edges: List[str]


@dataclass
class _ActiveRoute:
    segments: List[_RouteSegment]
    segment_index: int
    distance_offset: float
    part_id: int
    arrival_pos: Optional[float] = None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "meso", "mesoscopic"}:
            return True
        if v in {"0", "false", "no", "n", "micro", "microscopic", "macro"}:
            return False
    return bool(value)


def _edge_list(route: Union[Stage, Sequence[str], Any]) -> List[str]:
    if isinstance(route, Stage) or hasattr(route, "edges"):
        return route.edges # type: ignore
    return list(route)


def _import_single_sumo_api(gui: bool = False):
    """Import the SUMO control module for a non-partitioned simulation.

    V2Sim historically used libsumo on Linux and optionally traci for the
    Windows visualizer.  Keep that behavior for normal single-SUMO runs.  The
    partitioned backend never calls this helper; it imports libsumo directly in
    each worker process.
    """

    if platform.system() != "Linux":
        try:
            from .win_vis import WINDOWS_VISUALIZE
        except Exception:
            WINDOWS_VISUALIZE = False
        if gui and WINDOWS_VISUALIZE:
            import traci as api  # type: ignore
            return api
    import libsumo as api  # type: ignore
    return api


def detect_sumo_partition(case_dir: Union[str, Path], default_meso: bool = False) -> Optional[SUMOPartitionSpec]:
    """Detect and load SUMO partition metadata in a case folder.

    The new convention is ``partition/partition.json``.  The splitter bundled
    with older V2Sim builds and the provided 37-node sample use
    ``partitions/partitions.json``.  Both spellings are accepted.
    """

    cdir = Path(case_dir)
    part_folder: Optional[Path] = None
    for name in ("partition", "partitions"):
        p = cdir / name
        if p.is_dir():
            part_folder = p
            break
    if part_folder is None:
        return None

    part_json: Optional[Path] = None
    for base in (cdir, part_folder):
        for name in ("partition.json", "partitions.json"):
            p = base / name
            if p.is_file():
                part_json = p
                break
        if part_json is not None:
            break
    if part_json is None:
        raise FileNotFoundError(
            f"SUMO partition folder exists in {cdir}, but partition.json/partitions.json was not found."
        )

    with open(part_json, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid SUMO partition file: {part_json}")

    raw_edges = data.get("edges") or data.get("partitions") or data.get("parts")
    if not isinstance(raw_edges, dict):
        raise RuntimeError(f"Invalid SUMO partition file {part_json}: missing edges dictionary")

    edges: Dict[int, List[str]] = {}
    edge_to_part: Dict[str, int] = {}
    for pid_raw, eids_raw in raw_edges.items():
        pid = int(pid_raw)
        if not isinstance(eids_raw, list):
            raise RuntimeError(f"Invalid edge list for partition {pid} in {part_json}")
        eids = [str(e) for e in eids_raw]
        edges[pid] = eids
        for eid in eids:
            if eid in edge_to_part and edge_to_part[eid] != pid:
                raise RuntimeError(f"Edge {eid} appears in multiple SUMO partitions")
            edge_to_part[eid] = pid

    raw_meso = data.get(
        "meso",
        data.get(
            "mesosim",
            data.get(
                "mode",
                data.get("type", data.get("types", data.get("sim_type", data.get("simulation_type"))))
            ),
        ),
    )
    meso: Dict[int, bool] = {pid: bool(default_meso) for pid in edges}
    if isinstance(raw_meso, dict):
        for pid_raw, val in raw_meso.items():
            pid = int(pid_raw)
            if pid in meso:
                meso[pid] = _as_bool(val, default_meso)
    elif isinstance(raw_meso, list):
        for i, val in enumerate(raw_meso):
            if i in meso:
                meso[i] = _as_bool(val, default_meso)
    elif raw_meso is not None:
        global_meso = _as_bool(raw_meso, default_meso)
        for pid in meso:
            meso[pid] = global_meso

    net_files: Dict[int, Path] = {}
    for pid in edges:
        candidates = [
            part_folder / f"{pid}.net.xml",
            part_folder / f"{pid}.net.xml.gz",
            part_folder / f"part{pid}.net.xml",
            part_folder / f"part{pid}.net.xml.gz",
        ]
        for candidate in candidates:
            if candidate.is_file():
                net_files[pid] = candidate
                break
        if pid not in net_files:
            raise FileNotFoundError(f"Network file for SUMO partition {pid} was not found in {part_folder}")

    return SUMOPartitionSpec(part_folder, part_json, edges, edge_to_part, meso, net_files)


def _safe_outgoing(edge: Any) -> Iterable[Any]:
    try:
        outgoing = edge.getAllowedOutgoing("passenger")
        if hasattr(outgoing, "keys"):
            return outgoing.keys()
        return outgoing
    except Exception:
        try:
            outgoing = edge.getOutgoing()
            if hasattr(outgoing, "keys"):
                return outgoing.keys()
            return outgoing
        except Exception:
            return []


class _RouteFinderMixin:
    """Dijkstra route finding on the full SUMO network.

    Partitioned SUMO cannot call ``simulation.findRoute`` on a full network
    because each libsumo worker only owns one sub-network.  This fallback also
    lets single-SUMO mode recover if SUMO's online router returns no route.
    """

    _snet: Any
    _edge_time_cache: Dict[str, float]

    def _static_travel_time(self, edge_id: str) -> float:
        if edge_id in self._edge_time_cache:
            return self._edge_time_cache[edge_id]
        edge = self._snet.getEdge(edge_id)
        speed = max(float(edge.getSpeed()), 1e-6)
        tt = float(edge.getLength()) / speed
        self._edge_time_cache[edge_id] = tt
        return tt

    def get_traveltime(self, edge_id: str) -> float:
        return self._static_travel_time(edge_id)

    def find_route(self, from_edge: str, to_edge: str) -> Stage:
        return self._dijkstra_route(from_edge, to_edge)

    def _dijkstra_route(self, from_edge: str, to_edge: str) -> Stage:
        try:
            self._snet.getEdge(from_edge)
            self._snet.getEdge(to_edge)
        except Exception:
            return Stage(edges=[], travelTime=float("inf"), length=float("inf"))

        heap: List[Tuple[float, float, str, List[str]]] = []
        start_len = float(self._snet.getEdge(from_edge).getLength())
        start_time = self.get_traveltime(from_edge)
        heapq.heappush(heap, (start_time, start_len, from_edge, [from_edge]))
        best: Dict[str, float] = {from_edge: start_time}
        visited = set()

        while heap:
            cur_time, cur_len, cur_edge, path = heapq.heappop(heap)
            if cur_edge in visited:
                continue
            visited.add(cur_edge)
            if cur_edge == to_edge:
                return Stage(edges=path, travelTime=cur_time, length=cur_len)

            edge_obj = self._snet.getEdge(cur_edge)
            for out_edge in _safe_outgoing(edge_obj):
                try:
                    nid = out_edge.getID()
                except Exception:
                    continue
                if nid in visited:
                    continue
                try:
                    n_len = cur_len + float(out_edge.getLength())
                    n_time = cur_time + self.get_traveltime(nid)
                except Exception:
                    continue
                if n_time < best.get(nid, float("inf")):
                    best[nid] = n_time
                    heapq.heappush(heap, (n_time, n_len, nid, path + [nid]))

        return Stage(edges=[], travelTime=float("inf"), length=float("inf"))


class SUMOSingleBackend(_RouteFinderMixin):
    """Wrapper around a single SUMO/libsumo simulation."""

    def __init__(
        self,
        *,
        snet: Any,
        sumocfg_file: str,
        net_file: str,
        start_time: int,
        end_time: int,
        step_length: int,
        routing_algo: str,
        seed: int,
        gui: bool,
        mesosim: bool,
    ):
        self._snet = snet
        self._sumocfg_file = sumocfg_file
        self._net_file = net_file
        self._start_time = start_time
        self._end_time = end_time
        self._step_length = step_length
        self._routing_algo = routing_algo
        self._seed = seed
        self._gui = gui
        self._mesosim = mesosim
        self._edge_time_cache: Dict[str, float] = {}
        self._last = SUMOStepResult(start_time, {}, [], {})

    @property
    def is_partitioned(self) -> bool:
        return False

    def start(self):
        self._api = _import_single_sumo_api(self._gui)
        self._tc = self._api.constants
        sumo_cmd = [
            "sumo-gui" if self._gui else "sumo",
            "-c", self._sumocfg_file,
            "-n", self._net_file,
            "-b", str(self._start_time),
            "-e", str(self._end_time),
            "--step-length", str(self._step_length),
            "--no-warnings",
            "--routing-algorithm", self._routing_algo,
            "--keep-after-arrival", str(self._step_length),
            "--seed", str(self._seed),
            "--mesosim", str(self._mesosim).lower(),
        ]
        self._api.start(sumo_cmd)

    def close(self):
        if self._api is not None:
            self._api.close()
            del self._api

    def get_time(self) -> int:
        return int(self._api.simulation.getTime())

    def simulation_step(self, until_s: int) -> SUMOStepResult:
        self._api.simulationStep(float(until_s))
        new_time = int(self._api.simulation.getTime())
        arrived: Dict[str, SUMOVehicleSnapshot] = {}
        for veh_id in self._api.simulation.getArrivedIDList():
            arrived[veh_id] = self._snapshot(veh_id)
        arrived_ids = set(arrived)
        running: Dict[str, SUMOVehicleSnapshot] = {}
        for veh_id in self._api.vehicle.getIDList():
            if veh_id not in arrived_ids:
                running[veh_id] = self._snapshot(veh_id)
        self._last = SUMOStepResult(new_time, arrived, list(self._api.simulation.getDepartedIDList()), running)
        return self._last

    def _snapshot(self, veh_id: str) -> SUMOVehicleSnapshot:
        try:
            dist = float(self._api.vehicle.getDistance(veh_id))
        except Exception:
            dist = 0.0
        try:
            road = str(self._api.vehicle.getRoadID(veh_id))
        except Exception:
            road = ""
        try:
            pos = tuple(self._api.vehicle.getPosition(veh_id))
            if len(pos) != 2:
                pos = (math.nan, math.nan)
        except Exception:
            pos = (math.nan, math.nan)
        return SUMOVehicleSnapshot(veh_id, dist, road, pos)  # type: ignore[arg-type]

    def add_vehicle_route(
        self,
        veh_id: str,
        route: Union[Stage, Sequence[str]],
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
    ):
        route_edges = _edge_list(route)
        if len(route_edges) == 0:
            raise RuntimeError(f"Cannot add vehicle {veh_id}: empty route")
        _add_vehicle_with_route(self._api, veh_id, route_edges, depart_pos, arrival_pos)
        if agg_routing:
            self._api.vehicle.setRoutingMode(veh_id, self._tc.ROUTING_MODE_AGGREGATED)

    def add_vehicle_od(
        self,
        veh_id: str,
        st_edge: str,
        ed_edge: str,
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
    ):
        stage = self.find_route(st_edge, ed_edge)
        if len(stage.edges) == 0:
            raise RuntimeError(f"Route not found for vehicle {veh_id}: {st_edge}->{ed_edge}")
        self.add_vehicle_route(
            veh_id, stage.edges, agg_routing,
            depart_pos=depart_pos, arrival_pos=arrival_pos,
        )

    def set_route(self, veh_id: str, route: Union[Stage, Sequence[str]]):
        self._api.vehicle.setRoute(veh_id, _edge_list(route))

    def remove_vehicle(self, veh_id: str):
        try:
            self._api.vehicle.remove(veh_id)
        except Exception:
            pass

    def get_vehicle_position(self, veh_id: str) -> Tuple[float, float]:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None and not math.isnan(snap.position[0]):
            return snap.position
        pos = self._api.vehicle.getPosition(veh_id)
        return float(pos[0]), float(pos[1])

    def get_vehicle_road(self, veh_id: str) -> str:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None and snap.road:
            return snap.road
        return str(self._api.vehicle.getRoadID(veh_id))

    def get_vehicle_distance(self, veh_id: str) -> float:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None:
            return snap.distance
        return float(self._api.vehicle.getDistance(veh_id))

    def find_route(self, from_edge: str, to_edge: str) -> Stage:
        try:
            ret = self._api.simulation.findRoute(
                from_edge, to_edge, routingMode=self._tc.ROUTING_MODE_AGGREGATED
            )
            if len(ret.edges) > 0:
                return ret
        except Exception:
            pass
        return self._dijkstra_route(from_edge, to_edge)

    def get_traveltime(self, edge_id: str) -> float:
        try:
            return float(self._api.edge.getTraveltime(edge_id))
        except Exception:
            return self._static_travel_time(edge_id)

    def get_average_vcr(self, edges: Sequence[Any]) -> float:
        total = 0.0
        count = 0
        for edge in edges:
            try:
                eid = edge.getID()
                free_speed = max(float(edge.getSpeed()), 1e-6)
                total += float(self._api.edge.getLastStepMeanSpeed(eid)) / free_speed
                count += 1
            except Exception:
                continue
        return 1.0 if count == 0 else total / count

    def save_state(self, folder: Union[str, Path]) -> Optional[dict]:
        path = Path(folder) / SUMO_FILE_NAME
        self._api.simulation.saveState(str(path))
        return None

    def load_state(self, folder: Union[str, Path], meta: Optional[dict] = None):
        path = Path(folder) / SUMO_FILE_NAME
        if not path.exists():
            raise FileNotFoundError(f"SUMO state file not found: {path}")
        self._api.simulation.loadState(str(path))


class _PartitionWorker:
    def __init__(self, ctx: Any, part_id: int, cmd: List[str], edge_speeds: Dict[str, float]):
        self.part_id = part_id
        self.parent_conn, child_conn = ctx.Pipe()
        self.process = ctx.Process(
            target=_sumo_partition_worker_main,
            args=(child_conn, part_id, cmd, edge_speeds),
            daemon=True,
        )
        self.process.start()
        status, payload = self.parent_conn.recv()
        if status != "ok":
            raise RuntimeError(f"Failed to start SUMO partition {part_id}:\n{payload}")
        self.time = int(payload)

    def send(self, op: str, *args: Any):
        self.parent_conn.send((op, args))

    def recv(self) -> Any:
        status, payload = self.parent_conn.recv()
        if status != "ok":
            raise RuntimeError(f"SUMO partition {self.part_id} failed:\n{payload}")
        return payload

    def call(self, op: str, *args: Any) -> Any:
        self.send(op, *args)
        return self.recv()

    def close(self):
        if self.process.is_alive():
            try:
                self.call("close")
            except Exception:
                try:
                    self.parent_conn.close()
                except Exception:
                    pass
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=2)


def _sumo_partition_worker_main(conn: Any, part_id: int, cmd: List[str], edge_speeds: Dict[str, float]):
    api = None
    try:
        import libsumo as api  # type: ignore
        api.start(cmd)
        conn.send(("ok", int(api.simulation.getTime())))
    except BaseException:
        conn.send(("err", traceback.format_exc()))
        return

    def snapshot(veh_id: str) -> Tuple[str, float, str, Tuple[float, float]]:
        try:
            dist = float(api.vehicle.getDistance(veh_id))
        except Exception:
            dist = 0.0
        try:
            road = str(api.vehicle.getRoadID(veh_id))
        except Exception:
            road = ""
        try:
            pos_raw = api.vehicle.getPosition(veh_id)
            pos = (float(pos_raw[0]), float(pos_raw[1]))
        except Exception:
            pos = (math.nan, math.nan)
        return veh_id, dist, road, pos

    while True:
        try:
            op, args = conn.recv()
        except EOFError:
            break
        try:
            if op == "step":
                until_s = args[0]
                api.simulationStep(float(until_s))
                arrived: Dict[str, Tuple[str, float, str, Tuple[float, float]]] = {}
                for vid in api.simulation.getArrivedIDList():
                    arrived[vid] = snapshot(vid)
                arrived_ids = set(arrived)
                # For normal energy accounting V2Sim only needs cumulative
                # distance for running vehicles.  Road/position are requested
                # lazily only for exceptional paths (depletion, offline charging
                # station redirection, GUI queries).  Returning just a float per
                # running vehicle cuts IPC serialization dramatically on 100k+
                # vehicle cases and keeps the workers doing useful SUMO work.
                running: Dict[str, float] = {}
                for vid in api.vehicle.getIDList():
                    if vid not in arrived_ids:
                        try:
                            running[vid] = float(api.vehicle.getDistance(vid))
                        except Exception:
                            running[vid] = 0.0
                conn.send(("ok", {
                    "time": int(api.simulation.getTime()),
                    "arrived": arrived,
                    "departed": list(api.simulation.getDepartedIDList()),
                    "running": running,
                }))
            elif op == "vcr":
                # Average VCR is rarely requested in core V2Sim.  Computing it
                # on every step adds an O(edges) libsumo loop and larger IPC
                # payloads, which is visible on small partitioned cases.
                speed_sum = 0.0
                speed_count = 0
                for eid, free_speed in edge_speeds.items():
                    try:
                        speed_sum += float(api.edge.getLastStepMeanSpeed(eid)) / max(float(free_speed), 1e-6)
                        speed_count += 1
                    except Exception:
                        pass
                conn.send(("ok", (speed_sum, speed_count)))
            elif op == "add_route":
                veh_id, route_edges, agg_routing, depart_pos, arrival_pos = args
                _add_vehicle_with_route(api, veh_id, route_edges, depart_pos, arrival_pos)
                if agg_routing:
                    api.vehicle.setRoutingMode(veh_id, api.constants.ROUTING_MODE_AGGREGATED)
                conn.send(("ok", None))
            elif op == "add_routes":
                # Batch insertion is important in partition mode: otherwise a
                # burst of vehicles crossing a boundary creates one blocking
                # IPC round-trip per vehicle.
                items = args[0]
                for veh_id, route_edges, agg_routing, depart_pos, arrival_pos in items:
                    _add_vehicle_with_route(api, veh_id, route_edges, depart_pos, arrival_pos)
                    if agg_routing:
                        api.vehicle.setRoutingMode(veh_id, api.constants.ROUTING_MODE_AGGREGATED)
                conn.send(("ok", None))
            elif op == "set_route":
                veh_id, route_edges = args
                api.vehicle.setRoute(veh_id, list(route_edges))
                conn.send(("ok", None))
            elif op == "remove":
                veh_id = args[0]
                try:
                    api.vehicle.remove(veh_id)
                except Exception:
                    pass
                conn.send(("ok", None))
            elif op == "get_snapshot":
                conn.send(("ok", snapshot(args[0])))
            elif op == "save":
                api.simulation.saveState(str(args[0]))
                conn.send(("ok", int(api.simulation.getTime())))
            elif op == "load":
                api.simulation.loadState(str(args[0]))
                conn.send(("ok", int(api.simulation.getTime())))
            elif op == "time":
                conn.send(("ok", int(api.simulation.getTime())))
            elif op == "close":
                try:
                    api.close()
                finally:
                    conn.send(("ok", None))
                break
            else:
                raise RuntimeError(f"Unknown SUMO worker command: {op}")
        except BaseException:
            conn.send(("err", traceback.format_exc()))


class SUMOParallelBackend(_RouteFinderMixin):
    """Multi-process libsumo backend for partitioned SUMO cases."""

    def __init__(
        self,
        *,
        snet: Any,
        partition: SUMOPartitionSpec,
        start_time: int,
        end_time: int,
        step_length: int,
        routing_algo: str,
        seed: int,
        gui: bool,
    ):
        self._snet = snet
        self._partition = partition
        self._start_time = start_time
        self._end_time = end_time
        self._step_length = step_length
        self._routing_algo = routing_algo
        self._seed = seed
        self._gui = gui
        self._edge_time_cache: Dict[str, float] = {}
        self._workers: Dict[int, _PartitionWorker] = {}
        self._active: Dict[str, _ActiveRoute] = {}
        # Route search and IPC are the two largest sources of parent-process
        # overhead on large partitioned SUMO cases.  Many generated trips reuse
        # the same OD pair, so keep a backend-level OD cache in addition to the
        # higher level TrafficSUMO cache, which is not used by add_vehicle_od().
        self._route_cache: Dict[Tuple[str, str], Stage] = {}
        # Vehicles added by V2Sim during one tick are queued and flushed to each
        # worker in batches.  This avoids one blocking Pipe round-trip per
        # departing vehicle, which can otherwise keep libsumo workers idle while
        # the parent process is busy injecting tens of thousands of vehicles.
        self._pending_adds: Dict[int, List[Tuple[str, List[str], bool, Optional[float], Optional[float]]]] = {}
        self._last = SUMOStepResult(start_time, {}, [], {})
        self._last_speed_sum = 0.0
        self._last_speed_count = 0

    @property
    def is_partitioned(self) -> bool:
        return True

    @property
    def part_count(self) -> int:
        return self._partition.part_count

    def start(self):
        if self._gui:
            # Multiple GUI instances are not useful here; libsumo workers run headless.
            pass
        if platform.system() == "Linux":
            ctx = mp.get_context("fork")
        else:
            ctx = mp.get_context("spawn")
        for pid in sorted(self._partition.edges):
            cmd = [
                "sumo",
                "-n", str(self._partition.net_files[pid]),
                "-b", str(self._start_time),
                "-e", str(self._end_time),
                "--step-length", str(self._step_length),
                "--no-warnings",
                "--routing-algorithm", self._routing_algo,
                "--keep-after-arrival", str(self._step_length),
                "--seed", str(self._seed + pid),
                "--mesosim", str(self._partition.meso.get(pid, False)).lower(),
            ]
            edge_speeds: Dict[str, float] = {}
            for eid in self._partition.edges[pid]:
                try:
                    edge_speeds[eid] = float(self._snet.getEdge(eid).getSpeed())
                except Exception:
                    pass
            self._workers[pid] = _PartitionWorker(ctx, pid, cmd, edge_speeds)

    def close(self):
        for worker in list(self._workers.values()):
            worker.close()
        self._workers.clear()

    def get_time(self) -> int:
        if self._workers:
            return max(worker.call("time") for worker in self._workers.values())
        return self._last.time

    def _snapshot_from_tuple(self, data: Tuple[str, float, str, Tuple[float, float]], offset: float = 0.0) -> SUMOVehicleSnapshot:
        veh_id, dist, road, pos = data
        return SUMOVehicleSnapshot(veh_id, offset + float(dist), road, pos)

    def _edge_start_position(self, edge_id: str) -> Tuple[float, float]:
        try:
            shape = self._snet.getEdge(edge_id).getShape()
            if shape:
                return float(shape[0][0]), float(shape[0][1])
        except Exception:
            pass
        return math.nan, math.nan

    def find_route(self, from_edge: str, to_edge: str) -> Stage:
        key = (from_edge, to_edge)
        cached = self._route_cache.get(key)
        if cached is not None:
            return cached
        stage = self._dijkstra_route(from_edge, to_edge)
        if len(stage.edges) > 0:
            self._route_cache[key] = stage
        return stage

    def _split_route(self, edges: Sequence[str]) -> List[_RouteSegment]:
        if len(edges) == 0:
            raise RuntimeError("Cannot split an empty SUMO route")
        segments: List[_RouteSegment] = []
        cur_pid: Optional[int] = None
        cur_edges: List[str] = []
        for eid in edges:
            if eid not in self._partition.edge_to_part:
                raise RuntimeError(f"SUMO edge {eid} is not assigned to any partition")
            pid = self._partition.edge_to_part[eid]
            if cur_pid is None or pid == cur_pid:
                cur_edges.append(eid)
                cur_pid = pid
            else:
                assert cur_pid is not None
                segments.append(_RouteSegment(cur_pid, cur_edges))
                cur_edges = [eid]
                cur_pid = pid
        assert cur_pid is not None
        segments.append(_RouteSegment(cur_pid, cur_edges))
        return segments

    def _queue_vehicle_on_segment(
        self,
        veh_id: str,
        active: _ActiveRoute,
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
    ):
        seg = active.segments[active.segment_index]
        active.part_id = seg.part_id
        arrival_pos = active.arrival_pos if active.segment_index == len(active.segments) - 1 else None
        self._pending_adds.setdefault(seg.part_id, []).append(
            (veh_id, list(seg.edges), bool(agg_routing), depart_pos, arrival_pos)
        )

    def _flush_pending_adds(self):
        if not self._pending_adds:
            return
        pending = self._pending_adds
        self._pending_adds = {}
        for pid, payload in pending.items():
            if payload:
                self._workers[pid].send("add_routes", payload)
        for pid, payload in pending.items():
            if payload:
                self._workers[pid].recv()

    def _put_vehicles_on_segments_batch(self, items: Dict[int, List[Tuple[str, _ActiveRoute, bool]]]):
        # One IPC call per destination partition instead of one per transferred
        # vehicle.  This keeps boundary-crossing bursts from dominating large
        # partitioned cases.
        for pid, rows in items.items():
            payload = []
            for veh_id, active, agg_routing in rows:
                seg = active.segments[active.segment_index]
                active.part_id = seg.part_id
                arrival_pos = active.arrival_pos if active.segment_index == len(active.segments) - 1 else None
                payload.append((veh_id, list(seg.edges), bool(agg_routing), None, arrival_pos))
            if payload:
                self._workers[pid].send("add_routes", payload)
        for pid, rows in items.items():
            if rows:
                self._workers[pid].recv()

    def add_vehicle_route(
        self,
        veh_id: str,
        route: Union[Stage, Sequence[str]],
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
    ):
        route_edges = _edge_list(route)
        segments = self._split_route(route_edges)
        active = _ActiveRoute(
            segments=segments,
            segment_index=0,
            distance_offset=0.0,
            part_id=segments[0].part_id,
            arrival_pos=arrival_pos,
        )
        self._active[veh_id] = active
        self._queue_vehicle_on_segment(veh_id, active, agg_routing, depart_pos)

    def add_vehicle_od(
        self,
        veh_id: str,
        st_edge: str,
        ed_edge: str,
        agg_routing: bool = False,
        depart_pos: Optional[float] = None,
        arrival_pos: Optional[float] = None,
    ):
        stage = self.find_route(st_edge, ed_edge)
        if len(stage.edges) == 0:
            raise RuntimeError(f"Route not found for vehicle {veh_id}: {st_edge}->{ed_edge}")
        self.add_vehicle_route(veh_id, stage.edges, agg_routing, depart_pos, arrival_pos)

    def set_route(self, veh_id: str, route: Union[Stage, Sequence[str]]):
        route_edges = _edge_list(route)
        if len(route_edges) == 0:
            raise RuntimeError(f"Cannot set empty route for vehicle {veh_id}")
        if veh_id not in self._active:
            self.add_vehicle_route(veh_id, route_edges)
            return
        active = self._active[veh_id]
        snap = self._last.running.get(veh_id)
        current_road = snap.road if snap is not None else ""
        if not current_road:
            try:
                raw = self._workers[active.part_id].call("get_snapshot", veh_id)
                current_road = str(raw[2])
            except Exception:
                current_road = route_edges[0]
        if current_road in route_edges:
            route_edges = route_edges[route_edges.index(current_road):]
        segments = self._split_route(route_edges)
        if segments[0].part_id != active.part_id:
            # The vehicle is no longer on the partition that owns the new route.
            # Remove and re-insert it at the start of the new segment; this is a
            # recovery path for unusual rerouting calls.
            try:
                self._workers[active.part_id].call("remove", veh_id)
            except Exception:
                pass
            active.segments = segments
            active.segment_index = 0
            active.part_id = segments[0].part_id
            self._queue_vehicle_on_segment(veh_id, active)
            self._flush_pending_adds()
        else:
            active.segments = segments
            active.segment_index = 0
            self._workers[active.part_id].call("set_route", veh_id, segments[0].edges)

    def remove_vehicle(self, veh_id: str):
        active = self._active.pop(veh_id, None)
        if active is not None and active.part_id in self._workers:
            try:
                self._workers[active.part_id].call("remove", veh_id)
            except Exception:
                pass

    def simulation_step(self, until_s: int) -> SUMOStepResult:
        self._flush_pending_adds()
        for worker in self._workers.values():
            worker.send("step", until_s)

        raw_results: Dict[int, dict] = {}
        for pid, worker in self._workers.items():
            raw_results[pid] = worker.recv()

        arrived_final: Dict[str, SUMOVehicleSnapshot] = {}
        running: Dict[str, SUMOVehicleSnapshot] = {}
        departed: List[str] = []
        transferred: Dict[str, SUMOVehicleSnapshot] = {}
        transfer_batches: Dict[int, List[Tuple[str, _ActiveRoute, bool]]] = {}

        for pid, result in raw_results.items():
            departed.extend(result.get("departed", []))

            for veh_id, data in result.get("running", {}).items():
                active = self._active.get(veh_id)
                if active is None:
                    continue
                if isinstance(data, (int, float)):
                    running[veh_id] = SUMOVehicleSnapshot(veh_id, active.distance_offset + float(data))
                else:
                    running[veh_id] = self._snapshot_from_tuple(data, active.distance_offset)

        # Process arrivals after all workers have advanced to the same time.
        for pid, result in raw_results.items():
            for veh_id, data in result.get("arrived", {}).items():
                active = self._active.get(veh_id)
                if active is None:
                    continue
                snap = self._snapshot_from_tuple(data, active.distance_offset)
                if active.segment_index + 1 < len(active.segments):
                    active.distance_offset = snap.distance
                    active.segment_index += 1
                    next_seg = active.segments[active.segment_index]
                    active.part_id = next_seg.part_id
                    transfer_batches.setdefault(next_seg.part_id, []).append((veh_id, active, False))
                    transferred[veh_id] = SUMOVehicleSnapshot(
                        veh_id,
                        active.distance_offset,
                        next_seg.edges[0],
                        self._edge_start_position(next_seg.edges[0]),
                    )
                else:
                    arrived_final[veh_id] = snap
                    self._active.pop(veh_id, None)

        if transfer_batches:
            self._put_vehicles_on_segments_batch(transfer_batches)

        # A transferred vehicle has completed a segment in this step.  It has
        # not moved in its new worker yet, but V2Sim must see the cumulative
        # distance so that energy is deducted before the next step.
        running.update(transferred)

        new_time = max(int(r.get("time", until_s)) for r in raw_results.values()) if raw_results else until_s
        self._last = SUMOStepResult(new_time, arrived_final, departed, running)
        return self._last

    def get_vehicle_position(self, veh_id: str) -> Tuple[float, float]:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None and not math.isnan(snap.position[0]):
            return snap.position
        active = self._active[veh_id]
        data = self._workers[active.part_id].call("get_snapshot", veh_id)
        return float(data[3][0]), float(data[3][1])

    def get_vehicle_road(self, veh_id: str) -> str:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None and snap.road:
            return snap.road
        active = self._active[veh_id]
        data = self._workers[active.part_id].call("get_snapshot", veh_id)
        return str(data[2])

    def get_vehicle_distance(self, veh_id: str) -> float:
        snap = self._last.running.get(veh_id) or self._last.arrived.get(veh_id)
        if snap is not None:
            return snap.distance
        active = self._active[veh_id]
        data = self._workers[active.part_id].call("get_snapshot", veh_id)
        return active.distance_offset + float(data[1])

    def get_average_vcr(self, edges: Sequence[Any]) -> float:
        speed_sum = 0.0
        speed_count = 0
        for worker in self._workers.values():
            part_sum, part_count = worker.call("vcr")
            speed_sum += float(part_sum)
            speed_count += int(part_count)
        if speed_count == 0:
            return 1.0
        return speed_sum / speed_count

    def save_state(self, folder: Union[str, Path]) -> dict:
        self._flush_pending_adds()
        f = Path(folder)
        files: Dict[str, str] = {}
        for pid, worker in self._workers.items():
            state_path = f / f"traffic_part_{pid}.gz"
            worker.call("save", str(state_path))
            files[str(pid)] = state_path.name
        return {
            "type": "partitioned-sumo",
            "files": files,
            "active": {
                veh_id: {
                    "segments": [(seg.part_id, list(seg.edges)) for seg in active.segments],
                    "segment_index": active.segment_index,
                    "distance_offset": active.distance_offset,
                    "part_id": active.part_id,
                }
                for veh_id, active in self._active.items()
            },
        }

    def load_state(self, folder: Union[str, Path], meta: Optional[dict] = None):
        if not isinstance(meta, dict) or meta.get("type") != "partitioned-sumo":
            raise RuntimeError("Partitioned SUMO state metadata is missing or invalid")
        f = Path(folder)
        for pid_raw, filename in meta.get("files", {}).items():
            pid = int(pid_raw)
            if pid not in self._workers:
                continue
            state_path = f / filename
            if not state_path.exists():
                raise FileNotFoundError(f"SUMO partition state file not found: {state_path}")
            self._workers[pid].call("load", str(state_path))
        self._active.clear()
        for veh_id, item in meta.get("active", {}).items():
            segments = [_RouteSegment(int(pid), list(edges)) for pid, edges in item["segments"]]
            self._active[veh_id] = _ActiveRoute(
                segments=segments,
                segment_index=int(item["segment_index"]),
                distance_offset=float(item["distance_offset"]),
                part_id=int(item["part_id"]),
            )
