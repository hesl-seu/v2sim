import math
import numpy as np
import threading
import sumolib
from typing import Dict, List, Optional, Tuple, Union, Set
from collections import defaultdict
from dataclasses import dataclass, field
from sklearn.neighbors import KDTree
from collections import defaultdict
from ..locale.lang import Lang
from .seg import KDTreeSegmentSearch

def point_to_line_distance(
        point:Tuple[float, float],
        line_start:Tuple[float, float],
        line_end:Tuple[float, float]
    ):
    p = point
    a = line_start
    b = line_end
    
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    
    ab_length_sq = ab[0]**2 + ab[1]**2
    
    if ab_length_sq == 0:
        distance = math.sqrt(ap[0]**2 + ap[1]**2)
        return distance, a
    
    t = (ap[0] * ab[0] + ap[1] * ab[1]) / ab_length_sq
    
    t = max(0, min(1, t))
    
    closest_point = (
        a[0] + t * ab[0],
        a[1] + t * ab[1]
    )
    
    distance = math.sqrt(
        (p[0] - closest_point[0])**2 + 
        (p[1] - closest_point[1])**2
    )
    return distance, closest_point


def _largeStackExec(func, *args):
    import sys
    threading.stack_size(67108864) #64MB
    sys.setrecursionlimit(10**6)
    th = threading.Thread(target=func, args=args)
    th.start()
    th.join()


