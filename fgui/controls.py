from .view import *
from typing import Any, Callable, Literal
from feasytools import RangeList, SegFunc
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
)

ALWAYS_ONLINE = _loc['ALWAYS_ONLINE']
def _empty_postfunc(itm:tuple[Any,...], val:str): pass

# Double click to edit the cell: https://blog.csdn.net/falwat/article/details/127494533
class ScrollableTreeView(Frame):
    def __init__(self, master, allowSave:bool = False, **kwargs):
        super().__init__(master, **kwargs)
        self.post_func = _empty_postfunc
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
        self.edit_mode:'dict[str, tuple[str, Any, Callable[[tuple[Any,...], str],None]]]' = {}

    def save(self):
        if self.onSave:
            if self.onSave(self.getAllData()):
                self.lb_save.config(text=_loc["SAVED"],foreground="green")
    
    def setOnSave(self, onSave:Callable[[list[tuple]], bool]):
        self.onSave = onSave
    
    def item(self, item, option=None, **kw):
        return self.tree.item(item, option, **kw)
    
    def getAllData(self) -> list[tuple]:
        res = []
        for i in self.tree.get_children():
            res.append(self.tree.item(i, "values"))
        return res

    def setColEditMode(self, col:str, mode:Literal["disabled", "entry", "spin", "combo", "rangelist", "segfunc", "prop"], *,
                       spin_from:int=1, spin_to:int=100, combo_values:list[str]=[], rangelist_hint:bool = False, 
                       post_func:Callable[[tuple[Any,...], str],None] = _empty_postfunc):
        if mode == "spin":
            self.edit_mode[col] = (mode, (spin_from, spin_to), post_func)
        elif mode == "combo":
            self.edit_mode[col] = (mode, combo_values, post_func)
        elif mode == "rangelist":
            self.edit_mode[col] = (mode, rangelist_hint, post_func)
        else:
            self.edit_mode[col] = (mode, None, post_func)

    def disableEdit(self):
        self.tree.unbind('<Double-1>')
    
    def enableEdit(self):
        self.tree.bind('<Double-1>', func=self.tree_item_edit)
    
    def tree_item_edit(self, e: Event):
        if len(self.tree.selection()) == 0:
            return
        self.selected_item = self.tree.selection()[0]

        for i, col in enumerate(self.tree['columns']):
            x, y, w, h =  self.tree.bbox(self.selected_item, col)
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
        
        if self.selected_column not in self.edit_mode or self.selected_column is None: return
        mode_str, val, self.post_func = self.edit_mode[self.selected_column]
        if mode_str == 'combo':
            assert isinstance(val, list)
            self.delegate_widget = Combobox(self.tree, width=w // 10, textvariable=self.delegate_var, values=val)
            self.delegate_widget.bind('<<ComboboxSelected>>', self.tree_item_edit_done)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == 'spin':
            assert isinstance(val, tuple)
            self.delegate_widget = Spinbox(self.tree, width=w // 10, textvariable=self.delegate_var, from_=val[0], to=val[1], increment=1)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == 'entry':
            self.delegate_widget = Entry(self.tree, width=w // 10, textvariable=self.delegate_var)
            self.delegate_widget.bind('<FocusOut>', self.tree_item_edit_done)
        elif mode_str == 'rangelist':
            d = self.delegate_var.get()
            if d == ALWAYS_ONLINE: d = "[]"
            self.delegate_widget = RangeListEditor(RangeList(eval(d)), self.delegate_var, True)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif mode_str == 'prop':
            d = self.delegate_var.get()
            self.delegate_widget = PropertyEditor(eval(d), self.delegate_var)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        elif mode_str == 'segfunc':
            d = self.delegate_var.get()
            try:
                float(d)
                d = f"[(0,{d})]"
            except:
                pass
            self.delegate_widget = SegFuncEditor(SegFunc(eval(d)), self.delegate_var)
            self.delegate_widget.bind('<Destroy>', self.tree_item_edit_done)
        else:
            return
        
        if not isinstance(self.delegate_widget, Toplevel):
            self.delegate_widget.place(width=w, height=h, x=x, y=y)
        self.delegate_widget.focus()
        self.lb_save.config(text=_loc["UNSAVED"],foreground="red")

    def tree_item_edit_done(self, e):
        if not isinstance(self.delegate_widget, Toplevel):
            self.delegate_widget.place_forget()
        v = self.delegate_var.get()
        line = self.tree.item(self.selected_item, 'values')
        assert isinstance(line, tuple)
        self.post_func(line, v)
        if self.selected_column is None:
            self.tree.item(self.selected_item, text=v)
        else:
            self.tree.set(self.selected_item, self.selected_column, v)
    
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
    
    def delete(self, *args):
        self.tree.delete(*args)
    
    def get_children(self):
        return self.tree.get_children()
    
    def clear(self):
        self.delete(*self.get_children())
        self.lb_save.config(text=_loc["SAVED"],foreground="green")
    
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
        self.tree.setColEditMode("lb", "entry")
        self.tree.setColEditMode("rb", "entry")
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
        res:list[tuple[int,int]] = []
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
        self.tree.setColEditMode("t", "entry")
        self.tree.setColEditMode("d", "entry")
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
            self.var.set(ALWAYS_ONLINE)
        else:
            self.var.set(str(d))
        self.destroy()

    def getAllData(self) -> SegFunc:
        res:list[tuple[int,float]] = []
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res.append((int(x[0]), float(x[1])))
        return SegFunc(res)


class PropertyEditor(Toplevel):
    def __init__(self, data:dict[str,str], var:StringVar):
        super().__init__()
        self.title(_loc["PROPERTY_EDITOR"])
        self.data = data
        self.tree = ScrollableTreeView(self, allowSave=False)
        self.tree['show'] = 'headings'
        self.tree["columns"] = ("t", "d")
        self.tree.column("t", width=120, stretch=NO)
        self.tree.column("d", width=120, stretch=YES)
        self.tree.heading("t", text=_loc["PROPERTY"])
        self.tree.heading("d", text=_loc["VALUE"])
        self.tree.pack(fill="both", expand=True)
        for l,r in data.items():
            self.tree.insert("", "end", values=(l, r))
        self.tree.setColEditMode("d", "entry")
        self.fr = Frame(self)
        self.fr.pack(fill="x", expand=False)
        self.btn_save = Button(self.fr, text=_loc["SAVE_AND_CLOSE"], command=self.save)
        self.btn_save.grid(row=0,column=4,padx=3,pady=3,sticky="e")
        self.var = var

    def getAllData(self) -> dict[str,str]:
        res:dict[str, str] = {}
        for i in self.tree.get_children():
            x = self.tree.tree.item(i, "values")
            res[x[0]] = x[1]
        return res
    
    def save(self):
        d = self.getAllData()
        self.var.set(repr(d))
        self.destroy()
