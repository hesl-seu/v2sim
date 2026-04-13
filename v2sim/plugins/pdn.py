import os
from collections import defaultdict
from itertools import chain
from feasytools import TimeImplictFunc
from fpowerkit import Grid, GridSolveResult, CombinedSolver, Estimator, Calculator, LRSolverBase
from feasytools import LangLib
from ..utils import DetectFiles
from ..hub import CS
from .base import *


INF = float("inf")
EST = [Estimator.DistFlow.value, Estimator.LinDistFlow.value, Estimator.LinDistFlow2.value]
CAL = [Calculator.OpenDSS.value, Calculator.Newton.value, Calculator.NoneSolver.value]
SOLVER = ["CBC", "ECOS", "GUROBI"]

_locale = LangLib(["zh_CN", "en"])
_locale.SetLangLib("zh_CN",
    DESCRIPTION = "配电网模型",
    ERROR_NO_GRID = "未指定电网文件",
    ERROR_CS_NODE_NOT_EXIST = "错误: 充电站{0}的母线{1}在电网中不存在",
    ERROR_SOLVE_FAILED = "求解失败",
    ERROR_LAST_FAILED = "上次求解失败",
    PDN_SOLVE_FAILED = "[PDN]在时间{0}未能求解配电网. 总共失败{1}次",
    PDN_SOLVE_FAILED_CNT = "[PDN]总共求解失败{}次",
    PDN_SOLVE_OK_SINCE = "[PDN]从时间{0}开始成功求解配电网. 之前总共失败{1}次",
    DESC_ESTIMATOR = f"求解器的估计方法，必须是{EST}之一",
    DESC_CALCULATOR = f"求解器的计算方法，必须是{CAL}之一",
    DESC_MLRP = "最大负荷削减比例，0-1之间的小数",
    DESC_SOURCE_BUS = "电网的源母线，仅在使用OpenDSS计算器时有效",
    DESC_DECBUSES = "参与负荷削减的母线列表，逗号分隔，或使用%all%表示全部母线",
    DESC_SMARTCHARGE = "是否启用有序充电，YES或NO",
    DESC_CVXPYSOLVER = f"当估计器为LinDistFlow或DistFlow时使用的cvxpy求解器，必须是{SOLVER}之一"
)
_locale.SetLangLib("en",
    DESCRIPTION = "Power distribution network model",
    ERROR_NO_GRID = "No grid file specified",
    ERROR_CS_NODE_NOT_EXIST = "Error: The bus {1} of charging station {0} does not exist in the grid",
    ERROR_SOLVE_FAILED = "Failed to solve",
    ERROR_LAST_FAILED = "Last solve failed",
    PDN_SOLVE_FAILED = "[PDN] Failed to solve the PDN at time: {0}. Totally failed for {1} times",
    PDN_SOLVE_FAILED_CNT = "[PDN] Failed to solve the PDN for {} times",
    PDN_SOLVE_OK_SINCE = "[PDN] Succeed to solve the PDN since time: {0}. Previously failed for {1} times",
    DESC_ESTIMATOR = f"Estimator of the solver, must be one of {EST}",
    DESC_CALCULATOR = f"Calculator of the solver, must be one of {CAL}",
    DESC_MLRP = "Maximum load reduction proportion, a decimal between 0 and 1",
    DESC_SOURCE_BUS = "Source bus of the grid, only effective when using OpenDSS calculator",
    DESC_DECBUSES = "List of buses for load reduction, separated by commas, or use %all% for all buses",
    DESC_SMARTCHARGE = "Whether to enable smart charging, YES or NO",
    DESC_CVXPYSOLVER = f"cvxpy solver used when the estimator is LinDistFlow or DistFlow, must be one of {SOLVER}"
)

def _sv(x)->float:
    assert x is not None, _locale["ERROR_SOLVE_FAILED"]
    return x
    
