from enum import Enum
from .view import *
from typing import Any, Callable, Iterable, Optional, Union, Dict, List, Tuple
from feasytools import RangeList, SegFunc, CreatePDFunc
from v2sim.trafficgen.misc import * # import PDFuncs
from tkinter import messagebox as MB
from v2sim import CustomLocaleLib

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
    PROP_NODESC = "(No description)"
)

def _removeprefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    return s

ALWAYS_ONLINE = _loc['ALWAYS_ONLINE']
def empty_postfunc(itm:Tuple[Any,...], val:str): pass

class EditMode(Enum):
    DISABLED = "disabled"
    ENTRY = "entry"
    SPIN = "spin"
    COMBO = "combo"
    RANGELIST = "rangelist"
    SEGFUNC = "segfunc"
    PROP = "prop"
    PDFUNC = "pdfunc"

EditModeLike = Union[EditMode, str]

def parseEditMode(em:str):
    '''
    (**Unsafe method**) Parse an EditMode-like string to (EditMode, Dict[str, str])

    An EditMode-like string is defined as an EditMode string (the values of EditMode enum) or something like
        "mode={'key1':value1, 'key2':value2, ...}", where mode is an EditMode string, and keys and values represent the parameters
    
    Legal examples:
    ```
    rangelist
    spin={'from': 1, 'to': 2}
    combo={'values': ['item1', 'item2']}
    rangelist={'hint_hms': True}
    prop={
        'edit_modes':{
            'prop1': "spin={'from': 1, 'to': 2}",
            'prop2': "combo={'values': ['item1', 'item2']}",
        },
        'default_mode':'entry',
        'desc':{
            'prop1': 'description of prop1',
            'prop2': 'description of prop2',
        }
    }
    ```
    '''
    eq_pos = em.find("=")
    if eq_pos == -1:
        return EditMode(em), {}
    mode = em[:eq_pos]
    pars = eval(em[eq_pos+1:])
    assert isinstance(pars, dict), "EditMode string must be like 'mode={key1:value1, key2:value2, ...}'"
    return mode, pars

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
    
    
# Double click to edit the cell: https://blog.csdn.net/falwat/article/details/127494533
class ScrollableTreeView(Frame):
    def show_title(self, title:str):
        self.lb_title.config(text=title)
        self.lb_title.grid(row=0,column=0,padx=3,pady=3,sticky="w",columnspan=2)

    def hide_title(self):
        self.lb_title.grid_remove()
    
    def __init__(self, master, allowSave:bool = False, **kwargs):
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
        self.save_panel = Frame(self)
        self.btn_save = Button(self.save_panel, text=_loc["SAVE"], command=self.save)
        self.lb_save = Label(self.save_panel, text=_loc["NOT_OPEN"])
        self.lb_note = Label(self.save_panel, text=_loc["EDIT_NOTE"])
        if allowSave:
            self.save_panel.grid(row=3,column=0,padx=3,pady=3,sticky="nsew")
            self.btn_save.grid(row=0,column=0,padx=3,pady=3,sticky="w")
            self.lb_save.grid(row=0,column=1,padx=3,pady=3,sticky="w")
            self.lb_note.grid(row=0,column=2,padx=20,pady=3,sticky="w")
        self.delegate_var = StringVar()
        self.tree.bind('<Double-1>', func=self.tree_item_edit)
        self.onSave = None
        self.edit_mode:'Dict[str, Tuple[EditModeLike, Any, Callable[[Tuple[Any,...], str],None]]]' = {}
        self.delegate_widget = None
        self.selected_item = None

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
    
    def setColEditMode(self, col:str, mode:EditMode, **kwargs):
        self.__setEditMode("COL:" + col, mode, **kwargs)
    
    def setRowEditMode(self, row:str, mode:EditMode, **kwargs):
        self.__setEditMode("ROW:" + row, mode, **kwargs)
        print(row,mode)
    
    def setCellEditMode(self, row:str, col:str, mode:EditMode, **kwargs):
        self.__setEditMode("CELL:" + row + "@" + col, mode, **kwargs)
    
    def clearEditModes(self):
        self.edit_mode.clear()
    
    def __setEditMode(self, label:str, mode:EditModeLike, *,
            spin_from:int=1, spin_to:int=100, 
            prop_edit_modes:Optional[Dict[str, EditModeLike]] = None, 
            prop_default_mode:EditModeLike = EditMode.ENTRY,
            prop_desc:Optional[Dict[str, str]] = None,
            combo_values:Optional[List[str]] = None,
            rangelist_hint:bool = False, 
            post_func:Callable[[Tuple[Any,...], str], None] = empty_postfunc):
        if not isinstance(mode, EditMode):
            mode, pars = parseEditMode(mode)
            if mode == EditMode.SPIN:
                spin_from = pars.get("from", spin_from)
                assert isinstance(spin_from, int), "Spin from must be an integer"
                spin_to = pars.get("to", spin_to)
                assert isinstance(spin_to, int), "Spin to must be an integer"
            elif mode == EditMode.COMBO:
                combo_values = pars.get("values", combo_values)
                assert isinstance(combo_values, (list, tuple)), "Combo values must be a list or tuple"
            elif mode == EditMode.RANGELIST:
                rangelist_hint = pars.get("hint_hms", rangelist_hint)
                assert isinstance(rangelist_hint, bool), "Rangelist hint_hms must be a boolean"
            elif mode == EditMode.PROP:
                prop_edit_modes = pars.get("edit_modes", prop_edit_modes)
                assert isinstance(prop_edit_modes, dict), "Property edit modes must be a Dict[str, EditModeLike]"
                prop_default_mode = pars.get("default_mode", prop_default_mode)
                assert isinstance(prop_default_mode, (str, EditMode)), "Property default mode must be an EditMode or a str"
                prop_desc = pars.get("prop_desc", prop_desc)
                assert isinstance(prop_desc, dict), "Property description must be a Dict[str, str]"
        if mode == EditMode.SPIN:
            self.edit_mode[label] = (mode, (spin_from, spin_to), post_func)
        elif mode == EditMode.COMBO:
            if combo_values is None: combo_values = []
            self.edit_mode[label] = (mode, combo_values, post_func)
        elif mode == EditMode.RANGELIST:
            self.edit_mode[label] = (mode, rangelist_hint, post_func)
        elif mode == EditMode.PROP:
            if prop_edit_modes is None: prop_edit_modes = {}
            if prop_desc is None: prop_desc = {}
            self.edit_mode[label] = (mode, (prop_edit_modes, prop_default_mode, prop_desc), post_func)
        else:
            self.edit_mode[label] = (mode, None, post_func)

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
        
        mode_str, val, self.post_func = self.edit_mode[label]
        if mode_str == EditMode.COMBO:
            assert isinstance(val, (list, tuple))
            self.delegate_widget = Combobox(self.tree, width=w // 10, textvariable=self.delegate_var, values=val)
            self.delegate_widget.bind('<<ComboboxSelected>>', self.tree_item_edit_done)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == EditMode.SPIN:
            assert isinstance(val, tuple)
            self.delegate_widget = Spinbox(self.tree, width=w // 10, textvariable=self.delegate_var, from_=val[0], to=val[1], increment=1)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == EditMode.ENTRY:
            self.delegate_widget = Entry(self.tree, width=w // 10, textvariable=self.delegate_var)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == EditMode.RANGELIST:
            d = self.delegate_var.get()
            if d == ALWAYS_ONLINE: d = "[]"
            self.delegate_widget = RangeListEditor(RangeList(eval(d)), self.delegate_var, True)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif mode_str == EditMode.PROP:
            d = self.delegate_var.get()
            self.delegate_widget = PropertyEditor(eval(d), self.delegate_var, edit_modes=val[0], default_edit_mode=val[1], desc=val[2])
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif mode_str == EditMode.PDFUNC:
            self.delegate_widget = PDFuncEditor(self.delegate_var)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif mode_str == EditMode.SEGFUNC:
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
        self.tree.setColEditMode("lb", EditMode.ENTRY)
        self.tree.setColEditMode("rb", EditMode.ENTRY)
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
        self.tree.setColEditMode("t", EditMode.ENTRY)
        self.tree.setColEditMode("d", EditMode.ENTRY)
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
        self.__desc_var.set(self.__desc_dict.get(selected_row, _loc["PROP_NODESC"]))
    
    def setObj(self, obj: Any, edesc:EditDesc):
        self.tree.tree_item_edit_done(None)
        self.setData(obj.__dict__, edesc._em, EditMode.ENTRY, edesc._desc, edesc._em_kwargs)

    def setData(self, data:Dict[str, Any],
            edit_modes:Optional[Dict[str,EditMode]] = None,
            default_edit_mode:EditMode = EditMode.ENTRY, 
            desc:Optional[Dict[str, str]] = None,
            edit_modes_kwargs:Optional[Dict[str,Dict[str,Any]]] = None):
        self.tree.tree_item_edit_done(None)
        self.data = data
        if edit_modes is None: edit_modes = {}
        self.tree.clear()
        for l, r in data.items():
            self.tree.insert("", "end", values=(l, r))
            if edit_modes_kwargs and l in edit_modes_kwargs:
                kwargs = edit_modes_kwargs[l]
            else:
                kwargs = {}
            self.tree.setCellEditMode(l, "d", edit_modes.get(l, default_edit_mode), **kwargs)
        self.__desc_dict = desc if desc else {}
    
    def setData2(self, data:Dict[str, Tuple[Any,...]], default_edit_mode:EditMode = EditMode.ENTRY):
        new_data = {}
        desc = {}
        edit_modes = {}
        edit_modes_kwargs = {}
        for key, val in data.items():
            assert len(val) >= 1
            new_data[key] = val[0]
            if len(val) >= 2:
                desc[key] = val[1]
            if len(val) >= 3:
                edit_modes[key] = val[2]
            if len(val) >= 4:
                edit_modes_kwargs[key] = val[3]
        self.setData(new_data, edit_modes, default_edit_mode, desc, edit_modes_kwargs)        
    
    def __init__(self, master, data:Dict[str,str],
            edit_modes:Optional[Dict[str,EditMode]] = None,
            default_edit_mode:EditMode = EditMode.ENTRY, 
            desc:Optional[Dict[str, str]] = None, **kwargs):
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
        self.setData(data,edit_modes,default_edit_mode,desc)
    
    def getAllData(self) -> Dict[str, str]:
        res:Dict[str, str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res

class PropertyEditor(Toplevel):
    def __init__(self, data:Dict[str,str], var:StringVar, 
            edit_modes:Optional[Dict[str,EditMode]] = None,
            default_edit_mode:EditMode = EditMode.ENTRY,
            desc:Optional[Dict[str,str]] = None):
        super().__init__()
        self.title(_loc["PROPERTY_EDITOR"])
        self.__panel = PropertyPanel(self, data, edit_modes, default_edit_mode, desc)
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
        self.tree.setColEditMode("d", EditMode.ENTRY)
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