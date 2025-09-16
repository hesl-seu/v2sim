from .view import *
from typing import Any, Callable, Iterable, Optional, Union, Dict, List, Tuple
from feasytools import RangeList, SegFunc, CreatePDFunc
from v2sim.trafficgen.misc import * # import PDFuncs
from tkinter import messagebox as MB
from v2sim import CustomLocaleLib, EditMode, ConfigItem, ConfigItemDict

_loc = CustomLocaleLib(["zh_CN","en"])
_loc.SetLanguageLib("zh_CN",
    ALWAYS_ONLINE = "总是启用",
    NOT_OPEN = "(未打开)",
    EDIT_NOTE = "双击以编辑单元格(可能不是所有列都可编辑)",
    SAVE = "保存",
    SAVED = "已保存",
    UNSAVED = "未保存",
    RANGE_LIST_EDITOR = "范围列表编辑器",
    TIME_FORMAT = "时间格式为HH:MM:SS",
    INVALID_TIME_FORMAT = "无效的时间格式",
    ERROR = "错误",
    ADD = "添加",
    DELETE = "删除",
    UP = "上移",
    DOWN = "下移",
    DELETE_CONFIRM = "确认删除{}吗？",
    SAVE_AND_CLOSE = "保存并关闭",
    SEG_FUNC_EDITOR = "分段函数编辑器",
    INVALID_SEG_FUNC = "无效的分段函数: 时间必须严格递增的整数，数据必须是浮点数",
    PROPERTY_EDITOR = "属性编辑器",
    LEFT_BOUND = "左边界",
    RIGHT_BOUND = "右边界",
    PROPERTY = "属性",
    VALUE = "值",
    PDFUNC_EDITOR = "概率密度函数编辑器",
    PDMODEL = "概率密度模型",
    PROP_NODESC = "(无描述)",
    ADD_FAILED = "添加项目失败: 获取的数据无效",
)

_loc.SetLanguageLib("en",
    ALWAYS_ONLINE = "Always online",
    NOT_OPEN = "(Not open)",
    EDIT_NOTE = "Double click to edit the cell (Perhaps NOT all columns are editable)",
    SAVE = "Save",
    SAVED = "Saved",
    UNSAVED = "Unsaved",
    RANGE_LIST_EDITOR = "Range List Editor",
    TIME_FORMAT = "Time format is HH:MM:SS",
    INVALID_TIME_FORMAT = "Invalid time format",
    ERROR = "Error",
    ADD = "Add",
    DELETE = "Delete",
    UP = "Up",
    DOWN = "Down",
    DELETE_CONFIRM = "Are you sure to delete {}?",
    SAVE_AND_CLOSE = "Save & Close",
    SEG_FUNC_EDITOR = "Segmented Function Editor",
    INVALID_SEG_FUNC = "Invalid segmented function: time must be strictly increasing integers, and data must be floats",
    PROPERTY_EDITOR = "Property Editor",
    LEFT_BOUND = "Left bound",
    RIGHT_BOUND = "Right bound",
    PROPERTY = "Property",
    VALUE = "Value",
    PDFUNC_EDITOR = "Probability Density Function Editor",
    PDMODEL = "PDF Model",
    PROP_NODESC = "(No description)",
    ADD_FAILED = "Failed to add item: invalid data from getter",
)

def _removeprefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    return s

ALWAYS_ONLINE = _loc['ALWAYS_ONLINE']
def empty_postfunc(itm:Tuple[Any,...], val:str): pass

