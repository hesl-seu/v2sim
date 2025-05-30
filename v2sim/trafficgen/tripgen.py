from enum import IntEnum, StrEnum
import random, time, sumolib
from typing import Dict, List, Optional, Union
from feasytools import ReadOnlyTable, CDDiscrete, PDDiscrete, PDGamma, DTypeEnum
import numpy as np

from ..locale import Lang
from ..traffic import EV, EVDict, ReadXML, DetectFiles
from .misc import VehicleType, random_diff, _TripInner, _EVInner, _xmlSaver
from .poly import PolygonMan

DictPDF = dict[int, Union[PDDiscrete[int], None]]

TAZ_TYPE_LIST = ("Home", "Work", "Relax", "Other")

class RoutingCacheMode(IntEnum):
    """Routing cache mode"""
    NONE = 0  # No cache
    RUNTIME = 1 # Cache during runtime
    STATIC = 2 # Static cache in generation time

    def __str__(self):
        return ("None", "Runtime", "Static")[self.value]

    def __repr__(self):
        return self.value
    
class TripsGenMode(StrEnum):
    """Generation mode"""

    AUTO = "Auto"  # Automatic
    TAZ = "TAZ"  # TAZ-based
    POLY = "Poly"  # Polygon-based

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value

class EVsGenerator:    
    """Class to generate trips"""
    def __init__(self, CROOT: str, PNAME: str, seed,
            mode: TripsGenMode = TripsGenMode.AUTO,
            route_cache: RoutingCacheMode = RoutingCacheMode.NONE):
        """
        Initialization
            CROOT: Trip parameter folder
            PNAME: SUMO configuration folder
            seed: Random seed
        """
        _fn = DetectFiles(PNAME)
        random.seed(seed)
        self.vTypes = [VehicleType(**x) for x in ReadOnlyTable(CROOT + "/ev_types.csv",dtype=DTypeEnum.FLOAT32).to_list_of_dict()]
        # Define various functional area types
        self._route_cache_mode = route_cache
        self.__route_cache:dict[tuple[str,str], list[str]] = {}
        self.dic_taz = {}
        self.net:sumolib.net.Net = sumolib.net.readNet(_fn["net"])
        if mode == TripsGenMode.AUTO:
            if _fn.taz and _fn.taz_type: mode = TripsGenMode.TAZ
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
        elif mode == TripsGenMode.POLY:
            assert _fn.poly and _fn.net and _fn.fcs, Lang.ERROR_NO_TAZ_OR_POLY
            self._mode = "poly"
            from .graph import RoadNetConnectivityChecker
            net = RoadNetConnectivityChecker(_fn.net, _fn.fcs)
            polys = PolygonMan(_fn.poly)
            self.dic_taztype = {k:[] for k in TAZ_TYPE_LIST}
            for poly in polys:
                taz_id = poly.ID
                taz_type = poly.getConvertedType()
                poi_pos = poly.center()
                if taz_type:
                    try:
                        eid = net.find_nearest_edge_id(poi_pos)
                    except RuntimeError:
                        continue
                    self.dic_taztype[taz_type].append(taz_id)
                    self.dic_taz[taz_id] = [eid]
        else:
            raise RuntimeError(Lang.ERROR_NO_TAZ_OR_POLY)
        
        # Start time of first trip
        self.pdf_start_weekday = PDGamma(6.63, 65.76, 114.54)
        self.pdf_start_weekend = PDGamma(3.45, 84.37, 197.53)
        
        # Spatial transfer probability of weekday and weekend. 
        # key1 = from_type, key2 = time (0~95, each unit = 15min), value = CDF of (to_type1, to_type2, to_type3, to_type4)
        self.PSweekday:dict[str, DictPDF] = {}
        self.PSweekend:dict[str, DictPDF] = {}
        # Parking duration CDF of weekday and weekend.
        self.park_cdf_wd:dict[str, CDDiscrete[int]] = {} 
        self.park_cdf_we:dict[str, CDDiscrete[int]] = {}

        def read_trans_pdfs(path:str) -> DictPDF:
            tbwd = ReadOnlyTable(path, dtype=DTypeEnum.FLOAT32)
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
            self.PSweekday[dtype] = read_trans_pdfs(f"{CROOT}/space_transfer_probability/{dtype[0]}_spr_weekday.csv")
            self.PSweekend[dtype] = read_trans_pdfs(f"{CROOT}/space_transfer_probability/{dtype[0]}_spr_weekend.csv")
            self.park_cdf_wd[dtype] = CDDiscrete(f"{CROOT}/duration_of_parking/{dtype[0]}_spr_weekday.csv", True, int)
            self.park_cdf_we[dtype] = CDDiscrete(f"{CROOT}/duration_of_parking/{dtype[0]}_spr_weekend.csv", True, int)

        self.soc_pdf = PDDiscrete.fromCSVFileI(f"{CROOT}/soc_dist.csv", True)
    
    def __getPs(self, is_weekday: bool, dtype: str, time_index:int):
        return self.PSweekday[dtype].get(time_index, None) if is_weekday else self.PSweekend[dtype].get(time_index, None)
    
    def __getDest1(self, pfr: str, weekday: bool = True):
        """
        Get the destination of the trip secondary to the first trip
            pfr: Departure functional area type, such as "Home"
            weekday: Whether it is weekday or weekend
        Returns: 
            First trip: First departure time, arrival destination functional area type, such as "Work"
        """
        pdf = None
        while pdf is None:
            init_time = self.pdf_start_weekday.sample() if weekday else self.pdf_start_weekend.sample()
            # Time index (0~95, each unit = 15min)
            init_time_i = int(init_time / 15)
            pdf = self.__getPs(weekday, pfr, init_time_i)
        next_place = TAZ_TYPE_LIST[pdf.sample()]
        return int(init_time), next_place

    def __getDestA(self, from_type:str, init_time_i:int, weekday: bool):
        """
        Get the destination of the next trip for non-first trips
            from_type: Departure type, such as "Home"
            depart_time: Departure time
        Returns:
            Destination type
        """
        cdf = self.__getPs(weekday, from_type, init_time_i)
        return "Home" if cdf is None else TAZ_TYPE_LIST[cdf.sample()]

    def __getNextTAZandPlace(self, from_TAZ:str, from_EDGE:str, next_place_type:str) -> tuple[str,str,list[str]]:
        trial = 0
        while True:
            if self._mode == "taz":
                to_TAZ = random.choice(self.dic_taztype[next_place_type])
                to_EDGE = random_diff(self.dic_taz[to_TAZ], from_EDGE)
            else: # self._mode == "diff"
                to_TAZ = random_diff(self.dic_taztype[next_place_type], from_TAZ)
                to_EDGE = random.choice(self.dic_taz[to_TAZ])
            if from_EDGE != to_EDGE:
                if self._route_cache_mode == RoutingCacheMode.STATIC:
                    if (from_EDGE, to_EDGE) in self.__route_cache:
                        route = self.__route_cache[from_EDGE, to_EDGE]
                    else:
                        route0, _ = self.net.getFastestPath(
                            self.net.getEdge(from_EDGE),
                            self.net.getEdge(to_EDGE)
                        )
                        if route0 is None:
                            route = [from_EDGE, to_EDGE]
                        else:
                            route = [x.getID() for x in route0]
                        self.__route_cache[from_EDGE, to_EDGE] = route
                else:
                    route = [from_EDGE, to_EDGE]
                return to_TAZ, to_EDGE, route
            trial += 1
            if trial >= 5:
                raise RuntimeError("from_EDGE == to_EDGE")
        
    
    def __genFirstTrip1(self, trip_id, weekday: bool = True):
        """
        Generate the first trip of the first day
            trip_id: Trip ID
            weekday: hether it is weekday or weekend
        Return the trip's XML file line and the relevant information saved in dictionary form
            dic_save = {
                "trip_id":...,          Trip ID
                "depart_time":...,      Departure time of the first trip, in minutes
                "from_TAZ":...,         Departure area TAZ type, such as "TAZ1"
                "from_EDGE":...,        Departure roadside, such as "gnE29"
                "to_TAZ":...,           Arrival area TAZ type, such as "TAZ2"
                "to_EDGE":...,          Arrival roadside, such as "gnE2"
                "routes":...,           Routes type read from SUMO xml file, such as 'gneE22 gneE0 gneE16'
                "next_place_type":...   Arrival area attribute "Work"
            }
        """
        from_TAZ = random.choice(self.dic_taztype["Home"])
        from_EDGE = random.choice(self.dic_taz[from_TAZ])
        # Get departure time and destination area type
        depart_time, next_place_type = self.__getDest1("Home", weekday)  
        to_TAZ, to_EDGE, route = self.__getNextTAZandPlace(from_TAZ, from_EDGE, next_place_type)
        return _TripInner(trip_id, depart_time * 60, from_TAZ, from_EDGE,
            to_TAZ, to_EDGE, route, next_place_type)

    cdf_dict = {}

    def __genStopTime(self, from_type:str, weekday: bool):
        cdf = self.park_cdf_wd[from_type] if weekday else self.park_cdf_we[from_type]
        return int(cdf.sample() + 1) * 15

    def __genTripA(
        self, trip_id, from_TAZ, from_type, from_EDGE, start_time, weekday: bool = True
    )->_TripInner:
        """Generate the second trip"""
        stop_duration = self.__genStopTime(from_type, weekday)
        depart_time = start_time + stop_duration * 15 + 20
        next_place2 = self.__getDestA(from_type, stop_duration, weekday)
        taz_choose2, edge_choose2, route = self.__getNextTAZandPlace(from_TAZ, from_EDGE, next_place2)
        return _TripInner(trip_id, depart_time * 60, from_TAZ, from_EDGE,
            taz_choose2, edge_choose2, route, next_place2)

    def __genTripF(
        self, trip_id:str, from_TAZ:str, from_type, from_EDGE:str,
        start_time:int, first_TAZ:str, first_EDGE:str, weekday: bool = True,
    ):
        """Generate the third trip"""
        if first_EDGE == from_EDGE:
            return None
        stop_time = self.__genStopTime(from_type, weekday)
        depart_time = start_time + stop_time + 20
        return _TripInner(
            trip_id, depart_time * 60, from_TAZ, from_EDGE, first_TAZ, first_EDGE,
            [from_EDGE, first_EDGE], "Home"
        )

    def __genTripsChain1(self, ev:_EVInner):  # vehicle_trip
        """
        Generate a full day of trips on the first day
            ev: vehicle instance
        """
        daynum = 0
        weekday = True
        trip_1 = self.__genFirstTrip1("trip0_1", weekday)
        trip_2 = self.__genTripA("trip0_2",trip_1.toTAZ,
            trip_1.NTP,trip_1.toE,trip_1.DPTT,weekday)
        trip_3 = self.__genTripF("trip0_3",trip_2.toTAZ,
            trip_2.NTP,trip_2.toE,trip_2.DPTT,
            trip_1.frTAZ,trip_1.route[0],weekday)
        
        ev._add_trip(daynum, trip_1)
        ev._add_trip(daynum, trip_2)
        if trip_3: # Trip3: if O==D, don't generate trip 3
            ev._add_trip(daynum, trip_3)

    def __genFirstTripA(self, trip_id, ev: _EVInner, weekday: bool = True):
        """
        Generate the first trip of a non-first day
            trip_id: Trip ID
            vehicle_node: Vehicle node, such as rootNode.getElementsByTagName("vehicle")[0]
            weekday: Whether it is weekday or weekend
        """
        trip_last = ev.trips[-1]
        from_EDGE = trip_last.route[-1]
        from_TAZ = trip_last.toTAZ
        # Get departure time and destination area type
        depart_time, next_place_type = self.__getDest1("Home", weekday)
        to_TAZ, to_EDGE, route = self.__getNextTAZandPlace(from_TAZ, from_EDGE, next_place_type)
        return _TripInner(trip_id, depart_time * 60, from_TAZ, from_EDGE,
            to_TAZ, to_EDGE, route, next_place_type)

    def __genTripsChainA(self, ev: _EVInner, daynum: int = 1):  # vehicle_trip
        """
        Generate a full day of trips on a non-first day
        """
        weekday = (daynum - 1) % 7 + 1 in [1, 2, 3, 4, 5]
        trip2_1 = self.__genFirstTripA(f"trip{daynum}_1", ev, weekday)
        trip2_2 = self.__genTripA(f"trip{daynum}_2",trip2_1.toTAZ,
            trip2_1.NTP,trip2_1.toE,trip2_1.DPTT,weekday)
        trip2_3 = self.__genTripF(f"trip{daynum}_3",
            trip2_2.toTAZ,trip2_2.NTP,trip2_2.toE,
            trip2_2.DPTT,trip2_1.frTAZ,trip2_1.route[0],weekday)
                    
        ev._add_trip(daynum, trip2_1)
        ev._add_trip(daynum, trip2_2)
        if trip2_3:
            ev._add_trip(daynum, trip2_3)

    def __genEV(self, veh_id: str, day_count:int, **kwargs) -> _EVInner:
        '''
        Generate a full week of trips for a vehicle as an inner instance
        '''
        ev = _EVInner(veh_id, random.choice(self.vTypes), self.soc_pdf.sample()/100.0, **kwargs)
        self.__genTripsChain1(ev)
        for j in range(1, day_count + 1):
            self.__genTripsChainA(ev, j)
        return ev

    def genEV(self, veh_id: str, **kwargs) -> EV:
        """
        Generate a full week of trips for a vehicle.
        The generated vehicle is returned as an EV instance, and will not be held in the buffer.
            veh_id: ID of the vehicle
            v2g_prop: Proportion of users willing to participate in V2G
            omega: PDFunc | None = None,
            krel: PDFunc | None = None,
            ksc: PDFunc | None = None,
            kfc: PDFunc | None = None,
            kv2g: PDFunc | None = None
        """
        return self.__genEV(veh_id, **kwargs).toEV()

    def genEVs(
        self, N: int, fname: Optional[str] = None, day_count: int = 7, silent: bool = False, **kwargs
    ) -> EVDict:
        """
        Generate EV and trips of N vehicles.
        The generated vehicles are returned as an EVDict instance, and will be saved to the file if fname is provided.
        The vehicles will not be held in the buffer.
            N: Number of vehicles
            fname: Saved file name (if None, not saved)
            day_count: Number of days
            silent: Whether silent mode
            v2g_prop: Proportion of users willing to participate in V2G
            omega: PDFunc | None = None,
            krel: PDFunc | None = None,
            ksc: PDFunc | None = None,
            kfc: PDFunc | None = None,
            kv2g: PDFunc | None = None
        """
        st_time = time.time()
        last_print_time = 0
        saver = _xmlSaver(fname) if fname else None
        ret = EVDict()
        for i in range(0, N):
            ev = self.__genEV("v" + str(i), day_count,
                cache_route = self._route_cache_mode != RoutingCacheMode.NONE, **kwargs)
            ret.add(ev.toEV())
            if saver:
                saver.write(ev)
            if not silent and time.time()-last_print_time>1:
                print(f"\r{i+1}/{N}, {(i+1)/N*100:.2f}%", end="")
                last_print_time=time.time()
        if not silent:
            print(f"\r{N}/{N}, 100.00%")
            print(Lang.INFO_DONE_WITH_SECOND.format(round(time.time() - st_time, 1)))
        if saver:
            saver.close()
        return ret

