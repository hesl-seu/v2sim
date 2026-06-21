import os
import random, time
import concurrent.futures as cf
from abc import ABC, abstractmethod
from itertools import chain
from enum import Enum
from typing import Dict, Optional, Tuple, Union
from feasytools import ReadOnlyTable, CDDiscrete, PDDiscrete, PDGamma, DTypeEnum
from ..locale import Lang
from ..utils import DetectFiles
from ..veh import VDict
from ..net import RoadNet
from .misc import *
from .poly import PolygonMan

DictPDF = Dict[int, Union[PDDiscrete[int], None]]

TAZ_TYPE_LIST = ("Home", "Work", "Relax", "Other")

class ProgressBar:
    def __init__(self, total:int, silent:bool = False):
        self.total = total
        self.silent = silent
        self.last_print_time = 0
        self.current = 0
        self.st_time = time.time()
    
    def update(self, current:int):
        if not self.silent:
            if time.time() - self.last_print_time > 1 or current == self.total:
                print(f"\r{current}/{self.total}, {(current)/self.total*100:.2f}%", end="")
                self.last_print_time = time.time()
            if current == self.total:
                print(f"\n{Lang.INFO_DONE_WITH_SECOND.format(round(time.time() - self.st_time, 1))}")
        self.current = current
    
    def increment(self):
        self.update(self.current + 1)


_VEHGEN_WORKER = None


def _init_vehgen_worker(class_name: str, croot: str, pname: str, mode_value: str):
    """
    Initializer for ProcessPoolExecutor workers.
    Each process owns one generator instance and reuses it for all chunks.
    """
    global _VEHGEN_WORKER

    mode = TripsGenMode(mode_value)
    gen_cls = globals()[class_name]
    _VEHGEN_WORKER = gen_cls(croot, pname, mode)


