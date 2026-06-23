# v2sim/gui/mainbox/controls/vtype.py

from v2sim.gui.common import *
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree
from v2sim.utils import ReadXML, CheckFile
from .scrtv import ScrollableTreeView, ConfigItem, ConfigItemDict, EditMode

_L = LangLib.Load(__file__)


class VehicleTypeEditor(LabelFrame):
    def on_item_changed(self):
        self.lb_is_saved.config(text=_L["UNSAVED"], foreground="red")

    def __init__(self, master):
        super().__init__(master, text=_L["VEHICLE_PROTOTYPES"])
        self._file: Optional[str] = None

        self.tree = ScrollableTreeView(self)
        self.tree["show"] = "headings"
        self.tree["columns"] = ("kind", "vtype", "cap", "range", "pcf", "pcs", "pdv", "weight")

        widths = {
            "kind": 60,
            "vtype": 100,
            "cap": 90,
            "range": 90,
            "pcf": 80,
            "pcs": 80,
            "pdv": 80,
            "weight": 80,
        }
        texts = {
            "kind": _L["VEH_KIND"],
            "vtype": _L["VEH_VTYPE"],
            "cap": _L["VEH_CAP"],
            "range": _L["VEH_RANGE"],
            "pcf": _L["VEH_PCF"],
            "pcs": _L["VEH_PCS"],
            "pdv": _L["VEH_PDV"],
            "weight": _L["VEH_WEIGHT"]
        }
        for c, w in widths.items():
            self.tree.column(c, width=w, stretch=NO)
            self.tree.heading(c, text=texts[c])

        self.tree.pack(fill="x", expand=False)
        self.tree.setOnItemChanged(self.on_item_changed)

        self.tree.setColEditMode("kind", ConfigItem(
            name="kind",
            editor=EditMode.COMBO,
            desc=texts["kind"],
            combo_values=["ev", "gv"],
        ))
        self.tree.setColEditMode("vtype", ConfigItem(
            name="vtype",
            editor=EditMode.COMBO,
            desc=texts["vtype"],
            combo_values=["private", "taxi", "bus", "truck", "van", "sanitation", "emergency"],
        ))
        for c in ["cap", "range", "pcf", "pcs", "pdv"]:
            self.tree.setColEditMode(c, ConfigItem(
                name=c,
                editor=EditMode.ENTRY,
                desc=texts[c],
                default_value=""
            ))
        self.tree.setColEditMode("weight", ConfigItem(
            name="weight",
            editor=EditMode.SPIN,
            desc=texts["weight"],
            default_value=1,
            spin_range=(1, 1000)
        ))

        fr = Frame(self)
        fr.pack(fill="x", expand=False)

        Button(fr, text=_L["ADD_EV"], command=self.add_ev, width=10).pack(side="left", padx=3, pady=3)
        Button(fr, text=_L["ADD_GV"], command=self.add_gv, width=10).pack(side="left", padx=3, pady=3)
        Button(fr, text=_L["DELETE"], command=self.delete, width=8).pack(side="left", padx=3, pady=3)
        Button(fr, text=_L["SAVE"], command=self.save, width=8).pack(side="left", padx=3, pady=3)

        self.lb_is_global = Label(fr, text=_L["GLOBAL_VTYPES"], foreground="blue")
        self.lb_is_global.pack(side="left", padx=3, pady=3)

        self.lb_is_saved = Label(fr, text=_L["SAVED"], foreground="green")
        self.lb_is_saved.pack(side="left", padx=3, pady=3)

    def load(self, file: str, is_global: bool = False):
        self._file = file
        self.tree.delete(*self.tree.get_children())
        self.lb_is_global.config(text=_L["GLOBAL_VTYPES"] if is_global else _L["PROJECT_VTYPES"])
        self.lb_is_saved.config(text=_L["SAVED"])

        if not Path(file).exists():
            return

        root = ReadXML(file).getroot()
        if root is None:
            return

        for vt in root:
            if vt.tag == "ev":
                self.tree.insert("", "end", values=(
                    "ev",
                    vt.attrib.get("vtype", "Private"),
                    vt.attrib.get("cap", "50kWh"),
                    vt.attrib.get("range", "400km"),
                    vt.attrib.get("pcf", "100kW"),
                    vt.attrib.get("pcs", "7kW"),
                    vt.attrib.get("pdv", "7kW"),
                    vt.attrib.get("weight", "1"),
                ))
            elif vt.tag == "gv":
                self.tree.insert("", "end", values=(
                    "gv",
                    vt.attrib.get("vtype", "Private"),
                    vt.attrib.get("cap", "50L"),
                    vt.attrib.get("range", "600km"),
                    "",
                    "",
                    "",
                    vt.attrib.get("weight", "1"),
                ))

    def add_ev(self):
        self.tree.insert("", "end", values=(
            "ev", "Private", "50kWh", "400km", "100kW", "7kW", "7kW", "1"
        ))
        self.on_item_changed()

    def add_gv(self):
        self.tree.insert("", "end", values=(
            "gv", "Private", "50L", "600km", "", "", "", "1"
        ))

    def delete(self):
        for item in self.tree.tree.selection():
            self.tree.delete(item)
        self.on_item_changed()

    def save(self):
        if not self._file:
            MB.showerror("Error", "No vtypes.xml loaded.")
            return

        root = Element("root")

        for item in self.tree.get_children():
            kind, vtype, cap, rng, pcf, pcs, pdv, weight = self.tree.tree.item(item, "values")
            kind = str(kind).strip().lower()

            if kind == "ev":
                e = Element("ev", {
                    "vtype": str(vtype).strip(),
                    "cap": str(cap).strip(),
                    "range": str(rng).strip(),
                    "pcf": str(pcf).strip(),
                    "pcs": str(pcs).strip(),
                    "pdv": str(pdv).strip(),
                    "weight": str(weight).strip(),
                })
            elif kind == "gv":
                e = Element("gv", {
                    "vtype": str(vtype).strip(),
                    "cap": str(cap).strip(),
                    "range": str(rng).strip(),
                    "weight": str(weight).strip(),
                })
            else:
                MB.showerror("Error", f"Invalid vehicle prototype kind: {kind}")
                return

            root.append(e)

        CheckFile(self._file)
        ElementTree(root).write(self._file, encoding="utf-8", xml_declaration=True)
        self.lb_is_saved.config(text=_L["SAVED"], foreground="green")

__all__ = ["VehicleTypeEditor"]