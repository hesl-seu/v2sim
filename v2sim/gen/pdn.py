import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence
from xml.etree import ElementTree as ET
from v2sim.net import RoadNet


# Standard IEEE-33 base loads in MW/Mvar.  Index 0 is the zero-load root bus.
_IEEE33_LOADS: tuple[tuple[float, float], ...] = (
    (0.000, 0.000),
    (0.100, 0.060), (0.090, 0.040), (0.120, 0.080), (0.060, 0.030),
    (0.060, 0.020), (0.200, 0.100), (0.200, 0.100), (0.060, 0.020),
    (0.060, 0.020), (0.045, 0.030), (0.060, 0.035), (0.060, 0.035),
    (0.120, 0.080), (0.060, 0.010), (0.060, 0.020), (0.060, 0.020),
    (0.090, 0.040), (0.090, 0.040), (0.090, 0.040), (0.090, 0.040),
    (0.090, 0.040), (0.090, 0.050), (0.420, 0.200), (0.420, 0.200),
    (0.060, 0.025), (0.060, 0.025), (0.060, 0.020), (0.120, 0.070),
    (0.200, 0.600), (0.150, 0.070), (0.210, 0.100), (0.060, 0.040),
)

# Same hourly multiplier style as the supplied IEEE-33 reference file.
_DAILY_FACTORS: tuple[float, ...] = (
    0.70, 0.65, 0.625, 0.625, 0.625, 0.60,
    0.725, 0.90, 1.15, 1.60, 2.025, 2.20,
    2.25, 1.80, 1.00, 1.725, 1.975, 2.30,
    2.425, 2.50, 1.95, 1.40, 1.00, 0.80,
)


@dataclass(frozen=True)
class GridGenerationConfig:
    """Configuration for a synthetic spatially coupled distribution grid."""

    bus_count: int = 99
    feeder_count: int = 3
    base_voltage_kv: float = 110.0
    base_power_mva: float = 100.0
    min_voltage_pu: float = 0.90
    max_voltage_pu: float = 1.10
    resistance_ohm_per_km: float = 0.080
    reactance_ohm_per_km: float = 0.320
    max_current_ka: float = 1.0
    load_repeat: int = 8
    load_period_s: int = 86400
    # Match the supplied reference: generators at local buses 1, 2, 3, 6, 8.
    generator_local_buses: tuple[int, ...] = (1, 2, 3, 6, 8)
    generator_pmax_mw: float = 100.0
    generator_qmax_mvar: float = 100.0

    def validate(self, road_node_count: int) -> None:
        if self.bus_count < 2:
            raise ValueError("bus_count must be at least 2")
        if self.bus_count > road_node_count:
            raise ValueError(
                f"bus_count={self.bus_count} exceeds RoadNet node count={road_node_count}"
            )
        if not 1 <= self.feeder_count <= self.bus_count // 2:
            raise ValueError("feeder_count must be between 1 and bus_count // 2")
        if self.base_voltage_kv <= 0 or self.base_power_mva <= 0:
            raise ValueError("base voltage and power must be positive")
        if not 0 < self.min_voltage_pu < self.max_voltage_pu:
            raise ValueError("invalid per-unit voltage limits")
        if self.resistance_ohm_per_km < 0 or self.reactance_ohm_per_km <= 0:
            raise ValueError("invalid line series parameters")
        if self.load_repeat < 1 or self.load_period_s < 1:
            raise ValueError("load_repeat and load_period_s must be positive")
        if 1 not in self.generator_local_buses:
            raise ValueError("generator_local_buses must include feeder root bus 1")
        if self.generator_pmax_mw <= 0 or self.generator_qmax_mvar <= 0:
            raise ValueError("generator limits must be positive")


@dataclass(frozen=True)
class GridGenerationResult:
    """Generation summary and the spatial coupling map."""

    output_path: Path
    bus_count: int
    line_count: int
    generator_count: int
    feeder_count: int
    bus_to_road_node: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True)
class _Point:
    road_node_id: str
    x: float
    y: float


