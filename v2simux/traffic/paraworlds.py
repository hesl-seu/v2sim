import enum
import os
import sys
import threading
import time
import gzip
import dill as pickle
from collections import deque
from typing import DefaultDict, Deque, Dict, Generator, List, Optional, Set, Tuple, Iterable
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from v2simux.traffic.routing import Link
from .uxsim import World, Vehicle
from .utils import PyVersion, CheckPyVersion
from ..locale.lang import Lang
from .routing import *


class RoutingAlgorithm(enum.Enum):
    AstarFastest = 0
    AstarShortest = 1
    DijkstraFastest = 2
    DijkstraShortest = 3

    def run(self, gl:Graph, coords:CoordsDict, start_time:int, from_node:str, to_node:str):
        if self == RoutingAlgorithm.AstarFastest:
            return astarF(gl, coords, start_time, from_node, to_node)
        elif self == RoutingAlgorithm.AstarShortest:
            return astarS(gl, coords, start_time, from_node, to_node)
        elif self == RoutingAlgorithm.DijkstraFastest:
            return dijF(gl, start_time, from_node, to_node)
        elif self == RoutingAlgorithm.DijkstraShortest:
            return dijS(gl, start_time, from_node, to_node)
        else:
            raise ValueError(Lang.ROUTE_ALGO_NOT_SUPPORTED.format(""))

class WorldSpec(ABC):
    @abstractmethod
    def exec_simulation(self, until_s:int): ...

    @abstractmethod
    def add_vehicle(self, veh_id:str, from_node:str, to_node:str): ...

    @abstractmethod
    def get_arrived_vehicles(self) -> Generator[Tuple[str, Vehicle], None, None]: ...

    @abstractmethod
    def get_time(self) -> int: ...

    @abstractmethod
    def get_gl(self) -> Graph: ...

    @abstractmethod
    def has_vehicle(self, veh_id:str) -> bool: ...

    @abstractmethod
    def get_vehicle(self, veh_id:str) -> Vehicle: ...

    @abstractmethod
    def get_vehicle_count(self) -> int: ...

    @abstractmethod
    def get_coords(self) -> CoordsDict: ...

    @abstractmethod
    def get_average_speed(self) -> float: ...

    @abstractmethod
    def get_link(self, link_id:str) -> Optional[Link]: ...

    @abstractmethod
    def links(self) -> Iterable[Link]: ...

    @abstractmethod
    def shutdown(self): ...

    @abstractmethod
    def save(self, filepath:str): ...

    @staticmethod
    @abstractmethod
    def load(filepath:str): ...

def _load_world(filepath:str) -> WorldSpec:
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File {filepath} does not exist.")
    with gzip.open(filepath, 'rb') as f:
        data = pickle.load(f)
    assert isinstance(data, dict) and "obj" in data and "version" in data and "pickler" in data, "Invalid world file."
    world_obj = data["obj"]
    assert isinstance(world_obj, WorldSpec), "Invalid world object."
    assert CheckPyVersion(data["version"]), "Incompatible Python version for world: saved {}, current {}".format(data["version"], PyVersion())
    assert data["pickler"] == pickle.__name__, "Incompatible pickler for world: saved {}, current {}".format(data["pickler"], pickle.__name__)
    return world_obj

