import heapq, math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Dict, Mapping, Optional, Protocol, Sequence, Tuple, TypeVar
from scipy.spatial import KDTree


@dataclass
class Stage:
    nodes: List[str]
    edges: List[str]
    travelTime: float
    length: float

CoordsDict = Dict[str, Tuple[float, float]]  # node ID -> (x, y)

class LinkLike(Protocol):
    name: str
    length: float
    def instant_travel_time(self, t: int) -> float: ...

Graph = Mapping[str, Sequence[Tuple[str, LinkLike]]]  # node ID -> List of (to_node ID, Link object)


def get_network_speed_upper_bound(gl: Graph) -> float:
    """Return a conservative upper bound of link speed in m/s.

    UXsim links expose ``free_flow_speed`` while the lightweight road-network
    edges used by some callers expose ``speed_limit``.  Falling back to ``u``
    keeps this helper compatible with UXsim's internal link representation.

    A non-positive result means that no usable bound could be determined.  In
    that case time-based A* falls back to a zero heuristic (i.e. Dijkstra-like
    ordering), which is still admissible.
    """
    max_speed = 0.0
    seen_links = set()
    for outgoing in gl.values():
        for _, link in outgoing:
            lid = id(link)
            if lid in seen_links:
                continue
            seen_links.add(lid)
            speed = getattr(link, "free_flow_speed", None)
            if speed is None:
                speed = getattr(link, "speed_limit", None)
            if speed is None:
                speed = getattr(link, "u", None)
            try:
                speed = float(speed) # type: ignore
            except (TypeError, ValueError):
                continue
            if math.isfinite(speed) and speed > max_speed:
                max_speed = speed
    return max_speed


def _time_from_straight_line(distance: float, speed_upper_bound: float) -> float:
    """Convert a straight-line distance heuristic (m) into seconds."""
    if not math.isfinite(speed_upper_bound) or speed_upper_bound <= 0:
        return 0.0
    return distance / speed_upper_bound

@dataclass
class _MCLabel:
    """One reachable state in a resource-constrained station search."""
    node: str
    time_s: float
    length_m: float
    parent: Optional[int]
    via_edge: Optional[str]
    active: bool = True


def _mc_dominates(a: _MCLabel, time_s: float, length_m: float,
                  max_length: float, omega: float) -> bool:
    """Whether an existing prefix makes a proposed prefix unnecessary.

    At finite range, both time and distance are resources. Without a range
    limit only time matters (for omega > 0). When omega == 0, travel time is
    irrelevant to the objective, so shortest distance is sufficient.
    """
    if math.isinf(max_length):
        if omega == 0:
            return a.length_m <= length_m
        return (a.time_s < time_s or
                (a.time_s == time_s and a.length_m <= length_m))
    if omega == 0:
        return a.length_m <= length_m
    return a.time_s <= time_s and a.length_m <= length_m


def _mc_new_dominates(time_s: float, length_m: float, a: _MCLabel,
                      max_length: float, omega: float) -> bool:
    if math.isinf(max_length):
        if omega == 0:
            return length_m < a.length_m
        return (time_s < a.time_s or
                (time_s == a.time_s and length_m < a.length_m))
    if omega == 0:
        return length_m < a.length_m
    return time_s <= a.time_s and length_m <= a.length_m


def _mc_admissible_heuristic(
    gl: Graph, node_coords: CoordsDict, ctime: int,
    targets: set, omega: float, speed_upper_bound: Optional[float]
) -> Callable[[str], float]:
    """Certified lower bound on weighted remaining travel time.

    A geometric lower bound is safe only when every traversable graph edge
    has known endpoint coordinates and the speed bound is at least its
    straight-line distance divided by its snapshot travel time. Verify that
    property rather than assuming a link's free-flow speed is sufficient.
    If it cannot be verified, return a zero (Dijkstra) heuristic.

    Note: the certification scans graph edges once per station query. For a
    very large network, using dijMC() can avoid this preprocessing cost.
    """
    def zero(_node: str) -> float:
        return 0.0

    if omega == 0 or not targets or not all(t in node_coords for t in targets):
        return zero

    v = 0.0
    for source, outgoing in gl.items():
        if source not in node_coords:
            return zero
        x1, y1 = node_coords[source]
        for dest, edge in outgoing:
            if dest not in node_coords:
                return zero
            x2, y2 = node_coords[dest]
            direct = math.hypot(x2 - x1, y2 - y1)
            dt = float(edge.instant_travel_time(ctime))
            if math.isnan(dt) or dt < 0:
                raise ValueError('Negative or NaN road travel time')
            if math.isinf(dt):
                continue  # this edge is not traversable in this snapshot
            if dt == 0:
                if direct > 0:
                    return zero
                continue
            v = max(v, direct / dt)

    if speed_upper_bound is not None:
        bound = float(speed_upper_bound)
        if math.isfinite(bound) and bound > 0:
            v = max(v, bound)
    if v <= 0 or not math.isfinite(v):
        return zero

    kdtree = KDTree([node_coords[t] for t in targets])
    def heuristic(node: str) -> float:
        if node not in node_coords:
            return 0.0
        nearest_m = float(kdtree.query(node_coords[node], k=1)[0])
        return omega * nearest_m / (60.0 * v)
    return heuristic


