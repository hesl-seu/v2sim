from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union
from fpowerkit import Grid
from ..hub import MixedHub, LoadFCSList, LoadGSList, LoadSCSList
from ..locale import Lang
from ..net import RoadNet
from ..utils import DetectFiles, FileDetectResult, ReadXML
from ..veh import VDict


class CaseType(Enum):
    UXsim = "uxsim"
    SUMO = "sumo"


@dataclass
class TimeConfig:
    start_time:int
    step_length:int
    end_time:int
    
    def sumocfg_update(self, sumocfg_file:str):
        """Load from SUMO configuration file and update time settings. Return network file in the configuration."""
        from xml.etree.ElementTree import Element
        root = ReadXML(sumocfg_file, compressed=False).getroot()
        if root is None:
            raise RuntimeError(Lang.ERROR_FILE_TYPE_NOT_SUPPORTED.format(sumocfg_file))
        
        tnode = root.find("time")
        if isinstance(tnode, Element):
            bnode = tnode.find("begin")
            enode = tnode.find("end")
            if isinstance(bnode, Element):
                bt = int(bnode.get("value", "-1"))
                if bt >= 0: self.start_time = bt
            if isinstance(enode, Element):
                et = int(enode.get("value", "-1"))
                if et >= 0: self.end_time = et
        
        nf = None
        inode = root.find("input")
        if isinstance(inode, Element):
            nfnode = inode.find("net-file")
            if isinstance(nfnode, Element):
                nf = nfnode.get("value")
        
        if nf is None: return None
        return str(Path(sumocfg_file).parent / nf)
    

@dataclass
class CaseData:
    case_dir: str
    files: FileDetectResult
    case_type: CaseType
    time_config: TimeConfig
    road_network: RoadNet
    vehicles: VDict
    mixed_hub: MixedHub
    power_network: Grid

    def reset(self):
        """
        Reset case data to initial state. 
        Note:
        1. V2G plugin will alter the grid by adding generators, it will not be reset here.
        2. Road network is assumed to be static and will not be reset.
        """
        self.vehicles.reset()
        self.mixed_hub.reset()
    
    @staticmethod
    def parse(
        case_dir:Union[str, Path], 
        tc:TimeConfig,
        silent:bool = False,
        vehicles:Optional[VDict] = None,
    ):
        """Load case from folder, and return case type, time config, road network, vehicles, and mixed hub."""
        def __print(*args, **kwargs):
            if not silent: print(*args, **kwargs)
        
        # Check if the folder exists
        proj_dir = Path(case_dir)
        if not proj_dir.exists() or not proj_dir.is_dir():
            raise FileNotFoundError(f"Invalid project directory: {case_dir}")
        
        proj = DetectFiles(proj_dir)
        # Detect mode: sumo or uxsim
        uxsim_mode = proj.sumo is None
        if proj.sumo:
            __print(Lang.INFO_ENGINE.format("SUMO"))
            __print(Lang.INFO_SUMO.format(proj.sumo))
            rnet_file = tc.sumocfg_update(proj.sumo) or proj.net
        else:
            __print(Lang.INFO_ENGINE.format("UXsim"))
            rnet_file = proj.net
        
        # Detect road network file
        if rnet_file is None: raise RuntimeError(Lang.ERROR_NET_FILE_NOT_SPECIFIED)
        if uxsim_mode:
            rnet = RoadNet.load_raw(rnet_file)
        else:
            rnet = RoadNet.load_sumo(rnet_file)
        __print(Lang.INFO_NET.format(rnet_file))
        
        # Check vehicles and trips
        if proj.veh and vehicles is None:
            vehicles = VDict.from_file(proj.veh, uxsim_mode)
            __print(Lang.INFO_TRIPS.format(proj.veh, len(vehicles)))
        else:
            if vehicles is None: raise FileNotFoundError(Lang.ERROR_TRIPS_FILE_NOT_FOUND)
            __print(Lang.INFO_TRIPS.format("<given>", len(vehicles)))

        # Check FCS file
        fcs = []
        if proj.fcs:
            fcs = LoadFCSList(proj.fcs)
            __print(Lang.INFO_FCS.format(proj.fcs, len(fcs)))

        # Check SCS file
        scs = []
        if proj.scs:
            scs = LoadSCSList(proj.scs)
            __print(Lang.INFO_SCS.format(proj.scs, len(scs)))

        # Check GS file
        gs = []
        if proj.gs:
            gs = LoadGSList(proj.gs)
            __print(Lang.INFO_GS.format(proj.gs, len(gs)))
        
        # Check power network file
        if proj.grid is None:
            raise RuntimeError(Lang.ERROR_GRID_FILE_NOT_SPECIFIED)
        
        return CaseData(
            str(case_dir), proj, CaseType.UXsim if uxsim_mode else CaseType.SUMO,
            tc, rnet, vehicles, MixedHub(fcs, scs, gs), Grid.fromFile(proj.grid)
        )

__all__ = ["CaseType", "TimeConfig", "CaseData"]