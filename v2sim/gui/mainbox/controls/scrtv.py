from v2sim.gui.common import *

from feasytools import RangeList, SegFunc

_L = LangLib.Load(__file__)
ALWAYS_ONLINE = _L['ALWAYS_ONLINE']

def empty_postfunc(itm:Tuple[Any,...], val:str): pass

PostFunc = Callable[[Tuple[Any,...], str], None]    
    
# Double click to edit the cell: https://blog.csdn.net/falwat/article/details/127494533
class ScrollableTreeView(Frame):
    def show_title(self, title:str):
        self.lb_title.config(text=title)
        self.lb_title.grid(row=0,column=0,padx=3,pady=3,sticky="w",columnspan=2)

    def hide_title(self):
        self.lb_title.grid_remove()

    def __init__(self, master, allowSave:bool = False, allowAdd:bool = False, allowDel:bool = False, 
                 allowMove:bool = False, addgetter:Optional[Callable[[], Optional[List[Any]]]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.post_func = empty_postfunc
        self._afterf = None
        self.lb_title = Label(self, text=_L["NOT_OPEN"])
        self.tree = Treeview(self)
        self.tree.grid(row=1,column=0,sticky='nsew')
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.VScroll1 = Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.VScroll1.grid(row=1, column=1, sticky='ns')
        self.HScroll1 = Scrollbar(self, orient='horizontal', command=self.tree.xview)
        self.HScroll1.grid(row=2, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=self.VScroll1.set,xscrollcommand=self.HScroll1.set)
        self.bottom_panel = Frame(self)
        self.btn_save = Button(self.bottom_panel, text=_L["SAVE"], command=self.save)
        self.lb_save = Label(self.bottom_panel, text=_L["NOT_OPEN"])
        self.lb_note = Label(self.bottom_panel, text=_L["EDIT_NOTE"])
        self.btn_add = Button(self.bottom_panel, text=_L["ADD"], command=self.additm)
        self.btn_del = Button(self.bottom_panel, text=_L["DELETE"], command=self.delitm)
        self.btn_moveup = Button(self.bottom_panel, text=_L["UP"], command=self.moveup)
        self.btn_movedown = Button(self.bottom_panel, text=_L["DOWN"], command=self.movedown)
        self.addgetter = addgetter
        if allowSave or allowAdd or allowDel or allowMove:
            self.bottom_panel.grid(row=3,column=0,padx=3,pady=3,sticky="nsew")
        if allowSave:
            self.btn_save.grid(row=0,column=0,padx=3,pady=3,sticky="w")
            self.lb_save.grid(row=0,column=1,padx=3,pady=3,sticky="w")
            self.lb_note.grid(row=0,column=2,padx=20,pady=3,sticky="w")
        if allowAdd and self.addgetter is not None:
            self.btn_add.grid(row=0,column=3,pady=3,sticky="e")
        if allowDel:
            self.btn_del.grid(row=0,column=4,pady=3,sticky="e")
        if allowMove:
            self.btn_moveup.grid(row=0,column=5,pady=3,sticky="e")
            self.btn_movedown.grid(row=0,column=6,pady=3,sticky="e")
        self.delegate_var = StringVar()
        self.tree.bind('<Double-1>', func=self.tree_item_edit)
        self.onSave = None
        self.edit_mode:'Dict[str, Tuple[ConfigItem, PostFunc]]' = {}
        self.delegate_widget = None
        self.selected_item = None

    def additm(self):
        if self.addgetter:
            cols = self.addgetter()
            if cols is None or len(cols) != len(self.tree["columns"]):
                MB.showerror(_L["ERROR"], _L["ADD_FAILED"])
                return
            self.tree.insert("", "end", values=cols)
            self.lb_save.config(text=_L["UNSAVED"],foreground="red")
            if self._afterf: self._afterf()
    
    def delitm(self):
        dlist = [self.tree.item(x, "values")[0] for x in self.tree.selection()]
        if MB.askokcancel(_L["DELETE"], _L["DELETE_CONFIRM"].format(','.join(dlist))):
            for i in self.tree.selection():
                self.tree.delete(i)
            self.lb_save.config(text=_L["UNSAVED"],foreground="red")
            if self._afterf: self._afterf()

    def moveup(self):
        for i in self.tree.selection():
            p = self.tree.index(i)
            self.tree.move(i, "", p-1)
        self.lb_save.config(text=_L["UNSAVED"],foreground="red")
        if self._afterf: self._afterf()
    
    def movedown(self):
        for i in self.tree.selection():
            p = self.tree.index(i)
            self.tree.move(i, "", p+1)
        self.lb_save.config(text=_L["UNSAVED"],foreground="red")
        if self._afterf: self._afterf()
    
    def save(self):
        if self.onSave:
            if self.onSave(self.getAllData()):
                self.lb_save.config(text=_L["SAVED"],foreground="green")
    
    def setOnSave(self, onSave:Callable[[List[tuple]], bool]):
        self.onSave = onSave
    
    def item(self, item, option=None, **kw):
        return self.tree.item(item, option, **kw)
    
    def getAllData(self) -> List[tuple]:
        res = []
        for i in self.tree.get_children():
            res.append(self.tree.item(i, "values"))
        return res
    
    def setColEditMode(self, col:str, mode:ConfigItem, post_func:PostFunc = empty_postfunc):
        self.__setEditMode("COL:" + col, mode, post_func)

    def setRowEditMode(self, row:str, mode:ConfigItem, post_func:PostFunc = empty_postfunc):
        self.__setEditMode("ROW:" + row, mode, post_func)
        print(row,mode)

    def setCellEditMode(self, row:str, col:str, mode:ConfigItem, post_func:PostFunc = empty_postfunc):
        self.__setEditMode("CELL:" + row + "@" + col, mode, post_func)

    def clearEditModes(self):
        self.edit_mode.clear()
    
    def __setEditMode(self, label:str, cfgitm:ConfigItem, post_func:PostFunc = empty_postfunc):
        mode = cfgitm.editor
        if mode == EditMode.SPIN:
            if cfgitm.spin_range is None: cfgitm.spin_range = (0, 100)
        elif mode == EditMode.COMBO:
            if cfgitm.combo_values is None: cfgitm.combo_values = []
        self.edit_mode[label] = (cfgitm, post_func)

    def disableEdit(self):
        self.tree.unbind('<Double-1>')
    
    def enableEdit(self):
        self.tree.bind('<Double-1>', func=self.tree_item_edit)
    
    def tree_item_edit(self, e: Event):
        if len(self.tree.selection()) == 0:
            return
        
        self.selected_item = self.tree.selection()[0]
        selected_row = self.tree.item(self.selected_item, "values")[0]

        for i, col in enumerate(self.tree['columns']):
            x, y, w, h = self.tree.bbox(self.selected_item, col)
            assert isinstance(x, int) and isinstance(y, int) and isinstance(w, int) and isinstance(h, int)
            if x < e.x < x + w and y < e.y < y + h:
                self.selected_column = col
                text = self.tree.item(self.selected_item, 'values')[i]
                break
        else:
            self.selected_column = None
            x, y, w, h =  self.tree.bbox(self.selected_item)
            assert isinstance(x, int) and isinstance(y, int) and isinstance(w, int) and isinstance(h, int)
            text = self.tree.item(self.selected_item, 'text')
        
        self.delegate_var.set(text)
        possible_labels = []
        if self.selected_column is not None and selected_row is not None:
            possible_labels.append("CELL:" + selected_row + "@" + self.selected_column)
        if self.selected_column is not None:
            possible_labels.append("COL:" + self.selected_column)
        if selected_row is not None:
            possible_labels.append("ROW:" + selected_row)
        
        label = None
        for lb in possible_labels:
            if lb in self.edit_mode:
                label = lb
                break
        
        if label is None: return
        
        cfg, self.post_func = self.edit_mode[label]
        if cfg.editor == EditMode.COMBO:
            assert isinstance(cfg.combo_values, (list, tuple))
            self.delegate_widget = Combobox(self.tree, width=w // 10, textvariable=self.delegate_var, values=cfg.combo_values)
            self.delegate_widget.bind('<<ComboboxSelected>>', self.tree_item_edit_done)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.CHECKBOX:
            self.delegate_widget = Combobox(self.tree, width=w // 10, textvariable=self.delegate_var, values=[str(True), str(False)])
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.SPIN:
            assert isinstance(cfg.spin_range, tuple) and len(cfg.spin_range) == 2
            self.delegate_widget = Spinbox(self.tree, width=w // 10, textvariable=self.delegate_var, from_=cfg.spin_range[0], to=cfg.spin_range[1], increment=1)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.ENTRY:
            self.delegate_widget = Entry(self.tree, width=w // 10, textvariable=self.delegate_var)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.RANGELIST:
            d = self.delegate_var.get()
            if d == ALWAYS_ONLINE: d = "[]"
            from .rle import RangeListEditor
            self.delegate_widget = RangeListEditor(RangeList(eval(d)), self.delegate_var, True)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.PROP:
            assert isinstance(cfg.prop_config, ConfigItemDict)
            d = self.delegate_var.get()
            from .prope import PropertyEditor
            self.delegate_widget = PropertyEditor(eval(d), self.delegate_var, edit_modes=cfg.prop_config)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.PDFUNC:
            from .pdfe import PDFuncEditor
            self.delegate_widget = PDFuncEditor(self.delegate_var)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.SEGFUNC:
            d = self.delegate_var.get()
            obj = eval(d)
            if obj is None: obj = []
            elif isinstance(obj, (float, int)): obj = [(0,obj)]
            assert isinstance(obj, list)
            for xx in obj:
                assert isinstance(xx, tuple)
                assert isinstance(xx[0], int)
                assert isinstance(xx[1], (int,float))
            self.delegate_widget = SegFuncEditor(SegFunc(obj), self.delegate_var) # type: ignore
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        else:
            return
        if not isinstance(self.delegate_widget, Toplevel):
            self.delegate_widget.place(width=w, height=h, x=x, y=y)
        self.delegate_widget.focus()
        self.lb_save.config(text=_L["UNSAVED"],foreground="red")

    def tree_item_edit_done(self, e):
        if self.delegate_widget and not isinstance(self.delegate_widget, Toplevel):
            self.delegate_widget.place_forget()
        v = self.delegate_var.get()
        if not self.selected_item: return
        try:
            line = self.tree.item(self.selected_item, 'values')
        except:
            return
        assert isinstance(line, tuple)
        self.post_func(line, v)
        if self.selected_column is None:
            self.tree.item(self.selected_item, text=v)
        else:
            self.tree.set(self.selected_item, self.selected_column, v)
        if self._afterf: self._afterf()
    
    @property
    def AfterFunc(self):
        '''Function to be executed when an item is editted'''
        return self._afterf
    
    @AfterFunc.setter
    def AfterFunc(self, v):
        self._afterf = v
    
    def __setitem__(self, key, val):
        self.tree[key] = val
    
    def __getitem__(self, key):
        return self.tree[key]
    
    def column(self, *args, **kwargs):
        self.tree.column(*args, **kwargs)
    
    def heading(self, *args, **kwargs):
        self.tree.heading(*args, **kwargs)
    
    def insert(self, *args, **kwargs):
        self.tree.insert(*args, **kwargs)
    
    def delete(self, *items:Union[str,int]):
        self.tree.delete(*items)
    
    def set(self, item:Union[str, int], column:Union[None, str, int], value:Any):
        self.tree.set(item, column, value)
    
    def selection(self):
        return self.tree.selection()
    
    def get_children(self):
        return self.tree.get_children()
    
    def clear(self):
        self.delete(*self.get_children())
        self.lb_save.config(text=_L["SAVED"], foreground="green")
    
    @property
    def saved(self):
        return self.lb_save.cget("text") != _L["UNSAVED"]

__all__ = ["ScrollableTreeView", "ALWAYS_ONLINE", "empty_postfunc", "PostFunc"]