def _mc_search(
    gl: Graph, ctime: int, from_node: str, omega: float,
    to_nodes: Iterable[str], node_scores: Mapping[str, float],
    max_length: float = float('inf'),
    heuristic: Optional[Callable[[str], float]] = None,
) -> Stage:
    """Exact minimum-score, distance-constrained multi-target routing.

    Objective, in minutes and station-cost units:
        omega * (route_time_seconds / 60) + node_scores[target]
    Constraint:
        sum(link.length) <= max_length

    Road times and lengths are nonnegative snapshot costs. Destination
    station costs are paid ONLY on termination, not on intermediate nodes.
    Maintains Pareto (time, distance) labels when the distance bound is
    active; a single best-time label is not generally sufficient.
    """
    targets = set(to_nodes)
    empty = Stage([], [], float('inf'), float('inf'))
    if not targets:
        return empty
    if not math.isfinite(omega) or omega < 0:
        raise ValueError('omega must be finite and nonnegative')
    if math.isnan(max_length) or max_length < 0:
        raise ValueError('max_length must be nonnegative')
    if heuristic is None:
        heuristic = lambda _: 0.0

    terminal_costs = {s: float(node_scores.get(s, 0.0)) for s in targets}
    if any(not math.isfinite(value) for value in terminal_costs.values()):
        raise ValueError('Station terminal costs must be finite')
    min_terminal = min(terminal_costs.values())

    labels = [_MCLabel(from_node, 0.0, 0.0, None, None)]
    frontier: Dict[str, List[int]] = {from_node: [0]}
    # (admissible_bound, weighted_drive_cost, length_m, monotonically
    #  increasing label ID): never compare path lists or Link objects.
    heap = [(heuristic(from_node), 0.0, 0.0, 0)]
    best_cost = float('inf')
    best_index: Optional[int] = None

    while heap:
        lower_bound, _, _, index = heapq.heappop(heap)
        current = labels[index]
        if not current.active:
            continue
        if lower_bound + min_terminal > best_cost:
            break

        drive_cost = omega * current.time_s / 60.0
        if current.node in targets:
            total_cost = drive_cost + terminal_costs[current.node]
            if total_cost < best_cost:
                best_cost, best_index = total_cost, index

        for neighbor, link in gl.get(current.node, ()):
            dt = float(link.instant_travel_time(ctime))
            edge_length = float(link.length)
            if math.isnan(dt) or dt < 0 or not math.isfinite(edge_length) or edge_length < 0:
                raise ValueError('Road link must have nonnegative finite length and nonnegative time')
            if not math.isfinite(dt):
                continue
            new_length = current.length_m + edge_length
            if new_length > max_length:
                continue
            new_time = current.time_s + dt

            predecessors = frontier.get(neighbor, [])
            if any(_mc_dominates(labels[j], new_time, new_length, max_length, omega)
                   for j in predecessors if labels[j].active):
                continue

            survivors = []
            for j in predecessors:
                existing = labels[j]
                if not existing.active:
                    continue
                if _mc_new_dominates(new_time, new_length, existing, max_length, omega):
                    existing.active = False
                else:
                    survivors.append(j)

            new_id = len(labels)
            labels.append(_MCLabel(neighbor, new_time, new_length, index, link.name))
            survivors.append(new_id)
            frontier[neighbor] = survivors
            next_drive_cost = omega * new_time / 60.0
            estimate = next_drive_cost + heuristic(neighbor)
            if estimate + min_terminal <= best_cost:
                heapq.heappush(heap, (estimate, next_drive_cost, new_length, new_id))

    if best_index is None:
        return empty
    best = labels[best_index]
    nodes, edges = [], []
    index = best_index
    while index is not None:
        label = labels[index]
        nodes.append(label.node)
        if label.via_edge is not None:
            edges.append(label.via_edge)
        index = label.parent
    nodes.reverse()
    edges.reverse()
    return Stage(nodes, edges, best.time_s, best.length_m)


def dijMC(gl: Graph, ctime: int, from_node: str, omega: float, to_nodes: Iterable[str],
          node_scores: Dict[str, float], max_length: float = float('inf')) -> Stage:
    """Exact Dijkstra-based charging-station choice (with distance constraint)."""
    return _mc_search(gl, ctime, from_node, omega, to_nodes, node_scores, max_length)

def dijMF(gl: Graph, ctime: int, from_node: str, to_nodes: Iterable[str]) -> Stage:
    """
    Find the FASTEST route to any node in to_nodes.
    Uses time as primary key, length as secondary key.
    """
    # (time, length, node, path, path_edges)
    heap = [(0., 0., from_node, [from_node], [])]
    visited = set()
    min_time = {from_node: 0.}
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