class ManualEVsGenerator:
    """Class to manually add EVs to the buffer"""
    def __init__(self):
        self.__evs:Dict[str, _EVInner] = {}
    
    def addEV(self, vid:str, bcap_kWh:float, range_km:float, efc_rate_kW:float, 
            esc_rate_kW:float, max_V2G_kW:float, soc:float, omega:float, 
            krel:float, ksc:float, kfc:float, kv2g:float, cache_route:bool = False) -> _EVInner:
        """
        Add an EV to the generator's buffer
            vid: Vehicle ID
            vtype: Vehicle type
            soc: State of charge (0.0~1.0)
        """
        if vid in self.__evs:
            raise ValueError(f"Vehicle ID {vid} already exists.")
        ev = _EVInner(vid, VehicleType(-1, bcap_kWh, range_km, efc_rate_kW, esc_rate_kW, max_V2G_kW), 
            soc, omega=omega, krel=krel, ksc=ksc, kfc=kfc, kv2g=kv2g, cache_route=cache_route)
        self.__evs[vid] = ev
        return ev
    
    def dumpEVs(self, fname: str):
        """
        Dump all EVs in the buffer to a file
            fname: File name
        """
        saver = _xmlSaver(fname)
        for ev in self.__evs.values():
            saver.write(ev)
        saver.close()
    
    def getEVs(self) -> EVDict:
        """
        Get all EVs in the buffer as an EVDict instance
        """
        ret = EVDict()
        for ev in self.__evs.values():
            ret.add(ev.toEV())
        return ret