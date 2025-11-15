from v2simux.gui.common import *
from v2simux.gui.langhelper import *

import os
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from fpowerkit import Grid as PowerGrid
from feasytools import RangeList, PDUniform
from v2simux import (
    FileDetectResult, TrafficGenerator, V2SimConfig, DetectFiles,
    ReadXML, PluginBase, PluginPDN, RoadNet, csQuery, TripsGenMode, RoutingCacheMode
)
from .utils import *
from .loadingbox import LoadingBox
from .plugin import PluginEditor
from .cseditor import CSEditorGUI
from .cscsveditor import CSCSVEditor
from .controls import LogItemPad, PropertyPanel, PDFuncEditor, ALWAYS_ONLINE, NetworkPanel, OAfter


_L = LangLib.Load(__file__)
DEFAULT_GRID = '<grid Sb="1MVA" Ub="10.0kV" model="ieee33" fixed-load="false" grid-repeat="1" load-repeat="8" />'
LOAD_FCS = "Fast CS"
LOAD_SCS = "Slow CS"
LOAD_NET = "Network"
LOAD_CSCSV = "CS CSV"
LOAD_PLG = "Plugins"
LOAD_GEN = "Instance"
    

class MainBox(Tk):
    def __OnPluginEnabledSet(self, itm:Tuple[Any,...]=(), v:str=""):
        plgs = self.sim_plglist.GetEnabledPlugins()
        self.sim_statistic.check_by_enabled_plugins(plgs)
    
    def __init__(self, to_open:str = ""):
        super().__init__()
        self._Q = EventQueue(self)
        
        def proc_exception(e: Optional[Exception] = None):
            if e:
                self.setStatus(f"Error: {e}")
                showerr(f"Error: {e}")
            else:
                self.setStatus(_L["STA_READY"])
       
        def on_CSGendone(ctl: CSEditorGUI, e: Optional[Exception] = None,
                    warns:List[Tuple] = [], far_cnt = 0, scc_cnt = 0):
            ctl.btn_regen.config(state=NORMAL)
            proc_exception(e)

            if len(warns) == 0: return
            
            with open("CS_generation_warnings.log", "w") as fh:
                for ln in warns:
                    if ln[0] == "far_poly":
                        fh.write(f"A polygon (center: {ln[1]:.1f},{ln[2]:.1f}) is far away ({ln[3]:.1f}m) from the road network.\n")
                    elif ln[0] == "scc_poly":
                        fh.write(f"A polygon (center: {ln[1]:.1f},{ln[2]:.1f}) is not neighbouring to an edge in the largest SCC and allowing passengers.\n")
                    elif ln[0] == "far_down":
                        fh.write(f"Point {ln[1]},{ln[2]} (XY: {ln[3]:.1f},{ln[4]:.1f}) is far away ({ln[5]:.1f}m) from the road network.\n")
                    elif ln[0] == "scc_down":
                        fh.write(f"The nearest edge of point {ln[1]},{ln[2]} (XY: {ln[3]:.1f},{ln[4]:.1f}) is not in the max SCC which allows passengers.\n")
                    elif ln[0] == "scc_name":
                        fh.write(f"Edge {ln[1]} disallows passenger vehicles.")

            text = "Some warnings have been written in CS_generation_warnings.log:"
            if far_cnt: 
                text += f"{far_cnt} CS(s) are abondoned since their distance to the nearest edge is greater than 200m."
            if scc_cnt: 
                if text != "": text += "\n"
                text += f"{far_cnt} CS(s) are abondoned since they are not in the largest strongly connected component or disallow passenger vehicles."
            showwarn(text)
        
        self._Q.register("CSGenDone", on_CSGendone)

        def on_VehGenDone(e: Optional[Exception] = None):
            self.btn_genveh.config(state = NORMAL)
            proc_exception(e)
        
        self._Q.register("VehGenDone", on_VehGenDone)

        def on_CSCSVDownloadDone(e: Optional[Exception] = None):
            proc_exception(e)
        
        self._Q.register("CSCSVDownloadDone", on_CSCSVDownloadDone)

        def on_TrafficGenLoaded():
            self._ldfrm.setText(LOAD_GEN, _L['DONE'])
        self._Q.register("TrafficGenLoaded", on_TrafficGenLoaded)

        
        self._Q.register("cvnetloaded", self.on_cvnet_loaded)

        self.folder:str = to_open
        self.state:Optional[FileDetectResult] = None
        self.tg:Optional[TrafficGenerator] = None
        self._win()

        self.menu = Menu(self)
        self.menuFile = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_L["MENU_PROJ"], menu=self.menuFile)
        self.menuFile.add_command(label=_L["MENU_OPEN"], command=self.openFolder, accelerator='Ctrl+O')
        self.bind("<Control-o>", lambda e: self.openFolder())
        self.menuFile.add_command(label=_L["MENU_SAVEALL"], command=self.save, accelerator="Ctrl+S")
        self.bind("<Control-s>", lambda e: self.save())
        self.menuFile.add_separator()
        self.menuFile.add_command(label=_L["MENU_EXIT"], command=self.onDestroy, accelerator='Ctrl+Q')
        self.bind("<Control-q>", lambda e: self.onDestroy())
        add_lang_menu(self.menu)
        self.config(menu=self.menu)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.panel_info = Frame(self, borderwidth=1, relief="solid")
        self.panel_info.grid(row=0, column=0, padx=3, pady=3, sticky="nsew")

        self.lb_infotitle = Label(self.panel_info, text = _L["BAR_PROJINFO"], background="white")
        self.lb_infotitle.grid(row=0, column=0, columnspan=2, padx=3, pady=3, sticky="nsew")

        self.lb_fcs_indicatif = Label(self.panel_info, text = _L["BAR_FCS"])
        self.lb_fcs_indicatif.grid(row=1, column=0, padx=3, pady=3)
        self.lb_fcs = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_fcs.grid(row=1, column=1, padx=3, pady=3)

        self.lb_scs_indicatif = Label(self.panel_info, text = _L["BAR_SCS"])
        self.lb_scs_indicatif.grid(row=2, column=0, padx=3, pady=3)
        self.lb_scs = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_scs.grid(row=2, column=1, padx=3, pady=3)

        self.lb_grid_indicatif = Label(self.panel_info, text = _L["BAR_GRID"])
        self.lb_grid_indicatif.grid(row=3, column=0, padx=3, pady=3)
        self.lb_grid = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_grid.grid(row=3, column=1, padx=3, pady=3)

        self.lb_net_indicatif = Label(self.panel_info, text = _L["BAR_RNET"])
        self.lb_net_indicatif.grid(row=4, column=0, padx=3, pady=3)
        self.lb_net = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_net.grid(row=4, column=1, padx=3, pady=3)

        self.lb_veh_indicatif = Label(self.panel_info, text = _L["BAR_VEH"])
        self.lb_veh_indicatif.grid(row=5, column=0, padx=3, pady=3)
        self.lb_veh = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_veh.grid(row=5, column=1, padx=3, pady=3)

        self.lb_plg_indicatif = Label(self.panel_info, text = _L["BAR_PLG"])
        self.lb_plg_indicatif.grid(row=6, column=0, padx=3, pady=3)
        self.lb_plg = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_plg.grid(row=6, column=1, padx=3, pady=3)

        self.lb_cscsv_indicatif = Label(self.panel_info, text = _L["BAR_CSCSV"])
        self.lb_cscsv_indicatif.grid(row=7, column=0, padx=3, pady=3)
        self.lb_cscsv = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_cscsv.grid(row=7, column=1, padx=3, pady=3)

        self.lb_node_type_indicatif = Label(self.panel_info, text = _L["BAR_NODETYPE"])
        self.lb_node_type_indicatif.grid(row=8, column=0, padx=3, pady=3)
        self.lb_node_type = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_node_type.grid(row=8, column=1, padx=3, pady=3)

        self.lb_py_indicatif = Label(self.panel_info, text = _L["BAR_ADDON"])
        self.lb_py_indicatif.grid(row=9, column=0, padx=3, pady=3)
        self.lb_py = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_py.grid(row=9, column=1, padx=3, pady=3)

        self.lb_osm_indicatif = Label(self.panel_info, text = _L["BAR_OSM"])
        self.lb_osm_indicatif.grid(row=10, column=0, padx=3, pady=3)
        self.lb_osm = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_osm.grid(row=10, column=1, padx=3, pady=3)

        self.lb_poly_indicatif = Label(self.panel_info, text = _L["BAR_POLY"])
        self.lb_poly_indicatif.grid(row=11, column=0, padx=3, pady=3)
        self.lb_poly = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_poly.grid(row=11, column=1, padx=3, pady=3)

        self.lb_poi_indicatif = Label(self.panel_info, text = _L["BAR_POI"])
        self.lb_poi_indicatif.grid(row=12, column=0, padx=3, pady=3)
        self.lb_poi = Label(self.panel_info, text = _L["BAR_NONE"])
        self.lb_poi.grid(row=12, column=1, padx=3, pady=3)

        self.tabs = Notebook(self)
        self.tabs.grid(row=0, column=1, padx=3, pady=3, sticky="nsew")

        self.tab_sim = Frame(self.tabs)
        self.sim_time = LabelFrame(self.tab_sim, text=_L["SIM_BASIC"])
        self.sim_time.pack(fill="x", expand=False)
        self.lb_start = Label(self.sim_time, text=_L["SIM_BEGT"])
        self.lb_start.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.entry_start = Entry(self.sim_time)
        self.entry_start.insert(0, "0")
        self.entry_start.grid(row=0, column=1, padx=3, pady=3, sticky="w")

        self.lb_break = Label(self.sim_time, text=_L["SIM_BREAKT"])
        self.lb_break.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.entry_break = Entry(self.sim_time)
        self.entry_break.insert(0, "172800")
        self.entry_break.grid(row=1, column=1, padx=3, pady=3, sticky="w")

        self.lb_end = Label(self.sim_time, text=_L["SIM_ENDT"])
        self.lb_end.grid(row=2, column=0, padx=3, pady=3, sticky="w")
        self.entry_end = Entry(self.sim_time)
        self.entry_end.insert(0, "172800")
        self.entry_end.grid(row=2, column=1, padx=3, pady=3, sticky="w")

        self.lb_step = Label(self.sim_time, text=_L["SIM_STEP"])
        self.lb_step.grid(row=3, column=0, padx=3, pady=3, sticky="w")
        self.entry_step = Entry(self.sim_time)
        self.entry_step.insert(0, "10")
        self.entry_step.grid(row=3, column=1, padx=3, pady=3, sticky="w")

        self.lb_seed = Label(self.sim_time, text=_L["SIM_SEED"])
        self.lb_seed.grid(row=4, column=0, padx=3, pady=3, sticky="w")
        self.entry_seed = Entry(self.sim_time)
        self.entry_seed.insert(0, "0")
        self.entry_seed.grid(row=4, column=1, padx=3, pady=3, sticky="w")

        self.sim_state_load_panel = Frame(self.sim_time)
        self.sim_state_load_panel.grid(row=0, column=2, padx=0, pady=0, sticky="w")

        self.sim_lb_state_load = Label(self.sim_state_load_panel, text=_L["SIM_STATE_LOAD_OPTIONS"])
        self.sim_lb_state_load.grid(row=0, column=0, padx=3, pady=3, sticky="w")

        self.sim_load_state = IntVar(self, 0)

        self.sim_cb_no_load_state = Radiobutton(self.sim_state_load_panel, text=_L["SIM_NO_LOAD_STATE"], 
            value=0, variable=self.sim_load_state, command=self.on_load_state_changed)
        self.sim_cb_no_load_state.grid(row=0, column=1, padx=3, pady=3, sticky="w")
        
        self.sim_cb_load_last_state = Radiobutton(self.sim_state_load_panel, text=_L["SIM_LOAD_LAST_STATE"],
            value=1, variable=self.sim_load_state, command=self.on_load_state_changed)
        self.sim_cb_load_last_state.grid(row=0, column=2, padx=3, pady=3, sticky="w")

        self.sim_cb_load_saved_state = Radiobutton(self.sim_state_load_panel, text=_L["SIM_LOAD_SAVED_STATE"],
            value=2, variable=self.sim_load_state, command=self.on_load_state_changed)
        self.sim_cb_load_saved_state.grid(row=0, column=3, padx=3, pady=3, sticky="w")

        self.sim_state_save_panel = Frame(self.sim_time)
        self.sim_state_save_panel.grid(row=1, column=2, padx=0, pady=0, sticky="w")
        
        self.sim_lb_state_save = Label(self.sim_state_save_panel, text=_L["SIM_STATE_SAVE_OPTIONS"])
        self.sim_lb_state_save.grid(row=0, column=0, padx=3, pady=3, sticky="w")

        self.sim_save_on_abort = BooleanVar(self, False)
        self.sim_cb_save_on_abort = Checkbutton(self.sim_state_save_panel, text=_L["SIM_SAVE_ON_ABORT"], variable=self.sim_save_on_abort)
        self.sim_cb_save_on_abort.grid(row=0, column=1, padx=3, pady=3, sticky="w")

        self.sim_save_on_finish = BooleanVar(self, False)
        self.sim_cb_save_on_finish = Checkbutton(self.sim_state_save_panel, text=_L["SIM_SAVE_ON_FINISH"], variable=self.sim_save_on_finish)
        self.sim_cb_save_on_finish.grid(row=0, column=2, padx=3, pady=3, sticky="w")

        self.sim_copy_state = BooleanVar(self, False)
        self.sim_cb_copy_state = Checkbutton(self.sim_state_save_panel, text=_L["SIM_COPY_STATE"], variable=self.sim_copy_state)
        self.sim_cb_copy_state.grid(row=0, column=3, padx=3, pady=3, sticky="w")

        self.sim_ux_options_panel = Frame(self.sim_time)
        self.sim_ux_options_panel.grid(row=2, column=2, padx=0, pady=0, sticky="w")
        
        self.sim_no_parallel = BooleanVar(self, False)
        self.sim_cb_no_parallel = Checkbutton(self.sim_ux_options_panel, text=_L["SIM_NO_PARALLEL"], variable=self.sim_no_parallel)
        self.sim_cb_no_parallel.grid(row=0, column=0, padx=3, pady=3, sticky="w")

        self.sim_show_uxsim_info = BooleanVar(self, False)
        self.sim_cb_show_uxsim_info = Checkbutton(self.sim_ux_options_panel, text=_L["SIM_SHOW_UXSIM_INFO"], variable=self.sim_show_uxsim_info)
        self.sim_cb_show_uxsim_info.grid(row=0, column=1, padx=3, pady=3, sticky="w")

        self.sim_randomize_traffic = BooleanVar(self, False)
        self.sim_cb_randomize_traffic = Checkbutton(self.sim_ux_options_panel, text=_L["SIM_RANDOMIZE_TRAFFIC"], variable=self.sim_randomize_traffic)
        self.sim_cb_randomize_traffic.grid(row=0, column=2, padx=3, pady=3, sticky="w")

        self.sim_algo_panel = Frame(self.sim_time)
        self.sim_algo_panel.grid(row=4, column=2, padx=0, pady=0, sticky="w")

        self.ralgo = StringVar(self, "astar")
        self.lb_route_algo = Label(self.sim_algo_panel, text=_L["SIM_ROUTE_ALGO"])
        self.lb_route_algo.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.combo_ralgo = Combobox(self.sim_algo_panel, textvariable=self.ralgo, values=["dijkstra", "astar"])
        self.combo_ralgo.grid(row=0, column=1, padx=3, pady=3, sticky="w")

        self.sim_plugins = LabelFrame(self.tab_sim, text=_L["SIM_PLUGIN"])
        self.sim_plglist = PluginEditor(self.sim_plugins, self.__OnPluginEnabledSet)
        self.sim_plglist.pack(fill="both", expand=True)
        self.sim_plugins.pack(fill="x", expand=False)
        self.sim_plglist.setOnSave(self.savePlugins())
        self.sim_plglist.AfterFunc = self.__OnPluginEnabledSet

        self.sim_statistic = LogItemPad(self.tab_sim, _L["SIM_STAT"],self.sim_plglist.sta_pool)
        self.sim_statistic["ev"] = False
        self.sim_statistic.pack(fill="x", expand=False)
        self.__OnPluginEnabledSet()

        self.sim_btn = Button(self.tab_sim, text=_L["SIM_START"], command=self.simulate)
        self.sim_btn.pack(anchor="w", padx=3, pady=3)
        self.tabs.add(self.tab_sim, text=_L["TAB_SIM"])

        self.tab_CsCsv = Frame(self.tabs)
        self.CsCsv_editor = CSCSVEditor(self.tab_CsCsv, self.CSCSVDownloadWorker)
        self.CsCsv_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_CsCsv, text=_L["TAB_CSCSV"])

        self.tab_FCS = Frame(self.tabs)
        self.FCS_editor = CSEditorGUI(self.tab_FCS, self.generateCS, False)
        self.FCS_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_FCS, text=_L["TAB_FCS"])

        self.tab_SCS = Frame(self.tabs)
        self.SCS_editor = CSEditorGUI(self.tab_SCS, self.generateCS, True)
        self.SCS_editor.pack(fill="both", expand=True)
        self.tabs.add(self.tab_SCS, text=_L["TAB_SCS"])

        self.tab_Net = Frame(self.tabs)
        self.cv_net = NetworkPanel(self.tab_Net)
        self.cv_net.pack(fill=BOTH, expand=True)
        self.panel_net = LabelFrame(self.tab_Net, text=_L["RNET_TITLE"])
        self.lb_gridsave = Label(self.panel_net, text=_L["NOT_OPEN"])
        self.lb_gridsave.pack(side='left',padx=3,pady=3, anchor='w')
        def on_saved_changed(saved:bool):
            if saved:
                self.lb_gridsave.config(text=_L["SAVED"],foreground="green")
            else:
                self.lb_gridsave.config(text=_L["UNSAVED"],foreground="red")
        self.cv_net.save_callback = on_saved_changed
        self.btn_savegrid = Button(self.panel_net, text=_L["SAVE_GRID"], command=self.save)
        self.btn_savegrid.pack(side='left',padx=3,pady=3, anchor='w')
        self.lb_puvalues = Label(self.panel_net, text=_L["PU_VALS"].format('Null','Null'))
        self.lb_puvalues.pack(side='left',padx=3,pady=3, anchor='w')
        self.btn_savenetfig = Button(self.panel_net, text=_L["RNET_SAVE"], command=self.netsave)
        self.btn_savenetfig.pack(side="right", padx=3, pady=3, anchor="e")
        self.btn_draw = Button(self.panel_net, text=_L["RNET_DRAW"], command=self.draw)
        self.btn_draw.pack(side="right", padx=3, pady=3, anchor="e")
        self.entry_Ledges = Entry(self.panel_net)
        self.entry_Ledges.pack(side="right", padx=3, pady=3, anchor="e")
        self.lb_Ledges = Label(self.panel_net, text=_L["RNET_EDGES"])
        self.lb_Ledges.pack(side="right", padx=3, pady=3, anchor="e")
        
        self.panel_net.pack(fill="x", expand=False, anchor="s")
        self.tabs.add(self.tab_Net, text=_L["TAB_RNET"])

        self.tab_Veh = Frame(self.tabs)
        self.fr_veh_basic = LabelFrame(self.tab_Veh,text=_L["VEH_BASIC"])
        self.fr_veh_basic.pack(fill="x", expand=False)
        self.lb_carcnt = Label(self.fr_veh_basic, text=_L["VEH_COUNT"])
        self.lb_carcnt.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.entry_carcnt = Entry(self.fr_veh_basic)
        self.entry_carcnt.insert(0, "10000")
        self.entry_carcnt.grid(row=0, column=1, padx=3, pady=3, sticky="w")
        self.lb_daycnt = Label(self.fr_veh_basic, text=_L["VEH_DAY_COUNT"])
        self.lb_daycnt.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.entry_daycnt = Entry(self.fr_veh_basic)
        self.entry_daycnt.insert(0, "7")
        self.entry_daycnt.grid(row=1, column=1, padx=3, pady=3, sticky="w")
        self.lb_v2gprop = Label(self.fr_veh_basic, text=_L["VEH_V2GPROP"])
        self.lb_v2gprop.grid(row=2, column=0, padx=3, pady=3, sticky="w")
        self.entry_v2gprop = Entry(self.fr_veh_basic)
        self.entry_v2gprop.insert(0, "1.00")
        self.entry_v2gprop.grid(row=2, column=1, padx=3, pady=3, sticky="w")
        self.lb_v2gprop_info = Label(self.fr_veh_basic, text=_L["VEH_V2GPROP_INFO"])
        self.lb_v2gprop_info.grid(row=2, column=2, padx=3, pady=3, sticky="w")
        self.lb_carseed = Label(self.fr_veh_basic, text=_L["VEH_SEED"])
        self.lb_carseed.grid(row=3, column=0, padx=3, pady=3, sticky="w")
        self.entry_carseed = Entry(self.fr_veh_basic)
        self.entry_carseed.insert(0, "0")
        self.entry_carseed.grid(row=3, column=1, padx=3, pady=3, sticky="w")

        self.veh_pars = PropertyPanel(self.tab_Veh, {
            "Omega":repr(PDUniform(5.0, 10.0)),
            "KRel":repr(PDUniform(1.0, 1.2)),
            "KSC":repr(PDUniform(0.4, 0.6)),
            "KFC":repr(PDUniform(0.2, 0.25)),
            "KV2G":repr(PDUniform(0.65, 0.75)),
        }, ConfigItemDict((
            ConfigItem("Omega", EditMode.PDFUNC, _L["VEH_OMEGA_DESC"]),
            ConfigItem("KRel", EditMode.PDFUNC, _L["VEH_KREL_DESC"]),
            ConfigItem("KSC", EditMode.PDFUNC, _L["VEH_KSC_DESC"]),
            ConfigItem("KFC", EditMode.PDFUNC, _L["VEH_KFC_DESC"]),
            ConfigItem("KV2G", EditMode.PDFUNC, _L["VEH_KV2G_DESC"]),
        )))
        self.veh_pars.pack(fill="x", expand=False, pady=10)

        self.veh_gen_src = IntVar(self, 0)
        self.fr_veh_src = LabelFrame(self.tab_Veh,text=_L["VEH_ODSRC"])
        self.fr_veh_src.pack(fill="x", expand=False)
        self.rb_veh_src0 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODAUTO"], value=0, variable=self.veh_gen_src)
        self.rb_veh_src0.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_src1 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODTYPE"], value=1, variable=self.veh_gen_src)
        self.rb_veh_src1.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_src2 = Radiobutton(self.fr_veh_src, text=_L["VEH_ODPOLY"], value=2, variable=self.veh_gen_src)
        self.rb_veh_src2.grid(row=2, column=0, padx=3, pady=3, sticky="w")

        self.veh_route_cache = IntVar(self, 0)
        self.fr_veh_route_cache = LabelFrame(self.tab_Veh,text=_L["VEH_ROUTE_CACHE"])
        # self.fr_veh_route_cache.pack(fill="x", expand=False)
        self.rb_veh_route_cache0 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_NO_CACHE"], value=0, variable=self.veh_route_cache)
        self.rb_veh_route_cache0.grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_route_cache1 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_RUNTIME_CACHE"], value=1, variable=self.veh_route_cache)
        self.rb_veh_route_cache1.grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.rb_veh_route_cache2 = Radiobutton(self.fr_veh_route_cache, text=_L["VEH_ROUTE_STATIC_CACHE"], value=2, variable=self.veh_route_cache)
        self.rb_veh_route_cache2.grid(row=2, column=0, padx=3, pady=3, sticky="w")

        self.btn_genveh = Button(self.tab_Veh, text=_L["VEH_GEN"], command=self.generateVeh)
        self.btn_genveh.pack(anchor="w")
        self.tabs.add(self.tab_Veh, text=_L["TAB_VEH"])

        self.sbar = Label(self, text=_L["STA_READY"], anchor="w")
        self.sbar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.onDestroy)

        if self.folder != "":
            self.after(200, self._load)
    
    def on_load_state_changed(self):
        val = self.sim_load_state.get()
        s = NORMAL if val == 0 else DISABLED
        self.entry_start.config(state=s)
        # self.entry_break.config(state=s) # break time is always editable
        self.entry_end.config(state=s)
        self.entry_step.config(state=s)
        self.entry_seed.config(state=s)
        self.combo_ralgo.config(state=s)
        self.sim_cb_no_parallel.config(state=s)
        self.sim_cb_show_uxsim_info.config(state=s)
    
    def netsave(self):
        ret = filedialog.asksaveasfilename(
            defaultextension=".eps",
            filetypes=[
                (_L["EXT_EPS"],".eps"),             
            ]
        )
        if ret == "": return
        try:
            self.cv_net.savefig(ret)
        except RuntimeError:
            showerr(_L["RNET_SAVE_ERR"])
            return
        self.setStatus("Figure saved")

    def veh_par_edit(self, var:StringVar):
        def _f():
            e = PDFuncEditor(var)
            e.wait_window()
        return _f

    @property
    def saved(self):
        return self.sim_plglist.saved and self.FCS_editor.saved and self.SCS_editor.saved and self.cv_net.saved
    
    def save(self):
        if not self.sim_plglist.saved: self.sim_plglist.save()
        if not self.FCS_editor.saved: self.FCS_editor.save()
        if not self.SCS_editor.saved: self.SCS_editor.save()
        if not self.cv_net.saved: self.saveNet()
    
    def get_default_grid_path(self) -> str:
        return str(Path(self.folder) / Path(self.folder).name) + ".grid.xml"
    
    def get_default_roadnet_path(self) -> str:
        return str(Path(self.folder) / Path(self.folder).name) + ".net.xml"
    
    def saveNet(self):
        assert self.state is not None
        if self.state.grid:
            gpath = self.state.grid
            os.remove(gpath)
            if not gpath.lower().endswith(".xml"):
                gpath = self.get_default_grid_path()
        else:
            gpath = self.get_default_grid_path()
        if self.state.net:
            npath = self.state.net
            if not npath.lower().endswith(".xml"):
                npath = self.get_default_roadnet_path()
        else:
            npath = self.get_default_roadnet_path()
        self.cv_net.save(gpath, npath)
        
    def onDestroy(self):
        if not self.saved:
            ret = MB.askyesnocancel(_L["MB_INFO"], _L["MB_EXIT_SAVE"])
            if ret is None: return
            if ret: self.save()
        self.destroy()

    @errwrapper
    def simulate(self):
        if not self.__checkFolderOpened(): return
        start = try_int(self.entry_start.get(), "start time")
        assert start >= 0, "Start time must be non-negative integer"
        break_at = try_int(self.entry_break.get(), "break time")
        assert break_at > start, "Break time must be greater than start time"
        end = try_int(self.entry_end.get(), "end time")
        assert end >= break_at, "End time must be greater than or equal to break time"
        step = try_int(self.entry_step.get(), "time step")
        assert step > 0, "Time step must be positive integer"
        seed = try_int(self.entry_seed.get(), "random seed")
        assert self.state, "No project loaded"
        assert "scs" in self.state, "No SCS loaded"
        assert "fcs" in self.state, "No FCS loaded"
        assert "veh" in self.state, "No vehicles loaded"

        logs = []
        for x in ("fcs","scs","ev","gen","bus","line","pvw","ess"):
            if self.sim_statistic[x]:
                logs.append(x)
        assert logs, _L["NO_STA"]

        if not self.saved:
            if not MB.askyesno(_L["MB_INFO"],_L["MB_SAVE_AND_SIM"]): return
            self.save()
        
        # Save preference
        vcfg = V2SimConfig()
        vcfg.start_time = start
        vcfg.break_time = break_at
        vcfg.end_time = end
        vcfg.traffic_step = step
        vcfg.seed = seed
        vcfg.load_state = self.sim_load_state.get()
        vcfg.save_state_on_abort = self.sim_save_on_abort.get()
        vcfg.save_state_on_finish = self.sim_save_on_finish.get()
        vcfg.copy_state = self.sim_copy_state.get()
        vcfg.routing_method = self.ralgo.get()
        vcfg.disable_parallel = self.sim_no_parallel.get()
        vcfg.show_uxsim_info = self.sim_show_uxsim_info.get()
        vcfg.stats = logs
        vcfg.save(self.folder + "/preference.v2simcfg")
        
        if self.sim_load_state.get() == 0:
            cmd_load_state = ""
        elif self.sim_load_state.get() == 1:
            cmd_load_state = "--load-last-state"
        else:
            cmd_load_state = f'--initial-state="{self.folder}/saved_state"'
        commands = [sys.executable,
                    str(V2SIM_UX_DIR / "tools" / "sim_single.py"),
                    f'-d="{self.folder}"', 
                    f"-b={start}", 
                    f"--break-at={self.entry_break.get()}",
                    f"-e={end}", 
                    f"-l={step}", 
                    "-log", ','.join(logs),
                    "--seed", str(seed),
                    cmd_load_state,
                    "--save-on-abort" if self.sim_save_on_abort.get() else "",
                    "--save-on-finish" if self.sim_save_on_finish.get() else "",
                    "--copy-state" if self.sim_copy_state.get() else "",
                    "--route-algo", self.ralgo.get(),
                    "--no-parallel" if self.sim_no_parallel.get() else "",
                    "--show-uxsim-info" if self.sim_show_uxsim_info.get() else "",
                    "--randomize-uxsim" if self.sim_randomize_traffic.get() else ""
                ]
        
        self.destroy()
        try:
            os.system(" ".join(commands))
        except KeyboardInterrupt:
            pass
        

    def savePlugins(self):
        def _save(data:List[tuple]):
            if not self.__checkFolderOpened():
                return False
            self.setStatus(_L["SAVE_PLG"])
            if self.state and "plg" in self.state:
                filename = self.state["plg"]
            else:
                filename = self.folder + "/plugins.plg.xml"
            try:
                rt = ET.Element("root")
                with open(filename, "w") as f:
                    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    for d in data:
                        attr = {"interval":str(d[1]), "enabled":str(d[2])}
                        attr.update(eval(d[4]))
                        for k,v in attr.items():
                            if not isinstance(v, str):
                                attr[k] = str(v)
                        e = ET.Element(d[0], attr)
                        if d[3] != ALWAYS_ONLINE:
                            ol = ET.Element("online")
                            lst = eval(d[3])
                            for r in lst:
                                ol.append(ET.Element("item", {"btime":str(r[0]), "etime":str(r[1])}))
                            e.append(ol)
                        rt.append(e)
                    f.write(ET.tostring(rt, "unicode", ).replace("><", ">\n<"))
                pass
            except Exception as e:
                self.setStatus(f"Error: {e}")
                traceback.print_exc()
                showerr(f"Error saving plugins: {e}")
                return False
            self.setStatus("Plugins saved")
            return True
        return _save
    
    def __checkFolderOpened(self):
        if not self.folder:
            showerr(_L["PROJ_NO_OPEN"])
            return False
        return True
    
    def _load_tg(self, after:OAfter=None):
        try:
            self.tg = TrafficGenerator(self.folder)
        except Exception as e:
            traceback.print_exc()
            showerr(f"Error loading traffic generator: {e}")
            self.tg = None
        else:
            if after: after()
    
    def _load(self, loads:Optional[List[str]] = None, async_:bool = True):
        if not self.folder:
            showerr("No project folder selected")
            return
        if loads is None: loads = [
            LOAD_GEN, LOAD_FCS, LOAD_SCS, LOAD_CSCSV, LOAD_NET, LOAD_PLG
        ]
        self._ldfrm = LoadingBox(loads, self._Q)
        self.update()
        self.after(100, self.__load_part2, set(loads), async_)
    
    def __load_part2(self, loads:Set[str], async_:bool):
        self.state = res = DetectFiles(self.folder)
        self.title(f"{_L['TITLE']} - {Path(self.folder).name}")
        self.update()

        # Check if grid exists
        if not res.grid: 
            with open(self.get_default_grid_path(),"w") as f:
                f.write(DEFAULT_GRID)
            self.state = res = DetectFiles(self.folder)
        
        self.update()
        
        # Load traffic generator
        if LOAD_GEN in loads:
            self._Q.submit("TrafficGenLoaded", self._load_tg)

        self.update()

        # Load FCS
        if LOAD_FCS in loads:
            self._load_fcs(lambda: self._ldfrm.setText(LOAD_FCS, _L['DONE']))

        self.update()

        # Load SCS
        if LOAD_SCS in loads:
            self._load_scs(lambda: self._ldfrm.setText(LOAD_SCS, _L['DONE']))
        
        self.update()

        # Load CSCSV
        if LOAD_CSCSV in loads:
            self._load_cscsv(lambda: self._ldfrm.setText(LOAD_CSCSV, _L['DONE']))
        
        self.update()

        # Load plugins
        if LOAD_PLG in loads:
            self._load_plugins()
            self._ldfrm.setText(LOAD_PLG,_L['DONE'])
        
        self.update()

        self.rb_veh_src2.configure(state="normal" if "poly" in res else "disabled")
        self.rb_veh_src1.configure(state="normal" if "taz" in res else "disabled")
        
        self.state = res = DetectFiles(self.folder)

        self.update()
        
        if LOAD_NET in loads:
            self.cv_net.clear()
            self._load_network(self.tabs.select(),
                lambda: self._ldfrm.setText(LOAD_NET, _L['DONE']))
        
        self.update()

        def setText(lb:Label, itm:str, must:bool = False):
            if itm in res:
                lb.config(text=Path(res[itm]).name, foreground="black")
            else:
                lb.config(text="None", foreground="red" if must else "black")
        
        setText(self.lb_fcs, "fcs", True)
        setText(self.lb_scs, "scs", True)
        setText(self.lb_grid, "grid")
        setText(self.lb_net, "net", True)
        setText(self.lb_veh, "veh", True)
        setText(self.lb_plg, "plg")
        setText(self.lb_py, "py")
        setText(self.lb_node_type, "node_type")
        setText(self.lb_osm, "osm")
        setText(self.lb_poly, "poly")
        setText(self.lb_poi, "poi")
        setText(self.lb_cscsv, "cscsv")

        self.update()
        
        if self.state.pref:
            vcfg = V2SimConfig.load(self.state.pref)
            self.entry_start.delete(0, END)
            self.entry_start.insert(0, str(vcfg.start_time))
            self.entry_break.delete(0, END)
            self.entry_break.insert(0, str(vcfg.break_time))
            self.entry_end.delete(0, END)
            self.entry_end.insert(0, str(vcfg.end_time))
            self.entry_step.delete(0, END)
            self.entry_step.insert(0, str(vcfg.traffic_step))
            self.entry_seed.delete(0, END)
            self.entry_seed.insert(0, str(vcfg.seed))
            self.ralgo.set(vcfg.routing_method)
            self.sim_load_state.set(vcfg.load_state)
            self.on_load_state_changed()
            self.sim_save_on_finish.set(vcfg.save_state_on_finish)
            self.sim_save_on_abort.set(vcfg.save_state_on_abort)
            self.sim_copy_state.set(vcfg.copy_state)
            self.sim_no_parallel.set(vcfg.disable_parallel)
            self.sim_show_uxsim_info.set(vcfg.show_uxsim_info)
            if vcfg.stats:
                for x in vcfg.stats:
                    if x in self.sim_statistic:
                        self.sim_statistic[x] = True
                    else:
                        showerr(_L["UKN_STA_TYPE"].format(x, ', '.join(self.sim_statistic.keys())))
        
        self.sim_cb_load_last_state.configure(state="normal" if self.state.last_result_state else "disabled")
        self.sim_cb_load_saved_state.configure(state="normal" if self.state.saved_state else "disabled")

        self.update()

        self.setStatus(_L["STA_READY"])
        
        if len(loads) == 0: self._ldfrm.destroy()
    
    def _load_plugins(self):
        plg_set:Set[str] = set()
        plg_enabled_set:Set[str] = set()

        self.sim_plglist.clear()
        assert self.state is not None
        if self.state.plg:
            et = ReadXML(self.state.plg)
            if et is None:
                showerr(_L["ERR_LOAD_PLG"])
                return
            rt = et.getroot()
            if rt is None:
                showerr(_L["ERR_LOAD_PLG"])
                return
            for p in rt:
                try:
                    plg_type = self.sim_plglist.plg_pool.GetPluginType(p.tag.lower())
                except KeyError:
                    plg_list = ', '.join(self.sim_plglist.plg_pool.GetAllPlugins().keys())
                    showerr(_L["UKN_PLG_TYPE"].format(p.tag, plg_list))
                    continue
                assert issubclass(plg_type, PluginBase), "Plugin type is not a subclass of PluginBase"

                attr = plg_type.ElemShouldHave().default_value_dict()
                plg_set.add(p.tag.lower())

                # Check online attribute
                olelem = p.find("online")
                if olelem is not None: ol_str = RangeList(olelem)
                else: ol_str = ALWAYS_ONLINE

                # Check enabled attribute
                enabled = p.attrib.pop("enabled", SIM_YES)
                if enabled.upper() != SIM_NO:
                    enabled = SIM_YES
                    plg_enabled_set.add(p.tag.lower())
                
                # Check interval attribute
                intv = p.attrib.pop("interval")
                attr.update(p.attrib)
                self.sim_plglist.add(p.tag, intv, enabled, ol_str, attr)

        # Check if PDN exists
        if "pdn" not in plg_set:
            pdn_attr_default = PluginPDN.ElemShouldHave().default_value_dict()
            self.sim_plglist.add("pdn", 300, SIM_YES, ALWAYS_ONLINE, pdn_attr_default)
            plg_set.add("pdn")
            plg_enabled_set.add("pdn")
        
        # Check if V2G exists
        if "v2g" not in plg_set:
            self.sim_plglist.add("v2g", 300, SIM_YES, ALWAYS_ONLINE, {})
        if not self.state.plg:
            self.sim_plglist.save()
        
        self.__OnPluginEnabledSet()
        
    def _load_fcs(self, afterx:OAfter = None):
        assert self.state is not None
        def after():
            assert self.state is not None
            v = "fcs" in self.state
            self.sim_statistic["fcs"]=v
            self.sim_statistic.setEnabled("fcs", v)
            self.FCS_editor.setPoly("poly" in self.state)
            self.FCS_editor.setCSCSV("cscsv" in self.state)
            if afterx: afterx()
        if self.state.fcs:
            self.FCS_editor._Q.setcallback("loaded", after)
            self.FCS_editor.load(self.state.fcs)
        else:
            self.FCS_editor.clear()
            after()
        
    def _load_scs(self, afterx:OAfter=None):
        assert self.state is not None
        def after():
            assert self.state is not None
            v = "scs" in self.state
            self.sim_statistic["scs"] = v
            self.sim_statistic.setEnabled("scs", v)
            self.SCS_editor.setPoly("poly" in self.state)
            self.SCS_editor.setCSCSV("cscsv" in self.state)
            if afterx: afterx()
        if self.state.scs:
            self.SCS_editor._Q.setcallback("loaded", after)
            self.SCS_editor.load(self.state.scs)
        else:
            self.SCS_editor.clear()
            after()

    def _load_cscsv(self, after:OAfter = None):
        assert self.state is not None
        if self.state.cscsv:
            if after:
                self.CsCsv_editor._Q.setcallback("loaded", after)
            self.CsCsv_editor.load(self.state.cscsv)
        else:
            self.CsCsv_editor.clear()
            if after: after()
    
    def _load_network(self, tab_ret, after:OAfter = None):
        if self.state and self.state.net:
            self.tabs.select(self.tab_Net)
            time.sleep(0.01)
            self.tabs.select(tab_ret)
            self.lb_gridsave.config(text=_L["SAVED"],foreground="green")
            
            assert self.state is not None and self.state.net is not None
            if self.state.grid:
                self.cv_net.setGrid(PowerGrid.fromFile(self.state.grid))
            assert self.cv_net.Grid is not None
            self.lb_puvalues.configure(text=_L["PU_VALS"].format(self.cv_net.Grid.Ub,self.cv_net.Grid.Sb_MVA))

            def __el(state: FileDetectResult, after:OAfter=None):
                assert state.net is not None
                el = RoadNet.load(state.net)
                return el, after
            
            self._Q.submit("cvnetloaded", __el, self.state, after)

    def on_cvnet_loaded(self, el:RoadNet, after:OAfter=None):
        self.cv_net.setRoadNet(el, after = after)

    def openFolder(self):
        init_dir = Path("./cases")
        if not init_dir.exists(): init_dir.mkdir(parents=True, exist_ok=True)
        folder = filedialog.askdirectory(initialdir=str(init_dir),mustexist=True,title="Select project folder")
        if folder:
            self.folder = str(Path(folder))
            self._load()
    
    def generateCS(self, ctl:CSEditorGUI, cscsv_mode:int, **kwargs):
        if not self.tg:
            showerr("No traffic generator loaded")
            return
        self.setStatus("Generating CS...")
        if cscsv_mode == 0:
            cs_file = ""
            poly_file = ""
        elif cscsv_mode == 1:
            cs_file = self.state.cscsv if self.state else ""
            poly_file = ""
        else:
            cs_file = ""
            poly_file = self.state.poly if self.state else ""
        use_grid = kwargs.pop("use_grid", False)
        assert self.state is not None
        if use_grid:
            if self.state.grid is None:
                showerr("No grid loaded")
                return
            kwargs["grid_file"] = self.state.grid
        kwargs["cs_file"] = cs_file
        kwargs["poly_file"] = poly_file

        def work(ctl, **kwargs):
            try:
                if not self.tg: return
                warns, far_cnt, scc_cnt = self.tg._CS(**kwargs)
                if kwargs["mode"] == "fcs":
                    self._load([LOAD_FCS, LOAD_GEN])
                else:
                    self._load([LOAD_SCS, LOAD_GEN])
                return ctl, None, warns, far_cnt, scc_cnt
            except Exception as e:
                print(f"\nError generating CS: {e}")
                traceback.print_exc()
                return ctl, e, [], 0, 0
            
        self._Q.submit("CSGenDone", work, ctl, **kwargs)   
    
    @errwrapper
    def generateVeh(self):
        assert self.tg, _L["MSG_NO_TRAFFIC_GEN"]
        if not self.__checkFolderOpened(): return
        self.setStatus(_L["STA_GEN_VEH"])
        carcnt = try_int(self.entry_carcnt.get(), "Vehicle count")
        carseed = try_int(self.entry_carseed.get(), "Vehicle seed")
        day_count = try_int(self.entry_daycnt.get(), "Vehicle day count")
        
        try:
            pars = self.veh_pars.getAllData()
            new_pars = {
                "v2g_prop":float(self.entry_v2gprop.get()),
                "omega":eval(pars["Omega"]),
                "krel":eval(pars["KRel"]),
                "ksc":eval(pars["KSC"]),
                "kfc":eval(pars["KFC"]),
                "kv2g":eval(pars["KV2G"]),
            }
        except Exception as e:
            raise ValueError("Invalid Vehicle parameters") from e
        
        if self.veh_gen_src.get() == 0:
            mode = TripsGenMode.AUTO
        elif self.veh_gen_src.get() == 1:
            mode = TripsGenMode.TYPE
        else:
            mode = TripsGenMode.POLY
        route_cache = RoutingCacheMode(self.veh_route_cache.get())
        self.btn_genveh.config(state = DISABLED)

        def work() -> Optional[Exception]:
            try:
                assert self.tg
                self.tg.EVTrips(carcnt, carseed, day_count, mode = mode, route_cache = route_cache, **new_pars)
                self._load([])
                return None
            except Exception as e:
                return e
        
        self._Q.submit("VehGenDone", work)

    def draw(self):
        if not self.__checkFolderOpened(): return
        self.cv_net.UnlocateAllEdges()
        s = set(x.strip() for x in self.entry_Ledges.get().split(','))
        self.cv_net.LocateEdges(s)

    def CSCSVDownloadWorker(self):
        if not self.__checkFolderOpened(): return
        self.setStatus("Downloading CS CSV...")
        key = self.CsCsv_editor.entry_amapkey.get()
        def work():
            try:
                csQuery(self.folder,"",key,True)
                self._load([LOAD_CSCSV])
                return None
            except Exception as e:
                return e
        
        self._Q.submit("CSCSVDownloadDone", work)
        
    def setStatus(self, text:str):
        self.sbar.config(text=text)

    def _win(self):
        self.title(_L["TITLE"])

__all__ = ["MainBox"]