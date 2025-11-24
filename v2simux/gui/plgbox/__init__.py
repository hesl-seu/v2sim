from v2simux.gui.common import *
from collections import defaultdict
from v2simux import load_external_components, PLUGINS_DIR, get_internal_components
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

        tree = Treeview(self)
        # hide the column headings, show only the tree column
        tree["show"] = "tree"
        # ensure the tree column (#0) expands to fill available space
        tree.column("#0", anchor="w", stretch=True)
        tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        vsb = Scrollbar(self, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        def refresh_tree(confirm_have:str = ""):
            confirm_have_exists = False
            for iid in tree.get_children():
                tree.delete(iid)
            
            # Load internal components
            plgs_i, stas_i = get_internal_components()
            key_id = tree.insert('', 'end', text=_("INTERNAL"), open=False)
            for k, p, d in plgs_i:
                tree.insert(key_id, 'end', text=_("PLUGIN_ITEM").format(k, p.__name__, '.'.join(d)))
            for k, p in stas_i:
                tree.insert(key_id, 'end', text=_("STA_ITEM").format(k, p.__name__))

            # Load external components
            plgs, stas = load_external_components()
            combined = defaultdict(list)
            for k, v in plgs.items():
                combined[k].append(_("PLUGIN_ITEM").format(v[0], v[1].__name__, '.'.join(v[2])))
            for k, v in stas.items():
                combined[k].append(_("STA_ITEM").format(v[0], v[1].__name__))

            for key, val in combined.items():
                if (PLUGINS_DIR / f"{key}.py").exists():
                    fname = f"{key}.py"
                elif (PLUGINS_DIR / f"{key}.link").exists():
                    fname = f"{key}.link"
                else:
                    raise RuntimeError("Internal error: plugin/statistics file not found.")
                
                key_id = tree.insert('', 'end', text=fname, open=False)
                if key == confirm_have:
                    confirm_have_exists = True
                for v in val:
                    tree.insert(key_id, 'end', text=v)
            return confirm_have_exists

        def get_lang_file(src_path: Union[str, Path]) -> Union[Path, None]:
            src_parent = Path(src_path).parent
            if (src_parent / "_lang").is_dir():
                src_lang = src_parent / "_lang"
            elif (src_parent / (Path(src_path).stem + ".langs")).is_file():
                src_lang = src_parent / (Path(src_path).stem + ".langs")
            else:
                src_lang = None
            return src_lang
        
        def on_import(link = False):
            src = filedialog.askopenfilename(title=_("IMPORT_PLUGIN_TITLE"), filetypes=[(_("Python files"), "*.py")])
            if not src: return
            src_lang = get_lang_file(src)

            dest_dir = PLUGINS_DIR
            dest_dir.mkdir(parents=True, exist_ok=True)

            dest_path_link = dest_dir / (Path(src).stem + ".link")
            dest_path_py = dest_dir / (Path(src).stem + ".py")
            
            try:
                if dest_path_link.exists():
                    raise RuntimeError(_("ERROR_FILE_EXISTS").format(dest_path_link.name))
                if dest_path_py.exists():
                    raise RuntimeError(_("ERROR_FILE_EXISTS").format(dest_path_py.name))
                if link:
                    with open(dest_path_link, "w", encoding="utf-8") as f:
                        f.write(src)
                else:
                    shutil.copy2(src, dest_path_py)
                    if src_lang is not None:
                        shutil.copy2(src_lang, dest_dir / src_lang.name)
                plg_name = Path(src).stem
                if refresh_tree(plg_name):
                    MB.showinfo(_("INFO"), _("IMPORT_SUCCESS").format(plg_name))
                else:
                    MB.showwarning(_("WARNING"), _("IMPORT_BUT_NOT_LOADED").format(plg_name))
            except Exception as e:
                MB.showerror(_("ERROR"), str(e))
        
        def on_import_link():
            on_import(link=True)

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

            file = PLUGINS_DIR / text  # keep extension
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
                text = tree.item(sel[0], "text")
                if text and text != _("INTERNAL"):
                    state = "normal"
            btn_delete.config(state=state)

        # buttons frame
        btn_frame = Frame(self)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 10))

        btn_import = Button(btn_frame, text=_("IMPORT_BUTTON"), command=on_import)
        btn_import.pack(side="left", padx=(0, 4))

        btn_import_link = Button(btn_frame, text=_("IMPORT_LINK_BUTTON"), command=on_import_link)
        btn_import_link.pack(side="left", padx=(0, 4))

        btn_delete = Button(btn_frame, text=_("DELETE_BUTTON"), command=on_delete, state="disabled")
        btn_delete.pack(side="left")

        # bind selection change
        tree.bind("<<TreeviewSelect>>", on_tree_select)

        # initial enable/disable state
        on_tree_select()

        # make sure the tree reflects any changes (in case import/delete used internal APIs)
        refresh_tree()