class LogItemPad(LabelFrame):
    def __init__(self, master, title:str, items:Dict[str,str], **kwargs):
        super().__init__(master, text=title, **kwargs)
        self._bvs:Dict[str,BooleanVar] = {}
        self._cbs:Dict[str,Checkbutton] = {}
        for id, val in items.items():
            bv = BooleanVar(self, True)
            self._bvs[id] = bv
            cb = Checkbutton(self, text=val, variable=bv)
            cb.pack(anchor='w', side='left')
            self._cbs[id] = cb
            
    def __getitem__(self, key:str):
        return self._bvs[key].get()
    
    def __setitem__(self, key:str, val:bool):
        self._bvs[key].set(val)
    
    def enable(self, key:str):
        return self._cbs[key].configure(state="enabled")

    def disable(self, key:str):
        return self._cbs[key].configure(state="disabled")
    
    def setEnabled(self, key:str, v:bool):
        if v:
            return self._cbs[key].configure(state="enabled")
        else:
            return self._cbs[key].configure(state="disabled")
    
    def getSelected(self):
        return [k for k, v in self._bvs.items() if v.get()]
    
    def __contains__(self, key:str):
        return key in self._bvs

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
        self.lb_title = Label(self, text=_loc["NOT_OPEN"])
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
        self.btn_save = Button(self.bottom_panel, text=_loc["SAVE"], command=self.save)
        self.lb_save = Label(self.bottom_panel, text=_loc["NOT_OPEN"])
        self.lb_note = Label(self.bottom_panel, text=_loc["EDIT_NOTE"])
        self.btn_add = Button(self.bottom_panel, text=_loc["ADD"], command=self.additm)
        self.btn_del = Button(self.bottom_panel, text=_loc["DELETE"], command=self.delitm)
        self.btn_moveup = Button(self.bottom_panel, text=_loc["UP"], command=self.moveup)
        self.btn_movedown = Button(self.bottom_panel, text=_loc["DOWN"], command=self.movedown)
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
                messagebox.showerror(_loc["ERROR"], _loc["ADD_FAILED"])
                return
            self.tree.insert("", "end", values=cols)
            self.lb_save.config(text=_loc["UNSAVED"],foreground="red")
            if self._afterf: self._afterf()
    
    def delitm(self):
        dlist = [self.tree.item(x, "values")[0] for x in self.tree.selection()]
        if messagebox.askokcancel(_loc["DELETE"], _loc["DELETE_CONFIRM"].format(','.join(dlist))):
            for i in self.tree.selection():
                self.tree.delete(i)
            self.lb_save.config(text=_loc["UNSAVED"],foreground="red")
            if self._afterf: self._afterf()

    def moveup(self):
        for i in self.tree.selection():
            p = self.tree.index(i)
            self.tree.move(i, "", p-1)
        self.lb_save.config(text=_loc["UNSAVED"],foreground="red")
        if self._afterf: self._afterf()
    
    def movedown(self):
        for i in self.tree.selection():
            p = self.tree.index(i)
            self.tree.move(i, "", p+1)
        self.lb_save.config(text=_loc["UNSAVED"],foreground="red")
        if self._afterf: self._afterf()
    
    def save(self):
        if self.onSave:
            if self.onSave(self.getAllData()):
                self.lb_save.config(text=_loc["SAVED"],foreground="green")
    
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
            self.delegate_widget = RangeListEditor(RangeList(eval(d)), self.delegate_var, True)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.PROP:
            assert isinstance(cfg.prop_config, ConfigItemDict)
            d = self.delegate_var.get()
            self.delegate_widget = PropertyEditor(eval(d), self.delegate_var, edit_modes=cfg.prop_config)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif cfg.editor == EditMode.PDFUNC:
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
        self.lb_save.config(text=_loc["UNSAVED"],foreground="red")

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
        self.lb_save.config(text=_loc["SAVED"], foreground="green")
    
    @property
    def saved(self):
        return self.lb_save.cget("text") != _loc["UNSAVED"]


