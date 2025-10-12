from dataclasses import dataclass
import sys
from typing import DefaultDict, Dict, List, Set, Tuple, Union
from xml.etree.ElementTree import ElementTree


class Node:
    def __init__(self, node_id:str, x:int, y:int):
        self.id = node_id
        self.x = x
        self.y = y
        self.incoming_edges:List[Edge] = []
        self.outgoing_edges:List[Edge] = []
    
    def get_coord(self) -> Tuple[int, int]:
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
    

class RoadNet:
    VERSION = "1.0"
    def __init__(self):
        self.nodes:Dict[str, Node] = {}
        self.edges:Dict[str, Edge] = {}
        self.gl:Dict[Node, Edge] = {}
    
    def add_node(self, node_id:str, x:int, y:int) -> Node:
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
    
    def add_edge(self, edge_id:str, from_node:Union[str, Node], to_node:Union[str, Node], 
            length_m:float, lanes:int, speed_limit:float, world_id:int = -1) -> Edge:
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
        return ret
    
    @staticmethod
    def load_sumo(fname:str):
        ret = RoadNet()
        from sumolib.net import readNet, Net
        r = readNet(fname)
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
        with open(fname, 'w') as f:
            f.write(f'<roadnet v2simfmtver="{RoadNet.VERSION}">\n')
            for node in self.nodes.values():
                f.write(f'  <node id="{node.id}" x="{node.x}" y="{node.y}"/>\n')
            for edge in self.edges.values():
                f.write(f'  <edge id="{edge.id}" from="{edge.from_node.id}" to="{edge.to_node.id}" length="{edge.length}" lanes="{edge.lanes}" speed="{edge.speed_limit}" world_id="{edge.world_id}"/>\n')
            f.write("</roadnet>\n")
    
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
