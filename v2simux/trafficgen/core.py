from collections import defaultdict
from enum import IntEnum
from itertools import repeat
from pathlib import Path
from feasytools import ArgChecker
from fpowerkit import Grid
from scipy.spatial import KDTree
from typing import IO, Any, Literal, Tuple, TypeVar, Union, Dict, List
import time
import random

from ..locale import Lang
from ..traffic import DetectFiles, V2SimConfig, RoadNet
from .poly import PolygonMan
from .tripgen import EVsGenerator, RoutingCacheMode, TripsGenMode
from .misc import *

DEFAULT_CNAME = str(Path(__file__).parent.parent / "probtable")

class ProcExisting(IntEnum):
    """How to handle existing files"""

    OVERWRITE = 0  # Overwrite
    SKIP = 1  # Skip
    BACKUP = 2  # Backup
    EXCEPTION = 3  # Raise an exception

    def do(self, path: str):
        if self == ProcExisting.OVERWRITE:
            Path(path).unlink()
        elif self == ProcExisting.SKIP:
            pass
        elif self == ProcExisting.BACKUP:
            i = 0
            while Path(f"{path}.{i}.bak").exists():
                i += 1
            Path(path).rename(f"{path}.{i}.bak")
        else:
            raise FileExistsError(Lang.ERROR_FILE_EXISTS.format(path))

    def check(self, path: str):
        if Path(path).exists():
            self.do(path)


T = TypeVar("T")

class ListSelection(IntEnum):
    """List selection method"""

    ALL = 0  # All
    RANDOM = 1  # Random
    GIVEN = 2  # Given

    def select(self, lst: List[T], n: int = -1, given: List[T] = []) -> List[T]:
        if self == ListSelection.ALL:
            return lst
        elif self == ListSelection.RANDOM:
            if n == -1:
                raise ValueError(Lang.ERROR_NUMBER_NOT_SPECIFIED)
            return random.sample(lst, n)
        else:
            return given


class PricingMethod(IntEnum):
    FIXED = 0  # Fixed price
    RANDOM = 1  # 5-tier random price


