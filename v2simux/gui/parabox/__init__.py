from v2simux.gui.com_no_vx import *
from v2simux.gui.langhelper import *

import time
from feasytools import time2str
from v2simux import MsgPack, DetectFiles
from ..mainbox.controls import ScrollableTreeView
from .pareditor import *
from .lgb import *
from .utils import *


class ParaBox(Tk):
    def __init__(self):
        super().__init__()
        self.title(_L["PARAMS_EDITOR"])
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=0)
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
        self.tr.column("case", width=120, minwidth=80, stretch=NO)
        self.tr.column("par", width=160, minwidth=80, stretch=NO)
        self.tr.column("alt", width=100, minwidth=80, stretch=NO)
        self.tr.column("output", width=120, minwidth=80, stretch=NO)
        self.tr.column("path", width=200, minwidth=200, stretch=NO)
        self.tr.column("prog", width=150, minwidth=100, stretch=NO)
        self.tr.heading("case", text=_L("CASE_NAME"), anchor=W)
        self.tr.heading("par", text=_L("CASE_PARAMS"), anchor=W)
        self.tr.heading("alt", text=_L("ALT_CMD"), anchor=W)
        self.tr.heading("output", text=_L("OUTPUT_FOLDER"), anchor=W)
        self.tr.heading("path", text=_L("CASE_PATH"), anchor=W)
        self.tr.heading("prog", text=_L("CASE_PROG"), anchor=W)
        self.tr.pack(expand=True, fill='both',padx=3, pady=3)
        self.fr = Frame(self)
        self.fr.pack(expand=False, fill='x', padx=3, pady=3)
        self.btn_load = Button(self.fr, text=_L("LOAD_CASE"), command=self.load)
        self.btn_load.pack(padx=3, pady=3, anchor=W, side=LEFT)
        self.btn_remove = Button(self.fr, text=_L("REMOVE_CASE"), command=self.remove)
        self.btn_remove.pack(padx=3, pady=3, anchor=W, side=LEFT)
        self.lb_time = Label(self.fr, text="00:00:00")
        self.lb_time.pack(padx=3, pady=3, anchor=W, side=LEFT)
        self.btn_run = Button(self.fr, text=_L("RUN"), command=self.run)
        self.btn_run.pack(padx=3, pady=3, anchor=E, side=RIGHT)
    
    def disable(self):
        self.btn_load["state"] = DISABLED
        self.btn_remove["state"] = DISABLED
        self.btn_run["state"] = DISABLED
    
    def enable(self):
        self.btn_load["state"] = NORMAL
        self.btn_remove["state"] = NORMAL
        self.btn_run["state"] = NORMAL
    
    def _load(self):
        init_dir = Path("./cases")
        if not init_dir.exists(): init_dir.mkdir(parents=True, exist_ok=True)
        folder = filedialog.askdirectory(initialdir=str(init_dir),mustexist=True,title=_L("SEL_CASE_FOLDER"))
        if folder:
            dr = DetectFiles(folder)
            if dr.net is None:
                MB.showerror(_L("ERROR"), _L("NO_NET_FILE"))
                return
            if dr.veh is None:
                MB.showerror(_L("ERROR"), _L("NO_VEH_FILE"))
                return
            if dr.fcs is None:
                MB.showerror(_L("ERROR"), _L("NO_FCS_FILE"))
                return
            if dr.scs is None:
                MB.showerror(_L("ERROR"), _L("NO_SCS_FILE"))
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
                MB.showerror(_L("ERROR"), _L("NO_GROUP"))
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
            MB.showerror(_L("ERROR"),_L("CASE_NOT_SEL"))
    
    def run(self):
        chd = self.tr.get_children()
        self.item_cnt = len(chd)
        if self.item_cnt == 0:
            MB.showinfo(_L("INFO"),_L("NO_CASE"))
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
            if not isinstance(t, MsgPack):
                print("Invalid message from worker:", t)
                continue
            ln = t.clntID
            text = t.cmd.strip()
            if len(text)>0:
                if text.startswith("done:"): 
                    tm = time2str(float(text.replace("done:","",1)))
                    self.done_cnt += 1
                    self.tr.set(ln, "prog", _L("DONE") + f" ({tm})")
                elif text.startswith("sim:"):
                    self.tr.set(ln, "prog", text.replace("sim:","",1) + "%")
                else:
                    self.tr.set(ln, "prog", text)
        self.lb_time["text"] = time2str(time.time()-self.start_t)
        if self.done_cnt < self.item_cnt:
            self.after(1000, self.check)

__all__ = ["ParaBox"]