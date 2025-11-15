import traceback
from v2simux.gui.com_no_vx import *

import os, threading


_ = LangLib.Load(__file__)


class ConvertBox(Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(_("TITLE"))
        self.geometry("600x350")
        
        self.input_folder = StringVar()
        self.output_folder = StringVar()
        
        self.setup_ui()
    
    def setup_ui(self):
        input_frame = Frame(self)
        input_frame.pack(pady=10, padx=20, fill="x")

        Label(input_frame, text=_("INPUT")).pack(anchor="w")

        input_select_frame = Frame(input_frame)
        input_select_frame.pack(fill="x", pady=5)
        
        Entry(input_select_frame, textvariable=self.input_folder).pack(side="left", fill="x", expand=True)
        Button(input_select_frame, text=_("BROWSE"), 
                 command=self.select_input_folder, width=10).pack(side="right", padx=(5, 0))
        
        output_frame = Frame(self)
        output_frame.pack(pady=10, padx=20, fill="x")
        
        Label(output_frame, text=_("OUTPUT")).pack(anchor="w")
        
        output_select_frame = Frame(output_frame)
        output_select_frame.pack(fill="x", pady=5)
        
        Entry(output_select_frame, textvariable=self.output_folder).pack(side="left", fill="x", expand=True)
        Button(output_select_frame, text=_("BROWSE"), 
                 command=self.select_output_folder, width=10).pack(side="right", padx=(5, 0))
        
        partition_frame = Frame(self)
        partition_frame.pack(pady=10, padx=20, fill="x")
        partition_frame.columnconfigure(2, weight=1)

        self.partition_count = StringVar(value="1")
        self.auto_partition = BooleanVar(value=False)

        Label(partition_frame, text=_("PARTITION_COUNT")).grid(row=0, column=0, sticky="w")
        def on_auto_partition_changed(*args):
            state = "disabled" if self.auto_partition.get() else "normal"
            self.entry_count_widget.config(state=state)

        self.entry_count_widget = Spinbox(partition_frame, from_=1, to=32, textvariable=self.partition_count, width=5)
        self.entry_count_widget.grid(row=0, column=1, sticky="w")
        self.check_auto_part_widget = Checkbutton(partition_frame, text=_("PARTITION_TIP"), variable=self.auto_partition)
        self.check_auto_part_widget.grid(row=0, column=2, sticky="e")
        self.auto_partition.trace_add("write", on_auto_partition_changed)

        self.options_frame = Frame(self)
        self.options_frame.pack(pady=10, padx=20, fill="x")

        self.non_passenger_links = BooleanVar(value=False)
        self.check_non_passenger_links = Checkbutton(self.options_frame, text=_("NON_PASSENGER_LINKS"), variable=self.non_passenger_links)
        self.check_non_passenger_links.pack(anchor="w")

        self.non_scc_links = BooleanVar(value=False)
        self.check_non_scc_links = Checkbutton(self.options_frame, text=_("NON_SCC_LINKS"), variable=self.non_scc_links)
        self.check_non_scc_links.pack(anchor="w")

        self.execute_button = Button(self, text=_("EXECUTE"), command=self.execute_program)
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
            MB.showwarning(_("WARNING"), _("PLEASE_SELECT_FOLDER"))
            return
        
        self.execute_button.config(state="disabled", text=_("EXECUTING"))
        
        thread = threading.Thread(target=self.run_programs)
        thread.daemon = True
        thread.start()
    
    def run_programs(self):
        result1 = self.execute_first_program()
        self.after(0, self.first_program_completed, result1)
    
    def execute_first_program(self):
        self.input_path = self.input_folder.get()
        self.output_path = self.output_folder.get()

        if not os.path.isdir(self.input_path):
            return False, "", _("INPUT_NOT_EXIST")

        from v2simux import ConvertCase

        try:
            converted = ConvertCase(
                self.input_path, self.output_path, 
                part_cnt = int(self.partition_count.get()),
                auto_partition = self.auto_partition.get(),
                non_passenger_links = self.non_passenger_links.get(),
                non_scc_links = self.non_scc_links.get()
            )
            return converted, "", ""
        except Exception as e:
            traceback.print_exc()
            return False, "", str(e)

    def first_program_completed(self, result):
        ok, out, err = result
        if not ok:
            MB.showerror(_("ERROR"), _("FAILED_MSG").format(err))
            self.reset_ui()
            return
    
        answer = MB.askyesno(_("CONTINUE"), _("CONTINUE_MSG"))
        
        if answer:
            self.destroy()
            import os
            os.system(f'python gui_main.py -d "{self.output_path}"')
        else:
            self.reset_ui()
    
    def reset_ui(self):
        self.execute_button.config(state="normal", text=_("EXECUTE"))

__all__ = ["ConvertBox"]