import gzip, sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Iterable, Optional, Set, Dict, List, Tuple, Union
from xml.etree.ElementTree import ElementTree
from .locale import Lang


PathLike = Union[str, Path]
CONFIG_DIR = Path.home() / ".v2sim"
SAVED_STATE_FOLDER = "saved_state"
RECENT_PROJECTS_FILE = CONFIG_DIR / "recent_projects.txt"


def ClearRecentProjects():
    if RECENT_PROJECTS_FILE.exists():
        RECENT_PROJECTS_FILE.unlink()

def GetRecentProjects() -> List[str]:
    if not RECENT_PROJECTS_FILE.exists():
        return []
    with open(RECENT_PROJECTS_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def AddRecentProject(path: Union[str, Iterable[str]]):
    if isinstance(path, str):
        path = [path]
    elif not isinstance(path, list):
        path = list(path)
    projects = GetRecentProjects()
    for p in reversed(path):
        p = str(Path(p).absolute().resolve())
        if p in projects:
            projects.remove(p)
        projects.insert(0, p)
    with open(RECENT_PROJECTS_FILE, "w") as f:
        for proj in projects: # Keep only the 10 most recent projects
            f.write(proj + "\n")

def ReadXML(file: PathLike, compressed:Optional[bool]=None) -> ElementTree:
    '''
    Read XML file, support compressed GZ file
        file: file path
        compressed: whether the file is compressed. If None, the function will detect it, but only .xml and .xml.gz are supported.
    '''
    filel = str(file).lower()
    if filel.endswith(".xml.gz") or compressed == True:
        with gzip.open(file, "rt", encoding="utf8") as f:
            return ElementTree(file=f)
    elif filel.endswith(".xml") or compressed == False:
        return ElementTree(file=file)
    else:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(file))

def LoadFCS(filename: PathLike) -> Set[str]:
    '''Load FCS file and return a set of node names'''
    fcs_root = ReadXML(filename).getroot()
    if fcs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    fcs_nodes = set()
    for fcs in fcs_root:
        if fcs.tag == "fcs":
            fcs_nodes.add(fcs.attrib["node"])
    return fcs_nodes

def LoadSCS(filename: PathLike) -> Set[str]:
    '''Load SCS file and return a set of node names'''
    scs_root = ReadXML(filename).getroot()
    if scs_root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(filename))
    scs_nodes = set()
    for scs in scs_root:
        if scs.tag == "scs":
            scs_nodes.add(scs.attrib["node"])
    return scs_nodes

def CheckFile(file: PathLike):
    file_str = str(file)
    p = Path(file)
    if p.exists():
        i = 1
        while True:
            p = Path(file_str + f".bak{i}")
            i += 1
            if not p.exists(): break
        Path(file).rename(str(p))

def ClearBakFiles(dir: PathLike):
    for x in Path(dir).iterdir():
        if not x.is_file(): continue
        if x.suffix == ".bak": x.unlink()

@dataclass
class FileDetectResult:
    name: str
    sumo: Optional[str] = None
    fcs: Optional[str] = None
    scs: Optional[str] = None
    gs: Optional[str] = None
    grid: Optional[str] = None
    net: Optional[str] = None
    veh: Optional[str] = None
    plg: Optional[str] = None
    cfg: Optional[str] = None
    taz: Optional[str] = None
    py: Optional[str] = None
    node_type: Optional[str] = None
    taz_type: Optional[str] = None
    osm: Optional[str] = None
    poly: Optional[str] = None
    cscsv: Optional[str] = None
    gscsv: Optional[str] = None
    pref: Optional[str] = None
    poi: Optional[str] = None
    vtypes: Optional[str] = None
    saved_state: Optional[str] = None
    last_result_state: Optional[str] = None
    
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

def CheckAddtionalType(file: PathLike) -> AddtionalTypes:
    root = ReadXML(file, compressed=False).getroot()
    if root is None:
        raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(file))
    poly = root.find("poly") is not None
    poi = root.find("poi") is not None
    taz = root.find("taz") is not None
    return AddtionalTypes(Poly=poly, Poi=poi, Taz=taz)

def DetectFiles(dir: PathLike) -> FileDetectResult:
    """
    Detect simulation-realted files (SUMO config, SCS, FCS, power grid, etc.) in the given directory.
    Args:
        dir (str): Directory path
    Returns:
        FileDetectResult: A dictionary containing the detected files
    """
    p = Path(dir) if isinstance(dir, str) else dir
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
        if filenamel.endswith(".sumocfg"):
            add("sumo", filename)
        elif filenamel.endswith(".fcs.xml") or filenamel.endswith(".fcs.xml.gz"):
            add("fcs", filename)
        elif filenamel.endswith(".scs.xml") or filenamel.endswith(".scs.xml.gz"):
            add("scs", filename)
        elif filenamel.endswith(".gs.xml") or filenamel.endswith(".gs.xml.gz"):
            add("gs", filename)
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
        elif filenamel.endswith("taz_type.txt"):
            add("taz_type", filename)
        elif filenamel.endswith(".osm.xml") or filenamel.endswith(".osm.xml.gz"):
            add("osm", filename)
        elif filenamel.endswith("cs.csv"):
            add("cscsv", filename)
        elif filenamel.endswith("gs.csv"):
            add("gscsv", filename)
        elif filenamel.endswith(".v2simcfg"):
            add("pref", filename)
        elif filenamel == "vtypes.xml":
            add("vtypes", filename)
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
    
    if (p / SAVED_STATE_FOLDER).exists():
        add("saved_state", (p / SAVED_STATE_FOLDER).as_posix())
    
    if (p / "results" / SAVED_STATE_FOLDER).exists():
        add("last_result_state", (p / "results" / SAVED_STATE_FOLDER).as_posix())

    return FileDetectResult(**ret)


