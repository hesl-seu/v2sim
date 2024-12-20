from dataclasses import dataclass
from pathlib import Path
import random, string, gzip
from typing import Optional
from xml.etree import ElementTree as ET
from ..locale import Lang

TWeights = tuple[float, float, float]
_letters = string.ascii_letters + string.digits


def random_string(length: int):
    return "".join(random.choice(_letters) for _ in range(length))


def readXML(file: str, compressed:Optional[bool]=None) -> ET.ElementTree:
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


def load_fcs(filename: str) -> set[str]:
    fcs_root = readXML(filename).getroot()
    fcs_edges = set()
    for fcs in fcs_root:
        if fcs.tag == "fcs":
            fcs_edges.add(fcs.attrib["edge"])
    return fcs_edges


def load_scs(filename: str) -> set[str]:
    scs_root = readXML(filename).getroot()
    scs_edges = set()
    for scs in scs_root:
        if scs.tag == "scs":
            scs_edges.add(scs.attrib["edge"])
    return scs_edges
    
def get_sim_config(file: str):
    """Parse the SUMO configuration file"""
    root = readXML(file,compressed=False).getroot()

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
    return bt,et,nf

@dataclass
class SUMOConfig:
    BeginTime: int
    EndTime: int
    NetFile: str

def GetSUMOConfig(file: str) -> SUMOConfig:
    return SUMOConfig(*get_sim_config(file))


def _checkFile(file: str):
    p = Path(file)
    if p.exists():
        i = 1
        while True:
            p = Path(file + f".bak{i}")
            i += 1
            if not p.exists():
                break
        Path(file).rename(str(p))

CheckFile = _checkFile

def _clearBakFiles(dir: str):
    for x in Path(dir).iterdir():
        if not x.is_file():
            continue
        if x.suffix == ".bak":
            x.unlink()   

ClearBakFiles = _clearBakFiles

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

def DetectFiles(dir: str) -> FileDetectResult:
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