class TrafficGenerator:
    def __init__(
        self,
        root: str,
        silent: bool = False,
        existing: ProcExisting = ProcExisting.BACKUP,
    ):
        """
        Generator initialization
            root: Root directory
            silent: Whether to be silent
            existing: How to handle existing files
        """
        self.__root = root
        self.__cfg = DetectFiles(root)
        self.__name = self.__cfg["name"]
        self.__silent = silent
        self.__existing = existing
        self.__start_time = 0
        self.__end_time = 172800
        if self.__cfg.pref:
            pref = V2SimConfig.load(self.__cfg.pref)
            self.__start_time = pref.start_time
            self.__end_time = pref.end_time
        if not self.__cfg.net:
            raise FileNotFoundError(Lang.ERROR_NET_FILE_NOT_SPECIFIED)
        self.__rnet = RoadNet.load(self.__cfg.net)
        self.__ava_fcs: List[str] = [
            e for e in self.__rnet.node_ids if e.upper().startswith("CS")
        ]
        self.__ava_scs: List[str] = [
            e for e in self.__rnet.node_ids if not e.upper().startswith("CS")
        ]
        
        self.__bus_names = ["None"]
        if self.__cfg.grid: 
            self.__bus_names = Grid.fromFile(self.__cfg.grid).BusNames
        else:
            print("Grid is not defined, and thus buses are not included. CS generation may meet errors.")
        
        self.__cs_file = self.__cfg["cscsv"] if "cscsv" in self.__cfg else ""
        self.__grid_file = self.__cfg["grid"] if "grid" in self.__cfg else ""

    def EVTripsFromArgs(self, args: Union[str, ArgChecker]):
        """
        Generate trips from command line arguments
            args: ArgChecker or command line
        """
        if isinstance(args, str):
            args = ArgChecker(args)
        N_cnt = args.pop_int("n")
        day_cnt = args.pop_int("day", 7)
        cname = args.pop_str("c", DEFAULT_CNAME)
        seed = args.pop_int("seed", time.time_ns())
        v2g_prop = args.pop_float("v", 1.0)
        mode_str = args.pop_str("mode", "auto").lower()
        if mode_str == "auto":
            mode = TripsGenMode.AUTO
        elif mode_str == "type":
            mode = TripsGenMode.TYPE
        elif mode_str == "poly":
            mode = TripsGenMode.POLY
        else:
            raise ValueError(Lang.ERROR_INVALID_TRIP_GEN_MODE.format(mode_str))
        cache_route = args.pop_str("cache-route", "none").lower()
        if cache_route == "none":
            rcm = RoutingCacheMode.NONE
        elif cache_route == "runtime":
            rcm = RoutingCacheMode.RUNTIME
        elif cache_route == "static":
            rcm = RoutingCacheMode.STATIC
        else:
            raise ValueError(Lang.ERROR_INVALID_CACHE_ROUTE.format(cache_route))
        if not args.empty():
            raise KeyError(Lang.ERROR_ILLEGAL_CMD.format(','.join(args.to_dict().keys())))
        return self.EVTrips(N_cnt, seed, day_cnt, cname, mode, rcm, v2g_prop=v2g_prop)
    
    def EVTrips(self, n: int, seed: int,
            day_count: int = 7,
            cname: str = DEFAULT_CNAME,
            mode: TripsGenMode = TripsGenMode.AUTO, 
            route_cache: RoutingCacheMode = RoutingCacheMode.NONE,
        **kwargs):
        """
        Generate trips
            n: Number of vehicles
            seed: Randomization seed
            day_count: Number of days
            cname: Trip parameter folder
            mode: Generation mode, "Auto" for automatic, "TAZ" for TAZ-based, "Poly" for polygon-based
            routing_cache: Routing cache mode
            v2g_prop: Proportion of users willing to participate in V2G
            omega: PDFunc | None = None,
            krel: PDFunc | None = None,
            ksc: PDFunc | None = None,
            kfc: PDFunc | None = None,
            kv2g: PDFunc | None = None
        """
        if "veh" in self.__cfg:
            self.__existing.do(self.__cfg["veh"])
        fname = f"{self.__root}/{self.__name}.veh.xml.gz"
        return EVsGenerator(cname, self.__root, seed, mode, route_cache).genEVs(n, fname, day_count, self.__silent, **kwargs)

    def _CS(
        self,
        seed: int,
        *,
        cs_file: str = "",
        poly_file: str = "",
        slots: int = 10,
        mode: Literal["fcs", "scs"] = "fcs",
        bus: ListSelection = ListSelection.ALL,
        busCount: int = -1,
        grid_file: str = "",
        givenBus: List[str] = [],
        cs: ListSelection = ListSelection.ALL,
        csCount: int = -1,
        givenCS: List[str] = [],
        priceBuyMethod: PricingMethod = PricingMethod.FIXED,
        priceBuy: float = 1.0,
        hasSell: bool = False,
        priceSellMethod: PricingMethod = PricingMethod.FIXED,
        priceSell: float = 1.5,
    ):
        def write(fp: IO, price: float):
            loop_end = self.__end_time // 86400
            for d in range(0, loop_end):
                t = [0, 0, 0, 0, 0]
                p = [0.0, 0.0, 0.0, 0.0, 0]
                t[0] = random.choice([0, 1]) if d > 0 else 1
                p[0] = random.uniform(price - 0.5, price - 0.4)
                t[1] = random.choice([6, 7, 8])
                p[1] = random.uniform(price + 0.3, price + 0.6)
                t[2] = random.choice([10, 11])
                p[2] = random.uniform(price - 0.1, price + 0.1)
                t[3] = random.choice([15, 16, 17])
                p[3] = random.uniform(price + 0.2, price + 0.5)
                t[4] = random.choice([19, 20])
                p[4] = random.uniform(price, price + 0.2)
                for tx, px in zip(t, p):
                    fp.write(
                        f'    <item btime="{d*86400+tx*3600}" price="{px:.3}" />\n'
                    )
        warns = []; far_cnt = 0; scc_cnt = 0
        random.seed(seed)
        if mode in self.__cfg:
            self.__existing.do(self.__cfg[mode])
        fname = f"{self.__root}/{self.__name}.{mode}.xml"
        fp = open(fname, "w")
        fp.write("<root>\n")
        cs_pos:Dict[str, Tuple[float, float]] = {}
        if cs_file != "":
            with open(cs_file, "r") as f:
                con = f.readlines()
                _, _, i0, i1 = con[0].strip().split(",")
                if i0 == "lat" and i1 == "lng":
                    swap = False
                elif i0 == "lng" and i1 == "lat":
                    swap = True
                else:
                    raise ValueError("Invalid CSV file.")
                for i in range(1, len(con) - 1):
                    _, _, lat, lng = con[i].strip().split(",")
                    if swap: lat, lng = lng, lat
                    x, y = self.__rnet.convertLonLat2XY(float(lng), float(lat))
                    dist, node = self.__rnet.find_nearest_node_with_distance(x, y)
                    if dist > 200:
                        warns.append(("far_down", lat, lng, x, y, dist))
                        far_cnt += 1
                        continue
                    if not self.__rnet.is_node_in_largest_scc(node.id):
                        warns.append(("scc_down", lat, lng, x, y))
                        scc_cnt += 1
                        continue
                    cs_pos[node.id] = (x, y)
            cs_names = cs.select(sorted(cs_pos.keys()), csCount, givenCS)
            cs_slots = repeat(slots, len(con) - 1)
        elif poly_file != "":
            cs_type:Dict[str,Any] = defaultdict(int)
            PolyMan = PolygonMan(poly_file)
            for poly in PolyMan:
                t = poly.getConvertedType()
                if t is None or t == "Other": continue
                p = poly.center()
                dist, node = self.__rnet.find_nearest_node_with_distance(*p)
                if dist > 200:
                    warns.append(("far_poly", p[0], p[1], dist))
                    far_cnt += 1
                    continue
                if not self.__rnet.is_node_in_largest_scc(node.id):
                    warns.append(("scc_poly", p[0], p[1]))
                    scc_cnt += 1
                    continue
                cs_pos[node.id] = p
                cs_type[node.id] = t
            cs_names = cs.select(sorted(cs_type.keys()), csCount, givenCS)
            def trans(x: str):
                if x == "Home" or x == "Work":
                    return 10 #50
                elif x == "Relax":
                    return 10 #30
                else:
                    raise RuntimeError(f"Invalid type: {x}")
            cs_slots = [trans(cs_type[x]) for x in cs_names]
        else:
            used_cs = self.__ava_fcs if mode == "fcs" else self.__ava_scs
            cs_candidates = []
            for name in used_cs:
                if self.__rnet.is_node_in_largest_scc(name):
                    cs_candidates.append(name)
                else:
                    warns.append(("scc_name", name))
            cs_names = cs.select(cs_candidates, csCount, givenCS)
            cs_slots = repeat(slots, len(cs_names))
            cs_pos = {name: self.__rnet.get_node(name).get_coord() for name in cs_names}
        use_grid = False
        bus_pos:List[Tuple[float, float]] = []
        if grid_file != "":
            gr = Grid.fromFile(grid_file)
            use_grid = True
            for b in gr.Buses:
                lon, lat = b.LonLat
                try:
                    assert lon is not None or lat is not None
                    x, y = self.__rnet.convertLonLat2XY(lon, lat)
                except:
                    use_grid = False
                    break
                bus_pos.append((x, y))
            bus_names = gr.BusNames
        if use_grid:
            bkdt = KDTree(bus_pos)
            selector = lambda cname: bus_names[bkdt.query([self.__rnet.get_node(cname).get_coord()], k=1)[1].item()]
        else:
            bus_names = bus.select(self.__bus_names, busCount, givenBus)
            selector = lambda cname: random.choice(bus_names)
        for sl, cname in zip(cs_slots, cs_names):            
            fp.write(f'<{mode} name="{mode}_{cname}" node="{cname}" slots="{sl}" bus="{selector(cname)}"')
            if mode == "scs":
                fp.write(f' v2galloc="Average"')
            if cname in cs_pos:
                x, y = cs_pos[cname]
                fp.write(f' x="{x:.1f}" y="{y:.1f}"')
            fp.write(">\n")
            fp.write(f"  <pbuy>\n")
            if priceBuyMethod == PricingMethod.FIXED:
                fp.write(f'    <item btime="0" price="{priceBuy}" />\n')
            else:
                fp.write(f'    <item btime="0" price="1.00" />\n')
                write(fp, priceBuy)
            fp.write(f"  </pbuy>\n")
            if hasSell:
                fp.write(f"  <psell>\n")
                if priceSellMethod == PricingMethod.FIXED:
                    fp.write(f'    <item btime="0" price="{priceSell}" />\n')
                else:
                    fp.write(f'    <item btime="0" price="1.00" />\n')
                    write(fp, priceSell)
                fp.write(f"  </psell>\n")
            fp.write(f"</{mode}>\n")
        fp.write("</root>")
        fp.close()
        return warns, far_cnt, scc_cnt
    
    def FCS(
        self,
        seed: int,
        slots: int,
        *,
        file: str = "",
        bus: ListSelection = ListSelection.ALL,
        busCount: int = -1,
        grid_file: str = "",
        givenBus: List[str] = [],
        cs: ListSelection = ListSelection.ALL,
        csCount: int = -1,
        givenCS: List[str] = [],
        priceBuyMethod: PricingMethod = PricingMethod.FIXED,
        priceBuy: float = 1.5,
    ):
        """
        Generate fast charging station file
            seed: Randomization seed
            slots: Number of charging piles per fast charging station
            bus: Bus selection method
            busCount: Number of buses selected, valid when the bus selection method is random
            givenBus: Specified bus, valid when the bus selection method is specified
            cs: Charging station selection method
            csCount: Number of charging stations selected, valid when the charging station selection method is random
            givenCS: Specified charging station, valid when the charging station selection method is specified
            priceBuyMethod: Pricing method
            priceBuy: Specified price (list)
        """
        return self._CS(
            seed,
            slots = slots,
            mode = "fcs",
            cs_file = file,
            bus=bus,
            busCount=busCount,
            grid_file=grid_file,
            givenBus=givenBus,
            cs=cs,
            csCount=csCount,
            givenCS=givenCS,
            priceBuyMethod=priceBuyMethod,
            priceBuy=priceBuy,
        )
    
    def SCS(
        self,
        seed: int,
        slots: int,
        *,
        file: str = "",
        bus: ListSelection = ListSelection.ALL,
        busCount: int = -1,
        grid_file: str = "",
        givenBus: List[str] = [],
        cs: ListSelection = ListSelection.ALL,
        csCount: int = -1,
        givenCS: List[str] = [],
        priceBuyMethod: PricingMethod = PricingMethod.FIXED,
        priceBuy: float = 1.5,
        priceSellMethod: PricingMethod = PricingMethod.FIXED,
        priceSell: float = 1.5,
    ):
        """
        Generate slow charging station file
            seed: Randomization seed
            slots: Number of charging piles per fast charging station
            bus: Bus selection method
            busCount: Number of buses selected, valid when the bus selection method is random
            givenBus: Specified bus, valid when the bus selection method is specified
            cs: Charging station selection method
            csCount: Number of charging stations selected, valid when the charging station selection method is random
            givenCS: Specified charging station, valid when the charging station selection method is specified
            priceBuyMethod: User purchase price pricing method
            priceBuy: Specified price (list)
            hasSell: Whether to sell electricity
            priceSellMethod: User selling price pricing method
            priceSell: Specified price (list)
        """
        return self._CS(
            seed,
            slots = slots,
            mode = "scs",
            cs_file = file,
            bus=bus,
            busCount=busCount,
            grid_file=grid_file,
            givenBus=givenBus,
            cs=cs,
            csCount=csCount,
            givenCS=givenCS,
            priceBuyMethod=priceBuyMethod,
            priceBuy=priceBuy,
            hasSell=True,
            priceSellMethod=priceSellMethod,
            priceSell=priceSell,
        )
        
    def __CSFromArgs(self, cs_type:str, params: ArgChecker):
        slots = params.pop_int("slots", 10)
        seed = params.pop_int("seed", time.time_ns())
        pbuy = params.pop_float("pbuy", 1.5)
        if self.__cs_file != "":
            cs_file = self.__cs_file
            print("CS file detected: ", cs_file)
        else:
            cs_file = params.pop_str("cs-file", "")
        if self.__grid_file != "":
            grid_file = self.__grid_file
            print("Grid file detected: ", grid_file)
        else:
            grid_file = params.pop_str("grid-file", "")
        randomize_pbuy = params.pop_bool("randomize-pbuy")
        pbuy_method = PricingMethod.RANDOM if randomize_pbuy else PricingMethod.FIXED
        psell = params.pop_float("psell", 1.0)
        randomize_psell = params.pop_bool("randomize-psell")
        psell_method = PricingMethod.RANDOM if randomize_psell else PricingMethod.FIXED
        n_cs = params.pop_int("n-cs", 0)
        cs_names = params.pop_str("cs-names", "").split(",")
        if len(cs_names) == 1 and len(cs_names[0]) == 0:
            cs_names = []
        if n_cs > 0 and len(cs_names) > 0:
            raise Exception(Lang.ERROR_CANNOT_USE_TOGETHER.format("n-cs","cs-names"))
        if n_cs == 0 and len(cs_names) == 0:
            cs_sel = ListSelection.ALL
        elif n_cs > 0:
            cs_sel = ListSelection.RANDOM
        else:
            cs_sel = ListSelection.GIVEN
            
        n_bus = params.pop_int("n-bus", 0)
        new_buses = params.pop_str("bus-names", "").split(",")
        if len(new_buses) == 1 and len(new_buses[0]) == 0:
            new_buses = []
        if n_bus > 0 and len(new_buses) > 0:
            raise Exception(Lang.ERROR_CANNOT_USE_TOGETHER.format("n-bus","bus-names"))
        if n_bus == 0 and len(new_buses) == 0:
            bus_sel = ListSelection.ALL
        elif n_bus > 0:
            bus_sel = ListSelection.RANDOM
        else:
            bus_sel = ListSelection.GIVEN
        
        if cs_type == "fcs":
            self.FCS(seed, slots, file = cs_file, bus=bus_sel, busCount=n_bus, givenBus=new_buses,
                    cs=cs_sel, csCount=n_cs, givenCS=cs_names, priceBuyMethod=pbuy_method, priceBuy=pbuy)
        else:
            self.SCS(seed, slots, file = cs_file, bus=bus_sel, busCount=n_bus, givenBus=new_buses,
                    cs=cs_sel, csCount=n_cs, givenCS=cs_names, priceBuyMethod=pbuy_method, priceBuy=pbuy,
                    priceSellMethod=psell_method, priceSell=psell)

    def CSFromArgs(self, params: Union[str,ArgChecker]):
        if isinstance(params, str):
            params = ArgChecker(params)
        type = params.pop_str("type", "fcs")
        if type not in ["fcs", "scs"]:
            raise Exception(Lang.ERROR_UNKNOWN_CS_TYPE.format(type))
        self.__CSFromArgs(type, params)

    def FCSFromArgs(self, params: Union[str,ArgChecker]):
        if isinstance(params, str):
            params = ArgChecker(params)
        self.__CSFromArgs("fcs", params)
    
    def SCSFromArgs(self, params: Union[str,ArgChecker]):
        if isinstance(params, str):
            params = ArgChecker(params)
        self.__CSFromArgs("scs", params)