class SingleWorld(WorldSpec):
    def __init__(self, world:World, gl:Graph):
        self.world = world
        self.gl = gl
        self.__ct = 0
        self.__uvi:Dict[str, Vehicle] = {}
        self.__aQ:Deque[str] = deque()
        self.coords:CoordsDict = {}
        self.__cnt = 0
        for node in self.world.NODES:
            self.coords[node.name] = (node.x, node.y)
    
    def exec_simulation(self, until_s:int):
        self.__aQ.clear()
        self.world.exec_simulation(until_s)
        self.__ct = until_s
        self.__cnt += 1
    
    def add_vehicle(self, veh_id:str, from_node:str, to_node:str):
        tn = self.world.get_node(to_node)
        v = self.world.addVehicle(orig=from_node, dest=to_node, departure_time=self.__ct, name=veh_id, auto_rename=True)
        def __add_to_arrQ():
            self.__aQ.append(veh_id)
            v.node_event.clear()
        v.node_event[tn] = __add_to_arrQ
        self.__uvi[veh_id] = v
    
    def has_vehicle(self, veh_id:str) -> bool:
        return veh_id in self.__uvi
    
    def get_vehicle(self, veh_id:str) -> Vehicle:
        return self.__uvi[veh_id]
    
    def get_vehicle_count(self) -> int:
        return len(self.__uvi)
    
    def get_link(self, link_id:str) -> Optional[Link]:
        return self.world.get_link(link_id)
    
    def links(self) -> List[Link]:
        return self.world.LINKS

    def get_arrived_vehicles(self):
        while len(self.__aQ) > 0:
            veh_id = self.__aQ.popleft()
            yield veh_id, self.__uvi[veh_id]
            self.world.VEHICLES.pop(veh_id)
            del self.__uvi[veh_id]

    def get_time(self) -> int:
        return self.__ct
    
    def get_gl(self) -> Graph:
        return self.gl
    
    def get_coords(self) -> CoordsDict:
        return self.coords
    
    def get_average_speed(self) -> float:
        return self.world.analyzer.average_speed
    
    def shutdown(self):
        return f"Total steps: {self.__cnt}"
    
    def __lstack_save(self, filepath:str):
        sys.setrecursionlimit(10**9)
        with gzip.open(filepath, 'wb') as f:
            pickle.dump({
                "obj": self,
                "version": PyVersion(),
                "pickler": pickle.__name__
            }, f)

    def save(self, filepath:str):
        threading.stack_size(1024 * 1024 * 128)  # 128MB
        t = threading.Thread(target=self.__lstack_save, args=(filepath,))
        t.start()
        t.join()

    @staticmethod
    def load(filepath:str):
        data = _load_world(filepath)
        assert isinstance(data, SingleWorld)
        return data