def _gen_veh_chunk_worker(args: Tuple[Any, ...]):
    """
    Generate one chunk of vehicles in a worker process.

    args:
        kind: "any", "ev", or "gv"
        start: start vehicle index
        count: number of vehicles in this chunk
        day_count, omega, krel, kfc, v2g_prop, ksc, kv2g
        seed: per-chunk random seed
    """
    global _VEHGEN_WORKER
    if _VEHGEN_WORKER is None:
        raise RuntimeError("Vehicle generator worker is not initialized.")

    kind, start, count, day_count, omega, krel, kfc, v2g_prop, ksc, kv2g, seed = args

    if seed is not None:
        random.seed(seed)

    evs: Dict[str, EV] = {}
    gvs: Dict[str, GV] = {}

    gen = _VEHGEN_WORKER

    if kind == "ev":
        for i in range(start, start + count):
            v = gen.gen_ev(day_count, f"ev{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
            evs[v._name] = v
    elif kind == "gv":
        for i in range(start, start + count):
            v = gen.gen_gv(day_count, f"gv{i}", omega, krel, kfc)
            gvs[v._name] = v
    elif kind == "any":
        for i in range(start, start + count):
            v = gen.gen_veh(day_count, f"v{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
            if isinstance(v, EV):
                evs[v._name] = v
            elif isinstance(v, GV):
                gvs[v._name] = v
            else:
                raise RuntimeError(f"Invalid vehicle type: {type(v)}")
    else:
        raise ValueError(f"Unknown vehicle generation chunk kind: {kind}")

    return evs, gvs, count

def _gen_veh_chunk_worker_local(gen, args: Tuple[Any, ...]):
    """
    Local fallback used when workers <= 1.
    This avoids ProcessPoolExecutor startup overhead for small jobs.
    """
    kind, start, count, day_count, omega, krel, kfc, v2g_prop, ksc, kv2g, seed = args

    if seed is not None:
        random.seed(seed)

    evs: Dict[str, EV] = {}
    gvs: Dict[str, GV] = {}

    if kind == "ev":
        for i in range(start, start + count):
            v = gen.gen_ev(day_count, f"ev{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
            evs[v._name] = v
    elif kind == "gv":
        for i in range(start, start + count):
            v = gen.gen_gv(day_count, f"gv{i}", omega, krel, kfc)
            gvs[v._name] = v
    elif kind == "any":
        for i in range(start, start + count):
            v = gen.gen_veh(day_count, f"v{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
            if isinstance(v, EV):
                evs[v._name] = v
            elif isinstance(v, GV):
                gvs[v._name] = v
            else:
                raise RuntimeError(f"Invalid vehicle type: {type(v)}")
    else:
        raise ValueError(f"Unknown vehicle generation chunk kind: {kind}")

    return evs, gvs, count


class RoutingCacheMode(Enum):
    """Routing cache mode"""
    NONE = 0  # No cache
    RUNTIME = 1 # Cache during runtime
    STATIC = 2 # Static cache in generation time

    def __str__(self):
        return ("None", "Runtime", "Static")[self.value]

    def __repr__(self):
        return self.value


class TripsGenMode(Enum):
    """Generation mode"""
    AUTO = "Auto"  # Automatic
    NODE = "Node"  # Node Type-based, UXsim Only
    TAZ = "Taz"  # TAZ Type-based, SUMO Only
    POLY = "Poly"  # Polygon-based

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class VehGenerator(ABC):    
    """Class to generate trips"""
    def __init__(self, CROOT: str, PNAME: str):
        """
        Initialization

        :param CROOT: Trip parameter folder
        :param PNAME: Case folder
        """
        self._CROOT = CROOT
        self._PNAME = PNAME
        self._gen_mode = TripsGenMode.AUTO

        self.files = DetectFiles(PNAME)
        if not self.files.vtypes:
            self.vTypes = VehicleTypePool(os.path.join(CROOT, "vtypes.xml"))
        else:
            self.vTypes = VehicleTypePool(self.files.vtypes)
        
        # Start time of first trip
        self.pdf_start_weekday = PDGamma(6.63, 65.76, 114.54)
        self.pdf_start_weekend = PDGamma(3.45, 84.37, 197.53)
        
        # Spatial transfer probability of weekday and weekend. 
        # key1 = from_type, key2 = time (0~95, each unit = 15min), value = CDF of (to_type1, to_type2, to_type3, to_type4)
        self.PSweekday:Dict[str, DictPDF] = {}
        self.PSweekend:Dict[str, DictPDF] = {}
        # Parking duration CDF of weekday and weekend.
        self.park_cdf_wd:Dict[str, CDDiscrete[int]] = {} 
        self.park_cdf_we:Dict[str, CDDiscrete[int]] = {}

        def read_trans_pdfs(path:str) -> DictPDF:
            tbwd = ReadOnlyTable(path, dtype = DTypeEnum.FLOAT32)
            times = [int(x) for x in tbwd.head[1:]]
            values = list(map(int, tbwd.col(0)))
            ret:DictPDF = {}
            for i in range(1, len(times)+1):
                weights = list(map(float, tbwd.col(i)))
                assert len(values) == len(weights)
                try:
                    ret[i] = PDDiscrete(values, weights)
                except ZeroDivisionError:
                    ret[i] = None
            return ret
        
        for dtype in TAZ_TYPE_LIST:
            self.PSweekday[dtype] = read_trans_pdfs(os.path.join(CROOT, "space_transfer_probability", f"{dtype[0]}_spr_weekday.csv"))
            self.PSweekend[dtype] = read_trans_pdfs(os.path.join(CROOT, "space_transfer_probability", f"{dtype[0]}_spr_weekend.csv"))
            self.park_cdf_wd[dtype] = CDDiscrete(os.path.join(CROOT, "duration_of_parking", f"{dtype[0]}_spr_weekday.csv"), True, int)
            self.park_cdf_we[dtype] = CDDiscrete(os.path.join(CROOT, "duration_of_parking", f"{dtype[0]}_spr_weekend.csv"), True, int)

        self.soc_pdf = PDDiscrete.fromCSVFileI(os.path.join(CROOT, "soc_dist.csv"), True)
    
    def _getPs(self, is_weekday: bool, dtype: str, time_index:int):
        return self.PSweekday[dtype].get(time_index, None) if is_weekday else self.PSweekend[dtype].get(time_index, None)
    
    def _getDest1(self, pfr: str, weekday: bool = True):
        """
        Get the destination of the trip secondary to the first trip

        :param pfr: Departure functional area type, such as "Home"
        :param weekday: Whether it is weekday or weekend
        :returns: First departure time, arrival destination functional area type, such as "Work"
        """
        pdf = None
        while pdf is None:
            init_time = self.pdf_start_weekday.sample() if weekday else self.pdf_start_weekend.sample()
            if init_time >= 86400: continue
            # Time index (0~95, each unit = 15min)
            init_time_i = int(init_time / 15)
            pdf = self._getPs(weekday, pfr, init_time_i)
        next_place = TAZ_TYPE_LIST[pdf.sample()]
        return int(init_time), next_place
    
    def _getDestA(self, from_type:str, init_time_i:int, weekday: bool):
        """
        Get the destination of the next trip for non-first trips

        :param from_type: Departure type, such as "Home"
        :param init_time_i: Time index (0~95, each unit = 15min)
        :param weekday: Whether it is weekday or weekend
        :returns: Destination type
        """
        cdf = self._getPs(weekday, from_type, init_time_i)
        return "Home" if cdf is None else TAZ_TYPE_LIST[cdf.sample()]
    
    cdf_dict = {}

    def _genStopTimeIdx(self, from_type:str, weekday: bool):
        cdf = self.park_cdf_wd[from_type] if weekday else self.park_cdf_we[from_type]
        return int(cdf.sample() + 1)
    
    @abstractmethod
    def _genTripsChain1(self, v:Vehicle):  # vehicle_trip
        """Generate a full day of trips on the first day"""
        raise NotImplementedError()
    
    @abstractmethod
    def _genTripsChainA(self, v: Vehicle, daynum: int = 1):  # vehicle_trip
        """Generate a full day of trips on a non-first day"""
        raise NotImplementedError()
    
    def gen_trip_for_veh(self, day_count:int, veh:Vehicle, use_buffer_day: bool = True, clear_existing: bool = False):
        """
        Generate trips for an existing vehicle.

        :param day_count: Number of days
        :param veh: Vehicle instance
        :param use_buffer_day: Whether to use buffer day. When there are existing trips, this option does not work
        :param clear_existing: Whether to clear existing trips
        """
        if clear_existing:
            veh.clear_trips()
        if day_count <= 0: return
        if len(veh.trips) == 0:
            if use_buffer_day:
                self._genTripsChain1(veh)
                st = 1
            else:
                st = 0
        else:
            st = veh.trips[-1].depart_time % 86400 + 1
        for j in range(st, st + day_count):
            self._genTripsChainA(veh, j)
    
    def gen_veh(self, day_count: int, veh_id: str,
            omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None,
            v2g_prop:float = 1.0+1e-4, ksc:PDFuncLike = None, kv2g:PDFuncLike = None) -> Vehicle:
        """
        Generate trips for a vehicle. The generated vehicle is returned as a vehicle instance.
        
        :param day_count: Number of days
        :param veh_id: ID of the vehicle
        :param omega: PDFunc | None = None
        :param krel: PDFunc | None = None
        :param kfc: PDFunc | None = None
        :param v2g_prop: Proportion of users willing to participate in V2G, for EV only
        :param ksc: PDFunc | None = None, for EV only
        :param kv2g: PDFunc | None = None, for EV only
        :return: Vehicle instance
        """
        vt = self.vTypes.sample()
        pct = self.soc_pdf.sample() / 100.0
        if isinstance(vt, EVType):
            v = create_veh(veh_id, vt, pct, omega, krel, kfc, v2g_prop, ksc, kv2g)
        else:
            v = create_veh(veh_id, vt, pct, omega, krel, kfc)
        self.gen_trip_for_veh(day_count, v, use_buffer_day=True, clear_existing=False)
        return v
    
    def gen_ev(self, day_count: int, veh_id: str, 
            omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None,
            v2g_prop:float = 1.0+1e-4, ksc:PDFuncLike = None, kv2g:PDFuncLike = None) -> EV:
        vt = self.vTypes.sample_evtype()
        v = create_veh(veh_id, vt, self.soc_pdf.sample() / 100.0, omega, krel, kfc, v2g_prop, ksc, kv2g)
        self.gen_trip_for_veh(day_count, v, use_buffer_day=True, clear_existing=False)
        return v
    
    def gen_gv(self, day_count: int, veh_id: str,
            omega:PDFuncLike = None, krel:PDFuncLike = None, kfc:PDFuncLike = None) -> GV:
        vt = self.vTypes.sample_gvtype()
        v = create_veh(veh_id, vt, self.soc_pdf.sample() / 100.0, omega, krel, kfc)
        self.gen_trip_for_veh(day_count, v, use_buffer_day=True, clear_existing=False)
        return v
    
    def gen_vehs(self, N: Union[int, Tuple[int, int]], fname: Optional[str] = None, 
            day_count: int = 7, silent: bool = False, omega:PDFuncLike = None, 
            krel:PDFuncLike = None, kfc:PDFuncLike = None, v2g_prop:float = 1.0+1e-4, 
            ksc:PDFuncLike = None, kv2g:PDFuncLike = None, seed = None) -> VDict:
        """
        Generate EV and trips of N vehicles.
        The generated vehicles are returned as an EVDict instance, and will be saved to the file if fname is provided.
        If seed is not None, the random seed will be set for reproducibility. Note that the random seed is only set for the generation of vehicles and trips, and will be reset to the original state after generation.

        :param N: Number of vehicles, or (num_ev, num_gv)
        :param fname: Saved file name (if None, not saved)
        :param day_count: Number of days
        :param silent: Whether silent mode
        :param omega: PDFunc | None = None
        :param krel: PDFunc | None = None
        :param kfc: PDFunc | None = None
        :param v2g_prop: Proportion of users willing to participate in V2G, for EV only
        :param ksc: PDFunc | None = None, for EV only
        :param kv2g: PDFunc | None = None, for EV only
        :param seed: Random seed for reproducibility (if None, not set)
        """
        if seed is not None:
            rnd = random.getstate()
            random.seed(seed)

        evs: dict[str, EV] = {}; gvs: dict[str, GV] = {}
        if isinstance(N, tuple):
            pb = ProgressBar(N[0] + N[1], silent)
            for i in range(N[0]):
                v = self.gen_ev(day_count, f"ev{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
                evs[v._name] = v
                pb.increment()
            for i in range(N[1]):
                v = self.gen_gv(day_count, f"gv{i}", omega, krel, kfc)
                gvs[v._name] = v
                pb.increment()
        else:
            pb = ProgressBar(N, silent)
            for i in range(N):
                v = self.gen_veh(day_count, f"v{i}", omega, krel, kfc, v2g_prop, ksc, kv2g)
                if isinstance(v, EV): evs[v._name] = v
                elif isinstance(v, GV): gvs[v._name] = v
                else: raise RuntimeError(f"Invalid vehicle type: {type(v)}")
                pb.increment()
        ret = VDict(evs, gvs)
        if fname: ret.save(fname)
        if seed is not None: random.setstate(rnd)
        return ret
    
    def gen_vehs_parallel(self, N: Union[int, Tuple[int, int]], fname: Optional[str] = None, 
            day_count: int = 7, silent: bool = False, omega:PDFuncLike = None, 
            krel:PDFuncLike = None, kfc:PDFuncLike = None, v2g_prop:float = 1.0+1e-4, 
            ksc:PDFuncLike = None, kv2g:PDFuncLike = None, seed:int = 0,
            chunk_size: int = 1000, workers: Optional[int] = None) -> VDict:
        """
        Parallel version of gen_vehs.

        Vehicles are generated in chunks instead of one task per vehicle.
        The default chunk size is 1000 vehicles to reduce task scheduling overhead.

        Note:
        - Parallel generation is deterministic for a fixed seed/chunk_size/workers,
          but the result is not identical to the sequential gen_vehs() sequence.
        - omega/krel/kfc/ksc/kv2g must be pickleable when using multiprocessing.
        - On Windows, this uses process-based parallelism, so each worker creates
          its own generator instance once and reuses it for all assigned chunks.

        :param N: Number of vehicles, or (num_ev, num_gv)
        :param fname: Saved file name (if None, not saved)
        :param day_count: Number of days
        :param silent: Whether silent mode
        :param omega: PDFunc | None = None
        :param krel: PDFunc | None = None
        :param kfc: PDFunc | None = None
        :param v2g_prop: Proportion of users willing to participate in V2G, for EV only
        :param ksc: PDFunc | None = None, for EV only
        :param kv2g: PDFunc | None = None, for EV only
        :param seed: Base random seed
        :param chunk_size: Number of vehicles generated by each task
        :param workers: Number of worker processes. Default: os.cpu_count()
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")

        if workers is None or workers <= 0:
            workers = os.cpu_count() or 1
        workers = max(1, int(workers) - 1)  # Leave one CPU free

        def make_tasks(kind: str, total: int) -> List[Tuple[Any, ...]]:
            tasks: List[Tuple[Any, ...]] = []
            if total <= 0:
                return tasks

            chunk_id = 0
            for start in range(0, total, chunk_size):
                count = min(chunk_size, total - start)

                # Per-chunk seed. Keep it deterministic and independent of scheduling order.
                # Different kinds are separated to avoid EV/GV seed collisions.
                if seed is None:
                    task_seed = None
                else:
                    kind_offset = 0 if kind == "any" else (10_000_000 if kind == "ev" else 20_000_000)
                    task_seed = int(seed) + kind_offset + chunk_id

                tasks.append((kind, start, count, day_count, omega, krel, kfc, v2g_prop, ksc, kv2g, task_seed))
                chunk_id += 1
            return tasks

        if isinstance(N, tuple):
            total = N[0] + N[1]
            tasks = make_tasks("ev", N[0]) + make_tasks("gv", N[1])
        else:
            total = N
            tasks = make_tasks("any", N)

        pb = ProgressBar(total, silent)
        evs: Dict[str, EV] = {}
        gvs: Dict[str, GV] = {}

        if total == 0:
            ret = VDict(evs, gvs)
            if fname:
                ret.save(fname)
            pb.update(0)
            return ret

        # Small jobs do not benefit from multiprocessing startup overhead.
        if workers <= 1 or len(tasks) <= 1:
            old_state = random.getstate()
            try:
                for task in tasks:
                    ev_part, gv_part, done = _gen_veh_chunk_worker_local(
                        self, task
                    )
                    evs.update(ev_part)
                    gvs.update(gv_part)
                    pb.update(pb.current + done)
            finally:
                random.setstate(old_state)

            ret = VDict(evs, gvs)
            if fname:
                ret.save(fname)
            return ret

        class_name = self.__class__.__name__
        croot = self._CROOT
        pname = self._PNAME
        mode_value = self._gen_mode.value

        with cf.ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_vehgen_worker,
            initargs=(class_name, croot, pname, mode_value),
        ) as executor:
            futures = [executor.submit(_gen_veh_chunk_worker, task) for task in tasks]

            for fut in cf.as_completed(futures):
                ev_part, gv_part, done = fut.result()
                evs.update(ev_part)
                gvs.update(gv_part)
                pb.update(pb.current + done)

        ret = VDict(evs, gvs)
        if fname:
            ret.save(fname)
        return ret
        
    
    def gen_trip_for_vehs(
        self, day_count:int, vehs: VDict,
        use_buffer_day: bool = True, clear_existing: bool = False,
        silent: bool = False, fname: Optional[str] = None, seed = None
    ):
        """
        Generate trips for existing vehicles. If seed is not None, the random seed will be set for reproducibility. Note that the random seed is only set for the generation of trips, and will be reset to the original state after generation.

        :param day_count: Number of days
        :param vehs: Vehicle dictionary
        :param use_buffer_day: Whether to use buffer day. When there are existing trips, this option does not work
        :param clear_existing: Whether to clear existing trips
        :param silent: Whether silent mode
        :param fname: Saved file name (if None, not saved)
        :param seed: Random seed for reproducibility (if None, not set)
        """
        if seed is not None:
            rnd = random.getstate()
            random.seed(seed)

        total_veh = len(vehs)
        pb = ProgressBar(total_veh, silent)
        for v in chain(vehs.evs.values(), vehs.gvs.values()):
            self.gen_trip_for_veh(day_count, v, use_buffer_day, clear_existing)
            pb.increment()
        if fname: vehs.save(fname)
        if seed is not None: random.setstate(rnd)

@dataclass
class _TypeNodes:
    names:List[str]
    weights:List[float]

    def append(self, name:str, weight:float):
        self.names.append(name)
        self.weights.append(weight)

def _readNodeTypes(fname:str):
    dict_nodetype:Dict[str, _TypeNodes] = {}
    with open(fname, "r") as fp:
        for ln in fp.readlines():
            name, lst = ln.split(":", 1)
            name = name.strip()
            items_str = lst.strip().split(',')
            node_names:List[str] = []
            node_weights:List[float] = []
            for item_str in items_str:
                item_str = item_str.strip()
                if not item_str: continue
                if ':' in item_str:
                    node, weight = item_str.split(':', 1)
                    node = node.strip()
                    weight = float(weight.strip())
                else:
                    node = item_str
                    weight = 1.0
                node_names.append(node)
                node_weights.append(weight)
            dict_nodetype[name] = _TypeNodes(node_names, node_weights)
    return dict_nodetype


class UXVehGenerator(VehGenerator):
    """Class to generate trips for UXsim"""
    def __init__(self, CROOT: str, PNAME: str, mode: TripsGenMode = TripsGenMode.AUTO):
        """
        Initialization

        :param CROOT: Trip parameter folder
        :param PNAME: SUMO configuration folder
        :param mode: Generation mode
        """
        super().__init__(CROOT, PNAME)
        _fn = self.files
        # Define various functional area types
        self.net = RoadNet.load(_fn["net"])
        if mode == TripsGenMode.AUTO:
            if _fn.sumo is None and _fn.node_type: mode = TripsGenMode.NODE
            elif _fn.sumo and _fn.taz and _fn.taz_type: mode = TripsGenMode.TAZ
            elif _fn.poly and _fn.net and _fn.fcs: mode = TripsGenMode.POLY
            else: raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
        if mode == TripsGenMode.NODE:
            assert _fn.sumo is None and _fn.node_type, Lang.ERROR_NO_TAZ_OR_POLY
            self.dic_nodetype:Dict[str, _TypeNodes] = _readNodeTypes(_fn.node_type)
        elif mode == TripsGenMode.POLY:
            assert _fn.poly and _fn.net and _fn.fcs, Lang.ERROR_NO_TAZ_OR_POLY
            polys = PolygonMan(_fn.poly)
            self.dic_nodetype:Dict[str, _TypeNodes] = {dtype: _TypeNodes([], []) for dtype in TAZ_TYPE_LIST}
            for poly in polys:
                poly_type = poly.getConvertedType()
                if poly_type:
                    dist, node = self.net.find_nearest_node_with_distance(*poly.center())
                    # Ensure the edge is in the largest strongly connected component
                    if dist < 200 and self.net.is_node_in_largest_scc(node.name):
                        self.dic_nodetype[poly_type].append(node.name, 1.0)
        else:
            raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
        self._gen_mode = mode
    
    def _getNextNode(self, from_node:str, next_place_type:str) -> str:
        nt = self.dic_nodetype[next_place_type]
        return random_diff2(nt.names, nt.weights, from_node)        
    
    def _genFirstTrip1(self, v:Vehicle, trip_id, weekday: bool = True):
        """
        Generate the first trip of the first day

        :param trip_id: Trip ID
        :param weekday: Whether it is weekday or weekend
        :returns: a InnerTrip instance
        """
        from_Type = "Home"
        if v._base is not None:
            from_node = v._base
            assert from_node in self.dic_nodetype[from_Type].names, f"Vehicle base node {from_node} not in Home node list"
        else:
            nt = self.dic_nodetype[from_Type]
            from_node = random.choices(nt.names, weights=nt.weights, k=1)[0]
            v._base = from_node
        # Get departure time and destination area type
        depart_time_min, to_Type = self._getDest1(from_Type, weekday)  # Minimum departure time is 0
        while depart_time_min * 60 >= 86400 - 3600:  # Ensure that there is enough time for subsequent trips
            depart_time_min, to_Type = self._getDest1(from_Type, weekday)
        to_node = self._getNextNode(from_node, to_Type)
        return Trip(trip_id, depart_time_min * 60, from_node, to_node, None, from_Type, to_Type)

    def _genTripA(
        self, trip_id:str, from_type:str, from_node:str, start_time:int, weekday: bool = True
    ) -> Trip:
        """
        Generate the second trip

        :param trip_id: Trip ID
        :param from_type: Departure area type, such as "Home"
        :param from_node: Departure roadside, such as "T6"
        :param start_time: Departure time of the first trip, in seconds since midnight
        :param weekday: Whether it is weekday or weekend
        """
        depart_time_min = 1440
        cnt = 0
        while depart_time_min >= 1440:  # If the departure time is after midnight, regenerate
            stop_time_idx = self._genStopTimeIdx(from_type, weekday)
            depart_time_min = start_time // 60 + stop_time_idx * 15 + 20
            cnt += 1
            if cnt > 10:
                depart_time_min = min(start_time // 60 + 1, 1439)
                break
        next_place_type = self._getDestA(from_type, stop_time_idx, weekday)
        to_node = self._getNextNode(from_node, next_place_type)
        return Trip(trip_id, depart_time_min * 60, from_node, to_node, None, from_type, next_place_type)

    def _genTripF(
        self, trip_id:str, from_type:str, from_node:str,
        start_time:int, first_node:str, weekday: bool = True,
    ):
        if first_node == from_node:
            return None
        depart_time_min = 1440
        cnt = 0
        while depart_time_min >= 1440:  # If the departure time is after midnight, regenerate
            stop_time_idx = self._genStopTimeIdx(from_type, weekday)
            depart_time_min = start_time // 60 + stop_time_idx * 15 + 20
            cnt += 1
            if cnt > 10:
                return None
        return Trip(trip_id, depart_time_min * 60, from_node, first_node, None, from_type, "Home")

    def _genTripsChain1(self, v:Vehicle):  # vehicle_trip
        """
        Generate a full day of trips on the first day
            ev: vehicle instance
        """
        daynum = 0
        weekday = True
        trip_1 = self._genFirstTrip1(v, "trip0_1", weekday)
        trip_2 = self._genTripA("trip0_2", trip_1.DType, trip_1.D, trip_1.depart_time, weekday)
        trip_3 = self._genTripF("trip0_3", trip_2.DType, trip_2.D, trip_2.depart_time, trip_1.O, weekday)
        
        v.add_trip(trip_1, daynum)
        v.add_trip(trip_2, daynum)
        if trip_3: # Trip3: if O==D, don't generate trip 3
            if trip_3.depart_time < 86400:  # If the departure time is after midnight, it is not valid
                v.add_trip(trip_3, daynum)
            else:
                trip_2.D = trip_1.O
                trip_2.DType = trip_1.OType

    def _genFirstTripA(self, trip_id:str, v:Vehicle, weekday: bool = True):
        """
        Generate the first trip of a non-first day
        
        :param trip_id: Trip ID
        :param v: Vehicle instance
        :param weekday: Whether it is weekday or weekend
        """
        if len(v.trips) > 0:
            trip_last = v.trips[-1]
            from_node = trip_last.D
        else:
            assert v._base is not None, "Vehicle base node is not defined and no previous trips exist."
            from_node = v._base
        # Get departure time and destination area type
        from_Type = "Home"
        depart_time_min, to_Type = self._getDest1(from_Type, weekday)
        while depart_time_min * 60 >= 86400 - 3600:  # Ensure that there is enough time for subsequent trips
            depart_time_min, to_Type = self._getDest1(from_Type, weekday)
        to_node = self._getNextNode(from_node, from_Type)
        return Trip(trip_id, depart_time_min * 60, from_node, to_node, None, from_Type, to_Type)

    def _genTripsChainA(self, v: Vehicle, daynum: int = 1):  # vehicle_trip
        """Generate a full day of trips on a non-first day"""
        weekday = (daynum - 1) % 7 + 1 in [1, 2, 3, 4, 5]
        trip2_1 = self._genFirstTripA(f"trip{daynum}_1", v, weekday)
        trip2_2 = self._genTripA(f"trip{daynum}_2", trip2_1.DType, trip2_1.D, trip2_1.depart_time, weekday)
        trip2_3 = self._genTripF(f"trip{daynum}_3", trip2_2.DType, trip2_2.D, trip2_2.depart_time, trip2_1.O, weekday)
                    
        v.add_trip(trip2_1, daynum)
        v.add_trip(trip2_2, daynum)
        if trip2_3:
            if trip2_3.depart_time < 86400:  # If the departure time is after midnight, it is not valid
                v.add_trip(trip2_3, daynum)
            else:
                trip2_2.D = trip2_1.O
                trip2_2.DType = trip2_1.OType

class SUMOVehGenerator(VehGenerator):
    def __init__(self, CROOT: str, PNAME: str, mode: TripsGenMode = TripsGenMode.AUTO):
        """
        Initialization

        :param CROOT: Trip parameter folder
        :param PNAME: SUMO configuration folder
        :param mode: Generation mode
        """
        super().__init__(CROOT, PNAME)
        _fn = self.files
        # Define various functional area types
        import sumolib
        self.dic_taz = {} # taz_id -> [edge_id, edge_id, ...]
        self.taz_of_edge = {} # edge_id -> taz_id
        self.taz_pos = {} # taz_id -> SUMO edge position; POLY uses fixed POI position, TAZ uses random positions
        self.net:sumolib.net.Net = sumolib.net.readNet(_fn["net"])
        if mode == TripsGenMode.AUTO:
            if _fn.sumo and _fn.taz and _fn.taz_type: mode = TripsGenMode.TAZ
            elif _fn.poly and _fn.net and _fn.fcs: mode = TripsGenMode.POLY
            else: raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
        if mode == TripsGenMode.TAZ:
            assert _fn.taz and _fn.taz_type, Lang.ERROR_NO_TAZ_OR_POLY
            self._mode = "taz"
            self.dic_taztype = {}
            with open(_fn.taz_type, "r") as fp:
                for ln in fp.readlines():
                    name, lst = ln.split(":")
                    self.dic_taztype[name.strip()] = [x.strip() for x in lst.split(",")]
            root = ReadXML(_fn.taz).getroot()
            if root is None: raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
            for taz in root.findall("taz"):
                taz_id = taz.attrib["id"]
                if "edges" in taz.attrib:
                    self.dic_taz[taz_id] = taz.attrib["edges"].split(" ")
                else:
                    self.dic_taz[taz_id] = [edge.attrib["id"] for edge in taz.findall("tazSource")]
                self.taz_pos[taz_id] = None
                for edge_id in self.dic_taz[taz_id]:
                    self.taz_of_edge[edge_id] = taz_id
        elif mode == TripsGenMode.POLY:
            assert _fn.poly and _fn.net and _fn.fcs, Lang.ERROR_NO_TAZ_OR_POLY
            self._mode = "poly"
            net = RoadNet.load(_fn.net)
            polys = PolygonMan(_fn.poly)
            self.dic_taztype = {k:[] for k in TAZ_TYPE_LIST}
            for poly in polys:
                taz_id = poly.ID
                taz_type = poly.getConvertedType()
                poi_pos = poly.center()
                if taz_type:
                    dist, eid, edge_pos = net.find_nearest_edge_id_with_pos(*poi_pos)
                    # Ensure the edge is in the largest strongly connected component
                    if dist < 200 and net.is_edge_in_largest_scc(eid): 
                        self.dic_taztype[taz_type].append(taz_id)
                        self.dic_taz[taz_id] = [eid]
                        self.taz_pos[taz_id] = edge_pos
                        self.taz_of_edge[eid] = taz_id
        else:
            raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
        self._gen_mode = mode
    
    def _findTAZbyEdge(self, edge_id:str) -> Optional[str]:
        return self.taz_of_edge.get(edge_id, None)
    
    def _getEdgeLength(self, edge_id: str) -> float:
        return float(self.net.getEdge(edge_id).getLength())

    def _getRandomEdgePos(self, edge_id: str) -> float:
        return random.uniform(0.0, self._getEdgeLength(edge_id))

    def _getTAZPos(self, taz_id: str, edge_id: Optional[str] = None) -> Optional[float]:
        pos = self.taz_pos.get(taz_id, None)
        if pos is not None:
            return float(pos)
        if self._mode == "taz" and edge_id is not None:
            return self._getRandomEdgePos(edge_id)
        return None

    def _makeTrip(
        self, trip_id: str, depart_time: int, from_edge: str, to_edge: str,
        edges: Optional[List[str]], from_type: str, to_type: str, from_taz: str, to_taz: str,
        from_pos: Optional[float] = None, to_pos: Optional[float] = None
    ) -> Trip:
        if from_pos is None:
            from_pos = self._getTAZPos(from_taz, from_edge)
        if to_pos is None:
            to_pos = self._getTAZPos(to_taz, to_edge)
        return Trip(
            trip_id, depart_time, from_edge, to_edge, edges, from_type, to_type, from_taz, to_taz,
            OPos=from_pos, DPos=to_pos
        )

    def _getNextTAZandPlace(self, from_TAZ:str, from_EDGE:str, next_place_type:str) -> Tuple[str, str, Optional[float]]:
        trial = 0
        while True:
            if self._mode == "taz":
                to_TAZ = random.choice(self.dic_taztype[next_place_type])
                assert to_TAZ in self.dic_taz, f"TAZ {to_TAZ} not found in TAZ dictionary"
                to_EDGE = random_diff(self.dic_taz[to_TAZ], from_EDGE)
            else: # self._mode == "diff"
                to_TAZ = random_diff(self.dic_taztype[next_place_type], from_TAZ)
                assert to_TAZ in self.dic_taz, f"TAZ {to_TAZ} not found in TAZ dictionary"
                to_EDGE = random.choice(self.dic_taz[to_TAZ])
            if from_EDGE != to_EDGE:
                return to_TAZ, to_EDGE, self._getTAZPos(to_TAZ, to_EDGE)
            trial += 1
            if trial >= 5:
                raise RuntimeError("from_EDGE == to_EDGE")
        
    def _genFirstTrip1(self, v: Vehicle, trip_id, weekday: bool = True):
        """
        Generate the first trip of the first day

        :param v: Vehicle instance
        :param trip_id: Trip ID
        :param weekday: Whether it is weekday or weekend
        :returns: a InnerTrip instance
        """
        from_Type = "Home"
        if v._base is not None:
            from_EDGE = v._base
            from_TAZ = self._findTAZbyEdge(from_EDGE)
            if from_TAZ is None: raise RuntimeError(f"Vehicle base edge {from_EDGE} not in any TAZ edge list")
            from_pos = self._getTAZPos(from_TAZ, from_EDGE)
        else:
            from_TAZ = random.choice(self.dic_taztype[from_Type])
            from_EDGE = random.choice(self.dic_taz[from_TAZ])
            from_pos = self._getTAZPos(from_TAZ, from_EDGE)
            v._base = from_EDGE
        # Get departure time and destination area type
        depart_time_min, to_Type = self._getDest1(from_Type, weekday)  
        while depart_time_min * 60 >= 86400 - 3600:  # Ensure that there is enough time for subsequent trips
            depart_time_min, to_Type = self._getDest1(from_Type, weekday)  
        to_TAZ, to_EDGE, to_pos = self._getNextTAZandPlace(from_TAZ, from_EDGE, to_Type)
        return self._makeTrip(trip_id, depart_time_min * 60, from_EDGE, to_EDGE, None, from_Type, to_Type, from_TAZ, to_TAZ, from_pos, to_pos)

    def _genTripA(
        self, trip_id:str, from_TAZ:str, from_type:str, from_edge:str, start_time:int, weekday: bool = True,
        from_pos: Optional[float] = None
    ):
        """
        Generate the second trip

        :param trip_id: Trip ID
        :param from_TAZ: Departure area TAZ type, such as "TAZ1"
        :param from_type: Departure area type, such as "Home"
        :param from_EDGE: Departure roadside, such as "gnE29"
        :param start_time: Departure time of the first trip, in seconds since midnight
        :param weekday: Whether it is weekday or weekend
        """
        depart_time_min = 1440
        cnt = 0
        while depart_time_min >= 1440:  # If the departure time is after midnight, regenerate
            stop_time_idx = self._genStopTimeIdx(from_type, weekday)
            depart_time_min = start_time // 60 + stop_time_idx * 15 + 20
            cnt += 1
            if cnt > 10:
                depart_time_min = start_time // 60 + 1
                break
        to_type = self._getDestA(from_type, stop_time_idx, weekday)
        to_TAZ, to_edge, to_pos = self._getNextTAZandPlace(from_TAZ, from_edge, to_type)
        return self._makeTrip(trip_id, depart_time_min * 60, from_edge, to_edge, None, from_type, to_type, from_TAZ, to_TAZ, from_pos, to_pos)

    def _genTripF(
        self, trip_id:str, from_TAZ:str, from_type, from_EDGE:str,
        start_time:int, first_TAZ:str, first_EDGE:str, weekday: bool = True,
        from_pos: Optional[float] = None, first_pos: Optional[float] = None,
    ):
        """
        Generate the third trip

        :param trip_id: Trip ID
        :param from_TAZ: Departure area TAZ type, such as "TAZ1"
        :param from_type: Departure area type, such as "Home"
        :param from_EDGE: Departure roadside, such as "gnE29"
        :param start_time: Departure time of the first trip, in seconds since midnight
        :param first_TAZ: First trip's destination area TAZ type, such as "TAZ2"
        :param first_EDGE: First trip's destination roadside, such as "gnE2"
        :param weekday: Whether it is weekday or weekend
        """
        if first_EDGE == from_EDGE:
            return None
        depart_time_min = 1440
        cnt = 0
        while depart_time_min >= 1440:  # If the departure time is after midnight, regenerate
            stop_time_idx = self._genStopTimeIdx(from_type, weekday)
            depart_time_min = start_time // 60 + stop_time_idx * 15 + 20
            cnt += 1
            if cnt > 10:
                return None
        return self._makeTrip(trip_id, depart_time_min * 60, from_EDGE, first_EDGE, None, from_type, "Home", from_TAZ, first_TAZ, from_pos, first_pos)

    def _genTripsChain1(self, v: Vehicle):  # vehicle_trip
        """
        Generate a full day of trips on the first day

        :param v: vehicle instance
        """
        daynum = 0
        weekday = True
        trip_1 = self._genFirstTrip1(v, "trip0_1", weekday)
        trip_2 = self._genTripA("trip0_2",trip_1.DTaz,
            trip_1.DType,trip_1.D,trip_1.depart_time,weekday,trip_1.DPos)
        trip_3 = self._genTripF("trip0_3",trip_2.DTaz,
            trip_2.DType,trip_2.D,trip_2.depart_time,
            trip_1.OTaz,trip_1.O,weekday,trip_2.DPos,trip_1.OPos)
        
        v.add_trip(trip_1, daynum)
        v.add_trip(trip_2, daynum)
        if trip_3: # Trip3: if O==D, don't generate trip 3
            if trip_3.depart_time < 86400:  # If the departure time is after midnight, it is not valid
                v.add_trip(trip_3, daynum)
            else:
                trip_2.DTaz = trip_1.OTaz
                trip_2.D = trip_1.O
                trip_2.DType = trip_1.OType
                trip_2.DPos = trip_1.OPos

    def _genFirstTripA(self, trip_id, v: Vehicle, weekday: bool = True):
        """
        Generate the first trip of a non-first day

        :param trip_id: Trip ID
        :param v: Vehicle instance
        :param weekday: Whether it is weekday or weekend
        """
        if len(v.trips) > 0:
            trip_last = v.trips[-1]
            from_EDGE = trip_last.D
            from_TAZ = trip_last.DTaz
            from_pos = trip_last.DPos
        else:
            assert v._base is not None, "Vehicle base node is not defined and no previous trips exist."
            from_EDGE = v._base
            from_TAZ = self._findTAZbyEdge(from_EDGE)
            if from_TAZ is None: raise RuntimeError(f"Vehicle base edge {from_EDGE} not in any TAZ edge list")
            from_pos = self._getTAZPos(from_TAZ, from_EDGE)
        
        # Get departure time and destination area type
        from_Type = "Home"
        depart_time_min, to_Type = self._getDest1(from_Type, weekday)
        while depart_time_min * 60 >= 86400 - 3600:  # Ensure that there is enough time for subsequent trips
            depart_time_min, to_Type = self._getDest1(from_Type, weekday)
        to_TAZ, to_EDGE, to_pos = self._getNextTAZandPlace(from_TAZ, from_EDGE, to_Type)
        return self._makeTrip(trip_id, depart_time_min * 60, from_EDGE, to_EDGE, [], from_Type, to_Type, from_TAZ, to_TAZ, from_pos, to_pos)

    def _genTripsChainA(self, v: Vehicle, daynum: int = 1):  # vehicle_trip
        """Generate a full day of trips on a non-first day"""
        weekday = (daynum - 1) % 7 + 1 in [1, 2, 3, 4, 5]
        trip2_1 = self._genFirstTripA(f"trip{daynum}_1", v, weekday)
        trip2_2 = self._genTripA(f"trip{daynum}_2",trip2_1.DTaz,
            trip2_1.DType,trip2_1.D,trip2_1.depart_time,weekday,trip2_1.DPos)
        trip2_3 = self._genTripF(f"trip{daynum}_3",
            trip2_2.DTaz,trip2_2.DType,trip2_2.D,
            trip2_2.depart_time,trip2_1.OTaz,trip2_1.O,weekday,trip2_2.DPos,trip2_1.OPos)
                    
        v.add_trip(trip2_1, daynum)
        v.add_trip(trip2_2, daynum)
        if trip2_3:
            if trip2_3.depart_time < 86400:  # If the departure time is after midnight, it is not valid
                v.add_trip(trip2_3, daynum)
            else:
                trip2_2.DTaz = trip2_1.OTaz
                trip2_2.D = trip2_1.O
                trip2_2.DType = trip2_1.OType
                trip2_2.DPos = trip2_1.OPos

__all__ = ["VehGenerator", "UXVehGenerator", "SUMOVehGenerator", "TripsGenMode", "RoutingCacheMode"]