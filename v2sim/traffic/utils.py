from dataclasses import dataclass
from pathlib import Path
import random, string, gzip
from typing import Optional
from xml.etree import ElementTree as ET
from ..locale import Lang

IntPairList = list[tuple[int, int]]
#IntPairList.__doc__ = "List of int pairs, like [(1, 2), (3, 4)]"
PriceList = tuple[list[int], list[float]]
#PriceList.__doc__ = "Price list, like ([1, 2], [3.0, 4.0]), where the first list is the time and the second list is the price"
TWeights = tuple[float, float, float]
#TWeights.__doc__ = "Tuple of three weights, like (1.0, 2.0, 3.0)"
_letters = string.ascii_letters + string.digits


def random_string(length: int):
    return "".join(random.choice(_letters) for _ in range(length))


def ReadXML(file: str, compressed:Optional[bool]=None) -> ET.ElementTree:
    '''
    Read XML file, support compressed GZ file
        file: file path
        compressed: whether the file is compressed. If None, the function will detect it, but only .xml and .xml.gz are supported.
    '''
    filel = file.lower()
    if filel.endswith(".xml.gz") or compressed == True:
        with gzip.open(file, "rt", encoding="utf8") as f:
            return ET.ElementTree(file=f)
    elif filel.endswith(".xml") or compressed == False:
        return ET.ElementTree(file=file)
    else:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(file))

def LoadFCS(filename: str) -> set[str]:
    '''Load FCS file and return a set of edge names'''
    fcs_root = ReadXML(filename).getroot()
    if fcs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    fcs_edges = set()
    for fcs in fcs_root:
        if fcs.tag == "fcs":
            fcs_edges.add(fcs.attrib["edge"])
    return fcs_edges

def LoadSCS(filename: str) -> set[str]:
    '''Load SCS file and return a set of edge names'''
    scs_root = ReadXML(filename).getroot()
    if scs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    scs_edges = set()
    for scs in scs_root:
        if scs.tag == "scs":
            scs_edges.add(scs.attrib["edge"])
    return scs_edges
    
def GetTimeAndNetwork(file: str):
    """
    Parse the SUMO configuration file to get the simulation time and network file.
    Returns:
        bt (int): Begin time
        et (int): End time
        nf (str): Net file path
    """
    root = ReadXML(file,compressed=False).getroot()
    if root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(file))
    bt, et = -1, -1
    tnode = root.find("time")
    if isinstance(tnode, ET.Element):
        bnode = tnode.find("begin")
        enode = tnode.find("end")
        if isinstance(bnode, ET.Element) and isinstance(enode, ET.Element):
            bt, et = int(bnode.attrib.get("value", "-1")), int(enode.attrib.get("value", "-1")),
    
    nf = None
    inode = root.find("input")
    if isinstance(inode, ET.Element):
        nfnode = inode.find("net-file")
        if isinstance(nfnode, ET.Element):
            nf = nfnode.attrib.get("value")
    
    assert nf != None, "Net file must be defined!"
    return bt, et, nf

def CheckFile(file: str):
    p = Path(file)
    if p.exists():
        i = 1
        while True:
            p = Path(file + f".bak{i}")
            i += 1
            if not p.exists():
                break
        Path(file).rename(str(p))

def ClearBakFiles(dir: str):
    for x in Path(dir).iterdir():
        if not x.is_file():
            continue
        if x.suffix == ".bak":
            x.unlink()

@dataclass
class FileDetectResult:
    name: str
    fcs: Optional[str] = None
    scs: Optional[str] = None
    grid: Optional[str] = None
    net: Optional[str] = None
    veh: Optional[str] = None
    plg: Optional[str] = None
    cfg: Optional[str] = None
    taz: Optional[str] = None
    py: Optional[str] = None
    taz_type: Optional[str] = None
    osm: Optional[str] = None
    poly: Optional[str] = None
    cscsv: Optional[str] = None
    
    def __getitem__(self, key: str):
        return getattr(self, key)
    
    def has(self, key: str) -> bool:
        return hasattr(self, key)
    
    def get(self, key: str) -> Optional[str]:
        return getattr(self, key, None)
    
    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) != None

