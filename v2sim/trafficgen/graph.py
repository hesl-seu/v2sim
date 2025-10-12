from typing import DefaultDict, List, Dict, Set, Tuple
import threading
from feasytools import Point, KDTree
import matplotlib
matplotlib.use('Agg')
from ..locale import Lang
from ..traffic import LoadFCS, LoadSCS
from ..traffic.net import *

def _largeStackExec(func, *args):
    import sys
    threading.stack_size(67108864) #64MB
    sys.setrecursionlimit(10**6)
    th = threading.Thread(target=func, args=args)
    th.start()
    th.join()

class _TarjanSCC:
    def __init__(self, n:int, gl:List[List[int]]):
        self.dfn: List[int] = [0] * n
        self.low: List[int] = [0] * n
        self.dfncnt = 0

        self.scc: List[int] = [0] * n
        self.sc = 0

        self.stack: List[int] = []
        self.in_stack: set[int] = set()
        self.gl = gl
        self.max_scc = None
    
    def __tarjan(self, u: int):
        self.dfncnt += 1
        self.low[u] = self.dfn[u] = self.dfncnt
        self.stack.append(u)
        self.in_stack.add(u)
        for v in self.gl[u]:
            if self.dfn[v] == 0:
                self.__tarjan(v)
                self.low[u] = min(self.low[u], self.low[v])
            elif v in self.in_stack:
                self.low[u] = min(self.low[u], self.dfn[v])
        if self.low[u] == self.dfn[u]:
            self.sc += 1
            while True:
                v = self.stack.pop()
                self.in_stack.remove(v)
                self.scc[v] = self.sc
                if v == u:
                    break
    
    def get_scc(self):
        n = len(self.gl)
        for u in range(n):
            if self.low[u] == 0:
                self.__tarjan(u)
        
        scc_dict: Dict[int, List[int]] = DefaultDict(list)
        for i,x in enumerate(self.scc):
            scc_dict[x].append(i)
        
        max_scc_key = max(scc_dict, key=lambda x: len(scc_dict[x]))
        self.max_scc = scc_dict[max_scc_key]

        return self.max_scc
  
class RoadNetConnectivityChecker:
    '''
    A class to represent the graph of the road network.
    The graph is represented as a list of edges.
    The edges are the largest strongly connected component of the road network.
    CS edges that are not in the largest strongly connected component are also stored.
    '''
    def __init__(self, net_file:str, fcs_file:str="", scs_file:str=""):
        self._net = RoadNet.load(net_file)
        self._fcs_names = set() if fcs_file == "" else LoadFCS(fcs_file)
        self._scs_names = set() if scs_file == "" else LoadSCS(scs_file)
        self._cs_names = self._fcs_names.union(self._scs_names)
        self.all_nodeIDs:List[str] = list(self._net.nodes.keys())
        self._id2num:Dict[str, int] = {e:i for i,e in enumerate(self.all_nodeIDs)}
        gl:List[List[int]] = [[] for _ in range(len(self.all_nodeIDs))]
        for nd in self._net.nodes.values():
            u = self._id2num[nd.id]
            gl[u] = [self._id2num[neighbor.to_node.id] for neighbor in nd.outgoing_edges]

        tscc = _TarjanSCC(n=len(self.all_nodeIDs), gl=gl)
        _largeStackExec(tscc.get_scc)
        assert tscc.max_scc is not None

        self.nodeIDs:List[str] = [self.all_nodeIDs[x] for x in tscc.max_scc]
        self.nodes:List[Node] = [self._net.get_node(nd) for nd in self.nodeIDs]
        
        self.nodeIDset:Set[str] = set(self.nodeIDs)
        bad_fcs:Set[str] = set()
        bad_scs:Set[str] = set()
        for node_id in self.all_nodeIDs:
            if node_id in self._fcs_names and node_id not in self.nodeIDset:
                bad_fcs.add(node_id)
            if node_id in self._scs_names and node_id not in self.nodeIDset:
                bad_scs.add(node_id)
        self.unreachable_CS = bad_fcs.union(bad_scs)

        self.__node_finder = KDTree(
            points=[Point(*self.get_node_pos(nd.id)) for nd in self._net.nodes.values()],
            labels=[nd.id for nd in self._net.nodes.values()]
        )

    def checkBadCS(self, display:bool = True) -> bool:
        '''Check if there are any CS nodes that are not in the largest strongly connected component'''
        if len(self.unreachable_CS) > 0:
            if display: print(Lang.WARN_CS_NOT_IN_SCC.format(self.unreachable_CS))
            return False
        return True

    def checkSCCSize(self, display:bool = True) -> bool:
        '''Check if the size of the largest strongly connected component is large enough'''
        if len(self.nodeIDs) < 0.8 * len(self.all_nodeIDs):
            if display: print(Lang.WARN_SCC_TOO_SMALL.format(len(self.nodeIDs), len(self.all_nodeIDs)))
            return False
        return True
    
    def find_nearest_node_id(self, point: Point, threshold_m:float=1000) -> str:
        '''
        Find the nearest node ID to the given point.
        If the distance is greater than threshold_m, raise a RuntimeError.
        '''
        ret = self.__node_finder.nearest_mapped_with_distance(point)
        if ret is None:
            raise RuntimeError("No node found")
        node_id, dist = ret
        if dist > threshold_m:
            raise RuntimeError(str(dist))
        return node_id
    
    def get_node_pos(self, node:str):
        '''
        Get the position of the node in the road network.
        The position is the average of the shape of the node.
        '''
        nd:Node = self._net.get_node(node)
        return (nd.x, nd.y)
    
    @property
    def FCSNames(self) -> Set[str]:
        '''Return the set of FCS node names'''
        return self._fcs_names
    
    @property
    def SCSNames(self) -> Set[str]:
        '''Return the set of SCS node names'''
        return self._scs_names

    @property
    def CSNames(self) -> Set[str]:
        '''Return the set of CS node names'''
        return self._cs_names
    
    @property
    def Net(self):
        '''Return the road network'''
        return self._net
    
    @property
    def NodeIDs(self):
        '''List of node IDs in the largest strongly connected component'''
        return self.nodeIDs

    @property
    def NodeIDSet(self):
        '''List of node IDs in the largest strongly connected component'''
        return self.nodeIDset
    
    @property
    def AllNodeIDs(self):
        '''List of all node IDs in the road network'''
        return self.all_nodeIDs
    
    @property
    def Nodes(self):
        '''List of nodes in the largest strongly connected component'''
        return self.nodes
    
    @property
    def AllNodes(self):
        '''List of all nodes in the road network'''
        return list(self._net.nodes.values())

    @property
    def BadCS(self):
        '''CS nodes that are not in the largest strongly connected component'''
        return self.unreachable_CS

PointList = List[Tuple[float, float]]