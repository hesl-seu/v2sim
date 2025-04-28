from collections import defaultdict
from itertools import chain
from feasytools import TimeImplictFunc
from fpowerkit import Grid, FloatVar, GridSolveResult, CombinedSolver, Estimator, Calculator

from ..locale import CustomLocaleLib
from ..traffic import DetectFiles, CS
from .base import *

_locale = CustomLocaleLib(["zh_CN","en"])
_locale.SetLanguageLib("zh_CN",
    DESCRIPTION = "配电网模型",
    ERROR_NO_GRID = "未指定电网文件",
    ERROR_CS_NODE_NOT_EXIST = "错误: 充电站{0}的母线{1}在电网中不存在",
    ERROR_SOLVE_FAILED = "求解失败",
    ERROR_LAST_FAILED = "上次求解失败",
    PDN_SOLVE_FAILED = "[PDN]在时间{0}未能求解配电网. 总共失败{1}次",
    PDN_SOLVE_FAILED_CNT = "[PDN]总共求解失败{}次",
    PDN_SOLVE_OK_SINCE = "[PDN]从时间{0}开始成功求解配电网. 之前总共失败{1}次"
)
_locale.SetLanguageLib("en",
    DESCRIPTION = "Power distribution network model",
    ERROR_NO_GRID = "No grid file specified",
    ERROR_CS_NODE_NOT_EXIST = "Error: The bus {1} of charging station {0} does not exist in the grid",
    ERROR_SOLVE_FAILED = "Failed to solve",
    ERROR_LAST_FAILED = "Last solve failed",
    PDN_SOLVE_FAILED = "[PDN] Failed to solve the PDN at time: {0}. Totally failed for {1} times",
    PDN_SOLVE_FAILED_CNT = "[PDN] Failed to solve the PDN for {} times",
    PDN_SOLVE_OK_SINCE = "[PDN] Succeed to solve the PDN since time: {0}. Previously failed for {1} times"
)

def _sv(x)->float:
    assert x is not None, _locale["ERROR_SOLVE_FAILED"]
    return x

def _isfloat(x):
    try:
        float(x)
        return True
    except:
        return False

