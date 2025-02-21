import tkinter as tk
import multiprocessing as mp
from tkinter import filedialog as fd
from tkinter import messagebox as mb
from fgui import ScrollableTreeView
from v2sim import *

_L = CustomLocaleLib.LoadFromFolder("./resources/gui_para")


class RedirectStdout:
    def __init__(self, q:mp.Queue, id:int):
        self.q = q
        self.ln = id

    def write(self, text):
        self.q.put((self.ln, text))

    def flush(self):
        pass


class ParaBox(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(_L("TITLE"))
        self.geometry('800x600')
        self.tr = ScrollableTreeView(self)
        self.tr["show"] = 'headings'
        self.tr["columns"] = ("case", "path", "prog")
        self.tr.column("case", width=200, minwidth=80, stretch=tk.NO)
        self.tr.column("path", width=200, minwidth=200, stretch=tk.YES)
        self.tr.column("path", width=200, minwidth=200, stretch=tk.YES)
        self.tr.heading("case", text=_L("CASE_NAME"), anchor=tk.W)
        self.tr.heading("path", text=_L("CASE_PATH"), anchor=tk.W)
        self.tr.heading("prog", text=_L("CASE_PROG"), anchor=tk.W)
        self.tr.pack(expand=True, fill='both',padx=3, pady=3)
        self.fr = tk.Frame(self)
        self.fr.pack(expand=False, fill='x', padx=3, pady=3)
        self.btn_load = tk.Button(self.fr, text=_L("LOAD_CASE"), command=self.load)
        self.btn_load.pack(padx=3, pady=3, anchor=tk.W, side=tk.LEFT)
        self.btn_remove = tk.Button(self.fr, text=_L("REMOVE_CASE"), command=self.remove)
        self.btn_remove.pack(padx=3, pady=3, anchor=tk.W, side=tk.LEFT)
        self.btn_run = tk.Button(self.fr, text=_L("RUN"), command=self.run)
        self.btn_run.pack(padx=3, pady=3, anchor=tk.E, side=tk.RIGHT)
    
    def load(self):
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
            f = Path(folder)
            self.tr.insert("", "end", iid=str(len(self.tr.get_children())), values=(f.name, folder, _L("NOT_STARTED")))

    def remove(self):
        item = self.tr.selection()
        if len(item) > 0:
            self.tr.delete(item[0])
        else:
            mb.showerror(_L("ERROR"),_L("CASE_NOT_SEL"))
    
    def run(self):
        chd = self.tr.get_children()
        if len(chd) == 0:
            mb.showinfo(_L("INFO"),_L("NO_CASE"))
            return
        self.q = mp.Queue()
        for i, itm in enumerate(chd):
            root = self.tr.item(itm)["values"][1]
            mp.Process(
                target=work, 
                args=(root, RedirectStdout(self.q, i)),
                daemon=True
            ).start()
        self.fr.pack_forget()
        self.after(100, self.check)
    
    def check(self):
        while not self.q.empty():
            ln, text = self.q.get()
            text:str = text.strip()
            if len(text)>0: self.tr.set(ln, "prog", text)
        self.after(100, self.check)

def work(root:str, recv:RedirectStdout):
    sys.stdout = recv
    import sim_single
    t = time.time()
    sim_single.work({"d":root}, recv.ln, recv.q)
    print(_L("DONE").format(time2str(time.time()-t)))

if __name__ == "__main__":
    app = ParaBox()
    app.mainloop()