class ParaWorlds(WorldSpec):
    def __init__(self, worlds:Dict[int, World], gl:Graph):
        self.worlds = worlds
        self.gl = gl
        self.node_coords:Dict[str, Tuple[float, float]] = {}
        self.wid_of_edges:Dict[str, int] = {}
        self.wid_of_nodes:Dict[str, Set[int]] = DefaultDict(set)
        for wid, W in worlds.items():
            for edge in W.LINKS:
                self.wid_of_edges[edge.name] = wid
            for node in W.NODES:
                self.wid_of_nodes[node.name].add(wid)
                if node.name in self.node_coords:
                    assert self.node_coords[node.name] == (node.x, node.y), \
                        f"Node {node.name} has inconsistent coordinates across worlds."
                else:
                    self.node_coords[node.name] = (node.x, node.y)
        
        # Deque of (arrival vehicle id, current trip segment id)
        self.__aQs:List[Deque[Tuple[str, int]]] = [deque() for _ in range(len(worlds))]

        # Real queue for arrival vehicles, completing the whole trip
        self.__aQ:Deque[str] = deque()

        # time
        self.__ctime = 0

        # Vehicle itineraries: vehicle id -> list of splitting nodes: (node_name, next_world_id)
        self.__veh_itineraies:Dict[str, List[Tuple[str, int]]] = {}

        self.__uvi: Dict[str, Vehicle] = {}

        self.__lt: float = 1.0
        self.__cnt_para = 0
        self.__cnt_ser = 0
        self.__create_pool()
    
    def __create_pool(self):
        self.__pool = ThreadPoolExecutor(os.cpu_count())
    
    def get_coords(self) -> CoordsDict:
        return self.node_coords
    
    def __getitem__(self, wid:int) -> World:
        return self.worlds[wid]

    def get_gl(self) -> Graph:
        return self.gl
    
    def get_arrived_vehicles(self):
        while len(self.__aQ) > 0:
            veh_id = self.__aQ.popleft()
            yield veh_id, self.__uvi[veh_id]
            del self.__uvi[veh_id]
    
    def get_time(self) -> int:
        return self.__ctime

    def exec_simulation(self, until_s:int):
        self.__aQ.clear()
        
        st = time.time()
        if self.__lt < 0.01:
            for W in self.worlds.values():
                W.exec_simulation(until_s)
            self.__cnt_ser += 1
        else:
            futures = []
            for W in self.worlds.values():
                if len(futures) + 1 == len(self.worlds):
                    # The last task in conduct in main thread to reduce the overhead
                    W.exec_simulation(until_s)
                else:
                    futures.append(self.__pool.submit(W.exec_simulation, until_s))
            self.__cnt_para += 1
            for _ in as_completed(futures): pass

        self.__lt = time.time() - st
        
        self.__ctime = until_s

        for i, aQ in enumerate(self.__aQs):
            while len(aQ) > 0:
                veh_id, trip_segment = aQ.popleft()
                self.worlds[i].VEHICLES.pop(veh_id)
                splitting_nodes = self.__veh_itineraies[veh_id]
                if trip_segment + 2 < len(splitting_nodes):
                    trip_segment += 1
                    from_node, next_wid = splitting_nodes[trip_segment]
                    to_node, _ = splitting_nodes[trip_segment + 1]
                    del self.__uvi[veh_id]
                    self.__add_veh(next_wid, veh_id, from_node, to_node, trip_segment)
                else:
                    self.__aQ.append(veh_id)
                    self.__veh_itineraies.pop(veh_id)

    def get_link(self, link_id:str) -> Optional[Link]:
        return self.worlds[self.wid_of_edges[link_id]].get_link(link_id)
    
    def links(self) -> Iterable[Link]:
        return (link for W in self.worlds.values() for link in W.LINKS)

    def __add_veh(self, world_id:int, veh_id:str, from_node:str, to_node:str, trip_segment:int):
        assert world_id in self.wid_of_nodes[from_node], \
            f"Node {from_node} is not in world {world_id}, cannot add vehicle {veh_id}."
        assert world_id in self.wid_of_nodes[to_node], \
            f"Node {to_node} is not in world {world_id}, cannot add vehicle {veh_id}."
        W = self.worlds[world_id]
        tn = W.get_node(to_node)
        v = W.addVehicle(orig=from_node, dest=to_node, departure_time=self.__ctime, name=veh_id, auto_rename=True)
        def add_to_aQ():
            self.__aQs[world_id].append((veh_id, trip_segment))
            v.node_event.clear()
        v.node_event[tn] = add_to_aQ
        self.__uvi[veh_id] = v

    def add_vehicle(self, veh_id:str, from_node:str, to_node:str, algo:RoutingAlgorithm = RoutingAlgorithm.AstarFastest):
        if from_node == to_node:
            for wid in self.wid_of_nodes[from_node]:
                splitting_nodes:List[Tuple[str, int]] = [(from_node, wid), (to_node, -1)]
                break
        else:
            stage = algo.run(self.gl, self.node_coords, self.__ctime, from_node, to_node)
            Ecnt = len(stage.edges)
            assert Ecnt > 0, "Route not found."
            splitting_nodes:List[Tuple[str, int]] = [(stage.nodes[0], self.wid_of_edges[stage.edges[0]])]  # (node_name, prev_world_id, next_world_id)
            for i in range(Ecnt - 1):
                if self.wid_of_edges[stage.edges[i]] != self.wid_of_edges[stage.edges[i + 1]]:
                    splitting_nodes.append((stage.nodes[i + 1], self.wid_of_edges[stage.edges[i + 1]]))
            splitting_nodes.append((stage.nodes[-1], -1))  # Destination node, no next world

        self.__veh_itineraies[veh_id] = splitting_nodes
        self.__add_veh(splitting_nodes[0][1], veh_id, splitting_nodes[0][0], splitting_nodes[1][0], 0)

    def has_vehicle(self, veh_id: str) -> bool:
        return veh_id in self.__uvi
    
    def get_vehicle(self, veh_id: str) -> Vehicle:
        return self.__uvi[veh_id]

    def get_vehicle_count(self) -> int:
        return len(self.__uvi)
    
    def get_average_speed(self) -> float:
        return sum(W.analyzer.average_speed for W in self.worlds.values()) / len(self.worlds)
    
    def shutdown(self):
        self.__pool.shutdown(wait=True)
        return f"Total steps: {self.__cnt_ser} serial + {self.__cnt_para} parallel"

    def __lstack_save(self, filepath:str):
        sys.setrecursionlimit(10**9)
        with gzip.open(filepath, 'wb') as f:
            pickle.dump({
                "obj": self,
                "version": PyVersion(),
                "pickler": pickle.__name__
            }, f)

    def save(self, filepath:str):
        self.__pool.shutdown(wait=True)
        del self.__pool
        threading.stack_size(1024 * 1024 * 128)  # 128MB
        t = threading.Thread(target=self.__lstack_save, args=(filepath,))
        t.start()
        t.join()
        self.__create_pool()

    @staticmethod
    def load(filepath:str):
        data = _load_world(filepath)
        assert isinstance(data, ParaWorlds), "Invalid world object."
        return data

def load_world(filepath:str) -> WorldSpec:
    data = _load_world(filepath)
    assert isinstance(data, (SingleWorld, ParaWorlds)), "Invalid world object."
    return data

__all__ = ["WorldSpec", "SingleWorld", "ParaWorlds", "RoutingAlgorithm", "load_world"]