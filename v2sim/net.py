import math, os, shutil, sys, threading
import numpy as np
import sumolib
from xml.etree.ElementTree import Element, ElementTree
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Set
from collections import defaultdict
from dataclasses import dataclass, field
from scipy.cluster.vq import kmeans, vq
from scipy.spatial import KDTree
from collections import defaultdict
from .utils import DetectFiles, ReadXML
from .locale import Lang


def _largeStackExec(func, *args):
    import sys
    threading.stack_size(67108864) #64MB
    sys.setrecursionlimit(10**7)
    th = threading.Thread(target=func, args=args)
    th.start()
    th.join()


class Node:
    def __init__(self, node_id:str, x:float, y:float, extras:Optional[Dict[str, str]] = None):
        self.name = node_id
        self.x = x
        self.y = y
        self.incoming_edges:List[Edge] = []
        self.attrs = extras if extras is not None else {}
        self.outgoing_edges:List[Edge] = []
    
    def get_coord(self) -> Tuple[float, float]:
        """Get the coordinates of the node."""
        return (self.x, self.y)

    def __getitem__(self, key:str) -> str:
        return self.attrs[key]
    
    def __setitem__(self, key:str, value:str):
        self.attrs[key] = value


class Edge:
    def __init__(self, name:str, from_node:Node, to_node:Node, length:float, lanes:int, speed_limit:float = 13.89, world_id:int = -1, nickname:Optional[str] = None, extras:Optional[Dict[str, str]] = None):
        self.name = name
        self.from_node = from_node
        self.to_node = to_node
        self.length = length # in meters
        self.lanes = lanes
        self.speed_limit = speed_limit # Default 50 km/h in m/s
        self.world_id = world_id
        self.nickname = nickname
        self.attrs = extras if extras is not None else {}
    
    def instant_travel_time(self, t: int) -> float:
        """Get the travel time of free flowing condition. The parameter t is ignored, but kept for compatibility."""
        return self.length / self.speed_limit
    
    def __getitem__(self, key:str) -> str:
        return self.attrs[key]
    
    def __setitem__(self, key:str, value:str):
        self.attrs[key] = value
    

@dataclass
class SubNet:
    nodes: Set[str] = field(default_factory=set)
    edges: Set[str] = field(default_factory=set)

class _TarjanSCC:
    def __init__(self, n:int, gl:Dict[int, List[int]]):
        self.__dfn: List[int] = [0] * n
        self.__low: List[int] = [0] * n
        self.__dfncnt = 0

        self.__scc: List[int] = [0] * n
        self.__sc = 0

        self.__stk: List[int] = []
        self.__vis: set[int] = set()
        self.__gl = gl

        self.scc = None
    
    def __tarjan(self, u: int):
        self.__dfncnt += 1
        self.__low[u] = self.__dfn[u] = self.__dfncnt
        self.__stk.append(u)
        self.__vis.add(u)
        for v in self.__gl[u]:
            if self.__dfn[v] == 0:
                self.__tarjan(v)
                self.__low[u] = min(self.__low[u], self.__low[v])
            elif v in self.__vis:
                self.__low[u] = min(self.__low[u], self.__dfn[v])
        if self.__low[u] == self.__dfn[u]:
            self.__sc += 1
            while True:
                v = self.__stk.pop()
                self.__vis.remove(v)
                self.__scc[v] = self.__sc
                if v == u:
                    break
    
    def calc_scc(self):
        """
        Calculate the strongly connected components (SCC) of the graph.
        Returns a list of SCC in a decreasing order by size, each element indicates the nodes in this SCC
        """
        n = len(self.__gl)
        for u in range(n):
            if self.__low[u] == 0:
                self.__tarjan(u)

        scc_dict: Dict[int, List[int]] = defaultdict(list)
        for i, x in enumerate(self.__scc):
            scc_dict[x].append(i)

        ret = list(scc_dict.values())
        ret.sort(key=lambda x: len(x), reverse=True)

        self.scc = ret