class PluginPDN(PluginBase[float], IGridPlugin):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    @staticmethod
    def __create_closure(cslist: list[CS], Sb_MVA: float):
        def _sumP():
            return sum(c.Pc_MW for c in cslist)/Sb_MVA
        return _sumP
    
    def _save_state(self) -> object:
        '''Save the plugin state'''
        return None
        
    def _load_state(self, state:object) -> None:
        '''Load the plugin state'''

    @staticmethod
    def ElemShouldHave() -> ConfigDict:
        '''Get the plugin configuration item list'''
        return ConfigDict([
            PluginConfigItem("estimator", "combo={'values': ['distflow']}", "Estimator of the solver, must be 'distflow'", "distflow"),
            PluginConfigItem("calculator", "combo={'values': ['opendss','newton','none']}", "Calculator of the solver, can be 'opendss', 'newton' or 'none'", "none"),
            PluginConfigItem("MLRP", "entry", "Maximum load reduction percentage", 0.5),
            PluginConfigItem("source_bus", "entry", "Source bus of the grid", ""),
            PluginConfigItem("DecBuses", "entry", "List of buses for load reduction, separated by commas", ""),
            PluginConfigItem("SmartCharge", "combo={'values': ['YES', 'NO']}", "Whether to enable smart charging, 'YES' or 'NO'", "NO"),
        ])
    
    def Init(self, elem:ET.Element, inst:TrafficInst, work_dir:Path,
            res_dir:Path, plg_deps:'list[PluginBase]') -> float:
        '''Initialize the plugin from the XML element'''
        self.__inst = inst
        self.SetPreStep(self.PreStep)
        self.__fh = open(res_dir / "pdn_res.log", "w")
        self.SetPostSimulation(self.__fh.close)

        res = DetectFiles(str(work_dir))
        assert res.grid, _locale["ERROR_NO_GRID"]
        self.__gr = Grid.fromFile(res.grid, True)
        decs = list(map(lambda x:x.strip(), elem.get("DecBuses","").split(",")))
        if elem.get("SmartCharge", "NO") == "NO":
            decs.clear()
        self.__sol = CombinedSolver(self.__gr,
            estimator=Estimator(elem.get("estimator","DistFlow")),
            calculator=Calculator(elem.get("calculator", "None")),
            mlrp=float(elem.get("MLRP","0.5")),
            source_bus=elem.get("source_bus", ""),
        )
        self.__sol.SetErrorSaveTo(str(res_dir / "pdn_logs"))
        self.__badcnt = 0
        self.__pds:dict[str, list[CS]] = defaultdict(list)
        for c in chain(inst.FCSList,inst.SCSList):
            if not c.node in self.__gr.BusNames:
                raise ValueError(_locale["ERROR_CS_NODE_NOT_EXIST"].format(c.name,c.node))
            self.__pds[c.node].append(c)
        for b, css in self.__pds.items():
            v = TimeImplictFunc(self.__create_closure(css, self.__gr.Sb_MVA))
            self.__gr.Bus(b).Pd += v
            if b in decs:
                self.__sol.est.AddReduce(b, v)
        self.last_ok = GridSolveResult.Failed
        return 1e100

    def isSmartChargeEnabled(self)->bool:
        '''Check if smart charging is enabled'''
        return len(self.__sol.est.DecBuses) > 0
    
    @property
    def Solver(self):
        return self.__sol
    
    @property
    def Grid(self)->Grid:
        '''Get the grid instance'''
        return self.__gr
    
    def PreStep(self, _t:int, /, sta:PluginStatus)->tuple[bool,float]:
        '''Solve the optimal generation plan of the distribution network at time _t, 
        the solution result can be found in the relevant values of the Grid instance'''
        if sta == PluginStatus.EXECUTE:
            ok, val = self.__sol.solve(_t)
            if ok == GridSolveResult.Failed:
                self.__badcnt += 1
                if self.__badcnt>0 and self.__badcnt % 20 == 0:
                    print(_locale["PDN_SOLVE_FAILED_CNT"].format(self.__badcnt))
                if self.last_ok:
                    print(_locale["PDN_SOLVE_FAILED"].format(_t,self.__badcnt))
            else:
                self.__gr.ApplyAllESS(_t-self.LastTime)
                if ok == GridSolveResult.OKwithoutVICons or ok == GridSolveResult.SubOKwithoutVICons:
                    print(f"t={_t}, Relax!", file = self.__fh)
                if self.isSmartChargeEnabled():
                    for c in chain(self.__inst.FCSList,self.__inst.SCSList):
                        c.set_Pc_lim(float("inf"))
                    for b,x in self.__sol.est.DecBuses.items():
                        if x.Reduction:
                            tot = x.Limit(_t)
                            k = (tot - x.Reduction) / tot
                            print(f"t={_t}, Load reduction at bus {b}:",
                                  f"{x.Reduction*self.__gr.Sb_kVA:.2f} kW", file = self.__fh)
                            for c in self.__pds[b]:
                                l = k * c.Pc
                                c.set_Pc_lim(l)
                                print(f"    CS {c.name}: {l*3600:.2f} kW <- {c.Pc_kW:.2f} kW", file = self.__fh)
            if ok != GridSolveResult.Failed and self.last_ok == GridSolveResult.Failed and self.__badcnt>0:
                print(_locale["PDN_SOLVE_OK_SINCE"].format(_t,self.__badcnt))
            self.last_ok = ok
            return ok != GridSolveResult.Failed, val
        elif sta == PluginStatus.OFFLINE:
            return True, 0
        elif sta == PluginStatus.HOLD:
            return self.LastPostStepSucceed, self.LastPreStepResult
    
    @property
    def BestCost(self)->float: 
        '''Get the cost of the best generation plan, requires the last solve to be successful'''
        assert self.LastPreStepSucceed, _locale["ERROR_LAST_FAILED"]
        return self.LastPreStepResult
    
    @property
    def GeneratorPlan(self)->dict[str,float]:
        '''Get the best generation plan, requires the last solve to be successful'''
        assert self.LastPreStepSucceed, _locale["ERROR_LAST_FAILED"]
        return {g.ID: _sv(g.P) for g in self.__gr.Gens}