from dataclasses import dataclass
from typing import Callable, List, Dict, Tuple, Set
from sklearn.neighbors import KDTree
from uxsim import Link
import heapq
import math


@dataclass
class Stage:
    nodes: List[str]
    edges: List[str]
    travelTime: float
    length: float

CoordsDict = Dict[str, Tuple[float, float]]  # node ID -> (x, y)
Graph = Dict[str, List[Tuple[str, Link]]]  # node ID -> List of (to_node ID, Link object)


def dijMC(gl: Graph, ctime: int, from_node: str, to_nodes: Set[str], omega: float, 
          to_charge: float, wt: Dict[str, float], p: Dict[str, float], 
          max_length: float = float('inf')) -> Stage:
    """
    Find the BEST route based on score = omega * (time + waiting) + charging_cost.
    Uses time as primary key, length as secondary key.
    """
    # (time, length, node, path, path_edges)
    heap = [(0, 0, from_node, [from_node], [])]
    visited = set()
    min_time = {from_node: 0}
    best_score = float('inf')
    best_stage = Stage([], [], float('inf'), float('inf'))
    
    while heap:
        cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
        visited.add(cur_node)
        
        # 检查是否到达目标节点且满足长度约束
        if cur_node in to_nodes and cur_len <= max_length:
            score = omega * (cur_time / 60.0 + wt[cur_node]) + to_charge * p[cur_node]
            if score < best_score:
                best_score = score
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)
        
        # 探索邻居节点
        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            next_time = cur_time + link.instant_travel_time(ctime)
            next_len = cur_len + link.length
            
            if next_len > max_length:
                continue
                
            if neighbor not in min_time or next_time < min_time[neighbor]:
                min_time[neighbor] = next_time
                heapq.heappush(heap, (next_time, next_len, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return best_stage

def dijMF(gl: Graph, ctime: int, from_node: str, to_nodes: Set[str]) -> Stage:
    """
    Find the FASTEST route to any node in to_nodes.
    Uses time as primary key, length as secondary key.
    """
    # (time, length, node, path, path_edges)
    heap = [(0, 0, from_node, [from_node], [])]
    visited = set()
    min_time = {from_node: 0}
    best_stage = Stage([], [], float('inf'), float('inf'))
    
    while heap:
        cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)

        if cur_node in visited:
            continue
        visited.add(cur_node)
        
        if cur_node in to_nodes:
            if cur_time < best_stage.travelTime:
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)
        
        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            next_time = cur_time + link.instant_travel_time(ctime)
            next_len = cur_len + link.length
            
            if neighbor not in min_time or next_time < min_time[neighbor]:
                min_time[neighbor] = next_time
                heapq.heappush(heap, (next_time, next_len, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return best_stage

def dijMS(gl: Graph, ctime: int, from_node: str, to_nodes: Set[str]) -> Stage:
    """
    Find the SHORTEST route to any node in to_nodes.
    Uses length as primary key, time as secondary key.
    """
    # (length, time, node, path, path_edges)
    heap = [(0, 0, from_node, [from_node], [])]
    visited = set()
    min_length = {from_node: 0}
    best_stage = Stage([], [],float('inf'), float('inf'))
    
    while heap:
        cur_len, cur_time, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
        visited.add(cur_node)
        
        if cur_node in to_nodes:
            if cur_len < best_stage.length:
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)

        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            next_len = cur_len + link.length
            next_time = cur_time + link.instant_travel_time(ctime)
            
            if neighbor not in min_length or next_len < min_length[neighbor]:
                min_length[neighbor] = next_len
                heapq.heappush(heap, (next_len, next_time, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return best_stage

def dijF(gl: Graph, ctime: int, from_node: str, to_node: str) -> Stage:
    """Fastest path between two specific nodes."""
    return dijMF(gl, ctime, from_node, {to_node})

def dijS(gl: Graph, ctime: int, from_node: str, to_node: str) -> Stage:
    """Shortest path between two specific nodes."""
    return dijMS(gl, ctime, from_node, {to_node})

def astarF(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_node: str) -> Stage:
    """
    A* algorithm for FASTEST path using time as cost.
    Uses f_score (time + heuristic) as primary key, time as secondary key, length as tertiary key.
    """
    to_coord = node_coords[to_node]
    
    def heuristic(node):
        coord = node_coords[node]
        return math.hypot(coord[0] - to_coord[0], coord[1] - to_coord[1])
    
    heap = []
    initial_h = heuristic(from_node)
    # (f_score, time, length, node, path, path_edges)
    heapq.heappush(heap, (initial_h, 0, 0, from_node, [from_node], []))
    
    visited = set()
    g_scores = {from_node: 0}  # g_score = actual travel time
    
    while heap:
        f_score, cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
            
        if cur_node == to_node:
            return Stage(path, path_edges, cur_time, cur_len)
            
        visited.add(cur_node)

        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            time_cost = link.instant_travel_time(ctime)
            next_time = cur_time + time_cost
            next_len = cur_len + link.length
            
            if neighbor not in g_scores or next_time < g_scores[neighbor]:
                g_scores[neighbor] = next_time
                h_score = heuristic(neighbor)
                f_score = next_time + h_score
                
                heapq.heappush(heap, (f_score, next_time, next_len, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return Stage([], [], float('inf'), float('inf'))

def astarS(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_node: str) -> Stage:
    """
    A* algorithm for SHORTEST path using length as cost.
    Uses f_score (length + heuristic) as primary key, length as secondary key, time as tertiary key.
    """
    to_coord = node_coords[to_node]
    
    def heuristic(node):
        coord = node_coords[node]
        return math.hypot(coord[0] - to_coord[0], coord[1] - to_coord[1])
    
    heap = []
    initial_h = heuristic(from_node)
    # (f_score, length, time, node, path, path_edges)
    heapq.heappush(heap, (initial_h, 0, 0, from_node, [from_node], []))
    
    visited = set()
    g_scores = {from_node: 0}  # g_score = actual path length
    
    while heap:
        f_score, cur_len, cur_time, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
            
        if cur_node == to_node:
            return Stage(path, path_edges, cur_time, cur_len)
            
        visited.add(cur_node)
        
        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            length_cost = link.length
            next_len = cur_len + length_cost
            next_time = cur_time + link.instant_travel_time(ctime)
            
            if neighbor not in g_scores or next_len < g_scores[neighbor]:
                g_scores[neighbor] = next_len
                h_score = heuristic(neighbor)
                f_score = next_len + h_score

                heapq.heappush(heap, (f_score, next_len, next_time, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return Stage([], [], float('inf'), float('inf'))

# 构建kDTree的预处理函数
def build_target_kdtree(node_coords: CoordsDict, to_nodes: Set[str]) -> Tuple[KDTree, Dict[int, str]]:
    """
    为目标节点构建kDTree并建立索引到节点ID的映射
    Returns: (kdtree, index_to_node_id)
    """
    target_coords = []
    index_to_node = {}
    
    for idx, node_id in enumerate(to_nodes):
        if node_id in node_coords:
            coord = node_coords[node_id]
            target_coords.append(coord)
            index_to_node[idx] = node_id
    
    kdtree = KDTree(target_coords)
    return kdtree, index_to_node

# 修改后的启发式函数
def create_heuristic_with_kdtree(node_coords: CoordsDict, kdtree: KDTree) -> Callable:
    """
    创建使用kDTree的启发式函数
    """
    def heuristic(node):
        if node not in node_coords or kdtree is None:
            return float('inf')
        
        coord = node_coords[node]
        # 查询最近的一个目标节点
        distance, _ = kdtree.query([coord], k=1)
        return distance[0]
    
    return heuristic

def create_time_heuristic_with_kdtree(node_coords: CoordsDict, kdtree: KDTree, avg_speed: float = 20.0) -> Callable:
    """
    创建使用kDTree的时间启发式函数
    """
    def heuristic(node):
        if node not in node_coords or kdtree is None:
            return float('inf')
        
        coord = node_coords[node]
        # 查询最近的一个目标节点
        distance, _ = kdtree.query([coord], k=1)
        return distance[0] / avg_speed  # 将距离转换为时间估计
    
    return heuristic

# 修改后的A*算法（以astarMF为例）
def astarMF(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_nodes: Set[str], avg_speed:float) -> Stage:
    """
    A* version of dijMF - Find the FASTEST route to any node in to_nodes using kDTree heuristic.
    """
    # 构建kDTree
    kdtree, index_to_node = build_target_kdtree(node_coords, to_nodes)
    
    # 创建启发式函数
    heuristic = create_time_heuristic_with_kdtree(node_coords, kdtree, avg_speed=avg_speed)
    
    # (estimated_total_time, time, length, node, path, path_edges)
    initial_h = heuristic(from_node)
    heap = [(initial_h, 0, 0, from_node, [from_node], [])]
    
    visited = set()
    g_scores = {from_node: 0}  # g_score = actual travel time
    best_stage = Stage([], [], float('inf'), float('inf'))
    
    while heap:
        est_total_time, cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
            
        if cur_node in to_nodes:
            if cur_time < best_stage.travelTime:
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)
        
        visited.add(cur_node)

        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            time_cost = link.instant_travel_time(ctime)
            next_time = cur_time + time_cost
            next_len = cur_len + link.length
            
            if neighbor not in g_scores or next_time < g_scores[neighbor]:
                g_scores[neighbor] = next_time
                h_score = heuristic(neighbor)
                est_total = next_time + h_score

                heapq.heappush(heap, (est_total, next_time, next_len, neighbor, path + [neighbor], path_edges + [link.name]))

    return best_stage

def astarMS(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_nodes: Set[str]) -> Stage:
    """
    A* version of dijMS - Find the SHORTEST route to any node in to_nodes using kDTree heuristic.
    """
    # 构建kDTree
    kdtree, index_to_node = build_target_kdtree(node_coords, to_nodes)
    
    # 创建启发式函数
    heuristic = create_heuristic_with_kdtree(node_coords, kdtree)
    
    # (estimated_total_length, length, time, node, path, path_edges)
    initial_h = heuristic(from_node)
    heap = [(initial_h, 0, 0, from_node, [from_node], [])]
    
    visited = set()
    g_scores = {from_node: 0}  # g_score = actual path length
    best_stage = Stage([], [], float('inf'), float('inf'))
    
    while heap:
        est_total_len, cur_len, cur_time, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
            
        if cur_node in to_nodes:
            if cur_len < best_stage.length:
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)
        
        visited.add(cur_node)

        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            length_cost = link.length
            next_len = cur_len + length_cost
            next_time = cur_time + link.instant_travel_time(ctime)
            
            if neighbor not in g_scores or next_len < g_scores[neighbor]:
                g_scores[neighbor] = next_len
                h_score = heuristic(neighbor)
                est_total = next_len + h_score
                
                heapq.heappush(heap, (est_total, next_len, next_time, neighbor, path + [neighbor], path_edges + [link.name]))
    
    return best_stage

def astarMC(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_nodes: Set[str], 
           omega: float, to_charge: float, wt: Dict[str, float], p: Dict[str, float], 
           max_length: float = float('inf'), avg_speed: float = 20.0) -> Stage:
    """
    A* version of dijMC - Find the BEST route using kDTree heuristic.
    """
    # 构建kDTree
    kdtree, index_to_node = build_target_kdtree(node_coords, to_nodes)
    
    # 创建启发式函数（使用距离启发式）
    distance_heuristic = create_heuristic_with_kdtree(node_coords, kdtree)
    
    # 将距离启发式转换为score启发式（近似）
    def score_heuristic(node):
        dist = distance_heuristic(node)
        # 将距离转换为近似的score增量（这是一个保守估计）
        return omega * (dist / avg_speed / 60.0)  # 假设平均速度20.0m/s，转换为分钟
    
    # (estimated_total_score, actual_score, time, length, node, path, path_edges)
    initial_h = score_heuristic(from_node)
    initial_score = omega * (0 / 60.0 + wt.get(from_node, 0)) + to_charge * p.get(from_node, 0)
    heap = [(initial_h + initial_score, initial_score, 0, 0, from_node, [from_node], [])]
    
    visited = set()
    best_score = {from_node: initial_score}
    best_stage = Stage([], [], float('inf'), float('inf'))
    min_actual_score = float('inf')
    
    while heap:
        est_total_score, cur_score, cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)

        if cur_score > min_actual_score:
            continue
            
        if cur_node in visited:
            continue
        visited.add(cur_node)
        
        if cur_node in to_nodes and cur_len <= max_length:
            if cur_score < min_actual_score:
                min_actual_score = cur_score
                best_stage = Stage(path.copy(), path_edges.copy(), cur_time, cur_len)

        for neighbor, link in gl.get(cur_node, []):
            if neighbor in visited:
                continue
                
            next_time = cur_time + link.instant_travel_time(ctime)
            next_len = cur_len + link.length
            
            if next_len > max_length:
                continue
            
            neighbor_score = omega * (next_time / 60.0 + wt.get(neighbor, 0)) + to_charge * p.get(neighbor, 0)
            
            if neighbor not in best_score or neighbor_score < best_score[neighbor]:
                best_score[neighbor] = neighbor_score
                h_score = score_heuristic(neighbor)
                est_total = neighbor_score + h_score
                
                heapq.heappush(heap, (est_total, neighbor_score, next_time, next_len, 
                                    neighbor, path + [neighbor], path_edges + [link.name]))

    return best_stage