from v2simux_gui.com_no_vx import *
from v2simux_gui.langhelper import *

import multiprocessing as mp
import os


_ = LangLib.Load(__file__)
RECENT_PROJECTS_FILE = Path(__file__).parent / "recent_projects.txt"


class WelcomeBox(Tk):
    def __init__(self, Q:mp.Queue, to_open:str=""):
        super().__init__()
        self.wm_attributes('-topmost',1)
        self.title(_("WELCOME"))
        self.update_idletasks()
        width = 600
        height = 350
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        
        self.__q = Q

        self.menu = Menu(self)
        self.config(menu=self.menu)
        add_lang_menu(self.menu)

        # Header
        header_frame = Frame(self)
        header_frame.pack(side="top", fill="x", pady=(20, 10))

        # Image
        try:
            self.logo_img = PhotoImage(file=str(Path(__file__).parent / "v2sim.png"))
            logo_label = Label(header_frame, image=self.logo_img)
            logo_label.pack(side="left", padx=(20, 10))
        except Exception:
            logo_label = Label(header_frame, text="[Logo]")
            logo_label.pack(side="left", padx=(20, 10))

        title_label = Label(header_frame, text=_("WELCOME"), font=("Arial", 20, "bold"))
        title_label.pack(side="left", padx=10)

        # Middle section
        middle_frame = Frame(self)
        middle_frame.pack(expand=True, fill="both", pady=10, padx=20)
        
        recent_label = Label(middle_frame, text=_("RECENT_PROJ"))
        recent_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.recent_var = StringVar()
        self.proj_dir = Entry(middle_frame, textvariable=self.recent_var, state="readonly", width=40)
        self.proj_dir.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(5, 0), pady=(0, 5))

        self.project_list = Listbox(middle_frame, height=6)
        self.project_list.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(0, 5))

        def on_project_select(event):
            selection = self.project_list.curselection()
            if selection:
                selected_project = self.project_list.get(selection[0])
                self.recent_var.set(selected_project)

        self.project_list.bind("<<ListboxSelect>>", on_project_select)
        
        middle_frame.rowconfigure(1, weight=1)
        middle_frame.columnconfigure(1, weight=1)

        self.load_recent_projects()
        if os.path.isdir(to_open):
            self.project_list.insert(0, str(Path(to_open).absolute()))
            self.project_list.selection_set(0)
            on_project_select(None)
            self.save_recent_project()
        
        def clear_list(e):
            if MB.askyesno(_("CONFIRM"), _("CONFIRM_TEXT")):
                self.project_list.delete(0, END)
                self.recent_var.set("")
                if RECENT_PROJECTS_FILE.exists():
                    RECENT_PROJECTS_FILE.unlink()
                self.save_recent_project()

        def select_project(e):
            folder = filedialog.askdirectory(title=_("SELECT_PROJ_FOLDER"))
            if folder:
                self.project_list.insert(0, folder)
                while self.project_list.size() > 10:
                    self.project_list.delete(10)
                self.project_list.selection_clear(0, END)
                self.project_list.select_set(0)
                self.project_list.see(0)
                self.recent_var.set(folder)

                self.save_recent_project()

        # Links
        self.links_panel = Frame(middle_frame)
        self.links_panel.grid(row=2, column=0, columnspan=2, sticky="w")

        self.select_linklbl = Label(
            self.links_panel,
            text=_("ADD_PROJ"),
            foreground="blue",
            cursor="hand2",
            font=("Arial", 10, "underline")
        )
        self.select_linklbl.grid(row=0, column=0, sticky="w", pady=(5, 0))
        self.select_linklbl.bind("<Button-1>", select_project)
        
        self.convert_linklbl = Label(
            self.links_panel,
            text=_("CONV_CASE"),
            foreground="blue",
            cursor="hand2",
            font=("Arial", 10, "underline")
        )
        self.convert_linklbl.grid(row=0, column=1, sticky="w", pady=(5, 0), padx=(10, 0))
        self.convert_linklbl.bind("<Button-1>", self._convert_case)

        self.clear_linklbl = Label(
            self.links_panel,
            text=_("CLEAR_LIST"),
            foreground="blue",
            cursor="hand2",
            font=("Arial", 10, "underline")
        )
        self.clear_linklbl.grid(row=0, column=2, sticky="w", pady=(5, 0), padx=(10, 0))
        self.clear_linklbl.bind("<Button-1>", clear_list)

        # Buttons
        self.btn_panel = Frame(middle_frame)
        self.btn_panel.grid(row=2, column=2, sticky="ew")
        self.view_res_btn = Button(self.btn_panel, text=_("VIEW_RESULTS"), command=self._view_results)
        self.view_res_btn.grid(row=0, column=0, sticky="e", pady=(5, 0), padx=(5, 0))
        self.open_btn = Button(self.btn_panel, text=_("OPEN"), command=self._close, state=DISABLED)
        self.open_btn.grid(row=0, column=1, sticky="e", pady=(5, 0))

        # Footer (status bar)
        self.lb_sta = Label(self, text=_("LOAD_CORE"), anchor="w", relief="sunken")
        self.lb_sta.pack(side="bottom", fill="x")

        self.__load_error = False
    
    def _checkdone(self):
        try:
            ret = self.__q.get_nowait()
        except:
            self.after(100, self._checkdone)
            return
        if ret == "done":
            self.lb_sta.config(text=_("READY"))
            self.open_btn.config(state=NORMAL)
        elif ret == "error":
            self.lb_sta.config(text=_("FAILED_START"))
            self.select_linklbl.config(state=DISABLED)
            MB.showerror(_("ERROR"), _("FAILED_START"))
            self.open_btn.config(text=_("EXIT"), command=self._close, state=NORMAL)
            self.__load_error = True
        else:
            self.after(100, self._checkdone)
    
    def _destory(self):
        self.withdraw()
        self.quit()
        self.destroy()
    
    def _check_selected(self):
        if self.recent_var.get() == "":
            MB.showwarning(_("WARNING"), _("PLS_SELECT_PROJ"))
            return False
        return True

    def _close(self):
        if self.__load_error:
            self._destory()
            return
        if not self._check_selected(): return
        self.__q.put_nowait(("main", self.recent_var.get()))
        self._destory()
    
    def _view_results(self):
        if not self._check_selected(): return
        self.__q.put_nowait(("res", self.recent_var.get()))
        self._destory()
    
    def _convert_case(self, event):
        self.__q.put_nowait(("conv", None))
        self._destory()
    
    def show(self):
        self.update()
        self.deiconify()
        self.after(100, self._checkdone)
        self.mainloop()
        self.__q.put_nowait(("close", None))
    
    def load_recent_projects(self):
        self.project_list.delete(0, END)
        if not RECENT_PROJECTS_FILE.exists():
            return
        with open(RECENT_PROJECTS_FILE, 'r') as f:
            path_list = []
            for line in f:
                project_path = line.strip()
                if project_path and os.path.isdir(project_path):
                    abs_path = str(Path(project_path).absolute().resolve().as_posix())
                    if abs_path not in path_list:
                        path_list.append(abs_path)
                        self.project_list.insert(END, abs_path)

    def save_recent_project(self):
        with open(RECENT_PROJECTS_FILE, 'w') as f:
            for project in self.project_list.get(0, END):
                f.write(f"{project}\n")