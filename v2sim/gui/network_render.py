"""Pure-Python scene preparation and viewport culling for NetworkPanel.

This module intentionally has no Tk dependency.  Geometry can be prepared on a
worker thread, while all Canvas operations remain on Tk's main thread.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BBox = Tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class RoadEdgeVisual:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    color: str
    width: float

    @property
    def bbox(self) -> BBox:
        return (
            min(self.x0, self.x1), min(self.y0, self.y1),
            max(self.x0, self.x1), max(self.y0, self.y1),
        )


@dataclass(frozen=True, slots=True)
class RoadNodeVisual:
    name: str
    x: float
    y: float


class SpatialHash:
    """Uniform-grid index for viewport queries over line segments and points."""

    def __init__(self, bounds: BBox, approximate_items: int):
        minx, miny, maxx, maxy = bounds
        spanx = max(maxx - minx, 1.0)
        spany = max(maxy - miny, 1.0)
        side = max(8, min(128, int(math.sqrt(max(approximate_items, 1) / 24))))
        self.bounds = bounds
        self.cell_w = spanx / side
        self.cell_h = spany / side
        self.side = side
        self._cells: Dict[Tuple[int, int], List[int]] = {}

    def _cell(self, x: float, y: float) -> Tuple[int, int]:
        minx, miny, _, _ = self.bounds
        ix = int((x - minx) / self.cell_w)
        iy = int((y - miny) / self.cell_h)
        return max(0, min(self.side - 1, ix)), max(0, min(self.side - 1, iy))

    def add(self, index: int, bbox: BBox) -> None:
        ix0, iy0 = self._cell(bbox[0], bbox[1])
        ix1, iy1 = self._cell(bbox[2], bbox[3])
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                self._cells.setdefault((ix, iy), []).append(index)

    def query(self, bbox: BBox) -> List[int]:
        ix0, iy0 = self._cell(bbox[0], bbox[1])
        ix1, iy1 = self._cell(bbox[2], bbox[3])
        found = set()
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                found.update(self._cells.get((ix, iy), ()))
        return sorted(found)


class RoadScene:
    """Immutable road geometry with fast, deterministic viewport selection."""

    def __init__(
        self,
        bounds: BBox,
        edges: Sequence[RoadEdgeVisual],
        nodes: Sequence[RoadNodeVisual],
    ):
        self.bounds = bounds
        self.edges = tuple(edges)
        self.nodes = tuple(nodes)
        self.edge_by_name = {edge.name: edge for edge in self.edges}
        self.node_by_name = {node.name: node for node in self.nodes}
        self._edge_index = SpatialHash(bounds, len(self.edges))
        self._node_index = SpatialHash(bounds, len(self.nodes))
        for index, edge in enumerate(self.edges):
            self._edge_index.add(index, edge.bbox)
        for index, node in enumerate(self.nodes):
            self._node_index.add(index, (node.x, node.y, node.x, node.y))

    @staticmethod
    def build(roadnet, world_colors: Optional[Mapping[int, str]] = None) -> "RoadScene":
        """Snapshot RoadNet geometry without invoking Tk from the worker thread."""
        minx, miny, maxx, maxy = roadnet.getBoundary()
        # Scene Y is inverted once, matching Canvas coordinates before scaling.
        bounds = (float(minx), float(-maxy), float(maxx), float(-miny))
        diagonal = math.hypot(maxx - minx, maxy - miny)
        offset = diagonal * 1e-3
        colors = world_colors or {}
        edges: List[RoadEdgeVisual] = []
        for edge in roadnet.edges.values():
            x0, y0 = edge.from_node.get_coord()
            x1, y1 = edge.to_node.get_coord()
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length:
                right_x, right_y = dy / length, -dx / length
            else:
                right_x, right_y = 0.0, -1.0
            x0 += right_x * offset
            y0 += right_y * offset
            x1 += right_x * offset
            y1 += right_y * offset
            edges.append(RoadEdgeVisual(
                edge.name, float(x0), float(-y0), float(x1), float(-y1),
                colors.get(edge.world_id, "blue"), 2.0,
            ))
        nodes = [
            RoadNodeVisual(node.name, float(node.x), float(-node.y))
            for node in roadnet.nodes.values()
        ]
        if edges:
            bounds = (
                min(bounds[0], min(edge.bbox[0] for edge in edges)),
                min(bounds[1], min(edge.bbox[1] for edge in edges)),
                max(bounds[2], max(edge.bbox[2] for edge in edges)),
                max(bounds[3], max(edge.bbox[3] for edge in edges)),
            )
        return RoadScene(bounds, edges, nodes)

    @staticmethod
    def _intersects(a: BBox, b: BBox) -> bool:
        return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]

    def visible_edges(self, viewport: BBox) -> List[RoadEdgeVisual]:
        return [
            self.edges[i] for i in self._edge_index.query(viewport)
            if self._intersects(self.edges[i].bbox, viewport)
        ]

    def visible_nodes(self, viewport: BBox) -> List[RoadNodeVisual]:
        return [
            self.nodes[i] for i in self._node_index.query(viewport)
            if viewport[0] <= self.nodes[i].x <= viewport[2]
            and viewport[1] <= self.nodes[i].y <= viewport[3]
        ]

    @staticmethod
    def limit(items: Sequence, maximum: int) -> Sequence:
        """Stable LOD sampling that always returns at most ``maximum`` items."""
        if maximum <= 0:
            return ()
        if len(items) <= maximum:
            return items
        step = len(items) / maximum
        return [items[int(i * step)] for i in range(maximum)]

    def select(
        self,
        viewport: BBox,
        max_edges: int,
        max_nodes: int,
        force_edges: Iterable[str] = (),
    ) -> Tuple[Sequence[RoadEdgeVisual], Sequence[RoadNodeVisual]]:
        """Select a bounded number of visible objects for the current LOD."""
        visible_edges = self.visible_edges(viewport)
        edges = list(self.limit(visible_edges, max_edges))
        present = {edge.name for edge in edges}
        for name in force_edges:
            edge = self.edge_by_name.get(name)
            if edge is not None and name not in present:
                edges.append(edge)
                present.add(name)

        visible_nodes = self.visible_nodes(viewport)
        # At city overview level, nodes add thousands of Canvas objects with
        # almost no visual information.  They reappear automatically on zoom.
        nodes = visible_nodes if len(visible_nodes) <= max_nodes else ()
        return edges, nodes


__all__ = [
    "BBox", "RoadEdgeVisual", "RoadNodeVisual", "RoadScene", "SpatialHash"
]