class RoadNet:
    VERSION = "1.0"
    def __init__(self):
        self.nodes:Dict[str, Node] = {}
        self.__nodeL:List[Node] = []
        self.edges:Dict[str, Edge] = {}
        self.__edgeL:List[Edge] = []
        self.__scc:List[SubNet] = []
        self.__kdt:Optional[KDTree] = None
        self.__kdst = None
        self._proj = None
        self.netOffset = (0.,0.)
        self.convBoundary = (0.,0.,0.,0.)
        self.origBoundary = (0.,0.,0.,0.)
        self.projParameter = "!"
        self.__sumo:Optional[sumolib.net.Net] = None
    
    def calc_kdsegtree(self):
        """
        Calculate the KDTree of the road network nodes for fast nearest neighbor search.
        """
        from .seg import KDTreeSegmentSearch
        self.__edgeL = []
        segs = []
        for ename in self.edges:
            e = self.sumo.getEdge(ename)
            shape = e.getShape()
            for i in range(1, len(shape)):
                a = shape[i - 1]
                b = shape[i]
                segs.append((a[0], a[1], b[0], b[1]))
                self.__edgeL.append(self.edges[ename])
        self.__kdst = KDTreeSegmentSearch(np.array(segs))

    def calc_kdtree(self):
        """
        Calculate the KDTree of the road network nodes for fast nearest neighbor search.
        """
        self.__nodeL = list(self.nodes.values())
        coords = np.array([node.get_coord() for node in self.__nodeL])
        self.__kdt = KDTree(coords) # type: ignore

    @property
    def kdtree(self) -> KDTree:
        if self.__kdt is None:
            self.calc_kdtree()
        assert self.__kdt is not None
        return self.__kdt
    
    @property
    def sumo(self):
        assert self.__sumo is not None
        return self.__sumo
    
    def is_from_sumo(self):
        return self.__sumo is not None

    def check_scc_size(self, display:bool = True):
        '''Check if the size of the largest strongly connected component is large enough'''
        if len(self.scc[0].nodes) < len(self.nodes) * 0.8:
            if display: print(Lang.WARN_SCC_TOO_SMALL.format(len(self.scc[0].nodes), len(self.nodes)))
            return False
        return True
    
    def is_node_in_largest_scc(self, node_id:str) -> bool:
        """
        Check if a node is in the largest strongly connected component.
        """
        if len(self.__scc) == 0:
            self.calc_max_scc()
        return node_id in self.__scc[0].nodes
    
    def is_edge_in_largest_scc(self, edge_id:str) -> bool:
        """
        Check if a edge is in the largest strongly connected component.
        """
        if len(self.__scc) == 0:
            self.calc_max_scc()
        return edge_id in self.__scc[0].edges
    
    def find_nearest_edge_id(self, x:float, y:float) -> Tuple[float, str]:
        """
        Find the nearest edge to the given coordinates in max scc which allows passengers
        """
        if self.__kdst is None:
            self.calc_kdsegtree()
        assert self.__kdst is not None
        i, dist, _ = self.__kdst.find_closest_segment(np.array([x, y]))
        return dist, self.__edgeL[i].name
    
    def find_nearest_node(self, x:float, y:float) -> Node:
        """
        Find the nearest node to the given coordinates.
        """
        dist, idx = self.kdtree.query([[x, y]], k=1, workers=-1)
        return self.__nodeL[idx.item()]
    
    def find_nearest_node_with_distance(self, x:float, y:float) -> Tuple[float, Node]:
        """
        Find the nearest node to the given coordinates.
        """
        dist, idx = self.kdtree.query([[x, y]], k=1, workers=-1)
        return dist.item(), self.__nodeL[idx.item()]
    
    def get_edge_pos(self, edge:str):
        '''
        Get the position of the edge in the road network.
        The position is the average of the shape of the edge.
        '''
        e:sumolib.net.edge.Edge = self.sumo.getEdge(edge)
        shp = e.getShape()
        assert shp is not None
        sx = sy = 0
        for (x,y) in shp:
            sx += x; sy+= y
        sx /= len(shp); sy /= len(shp)
        assert isinstance(sx, (float,int))
        assert isinstance(sy, (float,int))
        return sx, sy

    def allows_passengers(self, edge_id:str) -> bool:
        return self.sumo.getEdge(edge_id).allows("passenger")
    
    def calc_max_scc(self):
        """
        Calculate the largest strongly connected component (SCC) of the road network.
        Returns a set of node IDs in the largest SCC.
        """
        nodes = list(self.nodes.values())
        nmp = {node.name: i for i, node in enumerate(nodes)}
        tscc = _TarjanSCC(n=self.node_count, gl={
            i: [nmp[e.to_node.name] for e in nodes[i].outgoing_edges] 
            for i in range(len(self.nodes))
        })
        _largeStackExec(tscc.calc_scc)
        
        assert tscc.scc is not None

        sccidx_of_nodes = {}
        for i, node_ids in enumerate(tscc.scc):
            for nid in node_ids:
                sccidx_of_nodes[nid] = i
        
        scc_tmp = {
            i: SubNet(nodes = {nodes[j].name for j in node_ids}) 
            for i, node_ids in enumerate(tscc.scc)
        }
        for edge in self.edges.values():
            if sccidx_of_nodes[nmp[edge.from_node.name]] == sccidx_of_nodes[nmp[edge.to_node.name]]:
                scc_tmp[sccidx_of_nodes[nmp[edge.from_node.name]]].edges.add(edge.name)
            
        self.__scc = list(scc_tmp.values())
        return self.__scc
    
    @property
    def scc(self) -> List[SubNet]:
        if len(self.__scc) == 0:
            self.calc_max_scc()
        return self.__scc

    def add_node(self, node_id:str, x:int, y:int, extras:Optional[Dict[str, str]] = None) -> Node:
        self.__scc = []
        self.__kdt = None
        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists.")
        node = Node(node_id, x, y, extras)
        self.nodes[node_id] = node
        return node
    
    def get_node(self, node_id:str) -> Node:
        return self.nodes[node_id]
    
    def rename_node(self, old_id:str, new_id:str):
        if new_id in self.nodes:
            raise ValueError(Lang.NODE_EXISTS.format(new_id))
        node = self.nodes.pop(old_id)
        for edge in node.incoming_edges:
            edge.to_node = node
        for edge in node.outgoing_edges:
            edge.from_node = node
        node.name = new_id
        self.nodes[new_id] = node
    
    def remove_node(self, node_id:str):
        self.__scc = []
        self.__kdt = None
        if not node_id in self.nodes:
            raise ValueError(Lang.NODE_NOT_FOUND.format(node_id))
        node = self.nodes.pop(node_id)
        enames = list(self.edges.keys())
        for e in enames:
            edge = self.edges[e]
            if edge.from_node == node or edge.to_node == node:
                self.remove_edge(e)
    
    def update_node(self, old_node_id:str, new_node_id:str):
        if not old_node_id in self.nodes:
            raise ValueError(Lang.NODE_NOT_FOUND.format(old_node_id))
        if new_node_id in self.nodes:
            raise ValueError(Lang.NODE_EXISTS.format(new_node_id))
        node = self.nodes.pop(old_node_id)
        node.name = new_node_id
        self.nodes[new_node_id] = node
        
    @property
    def node_ids(self):
        return list(self.nodes.keys())
    
    @property
    def node_count(self):
        return len(self.nodes)
    
    def add_edge(self, edge_id:str, from_node:Union[str, Node], to_node:Union[str, Node], 
            length_m:float, lanes:int, speed_limit:float, world_id:int = -1, nickname:Optional[str] = None) -> Edge:
        self.__scc = []
        if edge_id in self.edges:
            raise ValueError(Lang.EDGE_EXISTS.format(edge_id))
        if isinstance(from_node, str): from_node = self.get_node(from_node)
        if isinstance(to_node, str): to_node = self.get_node(to_node)
        edge = Edge(edge_id, from_node, to_node, length_m, lanes, speed_limit, world_id, nickname)
        self.edges[edge_id] = edge
        from_node.outgoing_edges.append(edge)
        to_node.incoming_edges.append(edge)
        return edge
    
    def get_edge(self, edge_id:str) -> Edge:
        return self.edges[edge_id]
    
    def rename_edge(self, old_id:str, new_id:str):
        if new_id in self.edges:
            raise ValueError(Lang.EDGE_EXISTS.format(new_id))
        edge = self.edges.pop(old_id)
        edge.name = new_id
        self.edges[new_id] = edge
    
    def remove_edge(self, edge_id:str):
        self.__scc = []
        if not edge_id in self.edges:
            raise ValueError(Lang.EDGE_NOT_FOUND.format(edge_id))
        self.edges.pop(edge_id)
    
    def update_edge(self, edge_id:str, new_from_node_id:str, new_to_node_id:str):
        if not edge_id in self.edges:
            raise ValueError(Lang.EDGE_NOT_FOUND.format(edge_id))
        if new_from_node_id not in self.nodes:
            raise ValueError(Lang.NODE_NOT_FOUND.format(new_from_node_id))
        if new_to_node_id not in self.nodes:
            raise ValueError(Lang.NODE_NOT_FOUND.format(new_to_node_id))
        e = self.edges[edge_id]
        new_from_node = self.nodes[new_from_node_id]
        if e.from_node != new_from_node:
            e.from_node.outgoing_edges.remove(e)
            new_from_node.outgoing_edges.append(e)
            e.from_node = new_from_node
        new_to_node = self.nodes[new_to_node_id]
        if e.to_node != new_to_node:
            e.to_node.incoming_edges.remove(e)
            new_to_node.incoming_edges.append(e)
            e.to_node = new_to_node
    
    def get_offset_shape(self, edge_id:str):
        e = self.get_edge(edge_id)
        start_x, start_y = e.from_node.get_coord()
        end_x, end_y = e.to_node.get_coord()

        # Direction vector
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.hypot(dx, dy)
        if length == 0:
            dir_dx, dir_dy = 1, 0
        else:
            dir_dx = dx / length
            dir_dy = dy / length

        # Perpendicular vector (right side)
        right_dx = dir_dy
        right_dy = -dir_dx

        # Offset along the right side
        minx, miny, maxx, maxy = self.getBoundary()
        offset_px = math.hypot(maxx - minx, maxy - miny) * 1e-3
        start_x += right_dx * offset_px
        start_y += right_dy * offset_px
        end_x += right_dx * offset_px
        end_y += right_dy * offset_px

        return ((start_x, start_y), (end_x, end_y))
    
    @property
    def edge_ids(self):
        return list(self.edges.keys())
    
    @property
    def edge_count(self):
        return len(self.edges)
    
    @staticmethod
    def load_raw(fname:str):
        ret = RoadNet()
        root = ReadXML(fname)
        
        if root is None:
            raise RuntimeError(f"Invalid xml file: {fname}")
        for node in root.findall("node"):
            ret.add_node(
                node_id = node.attrib.pop("id"),
                x = int(float(node.attrib.pop("x", "0"))),
                y = int(float(node.attrib.pop("y", "0"))),
                extras = node.attrib.copy() if len(node.attrib) > 0 else None
            )
        for edge in root.findall("edge"):
            ret.add_edge(
                edge_id = edge.attrib["id"],
                from_node = edge.attrib["from"],
                to_node = edge.attrib["to"],
                length_m = float(edge.attrib["length"]),
                lanes = int(edge.attrib.get("lanes", "1")),
                speed_limit = float(edge.attrib.get("speed", "13.89")),  # Default 50 km/h in m/s
                world_id = int(edge.attrib.get("world_id", "-1")),
                nickname = edge.attrib.get("name", None)
            )
        location = root.find("location")
        if location is not None:
            ret.netOffset = tuple(map(float, location.attrib.get("netOffset", "0,0").split(",")))
            ret.convBoundary = tuple(map(float, location.attrib.get("convBoundary", "0,0,0,0").split(",")))
            ret.origBoundary = tuple(map(float, location.attrib.get("origBoundary", "0,0,0,0").split(",")))
            ret.projParameter = location.attrib.get("projParameter", "!")
        return ret
    
    @staticmethod
    def load_sumo(fname:str, only_passenger:bool=True):
        ret = RoadNet()
        from sumolib.net import readNet, Net
        try:
            r: Net = readNet(fname)
        except Exception as e:
            raise RuntimeError(Lang.INVALID_SUMO_NETWORK.format(fname)) from e
        assert isinstance(r, Net), Lang.INVALID_SUMO_NETWORK.format(fname)
        for node in r.getNodes():
            ret.add_node(
                node_id = node.getID(),
                x = int(node.getCoord()[0]),
                y = int(node.getCoord()[1])
            )
        for edge in r.getEdges():
            if only_passenger and not edge.allows("passenger"): continue
            ret.add_edge(
                edge_id = edge.getID(),
                from_node = edge.getFromNode().getID(),
                to_node = edge.getToNode().getID(),
                length_m = edge.getLength(),
                lanes = edge.getLaneNumber(),
                speed_limit = edge.getSpeed(),
                world_id = -1
            )
        if len(r._location) > 0:
            ret.netOffset = tuple(r.getLocationOffset())
            ret.convBoundary = tuple(r.getBoundary())
            ret.origBoundary = tuple(map(float, r._location["origBoundary"].split(',')))
            ret.projParameter = r._location["projParameter"]
        ret.__sumo = r
        return ret
    
    @staticmethod
    def load(fname:str, fmt:str="auto"):
        if fmt == "raw":
            return RoadNet.load_raw(fname)
        elif fmt == "sumo":
            return RoadNet.load_sumo(fname)
        elif fmt == "auto":
            try:
                return RoadNet.load_sumo(fname)
            except:
                return RoadNet.load_raw(fname)
        else:
            raise ValueError(Lang.UNKNOWN_NET_FORMAT.format(fmt))
    
    def save(self, fname:str):
        root = Element("roadnet", { "v2simfmtver": str(RoadNet.VERSION) })
        def _w(x): return ','.join(map(str, x))
        if self.hasGeoProj():
            root.append(Element("location", {
                "netOffset": _w(self.netOffset),
                "convBoundary": _w(self.convBoundary),
                "origBoundary": _w(self.origBoundary),
                "projParameter": self.projParameter
            }))
        for node in self.nodes.values():
            root.append(Element("node", {
                "id": node.name,
                "x": str(node.x),
                "y": str(node.y)
            }))
        for edge in self.edges.values():
            e = Element("edge", {
                "id": edge.name,
                "from": edge.from_node.name,
                "to": edge.to_node.name,
                "length": str(edge.length),
                "lanes": str(edge.lanes),
                "speed": str(edge.speed_limit),
                "world_id": str(edge.world_id)
            })
            if edge.nickname is not None: e.set("name", edge.nickname)
            root.append(e)
        if fname.lower().endswith(".gz"):
            fname = fname[:-3]
        ElementTree(root).write(fname, encoding="utf-8", xml_declaration=True)

    
    def create_world(self, **kwargs):
        silent = kwargs.pop("silent", False)
        for edge in self.edges.values():
            world_id = edge.world_id
            break
        if all(edge.world_id == world_id for edge in self.edges.values()):
            return self.create_singleworld(**kwargs)
        else:
            if not hasattr(sys, "_is_gil_enabled") or sys._is_gil_enabled(): # type: ignore
                if not silent: print(Lang.GIL_NOT_DISABLED)
                return self.create_singleworld(**kwargs)
            return self.create_paraworlds(**kwargs)

    def get_gl(self) -> Dict[str, List[Tuple[str, Edge]]]:
        gl = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            fr = edge.from_node.name
            to = edge.to_node.name
            gl[fr].append((to, edge))
        return gl

    def create_singleworld(self, **kwargs):
        from .sim.uxsim import World
        from .sim.uxworld import SingleWorld
        from .sim.routing import Graph

        kwargs.pop("silent", None)
        kwargs.pop("name", None)
        kwargs.pop("save_mode", None)
        world = World(name="0", save_mode=0, **kwargs)
           
        gl: Graph = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            fr = edge.from_node.name
            to = edge.to_node.name
            if fr not in world.NODES_NAME_DICT:
                world.addNode(name = fr, x = edge.from_node.x, y = edge.from_node.y)
            if to not in world.NODES_NAME_DICT:
                world.addNode(name = to, x = edge.to_node.x, y = edge.to_node.y)
            link = world.addLink(name = edge.name, start_node = edge.from_node.name, end_node = edge.to_node.name,
                length = edge.length, free_flow_speed = edge.speed_limit, number_of_lanes = edge.lanes)
            gl[fr].append((to, link))
        
        return SingleWorld(world, gl)

    def create_paraworlds(self, **kwargs):
        from .sim.uxsim import World
        from .sim.uxworld import ParaWorlds
        from .sim.routing import Graph

        kwargs.pop("silent", None)
        kwargs.pop("name", None)
        kwargs.pop("print_mode", None)
        kwargs.pop("save_mode", None)

        # Check if all edges do not specify world_id
        if all(edge.world_id == -1 for edge in self.edges.values()):
            for edge in self.edges.values():
                edge.world_id = 0
        
        if any(edge.world_id == -1 for edge in self.edges.values()):
            raise RuntimeError("Some edges do not specify world_id while others do. Please specify world_id for all edges or none.")
        
        worlds:Dict[int, World] = {}
        gl:Graph = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            wid = edge.world_id
            if wid not in worlds:
                worlds[wid] = World(name=str(wid), print_mode=0, save_mode=0, **kwargs)
            W = worlds[wid]
            fr = edge.from_node.name
            to = edge.to_node.name
            if fr not in W.NODES_NAME_DICT:
                W.addNode(name = fr, x = edge.from_node.x, y = edge.from_node.y)
            if to not in W.NODES_NAME_DICT:
                W.addNode(name = to, x = edge.to_node.x, y = edge.to_node.y)
            link = W.addLink(name = edge.name, start_node = fr, end_node = to,
                length = edge.length, free_flow_speed = edge.speed_limit, number_of_lanes = edge.lanes)
            gl[fr].append((to, link))
        
        return ParaWorlds(worlds, gl)

    def hasGeoProj(self):
        return self.projParameter != "!"

    def getGeoProj(self):
        ret = self.getGeoProjOrNone()
        if ret is None:
            raise RuntimeError(Lang.NO_GEO_PROJ)
        return ret
    
    def getGeoProjOrNone(self):
        if not self.hasGeoProj(): return None
        if self._proj is None:
            import pyproj
            try:
                self._proj = pyproj.Proj(projparams=self.projParameter)
            except RuntimeError:
                if hasattr(pyproj.datadir, 'set_data_dir'): # type: ignore
                    pyproj.datadir.set_data_dir('/usr/share/proj') # type: ignore
                    self._proj = pyproj.Proj(projparams=self.projParameter)
                raise
        return self._proj
    
    def getProjectorOrNone(self):
        from fpowerkit import Projector
        if not self.hasGeoProj(): return None
        return Projector(self.projParameter, self.netOffset[0], self.netOffset[1])

    def getLocationOffset(self):
        """ offset to be added after converting from geo-coordinates to UTM"""
        return self.netOffset

    def getBoundary(self):
        """ return xmin,ymin,xmax,ymax network coordinates"""
        if self.convBoundary == (0.,0.,0.,0.):
            all_x = [node.x for node in self.nodes.values()]
            all_y = [node.y for node in self.nodes.values()]
            x_max, x_min = max(all_x), min(all_x)
            y_max, y_min = max(all_y), min(all_y)
            return x_min, y_min, x_max, y_max
        return self.convBoundary

    def convertLonLat2XY(self, lon, lat, rawUTM=False):
        x, y = self.getGeoProj()(lon, lat)
        if rawUTM:
            return x, y
        else:
            x_off, y_off = self.getLocationOffset()
            return x + x_off, y + y_off

    def convertXY2LonLat(self, x, y, rawUTM=False):
        if not rawUTM:
            x_off, y_off = self.getLocationOffset()
            x -= x_off
            y -= y_off
        return self.getGeoProj()(x, y, inverse=True)

    def partition_roadnet(self, num_partitions: int) -> None:
        edge_groups = self._group_reverse_edges()

        partition_assignment = self._geographic_clustering(edge_groups, num_partitions)
        
        for edge_id, partition_id in partition_assignment.items():
            self.edges[edge_id].world_id = partition_id

    def _group_reverse_edges(self) -> List[Set[str]]:
        edge_lookup = {}
        for edge_id, edge in self.edges.items():
            key = (edge.from_node.name, edge.to_node.name)
            edge_lookup[key] = edge_id
        
        visited = set()
        edge_groups = []
        
        for edge_id, edge in self.edges.items():
            if edge_id in visited:
                continue
                
            current_group = {edge_id}
            visited.add(edge_id)
            
            reverse_key = (edge.to_node.name, edge.from_node.name)
            if reverse_key in edge_lookup:
                reverse_edge_id = edge_lookup[reverse_key]
                current_group.add(reverse_edge_id)
                visited.add(reverse_edge_id)
            
            edge_groups.append(current_group)
        
        return edge_groups

    def _geographic_clustering(self, edge_groups: List[Set[str]], num_partitions: int) -> Dict[str, int]:
        group_features = []
        group_edges = []  # 记录每个组包含的边ID
        
        for edge_group in edge_groups:
            # 计算该组所有边的平均坐标
            coords = []
            for edge_id in edge_group:
                edge = self.edges[edge_id]
                # 使用边的中点作为坐标
                mid_x = (edge.from_node.x + edge.to_node.x) / 2
                mid_y = (edge.from_node.y + edge.to_node.y) / 2
                coords.append([mid_x, mid_y])
            
            avg_coord = np.mean(coords, axis=0)
            group_features.append(avg_coord)
            group_edges.append(list(edge_group))
        
        # 使用K-means进行地理聚类
        if len(group_features) <= num_partitions:
            # 如果组数少于分区数，直接分配
            assignment = {}
            for i, edge_group in enumerate(group_edges):
                partition_id = i % num_partitions
                for edge_id in edge_group:
                    assignment[edge_id] = partition_id
        else:
            # 使用K-means聚类
            centroids, distortion = kmeans(group_features, num_partitions, iter=10)
            group_labels, distances = vq(group_features, centroids)
            
            assignment = {}
            for i, (edge_group, label) in enumerate(zip(group_edges, group_labels)):
                for edge_id in edge_group:
                    assignment[edge_id] = label
        
        return assignment

    @property
    def world_count(self):
        world_ids = set(edge.world_id for edge in self.edges.values())
        return len(world_ids) if world_ids else 1
    
    def create_color_map(self):
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        # 获取所有不同的world_id
        world_ids = set(edge.world_id for edge in self.edges.values())
        num_partitions = len(world_ids) if world_ids else 1
        
        # 生成颜色映射
        if num_partitions <= 10:
            colors = list(mcolors.TABLEAU_COLORS.values())[:num_partitions]
        else:
            cmap = plt.cm.get_cmap('tab20', num_partitions)
            colors = [cmap(i) for i in range(num_partitions)]
        colors = [mcolors.to_hex(c) for c in colors]
        
        return {wid: colors[i] for i, wid in enumerate(sorted(world_ids))}

    def plot_roadnet(self, 
            figsize: Tuple[int, int] = (12, 10),
            node_size: int = 50,
            show_nodes: bool = True,
            show_labels: bool = False,
            title: str = "Road Network Partitioning") -> None:
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D

        fig, ax = plt.subplots(figsize=figsize)
        
        # 获取所有node的坐标范围
        x_min, y_min, x_max, y_max = self.getBoundary()

        color_map = self.create_color_map()
        
        # 首先绘制边
        for edge in self.edges.values():
            from_node = edge.from_node
            to_node = edge.to_node
            
            start_x, start_y = from_node.x, from_node.y
            end_x, end_y = to_node.x, to_node.y

            # 计算方向向量
            dx = end_x - start_x
            dy = end_y - start_y
            length = np.sqrt(dx**2 + dy**2)
            if length == 0:
                dir_dx, dir_dy = 1, 0
            else:
                dir_dx = dx / length
                dir_dy = dy / length

            # 计算垂直向量（右侧方向）
            right_dx = dir_dy
            right_dy = -dir_dx

            # 沿右侧偏移
            offset_px = math.hypot(x_max - x_min, y_max - y_min) * 1e-3
            start_x += right_dx * offset_px
            start_y += right_dy * offset_px
            end_x += right_dx * offset_px
            end_y += right_dy * offset_px
            
            # 获取颜色
            color = color_map.get(edge.world_id, 'gray')
            
            lw = min(2, offset_px * 0.02)
            # 绘制边
            ax.plot([start_x, end_x], 
                    [start_y, end_y], 
                    color=color, 
                    linewidth=lw,
                    linestyle='-',
                    alpha=0.8)
            
            # 绘制箭头
            mid_x = (start_x + end_x) / 2
            mid_y = (start_y + end_y) / 2

            arrow_dx = dx * 0.2
            arrow_dy = dy * 0.2
            
            ax.arrow(mid_x - arrow_dx/2, mid_y - arrow_dy/2, 
                    arrow_dx, arrow_dy, width=lw,
                    head_width=lw*5, head_length=lw*3,
                    fc=color, ec=color, alpha=0.8)
        
        # 绘制节点
        if show_nodes:
            node_x = [node.x for node in self.nodes.values()]
            node_y = [node.y for node in self.nodes.values()]
            node_ids = [node.name for node in self.nodes.values()]
            
            ax.scatter(node_x, node_y, s=node_size, c='black', alpha=0.7, zorder=5)
            
            if show_labels:
                for i, node_id in enumerate(node_ids):
                    ax.annotate(node_id, (node_x[i], node_y[i]), 
                            xytext=(5, 5), textcoords='offset points',
                            fontsize=8, alpha=0.8)
        
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        
        # 添加图例
        legend_elements = []
        for wid, color in color_map.items():
            legend_elements.append(Line2D([0], [0], color=color, lw=4, label=f'Partition {wid}'))
        ax.legend(handles=legend_elements, loc='best')
        
        plt.tight_layout()
        plt.savefig("roadnet_partitioned.png", dpi=300)
    
    def remove_items_outside_max_scc(self):
        max_scc = self.scc[0]
        to_remove = []
        for n in self.nodes:
            if n not in max_scc.nodes:
                to_remove.append(n)
        for n in to_remove:
            self.remove_node(n)

        to_remove = []
        for e in self.edges:
            if e not in max_scc.edges:
                to_remove.append(e)
        for e in to_remove:
            self.remove_edge(e)


