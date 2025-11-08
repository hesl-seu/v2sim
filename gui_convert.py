from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, messagebox
from v2simux import CustomLocaleLib

import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
import os
import subprocess
import threading

_ = CustomLocaleLib.LoadFromFolder(Path(__file__).parent / "resources" / "gui_convert")

class MainApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(_("TITLE"))
        self.root.geometry("600x350")
        
        self.input_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        
        self.setup_ui()
    
    def setup_ui(self):
        input_frame = ttk.Frame(self.root)
        input_frame.pack(pady=10, padx=20, fill="x")

        ttk.Label(input_frame, text=_("INPUT")).pack(anchor="w")

        input_select_frame = ttk.Frame(input_frame)
        input_select_frame.pack(fill="x", pady=5)
        
        ttk.Entry(input_select_frame, textvariable=self.input_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(input_select_frame, text=_("BROWSE"), 
                 command=self.select_input_folder, width=10).pack(side="right", padx=(5, 0))
        
        output_frame = ttk.Frame(self.root)
        output_frame.pack(pady=10, padx=20, fill="x")
        
        ttk.Label(output_frame, text=_("OUTPUT")).pack(anchor="w")
        
        output_select_frame = ttk.Frame(output_frame)
        output_select_frame.pack(fill="x", pady=5)
        
        ttk.Entry(output_select_frame, textvariable=self.output_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(output_select_frame, text=_("BROWSE"), 
                 command=self.select_output_folder, width=10).pack(side="right", padx=(5, 0))
        
        partition_frame = ttk.Frame(self.root)
        partition_frame.pack(pady=10, padx=20, fill="x")
        partition_frame.columnconfigure(2, weight=1)

        self.partition_count = tk.StringVar(value="1")
        self.auto_partition = tk.BooleanVar(value=False)

        ttk.Label(partition_frame, text=_("PARTITION_COUNT")).grid(row=0, column=0, sticky="w")
        def on_auto_partition_changed(*args):
            state = "disabled" if self.auto_partition.get() else "normal"
            self.entry_count_widget.config(state=state)

        self.entry_count_widget = ttk.Spinbox(partition_frame, from_=1, to=32, textvariable=self.partition_count, width=5)
        self.entry_count_widget.grid(row=0, column=1, sticky="w")
        self.check_auto_part_widget = ttk.Checkbutton(partition_frame, text=_("PARTITION_TIP"), variable=self.auto_partition)
        self.check_auto_part_widget.grid(row=0, column=2, sticky="e")
        self.auto_partition.trace_add("write", on_auto_partition_changed)

        self.options_frame = ttk.Frame(self.root)
        self.options_frame.pack(pady=10, padx=20, fill="x")

        self.non_passenger_links = tk.BooleanVar(value=False)
        self.check_non_passenger_links = ttk.Checkbutton(self.options_frame, text=_("NON_PASSENGER_LINKS"), variable=self.non_passenger_links)
        self.check_non_passenger_links.pack(anchor="w")

        self.non_scc_links = tk.BooleanVar(value=False)
        self.check_non_scc_links = ttk.Checkbutton(self.options_frame, text=_("NON_SCC_LINKS"), variable=self.non_scc_links)
        self.check_non_scc_links.pack(anchor="w")

        self.execute_button = ttk.Button(self.root, text=_("EXECUTE"), command=self.execute_program)
        self.execute_button.pack(pady=10)
        
    
    def select_input_folder(self):
        folder = filedialog.askdirectory(title=_("SELECT_INPUT_FOLDER"))
        if folder:
            self.input_folder.set(folder)
    
    def select_output_folder(self):
        folder = filedialog.askdirectory(title=_("SELECT_OUTPUT_FOLDER"))
        if folder:
            self.output_folder.set(str(Path(folder) / Path(self.input_folder.get()).name))
    
    def execute_program(self):
        if not self.input_folder.get() or not self.output_folder.get():
            messagebox.showwarning(_("WARNING"), _("PLEASE_SELECT_FOLDER"))
            return
        
        self.execute_button.config(state="disabled", text=_("EXECUTING"))
        
        thread = threading.Thread(target=self.run_programs)
        thread.daemon = True
        thread.start()
    
    def run_programs(self):
        result1 = self.execute_first_program()
        self.root.after(0, self.first_program_completed, result1)
    
    def execute_first_program(self):
        self.input_path = self.input_folder.get()
        self.output_path = self.output_folder.get()

        if not os.path.isdir(self.input_path):
            return False, "", _("INPUT_NOT_EXIST")

        cmd = [
                sys.executable, "convert_case.py", 
                "-i", self.input_path,
                "-o", self.output_path,
                "-p", self.partition_count.get(),
            ]
        if self.auto_partition.get(): 
            cmd.append("--auto-partition")
        if self.non_passenger_links.get():
            cmd.append("--non-passenger-links")
        if self.non_scc_links.get():
            cmd.append("--non-scc-items")
        
        p = subprocess.run(
            cmd, text=True,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        if p.returncode != 0:
            return False, p.stdout, p.stderr
        else:
            return True, p.stdout, p.stderr

    def first_program_completed(self, result):
        ok, out, err = result
        if not ok:
            messagebox.showerror(_("ERROR"), _("FAILED_MSG").format(err))
            self.reset_ui()
            return
    
        answer = messagebox.askyesno(_("CONTINUE"), _("CONTINUE_MSG"))
        
        if answer:
            self.root.destroy()
            import os
            os.system(f'python gui_main.py -d "{self.output_path}"')
        else:
            self.reset_ui()
    
    def reset_ui(self):
        self.execute_button.config(state="normal", text=_("EXECUTE"))


def main():
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()

if __name__ == "__main__":
    main()