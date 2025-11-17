from v2simux.gui.common import *
from collections import defaultdict
import v2simux
import os
import shutil


_ = LangLib.Load(__file__)


class PlgBox(Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title(_("TITLE"))
        self.geometry("640x480")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        plgs, stas = v2simux.load_external_components()
        combined:Dict[str, List[str]] = defaultdict(list)
        for k, v in plgs.items():
            combined[k].append(_("PLUGIN_ITEM").format(v[0], v[1].__name__, '.'.join(v[2])))
        for k, v in stas.items():
            combined[k].append(_("STA_ITEM").format(v[0], v[1].__name__))

        tree = Treeview(self)
        tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        vsb = Scrollbar(self, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        for key, val in combined.items():
            key_id = tree.insert('', 'end', text=f"{key}.py", open=False)
            for v in val:
                tree.insert(key_id, 'end', text=v)
        
        def refresh_tree():
            for iid in tree.get_children():
                tree.delete(iid)

            plgs, stas = v2simux.load_external_components()
            combined = defaultdict(list)
            for k, v in plgs.items():
                combined[k].append(_("PLUGIN_ITEM").format(v[0], v[1].__name__, '.'.join(v[2])))
            for k, v in stas.items():
                combined[k].append(_("STA_ITEM").format(v[0], v[1].__name__))

            for key, val in combined.items():
                key_id = tree.insert('', 'end', text=f"{key}.py", open=False)
                for v in val:
                    tree.insert(key_id, 'end', text=v)

        def get_lang_file(src_path: Union[str, Path]) -> Union[Path, None]:
            src_parent = Path(src_path).parent
            if (src_parent / "_lang").is_dir():
                src_lang = src_parent / "_lang"
            elif (src_parent / (Path(src_path).stem + ".langs")).is_file():
                src_lang = src_parent / (Path(src_path).stem + ".langs")
            else:
                src_lang = None
            return src_lang
        
        def on_import():
            src = filedialog.askopenfilename(title=_("IMPORT_PLUGIN_TITLE"), filetypes=[(_("Python files"), "*.py")])
            if not src:
                return
            src_lang = get_lang_file(src)

            dest_dir = v2simux.PLUGINS_DIR

            try:
                dest_path = os.path.join(dest_dir, os.path.basename(src))
                shutil.copy2(src, dest_path)
                if src_lang is not None:
                    shutil.copy2(src_lang, dest_dir / src_lang.name)
                MB.showinfo(_("INFO"), _("IMPORT_SUCCESS"))
                refresh_tree()
            except Exception as e:
                MB.showerror(_("ERROR"), str(e))

        def on_delete():
            sel = tree.selection()
            if not sel:
                return
            sel_id = sel[0]
            if tree.parent(sel_id) != '':
                MB.showwarning(_("WARNING"), _("DELETE_ONLY_TOPLEVEL"))
                return

            text = tree.item(sel_id, "text")  # like "name.py"
            if not text:
                return
            if not MB.askyesno(_("CONFIRM"), _("CONFIRM_DELETE").format(text)):
                return

            file = v2simux.PLUGINS_DIR / text  # keep extension
            src_lang = get_lang_file(file)
            try:
                os.remove(file)
                if src_lang is not None:
                    os.remove(src_lang)
                MB.showinfo(_("INFO"), _("DELETE_SUCCESS"))
                refresh_tree()
            except Exception as e:
                MB.showerror(_("ERROR"), str(e))

        def on_tree_select(event=None):
            sel = tree.selection()
            state = "disabled"
            if len(sel) == 1 and tree.parent(sel[0]) == '':
                state = "normal"
            btn_delete.config(state=state)

        # buttons frame
        btn_frame = Frame(self)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 10))

        btn_import = Button(btn_frame, text=_("IMPORT_BUTTON"), command=on_import)
        btn_import.pack(side="left", padx=(0, 4))

        btn_delete = Button(btn_frame, text=_("DELETE_BUTTON"), command=on_delete, state="disabled")
        btn_delete.pack(side="left")

        # bind selection change
        tree.bind("<<TreeviewSelect>>", on_tree_select)

        # initial enable/disable state
        on_tree_select()

        # make sure the tree reflects any changes (in case import/delete used internal APIs)
        refresh_tree()