def ReadSUMONet(file: str):
    """
    Read SUMO net file and return a sumolib.net.Net object.
    Args:
        file (str): Path to the SUMO net file
    Returns:
        sumolib.net.Net: A sumolib.net.Net object
    """
    import sumolib
    ret = sumolib.net.readNet(file)
    assert isinstance(ret, sumolib.net.Net), "Failed to read SUMO net file"
    return ret

def DetectFiles(dir: str) -> FileDetectResult:
    """
    Detect simulation-realted files (SUMO config, SCS, FCS, power grid, etc.) in the given directory.
    Args:
        dir (str): Directory path
    Returns:
        FileDetectResult: A dictionary containing the detected files
    """
    p = Path(dir)
    ret: dict[str, str] = {"name": p.name}
    def add(name: str, filename: str):
        if name in ret: raise FileExistsError(Lang.ERROR_CONFIG_DIR_FILE_DUPLICATE.format(name,ret[name],filename))
        ret[name] = filename
    for x in p.iterdir():
        if not x.is_file():
            continue
        filename = str(x)
        filenamel = filename.lower()
        if filenamel.endswith(".fcs.xml") or filenamel.endswith(".fcs.xml.gz"):
            add("fcs", filename)
        elif filenamel.endswith(".scs.xml") or filenamel.endswith(".scs.xml.gz"):
            add("scs", filename)
        elif filenamel.endswith(".grid.zip") or filenamel.endswith(".grid.xml"):
            add("grid", filename)
        elif filenamel.endswith(".net.xml") or filenamel.endswith(".net.xml.gz"):
            add("net", filename)
        elif filenamel.endswith(".veh.xml") or filenamel.endswith(".veh.xml.gz"):
            add("veh", filename)
        elif filenamel.endswith(".plg.xml") or filenamel.endswith(".plg.xml.gz"):
            add("plg", filename)
        elif filenamel.endswith(".sumocfg"):
            add("cfg", filename)
        elif filenamel.endswith(".taz.xml") or filenamel.endswith(".taz.xml.gz"):
            add("taz", filename)
        elif filenamel.endswith(".py"):
            add("py",filename)
        elif filenamel.endswith("taz_type.txt"):
            add("taz_type", filename)
        elif filenamel.endswith(".osm.xml") or filenamel.endswith(".osm.xml.gz"):
            add("osm", filename)
        elif filenamel.endswith(".poly.xml") or filenamel.endswith(".poly.xml.gz"):
            add("poly", filename)
        elif filenamel.endswith("cs.csv"):
            add("cscsv", filename)
    return FileDetectResult(**ret)

def FixSUMOConfig(cfg_path: str, start: int=0, end: int=172800) -> tuple[bool, ET.ElementTree, str]:
    """
    Fix the SUMO configuration file by adding time and removing report and routing nodes.
    Args:
        cfg_path (str): Path to the SUMO configuration file
        start (int): Start time (default: 0)
        end (int): End time (default: 172800)
    Returns:
        tuple[bool, ET.ElementTree, str]: A tuple containing:
            - cflag (bool): Whether the configuration file was modified
            - tr (ET.ElementTree): The modified configuration file as an ElementTree object
            - route_file_name (str): The name of the route file
    """
    cflag = False
    tr = ET.ElementTree(file = cfg_path)
    cfg = tr.getroot()
    if cfg is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(cfg_path))
    node_report = cfg.find("report")
    route_file_name = ""
    if node_report is not None:
        cfg.remove(node_report)
        cflag = True
    node_routing = cfg.find("routing")
    if node_routing is not None:
        cfg.remove(node_routing)
        cflag = True
    node_input = cfg.find("input")
    if node_input is not None:
        node_rf = node_input.find("route-files")
        if node_rf is not None:
            route_file_name = node_rf.get("value")
            if not isinstance(route_file_name, str):
                route_file_name = ""
            node_input.remove(node_rf)
            cflag = True
    node_time = cfg.find("time")
    if node_time is None:
        node_time = ET.Element("time")
        node_time.append(ET.Element("begin", {"value":str(start)}))
        node_time.append(ET.Element("end", {"value":str(end)}))
        cfg.append(node_time)
        cflag = True
    else:
        if node_time.find("begin") is None: 
            node_time.append(ET.Element("begin", {"value":str(start)}))
            cflag = True
        if node_time.find("end") is None:
            node_time.append(ET.Element("end", {"value":str(end)}))
            cflag = True
    return cflag, tr, route_file_name