class PluginPDN(PluginBase[float], IGridPlugin):
    @property
    def Description(self)->str:
        return _locale["DESCRIPTION"]
    
    @staticmethod
    def __create_closure(cslist: List[CS], Sb_MVA: float):
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
            ConfigItem("estimator", EditMode.COMBO, _locale("DESC_ESTIMATOR"), Estimator.DistFlow.value, combo_values=EST),
            ConfigItem("calculator", EditMode.COMBO, _locale("DESC_CALCULATOR"), Calculator.NoneSolver.value, combo_values=CAL),
            ConfigItem("MLRP", EditMode.ENTRY, _locale("DESC_MLRP"), 0.5),
            ConfigItem("source_bus", EditMode.ENTRY, _locale("DESC_SOURCE_BUS"), ""),
            ConfigItem("DecBuses", EditMode.ENTRY, _locale("DESC_DECBUSES"), ""),
            ConfigItem("SmartCharge", EditMode.COMBO, _locale("DESC_SMARTCHARGE"), "NO", combo_values=['YES', 'NO']),
            ConfigItem("solver", EditMode.COMBO, _locale("DESC_CVXPYSOLVER"), "ECOS", combo_values=SOLVER)
        ])
    
    def Init(self, elem:Element, inst:TrafficInst, work_dir:Path, res_dir:Path, plg_deps:'List[PluginBase]') -> float:
        '''Initialize the plugin from the XML element'''
        self.__inst = inst
        self.SetPreStep(self.PreStep)
        self.__fh = open(res_dir / "pdn_res.log", "w")
        self.SetPostSimulation(self.PostSimulation)

        res = DetectFiles(str(work_dir))
        assert res.grid, _locale["ERROR_NO_GRID"]

        # Directly use the grid instance in TrafficInst, which is already initialized with the grid file. This allows sharing the grid instance with other plugins that depend on PDN. V2G plugin will alter the grid by adding generators, which can be reflected in the shared grid instance.
        self.__gr = inst.pdn

        dec_bus = elem.get("DecBuses", "").strip()
        if dec_bus == r"%all%":
            decs = set(self.__gr.BusNames)
        else:
            decs = set(map(lambda x:x.strip(), dec_bus.split(",")))
        if elem.get("SmartCharge", "NO") == "NO":
            decs.clear()
        
        est = elem.get("estimator", "DistFlow")
        if est not in (Estimator.DistFlow.value, Estimator.LinDistFlow.value, Estimator.LinDistFlow2.value) and len(decs) > 0:
            from warnings import warn
            warn("Load reduction only supported in DistFlowSolver. Ignoring DecBuses.", UserWarning)
            decs.clear()
        est_solver = elem.get("solver", "CBC")

        cal = Calculator(elem.get("calculator", "None"))
        if cal == Calculator.OpenDSS:
            source_bus = elem.get("source_bus", "")
        else:
            source_bus = ""
        
        self.__save_to = str(res_dir / "pdn_logs")
        self.__sol = CombinedSolver(self.__gr,
            estimator = Estimator(est),
            estimator_solver = est_solver,
            calculator = Calculator(cal),
            mlrp = float(elem.get("MLRP", "0.5")),
            source_bus = source_bus,
            default_saveto = self.__save_to,
        )

        self.__sol.SetErrorSaveTo(self.__save_to)
        self.__badcnt = 0
        self.__pds:dict[str, List[CS]] = defaultdict(list)
        for c in chain(inst.FCSList, inst.SCSList):
            if not c.bus in self.__gr.BusNames:
                raise ValueError(_locale["ERROR_CS_NODE_NOT_EXIST"].format(c.name,c.bus))
            self.__pds[c.bus].append(c)
        
        # Max load reduction proportion for each CS, used for statistics
        self.__max_reduce_prop_cs:Dict[str, float] = {}

        # Max load reduction proportion for each bus, used for statistics
        self.__max_reduce_prop:Dict[str, float] = {}

        for b, css in self.__pds.items():
            v = TimeImplictFunc(self.__create_closure(css, self.__gr.Sb_MVA))
            self.__gr.Bus(b).Pd += v
            if b in decs:
                assert isinstance(self.__sol.est, LRSolverBase)
                self.__sol.est.AddReduce(b, v)
                self.__max_reduce_prop[b] = 0.0
                print(f"Enable load reduction at bus {b}", file = self.__fh)
        self.last_ok = GridSolveResult.Failed
        return 1e100

    def isSmartChargeEnabled(self) -> bool:
        '''Check if smart charging is enabled'''
        if isinstance(self.__sol.est, LRSolverBase):
            return len(self.__sol.est.DecBuses) > 0
        else:
            return False
    
    def HasEverFailed(self) -> bool:
        '''Check if the PDN has ever failed to solve'''
        return self.__badcnt > 0
    
    @property
    def Solver(self):
        return self.__sol
    
    @property
    def Grid(self) -> Grid:
        '''Get the grid instance'''
        return self.__gr
    
    def PreStep(self, _t:int, /, sta:PluginStatus) -> Tuple[bool, float]:
        '''Solve the optimal generation plan of the distribution network at time _t, 
        the solution result can be found in the relevant values of the Grid instance'''
        if sta == PluginStatus.EXECUTE:
            ok, val = self.__sol.solve(_t)
            if ok == GridSolveResult.Failed:
                print(f"[{_t}] Fail.", file = self.__fh)
                self.__gr.savePQofBus(os.path.join(self.__save_to, f"{_t}_load.csv"), _t)
                self.__badcnt += 1
                if self.__badcnt > 0 and self.__badcnt % 20 == 0:
                    print(_locale["PDN_SOLVE_FAILED_CNT"].format(self.__badcnt))
                if self.last_ok:
                    print(_locale["PDN_SOLVE_FAILED"].format(_t,self.__badcnt))
            else:
                self.__gr.ApplyAllESS(_t - self.LastTime)
                if ok == GridSolveResult.OKwithoutVICons or ok == GridSolveResult.SubOKwithoutVICons:
                    print(f"[{_t}] Relax.", file = self.__fh)
                if self.isSmartChargeEnabled():
                    assert isinstance(self.__sol.est, LRSolverBase)
                    for c in chain(self.__inst.fcs, self.__inst.scs):
                        c.set_Pc_lim(INF)
                    for b, x in self.__sol.est.DecBuses.items():
                        if x.Reduction:
                            tot = x.Limit(_t)
                            k = (tot - x.Reduction) / tot
                            print(f"[{_t}] Load reduction: bus = {b}, proportion = {k:.6f}, " +
                                  f"load = {x.Reduction * self.__gr.Sb_kVA:.2f} kW", file = self.__fh)
                            self.__max_reduce_prop[b] = max(self.__max_reduce_prop[b], 1 - k)
                            for c in self.__pds[b]:
                                l = k * c.Pc
                                c.set_Pc_lim(l)
                                self.__max_reduce_prop_cs[c.name] = max(self.__max_reduce_prop_cs.get(c.name, 0.0), 1 - k)
                                print(f"    CS {c.name}: {l*3600:.2f} kW <- {c.Pc_kW:.2f} kW", file = self.__fh)
            if ok != GridSolveResult.Failed and self.last_ok == GridSolveResult.Failed and self.__badcnt>0:
                print(_locale["PDN_SOLVE_OK_SINCE"].format(_t,self.__badcnt))
            self.last_ok = ok
            return ok != GridSolveResult.Failed, val
        elif sta == PluginStatus.OFFLINE:
            return True, 0
        elif sta == PluginStatus.HOLD:
            return self.LastPostStepSucceed, self.LastPreStepResult
    
    def GetMaxLoadReductionProportion(self, bus:str) -> float:
        '''Get the maximum load reduction proportion at the specified bus'''
        return self.__max_reduce_prop.get(bus, 0.0)
    
    GetMaxLoadReductionProportionOfBus = GetMaxLoadReductionProportion

    def GetMaxLoadReductionProportionOfCS(self, cs_name:str) -> float:
        '''Get the maximum load reduction proportion of the specified charging station'''
        return self.__max_reduce_prop_cs.get(cs_name, 0.0)
    
    def GetAverageMaxLoadReductionProportion(self) -> float:
        '''Get the average maximum load reduction proportion among all charging stations'''
        if len(self.__max_reduce_prop) == 0:
            return 0.0
        s = 0.0
        for b, p in self.__max_reduce_prop.items():
            s += p * len(self.__pds[b])
        s /= sum(len(v) for v in self.__pds.values())
        return s
    
    def PostSimulation(self):
        '''Post simulation processing'''
        if len(self.__max_reduce_prop) > 0:
            s = 0
            for b, p in self.__max_reduce_prop.items():
                print(f"Max load reduction proportion at bus {b}: {p:.6f}", file = self.__fh)
                s += p * len(self.__pds[b])
            s /= sum(len(v) for v in self.__pds.values())
            print(f"Average max load reduction proportion: {s:.6f}", file = self.__fh)
        self.__fh.close()
    
    @property
    def BestCost(self) -> float: 
        '''Get the cost of the best generation plan, requires the last solve to be successful'''
        assert self.LastPreStepSucceed, _locale["ERROR_LAST_FAILED"]
        return self.LastPreStepResult
    
    @property
    def GeneratorPlan(self) -> Dict[str, float]:
        '''Get the best generation plan, requires the last solve to be successful'''
        assert self.LastPreStepSucceed, _locale["ERROR_LAST_FAILED"]
        return {g.ID: _sv(g.P) for g in self.__gr.Gens}