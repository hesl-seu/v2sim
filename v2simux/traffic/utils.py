from dataclasses import dataclass
from pathlib import Path
import random, string, gzip
from typing import Optional, Set, Dict
from xml.etree import ElementTree as ET
from ..locale import Lang
from typing import List, Tuple

IntPairList = List[Tuple[int, int]]
PriceList = Tuple[List[int], List[float]]
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

def LoadFCS(filename: str) -> Set[str]:
    '''Load FCS file and return a set of node names'''
    fcs_root = ReadXML(filename).getroot()
    if fcs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    fcs_nodes = set()
    for fcs in fcs_root:
        if fcs.tag == "fcs":
            fcs_nodes.add(fcs.attrib["node"])
    return fcs_nodes

def LoadSCS(filename: str) -> Set[str]:
    '''Load SCS file and return a set of node names'''
    scs_root = ReadXML(filename).getroot()
    if scs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    scs_nodes = set()
    for scs in scs_root:
        if scs.tag == "scs":
            scs_nodes.add(scs.attrib["node"])
    return scs_nodes

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
    node_type: Optional[str] = None
    osm: Optional[str] = None
    poly: Optional[str] = None
    cscsv: Optional[str] = None
    pref: Optional[str] = None
    poi: Optional[str] = None
    
    def __getitem__(self, key: str):
        return getattr(self, key)
    
    def has(self, key: str) -> bool:
        return hasattr(self, key)
    
    def get(self, key: str) -> Optional[str]:
        return getattr(self, key, None)
    
    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) != None

@dataclass
class AddtionalTypes:
    Poly: bool
    Poi: bool
    Taz: bool

def CheckAddtionalType(file: str) -> AddtionalTypes:
    root = ReadXML(file, compressed=False).getroot()
    if root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(file))
    poly = root.find("poly") is not None
    poi = root.find("poi") is not None
    taz = root.find("taz") is not None
    return AddtionalTypes(Poly=poly, Poi=poi, Taz=taz)

def DetectFiles(dir: str) -> FileDetectResult:
    """
    Detect simulation-realted files (SUMO config, SCS, FCS, power grid, etc.) in the given directory.
    Args:
        dir (str): Directory path
    Returns:
        FileDetectResult: A dictionary containing the detected files
    """
    p = Path(dir)
    ret: Dict[str, str] = {"name": p.name}
    def add(name: str, filename: str):
        if name in ret: raise FileExistsError(Lang.ERROR_CONFIG_DIR_FILE_DUPLICATE.format(name,ret[name],filename))
        ret[name] = filename
    addtional: Set[str] = set()
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
        elif filenamel.endswith(".py"):
            add("py",filename)
        elif filenamel.endswith("node_type.txt"):
            add("node_type", filename)
        elif filenamel.endswith(".osm.xml") or filenamel.endswith(".osm.xml.gz"):
            add("osm", filename)
        elif filenamel.endswith("cs.csv"):
            add("cscsv", filename)
        elif filenamel.endswith(".v2simcfg"):
            add("pref", filename)
        elif (filenamel.endswith(".add.xml") or filenamel.endswith(".add.xml.gz") or
            filenamel.endswith(".poly.xml") or filenamel.endswith(".poly.xml.gz") or
            filenamel.endswith(".taz.xml") or filenamel.endswith(".taz.xml.gz")):
            addtional.add(Path(filename).absolute().as_posix())

    for a in addtional:
        aret = CheckAddtionalType(a)
        if aret.Poly:
            add("poly", a)
        if aret.Poi:
            add("poi", a)
        if aret.Taz:
            add("taz", a)

    return FileDetectResult(**ret)

@dataclass
class V2SimConfig:
    start_time: int = 0
    end_time: int = 172800
    traffic_step: int = 10
    seed: int = 0
    routing_method:str = "astar"
    load_state: bool = False
    save_state_on_abort: bool = False
    save_state_on_finish: bool = False
    copy_state: bool = False
    visualize: bool = False
    force_nogil: bool = False
    stats: Optional[List[str]] = None

    @staticmethod
    def load(file:str) -> 'V2SimConfig':
        """
        Load V2Sim configuration from a file.
        Args:
            file (str): Path to the configuration file
        Returns:
            V2SimConfig: A V2SimConfig object with the loaded configuration
        """
        import json
        with open(file, "r") as f:
            data = json.load(f)
        # Remove deprecated fields if present
        if "force_caching" in data:
            del data["force_caching"]
        return V2SimConfig(**data)
    
    def save(self, file:str):
        """
        Save V2Sim configuration to a file.
        Args:
            file (str): Path to the configuration file
        """
        import json
        with open(file, "w") as f:
            json.dump(self.__dict__, f, indent=4)

__all__ = [
    "IntPairList", "PriceList", "FileDetectResult", "V2SimConfig",
    "DetectFiles", "CheckFile", "ClearBakFiles", "ReadXML", "LoadFCS", "LoadSCS",
]