def ConvertCase(input_dir:str, output_dir:str, part_cnt:int, auto_partition:bool,
            non_passenger_links:bool, non_scc_links:bool):
    """Convert case files in input directory and save to output directory.
    
    Args:
        input_dir: Input directory path.
        output_dir: Output directory path.
        pcnt: Partition count.
        auto_part: Whether to auto determine partition count.
        non_passenger: Whether to include non-passenger links.
        non_scc: Whether to include links and edges not in the largest SCC.
    """
    files = DetectFiles(input_dir)
    converted = False
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if files.net:
        print("Found SUMO network file:", files.net)
        r = RoadNet.load_sumo(files.net, only_passenger=not non_passenger_links)
        if not non_scc_links:
            print("Extracting largest strongly connected component...")
            r.remove_items_outside_max_scc()
        if auto_partition:
            part_cnt = min(32, os.cpu_count() or 1, r.node_count // 40)
            print(f"Auto partition count determined: {part_cnt}")
        if part_cnt > 1:
            print(f"Partitioning network into {part_cnt} parts...")
            r.partition_roadnet(part_cnt)
        r.save(str(out_dir / Path(files.net).name))
        converted = True
    if files.poly:
        print("Found POLY file:", files.poly)
        shutil.copy(files.poly, str(out_dir / Path(files.poly).name))
        converted = True
    if files.cscsv:
        print("Found charging station CSV file:", files.cscsv)
        shutil.copy(files.cscsv, str(out_dir / Path(files.cscsv).name))
        converted = True
    if files.osm:
        print("Found OSM file:", files.osm)
        shutil.copy(files.osm, str(out_dir / Path(files.osm).name))
        converted = True
    if files.grid:
        print("Found power grid file:", files.grid)
        shutil.copy(files.grid, str(out_dir / Path(files.grid).name))
        converted = True
    if files.py:
        print("Found vehicle Python file:", files.py)
        shutil.copy(files.py, str(out_dir / Path(files.py).name))
        converted = True
    if files.pref:
        print("Found vehicle preference file:", files.pref)
        shutil.copy(files.pref, str(out_dir / Path(files.pref).name))
        converted = True
    if files.plg:
        print("Found plugin file:", files.plg)
        shutil.copy(files.plg, str(out_dir / Path(files.plg).name))
        converted = True
    if not converted:
        print("No supported files found in the input directory.")
    return converted


__all__ = ["Node", "Edge", "SubNet", "RoadNet", "ConvertCase"]