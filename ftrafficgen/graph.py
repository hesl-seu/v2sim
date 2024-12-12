from typing import DefaultDict, List, Dict
import threading
from ftraffic.utils import load_fcs, load_scs
import sumolib
from flocale import Lang
from ftraffic.geo import EdgeFinder, Point
import matplotlib
matplotlib.use('Agg')
from matplotlib.axes import Axes
import matplotlib.pyplot as plt
Net = sumolib.net.Net
Edge = sumolib.net.edge.Edge
Node = sumolib.net.node.Node
Conn = sumolib.net.connection.Connection

def _largeStackExec(func, *args):
    import sys
    threading.stack_size(67108864) #64MB
    sys.setrecursionlimit(10**6)
    th = threading.Thread(target=func, args=args)
    th.start()
    th.join()

class _TarjanSCC:
    def __init__(self, n:int, gl:list[list[int]]):
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
  
class ELGraph:
    '''
    A class to represent the graph of the road network.
    The graph is represented as a list of edges.
    The edges are the largest strongly connected component of the road network.
    CS edges that are not in the largest strongly connected component are also stored.
    '''
    def __init__(self, net_file:str, cs_file:str=""):
        self.net:Net = sumolib.net.readNet(net_file)
        if cs_file == "":
            self.cs_names = set()
        else:
            self.cs_names = load_fcs(cs_file)
        self.all_edges:List[Edge] = self.net.getEdges()
        self.all_edgeIDs:List[str] = [e.getID() for e in self.all_edges]
        self._id2num:dict[str, int] = {e:i for i,e in enumerate(self.all_edgeIDs)}
        gl:list[list[int]] = [[] for _ in range(len(self.all_edges))]
        for e in self.all_edges:
            e: Edge
            if not e.allows("passenger"): continue
            ret: dict[Edge, List[Conn]] = e.getAllowedOutgoing("passenger")
            u = self._id2num[e.getID()]
            gl[u] = [self._id2num[edge.getID()] for edge in ret.keys()]
        
        tscc = _TarjanSCC(n=len(self.all_edges), gl=gl)
        _largeStackExec(tscc.get_scc)
        assert tscc.max_scc is not None
        self.edgeIDs:List[str] = [self.all_edgeIDs[x] for x in tscc.max_scc]
        self.edges:List[Edge] = [self.net.getEdge(e) for e in self.edgeIDs]
        
        edgenames = set(self.edgeIDs)
        bad_CS:set[str] = set()
        for e in self.net.getEdges():
            eid:str = e.getID()
            if eid in self.cs_names and eid not in edgenames:
                bad_CS.add(eid)
        self.unreachable_CS = bad_CS

        self.__edge_finder = EdgeFinder({e.getID():e.getShape() for e in self.edges}) # type: ignore
    
    def checkBadCS(self, display:bool = True) -> bool:
        if len(self.unreachable_CS) > 0:
            if display: print(Lang.WARN_CS_NOT_IN_SCC.format(self.unreachable_CS))
            return False
        return True

    def checkSCCSize(self, display:bool = True) -> bool:
        if len(self.edgeIDs) < 0.8 * len(self.all_edges):
            if display: print(Lang.WARN_SCC_TOO_SMALL.format(len(self.edgeIDs), len(self.all_edges)))
            return False
        return True
    
    def find_nearest_edge_id(self, point: Point, threshold_m:float=1000) -> str:
        dist, edge_id = self.__edge_finder.find_nearest_edge(point)
        if dist > threshold_m:
            raise RuntimeError(str(dist))
        return edge_id
    
    @property
    def EdgeIDs(self):
        '''List of edge IDs in the largest strongly connected component'''
        return self.edgeIDs
    
    @property
    def AllEdgeIDs(self):
        '''List of all edge IDs in the road network'''
        return self.all_edgeIDs
    
    @property
    def Edges(self):
        '''List of edges in the largest strongly connected component'''
        return self.edges
    
    @property
    def AllEdges(self):
        '''List of all edges in the road network'''
        return self.all_edges
    
    @property
    def BadCS(self):
        '''CS edges that are not in the largest strongly connected component'''
        return self.unreachable_CS

PointList = list[tuple[float, float]]

def plot_graph(input_dir:str, elg:ELGraph, locate_edges:List[str] = [], route_edges:List[str] = [], mid_edges:List[str] = []):
    sccedges = set(elg.EdgeIDs)
    fig,ax = plt.subplots(figsize=(10,10),dpi=128,constrained_layout=True)
    ax: Axes
    for e in elg.net.getEdges():
        e: Edge
        ename:str = e.getID()
        shape:PointList = e.getShape() # type: ignore
        if ename in elg.cs_names:
            c = "darkblue" if ename in sccedges else "darkgray"
            lw = 2
        else:
            c = "blue" if ename in sccedges else "gray"
            lw = 0.5
        if ename in locate_edges:
            c = "green"
            lw = 3
        if ename in route_edges:
            c = "red"
            lw = 3
        elif ename in mid_edges:
            c = "magenta"
            lw = 3
        ax.plot([p[0] for p in shape],[p[1] for p in shape],color=c,linewidth=lw)
    ax.title.set_text("SCC Detection")
    xmin,xmax = ax.get_xlim()
    ymin,ymax = ax.get_ylim()
    ax.annotate("Blue=Edge in SCC, Gray=Edge not in SCC, DarkBlue=FCS in SCC, DarkGray=FCS not in SCC\n" +
                "LightGreen=Located Edge, Red=Route End Edge, Magenta=Route Mid Edge",
        (xmin+(xmax-xmin)*0.01,ymin+(ymax-ymin)*0.01),fontsize=12,ha="left",va="bottom",transform=ax)
    fig.savefig(f"{input_dir}/graph_helper.png")
    plt.close(fig)