class RangeListEditor(Toplevel):
    def __init__(self, data:RangeList, var:StringVar, hint_hms:bool=False):
        super().__init__()
        self.title(_loc["RANGE_LIST_EDITOR"])
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("lb", "rb")
        self.tree.column("lb", width=120, stretch=NO)
        self.tree.column("rb", width=120, stretch=NO)
        self.tree.heading("lb", text=_loc["LEFT_BOUND"])
        self.tree.heading("rb", text=_loc["RIGHT_BOUND"])
        self.tree.pack(fill="both", expand=True)
        for l,r in data:
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("lb", ConfigItem(
            name="lb", editor=EditMode.ENTRY, desc="Left Bound", default_value=0))
        self.tree.setColEditMode("rb", ConfigItem(
            name="rb", editor=EditMode.ENTRY, desc="Right Bound", default_value=0))
        if hint_hms:
            self.lb_hint = Label(self, text=_loc["TIME_FORMAT"])
            self.lb_hint.pack(fill="x", expand=False)
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_add = Button(self.fr, text=_loc["ADD"], command=self.add, width=6)
        self.btn_add.grid(row=0,column=0,pady=3,sticky="w")
        self.btn_del = Button(self.fr, text=_loc["DELETE"], command=self.delete, width=6)
        self.btn_del.grid(row=0,column=1,pady=3,sticky="w")
        self.btn_moveup = Button(self.fr, text=_loc["UP"], command=self.moveup, width=6)
        self.btn_moveup.grid(row=0,column=2,pady=3,sticky="w")
        self.btn_movedown = Button(self.fr, text=_loc["DOWN"], command=self.movedown, width=6)
        self.btn_movedown.grid(row=0,column=3,pady=3,sticky="w")
        self.btn_save = Button(self.fr, text=_loc["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var
    
    def add(self):
        self.tree.insert("", "end", values=(0, 0))
    
    def delete(self):
        for i in self.tree.tree.selection():
            self.tree.delete(i)
    
    def moveup(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p-1)
    
    def movedown(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p+1)
    
    def save(self):
        try:
            d = self.getAllData()
        except:
            MB.showerror(_loc["ERROR"], _loc["INVALID_TIME_FORMAT"])
            return
        if len(d) == 0:
            self.var.set(ALWAYS_ONLINE)
        else:
            self.var.set(str(d))
        self.destroy()

    def getAllData(self) -> RangeList:
        res:List[Tuple[int,int]] = []
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res.append((RangeList.parse_time(x[0]), RangeList.parse_time(x[1])))
        return RangeList(res)


class SegFuncEditor(Toplevel):
    def __init__(self, data:SegFunc, var:StringVar):
        super().__init__()
        self.title(_loc["SEG_FUNC_EDITOR"])
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=NO)
        self.tree.heading("t", text="Time")
        self.tree.heading("d", text="Data")
        self.tree.pack(fill="both", expand=True)
        for l,r in data:
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("t", ConfigItem(
            name="t", editor=EditMode.ENTRY, desc="Time"))
        self.tree.setColEditMode("d", ConfigItem(
            name="d", editor=EditMode.ENTRY, desc="Data"))
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_add = Button(self.fr, text=_loc["ADD"], command=self.add, width=6)
        self.btn_add.grid(row=0,column=0,pady=3,sticky="w")
        self.btn_del = Button(self.fr, text=_loc["DELETE"], command=self.delete, width=6)
        self.btn_del.grid(row=0,column=1,pady=3,sticky="w")
        self.btn_moveup = Button(self.fr, text=_loc["UP"], command=self.moveup, width=6)
        self.btn_moveup.grid(row=0,column=2,pady=3,sticky="w")
        self.btn_movedown = Button(self.fr, text=_loc["DOWN"], command=self.movedown, width=6)
        self.btn_movedown.grid(row=0,column=3,pady=3,sticky="w")
        self.btn_save = Button(self.fr, text=_loc["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var
    
    def add(self):
        self.tree.insert("", "end", values=(0, 0))
    
    def delete(self):
        for i in self.tree.tree.selection():
            self.tree.delete(i)
    
    def moveup(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p-1)
    
    def movedown(self):
        for i in self.tree.tree.selection():
            p = self.tree.tree.index(i)
            self.tree.tree.move(i, "", p+1)
    
    def save(self):
        try:
            d = self.getAllData()
        except:
            MB.showerror(_loc["ERROR"], _loc["INVALID_SEG_FUNC"])
            return
        if len(d) == 0:
            self.var.set(str(None))
        else:
            self.var.set(str(d))
        self.destroy()

    def getAllData(self) -> SegFunc:
        res:List[Tuple[int,float]] = []
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res.append((int(x[0]), float(x[1])))
        return SegFunc(res)


class EditDesc:
    def __init__(self, typename:type):
        self._t = typename.__name__
        self._desc:Dict[str,str] = {}
        self._text:Dict[str,str] = {}
        self._dtype:Dict[str,type] = {}
        self._em:Dict[str,EditMode] = {}
        self._em_kwargs:Dict[str,Dict[str,Any]] = {}
        self._onchanged:Dict[str,Optional[Callable[[Any,Any],None]]] = {}
    
    def add(self, key:str, show:str, dtype:type, desc:str, 
            edit_mode:EditMode, onchanged = None, **kwargs):
        self._desc[key] = desc
        self._text[key] = show
        self._dtype[key] = dtype
        self._em[key] = edit_mode
        self._em_kwargs[key] = kwargs
        self._onchanged[key] = onchanged
        return self
    
    @staticmethod
    def create(typename:type, default_edit_mode:EditMode):
        return EditDesc(typename)

class EditDescGroup:
    def __init__(self, EditDescs:Iterable[EditDesc]):
        self._eds = {ed._t:ed for ed in EditDescs}
    
    def get(self, inst:Any) -> EditDesc:
        typename = type(inst).__name__
        if typename not in self._eds:
            raise KeyError(f"Type {typename} not found in EditDescGroup")
        return self._eds[typename]
    

class PropertyPanel(Frame):
    def __onclick(self, event):
        if len(self.tree.selection()) == 0:
            self.__desc_var.set(_loc["PROP_NODESC"])
            return
        self.selected_item = self.tree.selection()[0]
        selected_row = self.tree.item(self.selected_item, "values")[0]
        self.__desc_var.set(self.__em.get_desc(selected_row))

    def setData(self, data:Dict[str, Any], edit_modes:ConfigItemDict):
        self.tree.tree_item_edit_done(None)
        self.data = data
        self.__em:ConfigItemDict = edit_modes
        if edit_modes is None: edit_modes = {}
        self.tree.clear()
        for l, r in data.items():
            self.tree.insert("", "end", values=(l, r))
            self.tree.setCellEditMode(l, "d", edit_modes.get(l))      
    
    def __init__(self, master, data:Dict[str,str], edit_modes:ConfigItemDict, **kwargs):
        super().__init__(master, **kwargs)
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=YES)
        self.tree.heading("t", text=_loc["PROPERTY"])
        self.tree.heading("d", text=_loc["VALUE"])
        self.tree.tree.bind("<<TreeviewSelect>>", self.__onclick)
        self.tree.pack(fill="both", expand=True)
        self.__desc_var = StringVar(self, _loc["PROP_NODESC"])
        self.__desc = Label(self, textvariable=self.__desc_var)
        self.__desc.pack(fill="x", expand=False)
        self.setData(data, edit_modes)

    def getAllData(self) -> Dict[str, str]:
        res:Dict[str, str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res

class PropertyEditor(Toplevel):
    def __init__(self, data:Dict[str,str], var:StringVar, edit_modes:ConfigItemDict):
        super().__init__()
        self.title(_loc["PROPERTY_EDITOR"])
        self.__panel = PropertyPanel(self, data, edit_modes)
        self.__panel.pack(fill="both", expand=True)
        self.__fr = Frame(self)
        self.__fr.pack(fill="x", expand=False)
        self.__btn_save = Button(self.__fr, text=_loc["SAVE_AND_CLOSE"], command=self.save)
        self.__btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var
    
    def getAllData(self) -> Dict[str,str]:
        return self.__panel.getAllData()
    
    def save(self):
        d = self.getAllData()
        self.var.set(repr(d))
        self.destroy()

class PDFuncEditor(Toplevel):
    def reset_tree(self, pdfunc:PDFunc):
        self.tree.clear()
        for l,r in pdfunc.__dict__.items():
            self.tree.insert("", "end", values=(l, r))
    
    def __init__(self, var: StringVar):
        super().__init__()
        self.title(_loc["PDFUNC_EDITOR"])
        pdfunc = eval(var.get())
        assert isinstance(pdfunc, PDFunc)
        self.model = StringVar(self, _removeprefix(pdfunc.__class__.__name__, "PD"))
        self.fr0 = Frame(self)
        self.mlabel = Label(self.fr0, text=_loc["PDMODEL"])
        self.mlabel.grid(row=0,column=0,padx=3,pady=3,sticky="w")
        self.cb = Combobox(self.fr0, textvariable=self.model,
            values=["Normal", "Uniform", "Triangular", 
            "Exponential", "Gamma", "Weibull", 
            "Beta", "LogNormal", "LogLogistic"])
        self.cb.bind('<<ComboboxSelected>>', lambda x: self.reset_tree(CreatePDFunc(self.model.get())))
        self.cb.grid(row=0,column=1,padx=3,pady=3,sticky="w")
        self.fr0.pack(fill="x", expand=True)
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=YES)
        self.tree.heading("t", text=_loc["PROPERTY"])
        self.tree.heading("d", text=_loc["VALUE"])
        self.tree.pack(fill="both", expand=True)
        self.reset_tree(pdfunc)
        self.tree.setColEditMode("d", ConfigItem(name="d", editor=EditMode.ENTRY, desc="Value"))
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_save = Button(self.fr, text=_loc["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var

    def getAllData(self) -> PDFunc:
        res:Dict[str, float] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = float(x[1])
        return CreatePDFunc(self.model.get(), **res)
    
    def save(self):
        d = self.getAllData()
        self.var.set(repr(d))
        self.destroy()