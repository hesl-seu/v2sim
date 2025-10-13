import math
import sys
import numpy as np
import threading
from typing import Dict, List, Optional, Tuple, Union, Set
from xml.etree.ElementTree import ElementTree
from collections import defaultdict
from dataclasses import dataclass, field
from sklearn.cluster import KMeans
from sklearn.neighbors import KDTree
from collections import defaultdict
from ..locale.lang import Lang


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
        self.__nodeL:List[Node] = []
        self.edges:Dict[str, Edge] = {}
        self.__scc:List[SubNet] = []
        self.__kdt:Optional[KDTree] = None
        self._proj = None
        self.netOffset = (0.,0.)
        self.convBoundary = (0.,0.,0.,0.)
        self.origBoundary = (0.,0.,0.,0.)
        self.projParameter = "!"
    
    def calc_kdtree(self):
        """
        Calculate the KDTree of the road network nodes for fast nearest neighbor search.
        """
        self.__nodeL = list(self.nodes.values())
        coords = np.array([node.get_coord() for node in self.__nodeL])
        self.__kdt = KDTree(coords, metric='euclidean')

    @property
    def kdtree(self) -> KDTree:
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
    
    def find_nearest_node(self, x:float, y:float) -> Node:
        """
        Find the nearest node to the given coordinates.
        """
        dist, idx = self.kdtree.query([[x, y]], k=1)
        return self.__nodeL[idx[0][0]]
    
    def find_nearest_node_with_distance(self, x:float, y:float) -> Tuple[float, Node]:
        """
        Find the nearest node to the given coordinates.
        """
        dist, idx = self.kdtree.query([[x, y]], k=1)
        return dist[0][0], self.__nodeL[idx[0][0]]
    
    def calc_max_scc(self):
        """
        Calculate the largest strongly connected component (SCC) of the road network.
        Returns a set of node IDs in the largest SCC.
        """
        nodes = list(self.nodes.values())
        nmp = {node.id: i for i, node in enumerate(nodes)}
        tscc = _TarjanSCC(n=self.node_count, gl={
            i: [nmp[e.to_node.id] for e in nodes[i].outgoing_edges] 
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
    
    def get_offset_shape(self, edge_id:str):
        e = self.get_edge(edge_id)
        start_x, start_y = e.from_node.get_coord()
        end_x, end_y = e.to_node.get_coord()

        # 计算方向向量
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.hypot(dx, dy)
        if length == 0:
            dir_dx, dir_dy = 1, 0
        else:
            dir_dx = dx / length
            dir_dy = dy / length

        # 计算垂直向量（右侧方向）
        right_dx = dir_dy
        right_dy = -dir_dx

        # 沿右侧偏移
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
        root = ElementTree(file = fname).getroot()
        
        if root is None:
            raise RuntimeError(f"Invalid xml file: {fname}")
        for node in root.findall("node"):
            ret.add_node(
                node_id = node.attrib["id"],
                x = int(float(node.attrib.get("x", "0"))),
                y = int(float(node.attrib.get("y", "0")))
            )
        for edge in root.findall("edge"):
            ret.add_edge(
                edge_id = edge.attrib["id"],
                from_node = edge.attrib["from"],
                to_node = edge.attrib["to"],
                length_m = float(edge.attrib["length"]),
                lanes = int(edge.attrib.get("lanes", "1")),
                speed_limit = float(edge.attrib.get("speed", "13.89")),  # Default 50 km/h in m/s
                world_id = int(edge.attrib.get("world_id", "-1"))
            )
        location = root.find("location")
        if location is not None:
            ret.netOffset = tuple(map(float, location.attrib.get("netOffset", "0,0").split(",")))
            ret.convBoundary = tuple(map(float, location.attrib.get("convBoundary", "0,0,0,0").split(",")))
            ret.origBoundary = tuple(map(float, location.attrib.get("origBoundary", "0,0,0,0").split(",")))
            ret.projParameter = location.attrib.get("projParameter", "!")
        return ret
    
    @staticmethod
    def load_sumo(fname:str):
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
            raise ValueError(f"Unknown format: {fmt}. Candidates: raw, sumo, auto")
    
    def save(self, fname:str):
        if fname.lower().endswith(".gz"):
            import gzip
            f = gzip.open(fname, "wt")
        else:
            f = open(fname, "w")
        f.write(f'<roadnet v2simfmtver="{RoadNet.VERSION}">\n')
        def _w(x): return ','.join(map(str, x))
        if self.hasGeoProj():
            f.write(f'  <location netOffset="{_w(self.netOffset)}" convBoundary="{_w(self.convBoundary)}" origBoundary="{_w(self.origBoundary)}" projParameter="{self.projParameter}"/>')
        for node in self.nodes.values():
            f.write(f'  <node id="{node.id}" x="{node.x}" y="{node.y}"/>\n')
        for edge in self.edges.values():
            f.write(f'  <edge id="{edge.id}" from="{edge.from_node.id}" to="{edge.to_node.id}" length="{edge.length}" lanes="{edge.lanes}" speed="{edge.speed_limit}" world_id="{edge.world_id}"/>\n')
        f.write("</roadnet>\n")
        f.close()
    
    def create_world(self, **kwargs):
        for edge in self.edges.values():
            world_id = edge.world_id
            break
        if all(edge.world_id == world_id for edge in self.edges.values()):
            return self.create_singleworld(**kwargs)
        else:
            if not hasattr(sys, "_is_gil_enabled") or sys._is_gil_enabled(): # type: ignore
                print("Warning: ParaWorlds requires Python to be built with GIL disabled. Falling back to SingleWorld.")
                return self.create_singleworld(**kwargs)
            return self.create_paraworlds(**kwargs)

    def create_singleworld(self, **kwargs):
        from uxsim import World
        from .paraworlds import SingleWorld
        from .routing import Graph

        kwargs.pop("name", None)
        kwargs.pop("save_mode", None)
        world = World(name="0", save_mode=0, **kwargs)
           
        gl:Graph = {nid: [] for nid in self.nodes}
        for edge in self.edges.values():
            fr = edge.from_node.id
            to = edge.to_node.id
            if fr not in world.NODES_NAME_DICT:
                world.addNode(name = fr, x = edge.from_node.x, y = edge.from_node.y)
            if to not in world.NODES_NAME_DICT:
                world.addNode(name = to, x = edge.to_node.x, y = edge.to_node.y)
            link = world.addLink(name = edge.id, start_node = edge.from_node.id, end_node = edge.to_node.id,
                length = edge.length, free_flow_speed = edge.speed_limit, number_of_lanes = edge.lanes)
            gl[fr].append((to, link))
        
        return SingleWorld(world, gl)

    def create_paraworlds(self, **kwargs):
        from uxsim import World
        from .paraworlds import ParaWorlds
        from .routing import Graph

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
            fr = edge.from_node.id
            to = edge.to_node.id
            if fr not in W.NODES_NAME_DICT:
                W.addNode(name = fr, x = edge.from_node.x, y = edge.from_node.y)
            if to not in W.NODES_NAME_DICT:
                W.addNode(name = to, x = edge.to_node.x, y = edge.to_node.y)
            link = W.addLink(name = edge.id, start_node = fr, end_node = to,
                length = edge.length, free_flow_speed = edge.speed_limit, number_of_lanes = edge.lanes)
            gl[fr].append((to, link))
        
        return ParaWorlds(worlds, gl)

    def hasGeoProj(self):
        return self.projParameter != "!"

    def getGeoProj(self):
        if not self.hasGeoProj():
            raise RuntimeError("Network does not provide geo-projection")
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
        # 步骤1: 识别并分组反向边
        edge_groups = self._group_reverse_edges()

        # 步骤2: 基于地理坐标聚类
        partition_assignment = self._geographic_clustering(edge_groups, num_partitions)
        
        # 步骤3: 分配world_id
        for edge_id, partition_id in partition_assignment.items():
            self.edges[edge_id].world_id = partition_id
        
        # 步骤4: 打印统计信息
        self._print_partition_stats()

    def _group_reverse_edges(self) -> List[Set[str]]:
        """
        识别并分组反向边，确保每对反向边在同一组
        """
        # 构建边查找字典: (from_id, to_id) -> edge_id
        edge_lookup = {}
        for edge_id, edge in self.edges.items():
            key = (edge.from_node.id, edge.to_node.id)
            edge_lookup[key] = edge_id
        
        # 分组反向边
        visited = set()
        edge_groups = []
        
        for edge_id, edge in self.edges.items():
            if edge_id in visited:
                continue
                
            current_group = {edge_id}
            visited.add(edge_id)
            
            # 查找反向边
            reverse_key = (edge.to_node.id, edge.from_node.id)
            if reverse_key in edge_lookup:
                reverse_edge_id = edge_lookup[reverse_key]
                current_group.add(reverse_edge_id)
                visited.add(reverse_edge_id)
            
            edge_groups.append(current_group)
        
        return edge_groups

    def _geographic_clustering(self, edge_groups: List[Set[str]], num_partitions: int) -> Dict[str, int]:
        """
        基于地理坐标进行聚类分区
        """
        # 为每个边组计算代表性坐标（中点坐标）
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
            kmeans = KMeans(n_clusters=num_partitions, random_state=42, n_init=10)
            group_labels = kmeans.fit_predict(group_features)
            
            assignment = {}
            for i, (edge_group, label) in enumerate(zip(group_edges, group_labels)):
                for edge_id in edge_group:
                    assignment[edge_id] = label
        
        return assignment

    def _print_partition_stats(self):
        """打印分区统计信息"""
        stats_edges = defaultdict(int)
        stats_nodes = defaultdict(set)
        reverse_edge_pairs = defaultdict(float)
        
        # 构建反向边查找
        reverse_lookup = {}
        for edge in self.edges.values():
            key = (edge.from_node.id, edge.to_node.id)
            reverse_lookup[key] = edge
        
        # 统计
        for edge in self.edges.values():
            wid = edge.world_id
            stats_edges[wid] += 1
            stats_nodes[wid].add(edge.from_node.id)
            stats_nodes[wid].add(edge.to_node.id)
            
            # 检查反向边是否在同一分区
            reverse_key = (edge.to_node.id, edge.from_node.id)
            if reverse_key in reverse_lookup:
                reverse_edge = reverse_lookup[reverse_key]
                if edge.world_id == reverse_edge.world_id:
                    reverse_edge_pairs[wid] += 0.5  # 每对计数一次
        
        print("\n改进分区算法统计:")
        print("World ID | 边数 | 节点数 | 反向边对数")
        print("-" * 40)
        total_edges = 0
        for wid in sorted(stats_edges.keys()):
            reverse_pairs = int(reverse_edge_pairs[wid])
            print(f"{wid:8} | {stats_edges[wid]:4} | {len(stats_nodes[wid]):6} | {reverse_pairs:10}")
            total_edges += stats_edges[wid]
        
        print(f"\n总共 {total_edges} 条边，{len(self.nodes)} 个节点")

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
            node_ids = [node.id for node in self.nodes.values()]
            
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
        
        # 打印统计
        self._print_partition_stats()

__all__ = ["Node", "Edge", "SubNet", "RoadNet"]