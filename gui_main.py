import os
from pathlib import Path
from feasytools import ArgChecker
import time
import tkinter as tk
import tkinter.messagebox as MB
from tkinter import filedialog, Tk, PhotoImage, StringVar
from tkinter import ttk
import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
import multiprocessing as mp

RECENT_PROJECTS_FILE = Path(__file__).parent / "recent_projects.txt"

class WelcomeBox(Tk):
    def __init__(self, Q:mp.Queue, to_open:str=""):
        super().__init__()
        self.wm_attributes('-topmost',1)
        self.title("Welcome to V2Sim")
        #self.overrideredirect(True)
        self.update_idletasks()
        width = 600
        height = 350
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        
        #self.resizable(False, False)
        self.__q = Q

        # Header
        header_frame = ttk.Frame(self)
        header_frame.pack(side="top", fill="x", pady=(20, 10))

        # Image (replace 'logo.png' with your actual image path)
        try:
            self.logo_img = PhotoImage(file=str(Path(__file__).parent / "fgui/v2sim.png"))
            logo_label = ttk.Label(header_frame, image=self.logo_img)
            logo_label.pack(side="left", padx=(20, 10))
        except Exception:
            logo_label = ttk.Label(header_frame, text="[Logo]")
            logo_label.pack(side="left", padx=(20, 10))

        title_label = ttk.Label(header_frame, text="Welcome to V2Sim", font=("Arial", 20, "bold"))
        title_label.pack(side="left", padx=10)

        # Middle section
        middle_frame = ttk.Frame(self)
        middle_frame.pack(expand=True, fill="both", pady=10, padx=20)

        recent_label = ttk.Label(middle_frame, text="Recent Projects:")
        recent_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.recent_var = StringVar()
        self.proj_dir = ttk.Entry(middle_frame, textvariable=self.recent_var, state="readonly", width=40)
        self.proj_dir.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(5, 0), pady=(0, 5))

        self.project_list = tk.Listbox(middle_frame, height=6)
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
            if MB.askyesno("Confirm", "Are you sure to clear the recent project list? This action cannot be undone."):
                self.project_list.delete(0, tk.END)
                self.recent_var.set("")
                if RECENT_PROJECTS_FILE.exists():
                    RECENT_PROJECTS_FILE.unlink()
                self.save_recent_project()

        def select_project(e):
            folder = filedialog.askdirectory(title="Select Project Folder")
            if folder:
                self.project_list.insert(0, folder)
                while self.project_list.size() > 10:
                    self.project_list.delete(10)
                self.project_list.selection_clear(0, tk.END)
                self.project_list.select_set(0)
                self.project_list.see(0)
                self.recent_var.set(folder)

                self.save_recent_project()
        
        self.open_btn = ttk.Button(middle_frame, text="Open", command=self._close, state="disabled")
        self.open_btn.grid(row=2, column=2, sticky="e", pady=(5, 0))
        self.select_linklbl = ttk.Label(
            middle_frame,
            text="Add project...",
            foreground="blue",
            cursor="hand2",
            font=("Arial", 10, "underline")
        )
        self.select_linklbl.bind("<Button-1>", select_project)
        self.select_linklbl.grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.clear_linklbl = ttk.Label(
            middle_frame,
            text="Clear list",
            foreground="blue",
            cursor="hand2",
            font=("Arial", 10, "underline")
        )
        self.clear_linklbl.grid(row=2, column=1, sticky="w", pady=(5, 0), padx=(10, 0))
        self.clear_linklbl.bind("<Button-1>", clear_list)

        # Footer (status bar)
        self.lb_sta = ttk.Label(self, text="Loading V2Sim core...", anchor="w", relief="sunken")
        self.lb_sta.pack(side="bottom", fill="x")
    
    def _checkdone(self):
        try:
            ret = self.__q.get_nowait()
        except:
            self.after(100, self._checkdone)
            return
        if ret == "done":
            self.lb_sta.config(text="V2Sim is ready!")
            self.open_btn.config(state="normal")
        elif ret == "error":
            self.lb_sta.config(text="Failed to start V2Sim core. See console for details.")
            self.select_linklbl.config(state="disabled")
            MB.showerror("Error", "Failed to start V2Sim core. Please check the console for details.")
            self.open_btn.config(text="Exit", command=self._close, state="normal")
        else:
            self.after(100, self._checkdone)
    
    def _close(self):
        self.__q.put_nowait(self.recent_var.get())
        self.withdraw()
        self.quit()
        self.destroy()
    
    def show(self):
        self.update()
        self.deiconify()
        self.after(100, self._checkdone)
        self.mainloop()
        self.__q.put_nowait("__close__")
    
    def load_recent_projects(self):
        self.project_list.delete(0, tk.END)
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
                        self.project_list.insert(tk.END, abs_path)

    def save_recent_project(self):
        with open(RECENT_PROJECTS_FILE, 'w') as f:
            for project in self.project_list.get(0, tk.END):
                f.write(f"{project}\n")

def welcome(chd_pipe, to_open):
    wb = WelcomeBox(chd_pipe, to_open)
    wb.show()

if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()

    args = ArgChecker()
    to_open = args.pop_str("d", "")
    
    Q = mp.Queue()
    mp.Process(target=welcome, args=(Q, to_open)).start()

    try:
        from fgui.mainbox import MainBox
        win = MainBox()
        success = True
    except Exception as e:
        import traceback
        print("Failed to start the main window:")
        print(traceback.format_exc())
        Q.put_nowait("error")
        success = False
    
    if success:
        Q.put_nowait("done")
        time.sleep(0.2)  # Give some time for the welcome box to show up
        msg = Q.get()
        if msg == "__close__":
            win.quit()
            win.destroy()
            exit(0)
        elif msg is not None and msg != "":
            win.folder = msg
            win._load()
        win.wm_attributes('-topmost', 1)
        win.after(100, lambda: win.wm_attributes('-topmost', 0))
        win.mainloop()