_DEPRECATED_FIELDS = {"force_caching", "force_nogil", "inital_state_dir"}
_RENAME_FIELDS = {
    "show_uxsim_info": "ux_show_info",
    "disable_parallel": "ux_no_para",
}

CHARGING_MODES = ("unordered", "smartcharge", "v2g", "v2g_manual")


@dataclass
class V2SimConfig:
    start_time: int = 0
    end_time: int = 172800
    break_time: int = -1
    traffic_step: int = 10
    seed: int = 0
    routing_method:str = "astar"
    load_state: int = 0
    save_state_on_abort: bool = False
    save_state_on_finish: bool = False
    copy_state: bool = False
    visualize: bool = False
    ux_no_para: bool = False
    ux_show_info: bool = False
    ux_rand: bool = False
    ux_internal_step_len: Optional[int] = None
    sumo_ignore_driving: bool = False
    sumo_raise_routing_error: bool = False
    sumo_mesosim: bool = False
    stats: Optional[List[str]] = None
    allow_scs_redirect: bool = False
    add_veh_to_scs: bool = False

    # Integrated power-distribution-network settings.  PDN and V2G are core
    # simulation features and are configured only through *.v2simcfg.
    charging_mode: str = "unordered"
    pdn_interval: int = 300
    v2g_online: List[Tuple[int, int]] = field(default_factory=list)
    pdn_estimator: str = "DistFlow"
    pdn_calculator: str = "None"
    pdn_mlrp: float = 0.5
    pdn_source_bus: str = ""
    pdn_dec_buses: str = "%all%"
    pdn_solver: str = "ECOS"
    pdn_max_workers: int = 1
    # If a v2g_manual command is infeasible, optionally fall back to the
    # original market/OPF-driven V2G mechanism for that control interval.
    v2g_manual_fallback_to_v2g: bool = False

    def __post_init__(self):
        self.charging_mode = str(self.charging_mode).lower()
        if self.charging_mode not in CHARGING_MODES:
            raise ValueError(
                f"Invalid charging_mode {self.charging_mode!r}; "
                f"expected one of {', '.join(CHARGING_MODES)}"
            )
        self.pdn_interval = max(1, int(self.pdn_interval))
        self.pdn_max_workers = max(1, int(self.pdn_max_workers))
        self.pdn_mlrp = float(self.pdn_mlrp)
        self.v2g_manual_fallback_to_v2g = bool(self.v2g_manual_fallback_to_v2g)
        if self.v2g_online is None:
            self.v2g_online = []
        normalized_v2g_online: List[Tuple[int, int]] = []
        for r in self.v2g_online:
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                raise ValueError("Each v2g_online range must be [start, end]")
            start, end = int(r[0]), int(r[1])
            if start >= end:
                raise ValueError("Each v2g_online range must satisfy start < end")
            normalized_v2g_online.append((start, end))
        self.v2g_online = normalized_v2g_online
        if self.charging_mode in ("v2g", "v2g_manual") and not self.v2g_online:
            raise ValueError(
                "V2G charging modes require at least one explicit v2g_online range"
            )

    @staticmethod
    def load(file:Union[str, Path]) -> 'V2SimConfig':
        """
        Load V2Sim configuration from a file.
        Args:
            file (str or Path): Path to the configuration file
        Returns:
            V2SimConfig: A V2SimConfig object with the loaded configuration
        """
        import json
        try:
            with open(file, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            # Return default config if the file doesn't exist
            print(f"Warning: Configuration file {file} not found. Using default configuration.")
            return V2SimConfig()
        except json.JSONDecodeError:
            # Return default config if the file is invalid
            print(f"Warning: Failed to parse JSON from {file}. Using default configuration.")
            return V2SimConfig() 
        
        if not isinstance(data, dict):
            # Return default config if the file is invalid
            return V2SimConfig() 
        
        # Remove deprecated fields if present
        for field in _DEPRECATED_FIELDS:
            if field in data: del data[field]
        
        # Rename fields if present       
        for old_name, new_name in _RENAME_FIELDS.items():
            if old_name in data: data[new_name] = data.pop(old_name)

        allowed = {x.name for x in fields(V2SimConfig)}
        unknown = sorted(set(data).difference(allowed))
        if unknown:
            raise ValueError("Unknown V2Sim configuration fields: " + ", ".join(unknown))

        return V2SimConfig(**data)
    
    def save(self, file:str):
        """
        Save V2Sim configuration to a file.
        Args:
            file (str): Path to the configuration file
        """
        import json
        with open(file, "w", newline="\r\n", encoding="utf-8") as f:
            json.dump(self.__dict__, f, indent=4)


def PyVersion() -> Tuple[int, int, int, bool]:
    ver_info = sys.version_info
    has_gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True # type: ignore
    return (ver_info.major, ver_info.minor, ver_info.micro, has_gil)

def CheckPyVersion(ver:Tuple[int, int, int, bool]) -> bool:
    cur_ver = PyVersion()
    # Allow micro version difference
    return ver[0] == cur_ver[0] and ver[1] == cur_ver[1] and ver[3] == cur_ver[3]

__all__ = [
    "FileDetectResult", "V2SimConfig", "CHARGING_MODES", "PyVersion", "CheckPyVersion", "CONFIG_DIR",
    "DetectFiles", "CheckFile", "ClearBakFiles", "ReadXML", "LoadFCS", "LoadSCS", "SAVED_STATE_FOLDER",
    "GetRecentProjects", "AddRecentProject", "RECENT_PROJECTS_FILE", "ClearRecentProjects"
]