import tkinter as tk
import tkinter.ttk as ttk
import multiprocessing as mp
import time
import sys
from pathlib import Path
from typing import Optional
from tkinter import filedialog as fd
from tkinter import messagebox as mb
from fgui import ScrollableTreeView, LogItemPad, EditMode, add_lang_menu
from feasytools import time2str
from v2sim import *

_L = CustomLocaleLib.LoadFromFolder("./resources/gui_para")
ITEM_NONE = "none"

class RedirectStdout:
    def __init__(self, q:mp.Queue, id:int):
        self.q = q
        self.ln = id

    def write(self, text):
        self.q.put((self.ln, text))

    def flush(self):
        pass

class ParamsEditor(tk.Toplevel):
    def __init__(self, data:dict[str,str]):
        super().__init__()
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("lb", "rb")
        self.tree.column("lb", width=120, stretch=tk.NO)
        self.tree.column("rb", width=120, stretch=tk.NO)
        self.tree.heading("lb", text=_L["PARAM_NAME"])
        self.tree.heading("rb", text=_L["PARAM_VALUE"])
        self.tree.pack(fill="both", expand=True)
        for l,r in data.items():
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("lb", EditMode.COMBO, combo_values=[
            'b','e','l','no-plg','seed','gen-veh','gen-fcs','gen-scs','plot'
        ])
        self.tree.setColEditMode("rb", EditMode.ENTRY)
        self.fr = ttk.Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_add = ttk.Button(self.fr, text=_L["ADD"], command=self.add, width=6)
        self.btn_add.grid(row=0,column=0,pady=3,sticky="w")
        self.btn_del = ttk.Button(self.fr, text=_L["DELETE"], command=self.delete, width=6)
        self.btn_del.grid(row=0,column=1,pady=3,sticky="w")
        self.btn_moveup = ttk.Button(self.fr, text=_L["CLEAR"], command=self.tree.clear, width=6)
        self.btn_moveup.grid(row=0,column=2,pady=3,sticky="w")
        self.btn_save = ttk.Button(self.fr, text=_L["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=3,padx=3,pady=3,sticky="e")
    
    def add(self):
        self.tree.insert("", "end", values=("no-plg",""))
    
    def delete(self):
        for i in self.tree.tree.selection():
            self.tree.delete(i)
    
    def save(self):
        self.data = self.getAllData()
        self.destroy()

    def getAllData(self) -> dict[str,str]:
        res:dict[str,str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res

class LoadGroupBox(tk.Toplevel):
    def __init__(self, parent, folder:str):
        super().__init__(parent)
        self.params = {}
        self.folder = folder
        self.results:Optional[list[tuple[str,str]]] = None
        self.title(_L("LOAD_GROUP_TITLE"))
        self.geometry('600x300')
        self.lb = ttk.Label(self, text=_L("FOLDER_NAME").format(self.folder))
        self.lb.pack(padx=3, pady=3)
        self.fr = ttk.Frame(self)
        self.fr.pack(padx=3, pady=3)
        self.lb_p = ttk.Label(self.fr, text=_L("OTHER_PARAMS"))
        self.lb_p.grid(row=0, column=0, padx=3, pady=3)
        self.fr2 = ttk.Frame(self.fr)
        self.fr2.grid(row=0, column=1, padx=3, pady=3)
        self.lb_pv = ttk.Label(self.fr2, text=str(self.params))
        self.lb_pv.pack(padx=3, anchor=tk.W, side=tk.LEFT)
        self.en_p = ttk.Button(self.fr2, command=self.edit_params, text="...",width=3)
        self.en_p.pack(padx=3, anchor=tk.W, side=tk.LEFT)
        self.lb_m = ttk.Label(self.fr, text=_L("MODE_ITEM"))
        self.lb_m.grid(row=1, column=0, padx=3, pady=3)
        self.cb = ttk.Combobox(self.fr)
        self.cb.grid(row=1, column=1, padx=3, pady=3)
        self.cb["values"] = [ITEM_NONE, "scs_slots", "fcs_slots", "start_time", "end_time", "traffic_step"]
        self.cb.current(0)
        self.lb_s = ttk.Label(self.fr, text=_L("START_VALUE"))
        self.lb_s.grid(row=2, column=0, padx=3, pady=3)
        self.en_s = ttk.Entry(self.fr)
        self.en_s.grid(row=2, column=1, padx=3, pady=3)
        self.lb_e = ttk.Label(self.fr, text=_L("END_VALUE"))
        self.lb_e.grid(row=3, column=0, padx=3, pady=3)
        self.en_e = ttk.Entry(self.fr)
        self.en_e.grid(row=3, column=1, padx=3, pady=3)
        self.lb_t = ttk.Label(self.fr, text=_L("STEP_VALUE"))
        self.lb_t.grid(row=4, column=0, padx=3, pady=3)
        self.en_t = ttk.Entry(self.fr)
        self.en_t.grid(row=4, column=1, padx=3, pady=3)
        self.lip = LogItemPad(self, _L["SIM_STAT"],{
            "fcs":_L["SIM_FCS"],
            "scs":_L["SIM_SCS"],
            "ev":_L["SIM_VEH"],
            "gen":_L["SIM_GEN"],
            "bus":_L["SIM_BUS"],
            "line":_L["SIM_LINE"],
            "pvw":_L["SIM_PVW"],
            "ess":_L["SIM_ESS"],
        })
        self.lip["ev"]=False
        self.lip.pack(padx=3, pady=3)
        self.btn = ttk.Button(self, text=_L("LGB_WORK"), command=self.work)
        self.btn.pack(padx=3, pady=3)
    
    def edit_params(self):
        pe = ParamsEditor(self.params)
        pe.wait_window()
        self.params = pe.data
        self.lb_pv["text"] = str(self.params)
    
    def work(self):
        self.results = []
        mode = self.cb.get()
        if mode == ITEM_NONE:
            self.results.append(('{}', ''))
        else:
            ms = ''.join(x[0] for x in mode.split('_'))
            try:
                start = int(self.en_s.get())
                end = int(self.en_e.get())
                step = int(self.en_t.get())
            except ValueError:
                mb.showerror(_L("ERROR"), _L("INVALID_VALUE"))
                self.focus()
                return
            for i in range(start, end, step):
                self.results.append(('{'+f"'{mode}':{i}"+'}', f"{ms}_{i}"))
        self.destroy()

class ParaBox(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(_L["PARAMS_EDITOR"])
        self.menu = tk.Menu(self)
        self.config(menu=self.menu)
        self.filemenu = tk.Menu(self.menu, tearoff=0)
        self.filemenu.add_command(label=_L("LOAD_CASE"), command=self.load)
        self.filemenu.add_command(label=_L("REMOVE_CASE"), command=self.remove)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_L("RUN"), command=self.run)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_L("EXIT"), command=self.destroy)
        self.menu.add_cascade(label=_L("OPERS"), menu=self.filemenu)
        add_lang_menu(self.menu)

        self.title(_L("TITLE"))
        self.geometry('1024x576')
        self.tr = ScrollableTreeView(self)
        self.tr["show"] = 'headings'
        self.tr["columns"] = ("case", "par", "alt", "output", "path", "prog")
        self.tr.column("case", width=120, minwidth=80, stretch=tk.NO)
        self.tr.column("par", width=160, minwidth=80, stretch=tk.NO)
        self.tr.column("alt", width=100, minwidth=80, stretch=tk.NO)
        self.tr.column("output", width=120, minwidth=80, stretch=tk.NO)
        self.tr.column("path", width=200, minwidth=200, stretch=tk.NO)
        self.tr.column("prog", width=150, minwidth=100, stretch=tk.NO)
        self.tr.heading("case", text=_L("CASE_NAME"), anchor=tk.W)
        self.tr.heading("par", text=_L("CASE_PARAMS"), anchor=tk.W)
        self.tr.heading("alt", text=_L("ALT_CMD"), anchor=tk.W)
        self.tr.heading("output", text=_L("OUTPUT_FOLDER"), anchor=tk.W)
        self.tr.heading("path", text=_L("CASE_PATH"), anchor=tk.W)
        self.tr.heading("prog", text=_L("CASE_PROG"), anchor=tk.W)
        self.tr.pack(expand=True, fill='both',padx=3, pady=3)
        self.fr = ttk.Frame(self)
        self.fr.pack(expand=False, fill='x', padx=3, pady=3)
        self.btn_load = ttk.Button(self.fr, text=_L("LOAD_CASE"), command=self.load)
        self.btn_load.pack(padx=3, pady=3, anchor=tk.W, side=tk.LEFT)
        self.btn_remove = ttk.Button(self.fr, text=_L("REMOVE_CASE"), command=self.remove)
        self.btn_remove.pack(padx=3, pady=3, anchor=tk.W, side=tk.LEFT)
        self.lb_time = ttk.Label(self.fr, text="00:00:00")
        self.lb_time.pack(padx=3, pady=3, anchor=tk.W, side=tk.LEFT)
        self.btn_run = ttk.Button(self.fr, text=_L("RUN"), command=self.run)
        self.btn_run.pack(padx=3, pady=3, anchor=tk.E, side=tk.RIGHT)
    
    def disable(self):
        self.btn_load["state"] = tk.DISABLED
        self.btn_remove["state"] = tk.DISABLED
        self.btn_run["state"] = tk.DISABLED
    
    def enable(self):
        self.btn_load["state"] = tk.NORMAL
        self.btn_remove["state"] = tk.NORMAL
        self.btn_run["state"] = tk.NORMAL
    
    def _load(self):
        init_dir = Path("./cases")
        if not init_dir.exists(): init_dir.mkdir(parents=True, exist_ok=True)
        folder = fd.askdirectory(initialdir=str(init_dir),mustexist=True,title=_L("SEL_CASE_FOLDER"))
        if folder:
            dr = DetectFiles(folder)
            if dr.cfg is None:
                mb.showerror(_L("ERROR"), _L("NO_CFG_FILE"))
                return
            if dr.net is None:
                mb.showerror(_L("ERROR"), _L("NO_NET_FILE"))
                return
            if dr.veh is None:
                mb.showerror(_L("ERROR"), _L("NO_VEH_FILE"))
                return
            if dr.fcs is None:
                mb.showerror(_L("ERROR"), _L("NO_FCS_FILE"))
                return
            if dr.scs is None:
                mb.showerror(_L("ERROR"), _L("NO_SCS_FILE"))
        return folder
    
    def check_outpath(self, out:str):
        for i in self.tr.get_children():
            if self.tr.item(i)["values"][3] == out:
                return False
        return True
    
    def rename_outpath(self, out:str):
        i = 0
        while not self.check_outpath(f"{out}_{i}"):
            i += 1
        return f"{out}_{i}"
            
    def load(self):
        folder = self._load()
        if folder:
            lgb = LoadGroupBox(self, folder)
            lgb.wait_window()
            if lgb.results is None: return
            f = Path(folder).name
            if len(lgb.results) == 0:
                mb.showerror(_L("ERROR"), _L("NO_GROUP"))
                return
            par = lgb.params
            par["log"] = ','.join(lgb.lip.getSelected())
            if len(lgb.results) == 1 and lgb.results[0][0] == '{}':
                self.tr.insert("", "end", iid=str(len(self.tr.get_children())), 
                    values=(f, par, "{}", self.rename_outpath(f"results/{f}"), folder, _L("NOT_STARTED")))
                return
            for alt, suf in lgb.results:
                self.tr.insert("", "end", iid=str(len(self.tr.get_children())), 
                    values=(f, par, alt, f"results/GRP_{f}/{suf}", folder, _L("NOT_STARTED")))


    def remove(self):
        item = self.tr.selection()
        if len(item) > 0:
            self.tr.delete(item[0])
        else:
            mb.showerror(_L("ERROR"),_L("CASE_NOT_SEL"))
    
    def run(self):
        chd = self.tr.get_children()
        self.item_cnt = len(chd)
        if self.item_cnt == 0:
            mb.showinfo(_L("INFO"),_L("NO_CASE"))
            return
        self.q:mp.Queue[MsgPack] = mp.Queue()
        self.start_t = time.time()
        self.lb_time["text"] = "00:00:00"
        self.done_cnt = 0
        for i, itm in enumerate(chd):
            v = self.tr.item(itm)["values"]
            par = eval(v[1])
            alt = eval(v[2])
            out = v[3]
            root = v[4]
            mp.Process(
                target=work, 
                args=(root, par, alt, out, RedirectStdout(self.q, i)),
                daemon=True
            ).start()
        self.disable()
        self.after(100, self.check)
    
    def check(self):
        while not self.q.empty():
            t = self.q.get()
            ln = t.clntID
            text = t.cmd.strip()
            if len(text)>0:
                if text.startswith("done:"): 
                    tm = time2str(float(text.removeprefix("done:")))
                    self.done_cnt += 1
                    self.tr.set(ln, "prog", _L("DONE") + f" ({tm})")
                elif text.startswith("sim:"):
                    self.tr.set(ln, "prog", text.removeprefix("sim:") + "%")
                else:
                    self.tr.set(ln, "prog", text)
        self.lb_time["text"] = time2str(time.time()-self.start_t)
        if self.done_cnt < self.item_cnt:
            self.after(1000, self.check)

def work(root:str, par:dict[str,str], alt:dict[str,str], out:str, recv:RedirectStdout):
    sys.stdout = recv
    import sim_single
    par.update({"d":root, "od":out})
    st_time = time.time()
    sim_single.work(par, recv.ln, recv.q, alt)
    print(f"done:{time.time()-st_time:.2f}")

if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()
    app = ParaBox()
    app.mainloop()