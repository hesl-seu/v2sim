from v2simux_gui.com_no_vx import *
from v2simux_gui.langhelper import add_lang_menu

import os
import gzip
import traceback
from v2simux import ReadOnlyStatistics, AdvancedPlot
from PIL import Image, ImageTk
from .srd import SelectResultsDialog
from .plotpage import PlotPage, AVAILABLE_ITEMS, AVAILABLE_ITEMS2
from .trips import TripsFrame
from .gridpage import GridFrame
from .statepage import StateFrame


_L = LangLib.Load(__file__)

ITEM_ALL = _L["ITEM_ALL"]
ITEM_SUM = _L["ITEM_SUM"]
ITEM_ALL_G = "<All common generators>"
ITEM_ALL_V2G = "<All V2G stations>"
ITEM_LOADING = "Loading..."


class ViewerBox(Tk):
    _sta:ReadOnlyStatistics
    _npl:AdvancedPlot

    def __init__(self, project_folder:Optional[str] = None):
        super().__init__()
        self.title(_L["TITLE"])
        self.geometry("1024x840")
        self.original_image = None
        
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=False)
        self.menu.add_cascade(label=_L["MENU_FILE"], menu=self.filemenu)
        self.filemenu.add_command(label=_L["MENU_OPEN"], command=self.open)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_L["MENU_EXIT"], command=self.destroy)
        add_lang_menu(self.menu)

        self.tab = Notebook(self)
        self.tab.pack(expand=True,fill='both',padx=20,pady=3)
        self.tab_curve = Frame(self.tab)
        self.tab.add(self.tab_curve,text=_L["TAB_CURVE"])
        self.tab_grid = GridFrame(self.tab, self)
        self.tab.add(self.tab_grid,text=_L["TAB_GRID"])
        self.tab_trip = TripsFrame(self.tab)
        self.tab.add(self.tab_trip,text=_L["TAB_TRIP"], sticky='nsew')
        self.tab_state = StateFrame(self.tab)
        self.tab.add(self.tab_state,text=_L["TAB_STATE"], sticky='nsew')

        self.fr_pic = Frame(self.tab_curve)
        self.fr_pic.pack(side="top",fill=BOTH, expand=False)
        self.lb_pic = Label(self.fr_pic,text=_L["NO_IMAGE"])
        self.lb_pic.pack(side="left",fill=BOTH, expand=True,anchor='w')
        self.pic_list = Listbox(self.fr_pic)
        self.pic_list.pack(side="right",fill=Y,anchor='e')
        self.pic_list.bind("<<ListboxSelect>>", self.on_file_select)

        self.fr_draw = Frame(self.tab_curve)
        self.fr_draw.pack(side="bottom",fill=BOTH, expand=True)
        self._ppc = Canvas(self.fr_draw)
        self._ppc.pack(side="left", fill="both", expand=True)
        self.scrollbar = Scrollbar(self.fr_draw, orient="vertical", command=self._ppc.yview)
        self.scrollbar.pack(side="right", fill="y")
        self._pp = PlotPage(self._ppc)
        self._pp.bind("<Configure>", lambda e: self._ppc.configure(scrollregion=self._ppc.bbox("all")))
        self.btn_draw = Button(self._pp.panel_time, text=_L["BTN_PLOT"], command=self.plotSelected)
        self.btn_draw.pack(side='right')
        self._ppc.create_window((0, 0), window=self._pp, anchor="nw")
        self._ppc.configure(yscrollcommand=self.scrollbar.set)

        self._sbar=Label(self,text=_L["STA_READY"])
        self._sbar.pack(side='bottom',anchor='w',padx=3,pady=3)
        
        self._ava ={
            "fcs": False,
            "scs": False, 
            "ev": False, 
            "gen": False, 
            "bus": False, 
            "line": False, 
            "pvw": False, 
            "ess": False,
        }
        self._Q = EventQueue(self)
        self._Q.register("exit", self.quit)
        self._Q.register("loaded", self.on_loaded)
        self._Q.register("state_loaded", self.on_state_loaded)
        self._Q.register("plot_done", self.on_plot_done)
        self._Q.do()

        self.disable_all()
        self.bind("<Configure>", self.on_resize)
        self.resize_timer = None

        if project_folder is not None and project_folder != "":
            self.__proj_folder = project_folder
            self.bind("<Visibility>", self.__on_win_loaded)

    def __on_win_loaded(self, event):
        self.unbind("<Visibility>")
        self.load_results(self.__proj_folder)
    
    def display_images(self, file_name:str):
        if self.folder is None: return
        img1_path = os.path.join(self.folder, file_name)
        
        try:
            if os.path.exists(img1_path):
                self.original_image = Image.open(img1_path)
            else:
                self.original_image = None
        except Exception as e:
            MB.showerror(_L["ERROR"], _L["LOAD_FAILED"].format(str(e)))
        
        self.resize()
    
    def resize(self):
        sz = (self.winfo_width() - 200, self.winfo_height() // 2 - 20)
        if self.original_image is not None:
            resized_image = self.original_image.copy()
            resized_image.thumbnail(sz)
            image = ImageTk.PhotoImage(resized_image)

            self.lb_pic.config(image=image,text="")
            self.image = image
        else:
            self.lb_pic.config(image='',text=_L["NO_IMAGE"])
            self.image = None

    def on_resize(self, event):
        if self.resize_timer is not None:
            self.after_cancel(self.resize_timer)
        self.resize_timer = self.after(100, self.resize_end)
    
    def resize_end(self):
        self.resize()
    
    def on_file_select(self, event):
        selected_index = self.pic_list.curselection()
        if selected_index:
            file_name = self.pic_list.get(selected_index)
            self.display_images(file_name)
       
    def disable_all(self):
        self._pp.disable()
        self.btn_draw['state']=DISABLED

    def enable_all(self):
        self._pp.enable([p for p, ok in self._ava.items() if ok])
        self.btn_draw['state']=NORMAL
    
    def set_status(self,text:str):
        self._sbar.configure(text=text)

    def update_file_list(self):
        self.pic_list.delete(0, END)
        self.original_image = None
        self.lb_pic.config(image='',text=_L["NO_IMAGE"])
        self.image = None
        if self.folder and os.path.exists(self.folder):
            files = set(os.listdir(self.folder))
            for file in sorted(files):
                if file.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):  # 只列出图片文件
                    self.pic_list.insert(END, file)

    def on_state_loaded(self, par):
        self.tab_state.setStateInst(par)
    
    def on_loaded(self, sta:ReadOnlyStatistics, npl:AdvancedPlot):
        assert isinstance(sta, ReadOnlyStatistics)
        assert isinstance(npl, AdvancedPlot)
        self._sta = sta
        self.tab_grid.setSta(sta)
        self._npl = npl
        for x in AVAILABLE_ITEMS:
            self._ava[x] = getattr(self._sta, f"has_{x.upper()}")()
        if self._sta.has_FCS():
            self._pp.fcs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.FCS_head)
            self.tab_state.cb_fcs_query['values'] = self._sta.FCS_head
            if self._sta.FCS_head:
                self.tab_state.cb_fcs_query.set(self._sta.FCS_head[0])
        if self._sta.has_SCS():
            self._pp.scs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.SCS_head)
            self.tab_state.cb_scs_query['values'] = self._sta.SCS_head
            if self._sta.SCS_head:
                self.tab_state.cb_scs_query.set(self._sta.SCS_head[0])
        if self._sta.has_GEN():
            self._pp.gen_pad.setValues([ITEM_ALL_G,ITEM_ALL_V2G,ITEM_ALL] + self._sta.gen_head)
        if self._sta.has_BUS():
            self._pp.bus_pad.setValues([ITEM_ALL] + self._sta.bus_head)
        if self._sta.has_LINE():
            self._pp.line_pad.setValues([ITEM_ALL] + self._sta.line_head)
        if self._sta.has_PVW():
            self._pp.pvw_pad.setValues([ITEM_ALL] + self._sta.pvw_head)
        if self._sta.has_ESS():
            self._pp.ess_pad.setValues([ITEM_ALL] + self._sta.ess_head)
        self.update_file_list()
        self.set_status(_L["STA_READY"])
        self.enable_all()
        
    def on_error(self, par):
        MB.showerror(_L["ERROR"], par[0])
        self.set_status(par[0])
        self.enable_all()
    
    def on_plot_done(self, ex:Optional[Exception] = None):
        if ex is None:
            self.update_file_list()
            self.set_status(_L["STA_READY"])
            self.enable_all()
        else:
            self.on_error((str(ex),))
    
    def askdir(self):
        p = Path(os.getcwd()) / "cases"
        p.mkdir(parents=True,exist_ok=True)
        return filedialog.askdirectory(
            title=_L["TITLE_SEL_FOLDER"],
            initialdir=str(p),
            mustexist=True,
        )
    
    def open(self):
        res_path = self.askdir()
        if res_path == "": return
        self.load_results(res_path)
    
    def load_results(self, folder: str):
        # Check folder existence
        first = True
        res_path = folder
        while True:
            res_path = Path(res_path)
            if res_path.exists():
                break
            else: 
                if not first: MB.showerror(_L["ERROR"], "Folder not found!")
            first = False
            res_path = self.askdir()
            if res_path == "":
                self._Q.trigger("exit")
                return
        
        # Check cproc.clog existence
        cproc = res_path / "cproc.clog"
        if cproc.exists():
            self.tab_trip.load(str(cproc))
        else:
            res_path_list = []
            for dir_ in res_path.iterdir():
                if dir_.is_dir() and dir_.name.lower().startswith("results") and (dir_ / "cproc.clog").exists():
                    res_path_list.append(dir_)
            if len(res_path_list) == 0:
                MB.showerror(_L["ERROR"], _L["NO_CPROC"])
                return
            elif len(res_path_list) == 1:
                res_path = res_path_list[0]
            else:
                self.disable_all()
                dsa = SelectResultsDialog(res_path_list)
                dsa.lift(self)
                self.wait_window(dsa)
                if dsa.folder is None:
                    self._Q.trigger("exit")
                    return
                res_path = Path(dsa.folder)
            cproc = res_path / "cproc.clog"
            self.tab_trip.load(str(cproc))
        
        # Load the results
        self.set_status(_L["LOADING"])
        self.folder = str(res_path.absolute() / "figures")
        self.title(f'{_L["TITLE"]} - {res_path.name}')
        self.disable_all()

        def load_async(res_path):
            sta = ReadOnlyStatistics(res_path)
            npl = AdvancedPlot()
            npl.load_series(sta)
            return (sta, npl)
        
        self._Q.submit("loaded", load_async, res_path)

        state_path = res_path / "saved_state" / "inst.gz"

        def load_state_async(state_path):
            try:
                with gzip.open(state_path, 'rb') as f:
                    inst = pickle.load(f) # type: ignore
            except:
                MB.showerror(_L["ERROR"], _L["SAVED_STATE_LOAD_FAILED"])
                inst = None
            return inst

        if state_path.exists():
            self._Q.submit("state_loaded", load_state_async, state_path)

    def plotSelected(self):
        cfg = self._pp.getConfig()
        self.disable_all()
        self.set_status("Plotting all...")
        self._npl.pic_ext = self._pp.cb_ext.get()
        self._npl.plot_title = self._pp.plot_title.get()
        try:
            self._npl.dpi = int(self._pp.entry_dpi.get())
        except:
            MB.showerror(_L["ERROR"], _L["INVALID_DPI"])
            self.enable_all()
            return
        for a in AVAILABLE_ITEMS2:
            if cfg[a]: break
        else:
            MB.showerror(_L["ERROR"], _L["NOTHING_PLOT"])
            self.enable_all()
        
        def work(cfg):
            def todo(plotpage, opt_name):
                getattr(plotpage, "plot_" + opt_name).set("False")

            try:
                for a in AVAILABLE_ITEMS2:
                    if cfg[a]:
                        getattr(self, "_plot_"+a)()
                        if "_" in a: continue
                        self._Q.delegate(todo, self._pp, a)
            except Exception as e:
                traceback.print_exc()
                return e
            return None

        self._Q.submit("plot_done", work, cfg)

    def _plot_scs_accum(self):
        tl,tr = self._pp.getTime()
        self._npl.quick_scs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)
    
    def _plot_fcs_accum(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_fcs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)

    def _plot_fcs(self):
        t = self._pp.fcs_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            cs = self._sta.FCS_head
        elif t==ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i,c in enumerate(cs,start=1):
            self._Q.delegate(self.set_status, f'({i} of {len(cs)})Plotting FCS graph...')
            self._npl.quick_fcs(
                cs_name=c, res_path=self._sta.root, 
                **self._pp.pars("fcs")
            )

    def _plot_scs(self):
        t = self._pp.scs_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            cs = self._sta.SCS_head
        elif t==ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i,c in enumerate(cs,start=1):
            self._Q.delegate(self.set_status, f'({i} of {len(cs)})Plotting SCS graph...')
            self._npl.quick_scs(
                cs_name=c, res_path=self._sta.root,
                **self._pp.pars("scs")
            )

    def _plot_ev(self):
        self._npl.tl = int(self._pp.entry_time.get())
        t = self._pp.ev_pad.get()
        evs=None if t.strip()=="" else [x.strip() for x in t.split(',')]
        if evs is None:
            self._Q.trigger("error", 'ID of EV cannot be empty')
            return
        for ev in evs:
            self._npl.quick_ev(ev_name = ev,
                res_path=self._sta.root,
                **self._pp.pars("ev")
            )
    
    def _plot_gen(self):
        t = self._pp.gen_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            gen = self._sta.gen_head
        elif t==ITEM_ALL_G:
            gen = [x for x in self._sta.gen_head if not x.startswith("V2G")]
        elif t==ITEM_ALL_V2G:
            gen = [x for x in self._sta.gen_head if x.startswith("V2G")]
        else: gen = [x.strip() for x in t.split(',')]
        for i, g in enumerate(gen, start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(gen)})Plotting generators...')
            self._npl.quick_gen(
                gen_name=g,res_path=self._sta.root,
                **self._pp.pars("gen")
            )

    def _plot_bus(self):
        t=self._pp.bus_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            bus=self._sta.bus_head
        else: bus=[x.strip() for x in t.split(',')]
        for i,g in enumerate(bus,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(bus)})Plotting buses...')
            self._npl.quick_bus(
                bus_name = g, res_path=self._sta.root,
                **self._pp.pars("bus")
            )
    
    def _plot_gen_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_gen_tot(tl,tr,True,True,True,res_path=self._sta.root)
    
    def _plot_bus_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_bus_tot(tl,tr,True,True,True,True,res_path=self._sta.root)
    
    def _plot_line(self):
        t=self._pp.line_pad.get()
        if t.strip()=="" or t==ITEM_ALL:
            line=self._sta.line_head
        else: line=[x.strip() for x in t.split(',')]
        for i,g in enumerate(line,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(line)})Plotting lines...')
            self._npl.quick_line(
                line_name = g, res_path=self._sta.root,
                **self._pp.pars("line")
            )

    def _plot_pvw(self):
        t = self._pp.pvw_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            pvw = self._sta.pvw_head
        else: pvw = [x.strip() for x in t.split(',')]
        for i, g in enumerate(pvw,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(pvw)})Plotting PV & Wind...')
            self._npl.quick_pvw(
                pvw_name = g, res_path=self._sta.root,
                **self._pp.pars("pvw")
            )

    def _plot_ess(self):
        t = self._pp.ess_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            ess = self._sta.ess_head
        else: ess = [x.strip() for x in t.split(',')]
        for i,g in enumerate(ess,start=1):
            self._Q.delegate(self.set_status, f'({i}/{len(ess)})Plotting ESS...')
            self._npl.quick_ess(
                ess_name = g, res_path = self._sta.root,
                **self._pp.pars("ess")
            )

__all__ = ["ViewerBox"]