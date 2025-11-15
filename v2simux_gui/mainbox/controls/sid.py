from v2simux_gui.common import *

_L = LangLib.Load(__file__)

class SelectItemDialog(Toplevel):
    def __init__(self, items:List[List[Any]], title:str, columns:List[Union[str, Tuple[str, str]]]):
        super().__init__()
        self.title(title)
        self.geometry("500x300")
        self.__dkt:Dict[str, Any] = {}
        self.selected_item = None

        col_id = []
        col_name = []
        for col in columns:
            if isinstance(col, str):
                col_id.append(col)
                col_name.append(col.capitalize())
            else:
                col_id.append(col[0])
                col_name.append(col[1])
        tree = Treeview(self, columns=col_id, show="headings", selectmode="browse")
        for i, n in zip(col_id, col_name):
            tree.heading(i, text=n)

        for item in items:
            idx = tree.insert("", "end", values=item)
            self.__dkt[idx] = item
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree = tree

        btn = Button(self, text=_L("CONFIRM"), command=self.confirm_selection)
        btn.pack(pady=5)

    def on_select(self, event):
        selected = self.tree.selection()
        if selected:
            self.selected_item = self.__dkt[selected[0]]

    def confirm_selection(self):
        if self.selected_item is not None:
            self.destroy()
        else:
            MB.showwarning(_L("WARNING"), _L("HINT_SELECT_ITEM"))


__all__ = ["SelectItemDialog"]