def _balanced_regions(points: Sequence[_Point], count: int) -> list[list[_Point]]:
    """Split points into deterministic, equally populated geographic bands."""
    min_x = min(p.x for p in points)
    max_x = max(p.x for p in points)
    min_y = min(p.y for p in points)
    max_y = max(p.y for p in points)
    if max_x - min_x >= max_y - min_y:
        ordered = sorted(points, key=lambda p: (p.x, p.y, p.road_node_id))
    else:
        ordered = sorted(points, key=lambda p: (p.y, p.x, p.road_node_id))
    return [
        list(ordered[len(ordered) * i // count : len(ordered) * (i + 1) // count])
        for i in range(count)
    ]


def _target_counts(total: int, groups: int) -> list[int]:
    return [total // groups + (1 if i < total % groups else 0) for i in range(groups)]


def _farthest_point_sample(points: Sequence[_Point], count: int) -> list[_Point]:
    """Deterministic max-min sampling to spread buses across a region."""
    if count > len(points):
        raise ValueError("not enough road nodes in a spatial region")
    cx = sum(p.x for p in points) / len(points)
    cy = sum(p.y for p in points) / len(points)
    first = min(points, key=lambda p: ((p.x - cx) ** 2 + (p.y - cy) ** 2, p.road_node_id))
    chosen = [first]
    remaining = [p for p in points if p.road_node_id != first.road_node_id]
    min_d2 = [(p.x - first.x) ** 2 + (p.y - first.y) ** 2 for p in remaining]

    while len(chosen) < count:
        index = max(range(len(remaining)), key=lambda i: (min_d2[i], remaining[i].road_node_id))
        picked = remaining.pop(index)
        min_d2.pop(index)
        chosen.append(picked)
        for i, point in enumerate(remaining):
            d2 = (point.x - picked.x) ** 2 + (point.y - picked.y) ** 2
            min_d2[i] = min(min_d2[i], d2)
    return chosen


def _euclidean_mst(points: Sequence[_Point]) -> list[tuple[int, int]]:
    """Return an undirected Euclidean minimum spanning tree using Prim's method."""
    in_tree = [False] * len(points)
    best_d2 = [math.inf] * len(points)
    parent = [-1] * len(points)
    best_d2[0] = 0.0
    for _ in points:
        u = min((i for i in range(len(points)) if not in_tree[i]), key=best_d2.__getitem__)
        in_tree[u] = True
        for v, point in enumerate(points):
            if in_tree[v]:
                continue
            d2 = (point.x - points[u].x) ** 2 + (point.y - points[u].y) ** 2
            if d2 < best_d2[v]:
                best_d2[v] = d2
                parent[v] = u
    return [(parent[v], v) for v in range(1, len(points))]


def _orient_and_reindex(
    points: Sequence[_Point], edges: Sequence[tuple[int, int]]
) -> tuple[list[_Point], list[tuple[int, int]]]:
    """Choose a central root, then orient and BFS-number the radial feeder."""
    cx = sum(p.x for p in points) / len(points)
    cy = sum(p.y for p in points) / len(points)
    root = min(
        range(len(points)),
        key=lambda i: ((points[i].x - cx) ** 2 + (points[i].y - cy) ** 2, points[i].road_node_id),
    )
    adjacency = [[] for _ in points]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)

    order: list[int] = []
    oriented_old: list[tuple[int, int]] = []
    queue = deque([(root, -1)])
    while queue:
        node, parent = queue.popleft()
        order.append(node)
        if parent >= 0:
            oriented_old.append((parent, node))
        children = [v for v in adjacency[node] if v != parent]
        children.sort(
            key=lambda v: (
                math.atan2(points[v].y - points[node].y, points[v].x - points[node].x),
                points[v].road_node_id,
            )
        )
        queue.extend((child, node) for child in children)

    old_to_new = {old: new for new, old in enumerate(order)}
    return [points[i] for i in order], [
        (old_to_new[parent], old_to_new[child]) for parent, child in oriented_old
    ]


def _add_load(parent: ET.Element, tag: str, base_value: float, config: GridGenerationConfig) -> None:
    unit = "MW" if tag == "Pd" else "Mvar"
    profile = ET.SubElement(
        parent,
        tag,
        repeat=str(config.load_repeat),
        period=str(config.load_period_s),
    )
    for hour, factor in enumerate(_DAILY_FACTORS):
        ET.SubElement(
            profile,
            "item",
            time=str(round(hour * config.load_period_s / 24)),
            value=f"{base_value * factor:.4f}{unit}",
        )


def _add_generator(
    root: ET.Element,
    feeder: int,
    local_bus: int,
    point: _Point,
    config: GridGenerationConfig,
) -> None:
    generator = ET.SubElement(
        root,
        "gen",
        ID=f"g{feeder}_{local_bus}",
        Bus=f"b{feeder}_{local_bus}",
        x=f"{point.x:.6f}",
        y=f"{point.y:.6f}",
    )
    values = (
        ("Pmin", "0.0MW"),
        ("Pmax", f"{config.generator_pmax_mw:.4f}MW"),
        ("Qmin", f"{-config.generator_qmax_mvar:.4f}Mvar"),
        ("Qmax", f"{config.generator_qmax_mvar:.4f}Mvar"),
        ("CostA", "0.0005$/kWh2"),
        ("CostB", "1.0$/kWh"),
        ("CostC", "10.0$"),
    )
    for tag, value in values:
        ET.SubElement(generator, tag, const=value)


def _add_prices(root: ET.Element, config: GridGenerationConfig) -> None:
    schedule = (
        (0.0, 0.35), (8 / 24, 1.10), (11 / 24, 0.70),
        (18 / 24, 1.10), (23 / 24, 0.70)
    )
    for tag in ("cprice", "dprice"):
        price = ET.SubElement(
            root, tag, repeat=str(config.load_repeat), period=str(config.load_period_s)
        )
        for period_fraction, value in schedule:
            time_s = round(period_fraction * config.load_period_s)
            ET.SubElement(price, "item", time=str(time_s), value=f"{value:.2f}$/kWh")


def generate_distribution_grid(
    roadnet: RoadNet,
    output_path: str | Path,
    config: GridGenerationConfig | None = None,
) -> GridGenerationResult:
    """Generate and save a V2Sim/FPowerKit grid XML from ``roadnet``.

    The selected bus locations are exact RoadNet node coordinates.  Each feeder
    is a radial Euclidean MST and is electrically independent, matching the
    multi-IEEE-33 organization used by the supplied V2Sim reference grid.
    """
    config = config or GridGenerationConfig()
    config.validate(len(roadnet.nodes))
    output = Path(output_path)
    if output.suffix.lower() != ".xml":
        raise ValueError("output_path must end with .xml (usually .grid.xml)")

    points = [
        _Point(str(node.name), float(node.x), float(node.y))
        for node in roadnet.nodes.values()
    ]
    if len({p.road_node_id for p in points}) != len(points):
        raise ValueError("RoadNet contains duplicate node IDs")

    regions = _balanced_regions(points, config.feeder_count)
    target_counts = _target_counts(config.bus_count, config.feeder_count)
    feeders: list[list[_Point]] = []
    feeder_edges: list[list[tuple[int, int]]] = []
    for region, target in zip(regions, target_counts):
        sampled = _farthest_point_sample(region, target)
        feeder_points, edges = _orient_and_reindex(sampled, _euclidean_mst(sampled))
        feeders.append(feeder_points)
        feeder_edges.append(edges)

    root = ET.Element(
        "grid",
        Sb=f"{config.base_power_mva:.1f}MVA",
        Ub=f"{config.base_voltage_kv:.1f}kV",
    )
    bus_to_road_node: dict[str, str] = {}
    for feeder_index, feeder in enumerate(feeders):
        for local_index, point in enumerate(feeder, start=1):
            bus_id = f"b{feeder_index}_{local_index}"
            bus_to_road_node[bus_id] = point.road_node_id
            attrs = {
                "ID": bus_id,
                "x": f"{point.x:.6f}",
                "y": f"{point.y:.6f}",
            }
            if local_index == 1:
                attrs["V"] = "1.0"
            else:
                attrs["MinV"] = f"{config.min_voltage_pu:.4f}"
                attrs["MaxV"] = f"{config.max_voltage_pu:.4f}"
            bus = ET.SubElement(root, "bus", attrs)
            if local_index == 1:
                ET.SubElement(bus, "Pd", const="0.0MW")
                ET.SubElement(bus, "Qd", const="0.0Mvar")
            else:
                load_index = 1 + ((local_index - 2) % (len(_IEEE33_LOADS) - 1))
                pd, qd = _IEEE33_LOADS[load_index]
                _add_load(bus, "Pd", pd, config)
                _add_load(bus, "Qd", qd, config)

    line_count = 0
    for feeder_index, (feeder, edges) in enumerate(zip(feeders, feeder_edges)):
        for line_index, (parent, child) in enumerate(edges, start=1):
            start = feeder[parent]
            end = feeder[child]
            length_km = math.hypot(end.x - start.x, end.y - start.y) / 1000.0
            ET.SubElement(
                root,
                "line",
                ID=f"l{feeder_index}_{line_index}",
                From=f"b{feeder_index}_{parent + 1}",
                To=f"b{feeder_index}_{child + 1}",
                R=f"{config.resistance_ohm_per_km * length_km:.6f}ohm",
                X=f"{config.reactance_ohm_per_km * length_km:.6f}ohm",
                MaxIkA=f"{config.max_current_ka:.4f}",
                Length_km=f"{length_km:.6f}",
            )
            line_count += 1

    generator_count = 0
    for feeder_index, feeder in enumerate(feeders):
        for local_bus in config.generator_local_buses:
            if 1 <= local_bus <= len(feeder):
                _add_generator(root, feeder_index, local_bus, feeder[local_bus - 1], config)
                generator_count += 1

    _add_prices(root, config)
    ET.indent(root, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return GridGenerationResult(
        output_path=output.resolve(),
        bus_count=config.bus_count,
        line_count=line_count,
        generator_count=generator_count,
        feeder_count=config.feeder_count,
        bus_to_road_node=bus_to_road_node,
    )

__all__ = [
    "GridGenerationConfig",
    "GridGenerationResult",
    "generate_distribution_grid",
]