def dijMS(gl: Graph, ctime: int, from_node: str, to_nodes: Iterable[str]) -> Stage:
    """
    Find the SHORTEST route to any node in to_nodes.
    Uses length as primary key, time as secondary key.
    """
    # (length, time, node, path, path_edges)
    heap = [(0., 0., from_node, [from_node], [])]
    visited = set()
    min_length = {from_node: 0.}
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

def astarF(
    gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_node: str,
    speed_upper_bound: Optional[float] = None,
) -> Stage:
    """
    A* algorithm for FASTEST path using time as cost.
    Uses f_score (time + heuristic) as primary key, time as secondary key, length as tertiary key.
    """
    to_coord = node_coords[to_node]
    if speed_upper_bound is None:
        speed_upper_bound = get_network_speed_upper_bound(gl)
    
    def heuristic(node):
        coord = node_coords[node]
        distance = math.hypot(coord[0] - to_coord[0], coord[1] - to_coord[1])
        return _time_from_straight_line(distance, speed_upper_bound)
    
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
def build_target_kdtree(node_coords: CoordsDict, to_nodes: Iterable[str]) -> Tuple[KDTree, Dict[int, str]]:
    """
    为目标节点构建kDTree并建立索引到节点ID的映射
    Returns: (kdtree, index_to_node_id)
    """
    target_coords:List[Tuple[float, float]] = []
    index_to_node = {}
    
    for idx, node_id in enumerate(to_nodes):
        if node_id in node_coords:
            coord = node_coords[node_id]
            target_coords.append(coord)
            index_to_node[idx] = node_id
    
    kdtree = KDTree(target_coords)
    return kdtree, index_to_node # pyright: ignore[reportReturnType]

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

def create_time_heuristic_with_kdtree(
    node_coords: CoordsDict, kdtree: KDTree, speed_upper_bound: float
) -> Callable:
    """
    创建使用kDTree的时间启发式函数
    """
    def heuristic(node):
        if node not in node_coords or kdtree is None:
            return float('inf')
        
        coord = node_coords[node]
        # 查询最近的一个目标节点
        distance, _ = kdtree.query([coord], k=1)
        return _time_from_straight_line(float(distance[0]), speed_upper_bound)
    
    return heuristic

# 修改后的A*算法（以astarMF为例）
def astarMF(
    gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str,
    to_nodes: Iterable[str], speed_upper_bound: Optional[float] = None,
) -> Stage:
    """
    A* version of dijMF - Find the FASTEST route to any node in to_nodes using kDTree heuristic.
    """
    targets = set(to_nodes)
    if not targets:
        return Stage([], [], float('inf'), float('inf'))

    # 构建kDTree
    kdtree, index_to_node = build_target_kdtree(node_coords, targets)

    if speed_upper_bound is None:
        speed_upper_bound = get_network_speed_upper_bound(gl)
    
    # 创建启发式函数
    heuristic = create_time_heuristic_with_kdtree(node_coords, kdtree, speed_upper_bound)
    
    # (estimated_total_time, time, length, node, path, path_edges)
    initial_h = heuristic(from_node)
    heap = [(initial_h, 0., 0., from_node, [from_node], [])]
    
    visited = set()
    g_scores = {from_node: 0.}  # g_score = actual travel time
    best_stage = Stage([], [], float('inf'), float('inf'))
    
    while heap:
        est_total_time, cur_time, cur_len, cur_node, path, path_edges = heapq.heappop(heap)
        
        if cur_node in visited:
            continue
            
        if cur_node in targets:
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

def astarMS(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, to_nodes: Iterable[str]) -> Stage:
    """
    A* version of dijMS - Find the SHORTEST route to any node in to_nodes using kDTree heuristic.
    """
    # 构建kDTree
    kdtree, index_to_node = build_target_kdtree(node_coords, to_nodes)
    
    # 创建启发式函数
    heuristic = create_heuristic_with_kdtree(node_coords, kdtree)
    
    # (estimated_total_length, length, time, node, path, path_edges)
    initial_h = heuristic(from_node)
    heap = [(initial_h, 0., 0., from_node, [from_node], [])]
    
    visited = set()
    g_scores = {from_node: 0.}  # g_score = actual path length
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

def astarMC(gl: Graph, node_coords: CoordsDict, ctime: int, from_node: str, omega: float,
            to_nodes: Iterable[str], node_scores: Dict[str, float],
            max_length: float = float('inf'), speed_upper_bound: Optional[float] = None) -> Stage:
    """Exact A*-ordered best-station route, with admissible geometric heuristic.

    Shares the same objective, distance restriction, and Pareto-label logic
    as dijMC(). A geometric speed lower bound is certified at each call;
    missing/inconsistent coordinates fall back to Dijkstra ordering.
    """
    targets = set(to_nodes)
    if not targets:
        return Stage([], [], float('inf'), float('inf'))
    if not math.isfinite(omega) or omega < 0:
        raise ValueError('omega must be finite and nonnegative')
    h = _mc_admissible_heuristic(gl, node_coords, ctime, targets, omega,
                                 speed_upper_bound)
    return _mc_search(gl, ctime, from_node, omega, targets, node_scores,
                      max_length, heuristic=h)