class Node:
    def __init__(self, node_id:str, x:float, y:float):
        self.id = node_id
        self.x = x
        self.y = y
        self.incoming_edges:List[Edge] = []
        self.outgoing_edges:List[Edge] = []
    
    def get_coord(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Edge:
    id: str
    from_node: Node
    to_node: Node
    length: float # in meters
    lanes: int = 1
    speed_limit: float = 13.89  # Default 50 km/h in m/s
    world_id: int = -1
    
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
        self.__edgeL:List[Edge] = []
        self.edges:Dict[str, Edge] = {}
        self.__scc:List[SubNet] = []
        self.__kdt:Optional[KDTreeSegmentSearch] = None
        self._proj = None
        self.netOffset = (0.,0.)
        self.convBoundary = (0.,0.,0.,0.)
        self.origBoundary = (0.,0.,0.,0.)
        self.projParameter = "!"
        self.__sumo:Optional[sumolib.net.Net] = None
    
    @property
    def sumo(self) -> 'sumolib.net.Net':
        assert self.__sumo is not None, "Sumo network not loaded."
        return self.__sumo
    
    def calc_kdtree(self):
        """
        Calculate the KDTree of the road network nodes for fast nearest neighbor search.
        """
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
        self.__kdt = KDTreeSegmentSearch(np.array(segs))

    @property
    def kdtree(self):
        if self.__kdt is None:
            self.calc_kdtree()
        assert self.__kdt is not None
        return self.__kdt
    
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
        i, dist, _ = self.kdtree.find_closest_segment(np.array([x, y]))
        return dist, self.__edgeL[i].id
    
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
        Calculate strongly connected components (SCCs) of the road network.
        Returns a set of node and edge IDs in SCC.
        """
        nodes = list(self.nodes.values())
        nmp = {node.id: i for i, node in enumerate(nodes)}
        tscc = _TarjanSCC(n=self.node_count, gl={
            i: [nmp[e.to_node.id] for e in nodes[i].outgoing_edges if self.allows_passengers(e.id)] 
            for i in range(len(self.nodes))
        })
        _largeStackExec(tscc.calc_scc)
        
        assert tscc.scc is not None

        sccidx_of_nodes = {}
        for i, node_ids in enumerate(tscc.scc):
            for nid in node_ids:
                sccidx_of_nodes[nid] = i
        
        scc_tmp = {
            i: SubNet(nodes = {nodes[j].id for j in node_ids}) 
            for i, node_ids in enumerate(tscc.scc)
        }
        for edge in self.edges.values():
            if not self.allows_passengers(edge.id): continue
            if sccidx_of_nodes[nmp[edge.from_node.id]] == sccidx_of_nodes[nmp[edge.to_node.id]]:
                scc_tmp[sccidx_of_nodes[nmp[edge.from_node.id]]].edges.add(edge.id)
            
        self.__scc = list(scc_tmp.values())
        return self.__scc
    
    @property
    def scc(self) -> List[SubNet]:
        if len(self.__scc) == 0:
            self.calc_max_scc()
        return self.__scc

    def add_node(self, node_id:str, x:int, y:int) -> Node:
        self.__scc = []
        self.__kdt = None
        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists.")
        node = Node(node_id, x, y)
        self.nodes[node_id] = node
        return node
    
    def get_node(self, node_id:str) -> Node:
        return self.nodes[node_id]
    
    def rename_node(self, old_id:str, new_id:str):
        if new_id in self.nodes:
            raise ValueError(f"Node {new_id} already exists.")
        node = self.nodes.pop(old_id)
        for edge in node.incoming_edges:
            edge.to_node = node
        for edge in node.outgoing_edges:
            edge.from_node = node
        node.id = new_id
        self.nodes[new_id] = node
    
    def remove_node(self, node_id:str):
        self.__scc = []
        self.__kdt = None
        if not node_id in self.nodes:
            raise ValueError(f"Node {node_id} does not exist.")
        node = self.nodes.pop(node_id)
        enames = list(self.edges.keys())
        for e in enames:
            edge = self.edges[e]
            if edge.from_node == node or edge.to_node == node:
                self.remove_edge(e)
    
    def update_node(self, old_node_id:str, new_node_id:str):
        if not old_node_id in self.nodes:
            raise ValueError(f"Node {old_node_id} does not exist.")
        if new_node_id in self.nodes:
            raise ValueError(f"Node {new_node_id} already exists.")
        node = self.nodes.pop(old_node_id)
        node.id = new_node_id
        self.nodes[new_node_id] = node
        
    @property
    def node_ids(self):
        return list(self.nodes.keys())
    
    @property
    def node_count(self):
        return len(self.nodes)
    
    def add_edge(self, edge_id:str, from_node:Union[str, Node], to_node:Union[str, Node], 
            length_m:float, lanes:int, speed_limit:float, world_id:int = -1) -> Edge:
        self.__scc = []
        if edge_id in self.edges:
            raise ValueError(f"Edge {edge_id} already exists.")
        if isinstance(from_node, str): from_node = self.get_node(from_node)
        if isinstance(to_node, str): to_node = self.get_node(to_node)
        edge = Edge(edge_id, from_node, to_node, length_m, lanes, speed_limit, world_id)
        self.edges[edge_id] = edge
        from_node.outgoing_edges.append(edge)
        to_node.incoming_edges.append(edge)
        return edge
    
    def get_edge(self, edge_id:str) -> Edge:
        return self.edges[edge_id]
    
    def rename_edge(self, old_id:str, new_id:str):
        if new_id in self.edges:
            raise ValueError(f"Edge {new_id} already exists.")
        edge = self.edges.pop(old_id)
        edge.id = new_id
        self.edges[new_id] = edge
    
    def remove_edge(self, edge_id:str):
        self.__scc = []
        if not edge_id in self.edges:
            raise ValueError(f"Edge {edge_id} does not exist.")
        self.edges.pop(edge_id)
    
    def update_edge(self, edge_id:str, new_from_node_id:str, new_to_node_id:str):
        if not edge_id in self.edges:
            raise ValueError(f"Edge {edge_id} does not exist.")
        if new_from_node_id not in self.nodes:
            raise ValueError(f"New from node {new_from_node_id} does not exist.")
        if new_to_node_id not in self.nodes:
            raise ValueError(f"New to node {new_to_node_id} does not exist.")
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
    
    @property
    def edge_ids(self):
        return list(self.edges.keys())
    
    @property
    def edge_count(self):
        return len(self.edges)
    
    @staticmethod
    def load(fname:str):
        ret = RoadNet()
        from sumolib.net import readNet, Net
        r: Net = readNet(fname)
        assert isinstance(r, Net), f"Invalid sumo network: {fname}"
        for node in r.getNodes():
            ret.add_node(
                node_id = node.getID(),
                x = int(node.getCoord()[0]),
                y = int(node.getCoord()[1])
            )
        for edge in r.getEdges():
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

__all__ = ["Node", "Edge", "SubNet", "RoadNet"]