import gzip
import sys
import os
import pickle
from pathlib import Path
from queue import Queue
import threading
from typing import Literal, Optional, Dict, List, Tuple
from fgui.trips_qt import TripsFrame
from fgui.view import *
from v2sim import AdvancedPlot, ReadOnlyStatistics, CS, CSList, EV, EVDict, CustomLocaleLib
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTabWidget, QListWidget, QLineEdit, QComboBox, QGroupBox, QGridLayout, QFrame,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QFileDialog, QMessageBox, QCheckBox
)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QPixmap, QResizeEvent

_L = CustomLocaleLib.LoadFromFolder("resources/gui_viewer")

AVAILABLE_ITEMS = ["fcs","scs","ev","gen","bus","line","pvw","ess"]
AVAILABLE_ITEMS2 = AVAILABLE_ITEMS + ["fcs_accum","scs_accum","bus_total","gen_total"]
ITEM_ALL = _L["ITEM_ALL"]
ITEM_SUM = _L["ITEM_SUM"]
ITEM_ALL_G = "<All common generators>"
ITEM_ALL_V2G = "<All V2G stations>"
ITEM_LOADING = "Loading..."

class OptionBox(QWidget):
    def __init__(self, parent, options:Dict[str, Tuple[str, bool]], lcnt:int = -1, **kwargs):
        super().__init__(parent)
        self._bools:List[QCheckBox] = []
        self._mp:Dict[str, QCheckBox] = {}
        self._fr:List[QHBoxLayout] = []
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setSpacing(5)
        self._main_layout.setContentsMargins(0,0,0,0)
        if lcnt <= 0:
            fr = QHBoxLayout()
            self._main_layout.addLayout(fr)
            self._fr.append(fr)
        i = 0
        for id, (text, v) in options.items():
            cb = QCheckBox(text, self)
            cb.setChecked(v)
            self._bools.append(cb)
            self._mp[id] = cb
            if lcnt > 0 and i % lcnt == 0:
                fr = QHBoxLayout()
                self._main_layout.addLayout(fr)
                self._fr.append(fr)
            self._fr[-1].addWidget(cb)
            i += 1
        self.setLayout(self._main_layout)

    def disable(self):
        for c in self._bools:
            c.setEnabled(False)

    def enable(self):
        for c in self._bools:
            c.setEnabled(True)

    def __setitem__(self, key:str, value:bool):
        self._mp[key].setChecked(value)

    def __getitem__(self, key:str)->bool:
        return self._mp[key].isChecked()

    def getValues(self):
        return {k: v.isChecked() for k, v in self._mp.items()}

    def getSelected(self):
        return [k for k, v in self._mp.items() if v.isChecked()]

class PlotPad(QWidget):
    def __init__(self, master, show_accum:bool=False, useEntry:bool=False, useTotalText:bool=False, **kwargs):
        super().__init__(master, **kwargs)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(0)
        
        if useEntry:
            self.cb = QLineEdit(self)
        else:
            self.cb = QComboBox(self)
        self.layout_.addWidget(self.cb)
        self.accum = False
        self.cb_accum = None
        if show_accum:
            self.accum = True
            self.cb_accum = QCheckBox(_L["BTN_TOTAL"] if useTotalText else _L["BTN_ACCUM"], self)
            self.cb_accum.setChecked(True)
            self.layout_.addWidget(self.cb_accum)
        self.setLayout(self.layout_)

    def setValues(self, values:List[str]):
        if hasattr(self.cb, 'clear') and hasattr(self.cb, 'addItems'):
            self.cb.clear()
            self.cb.addItems(values)
            if values:
                self.cb.setCurrentIndex(0)

    def set(self, item:str):
        if hasattr(self.cb, 'setCurrentText'):
            self.cb.setCurrentText(item)
        elif hasattr(self.cb, 'setText'):
            self.cb.setText(item)

    def get(self):
        if hasattr(self.cb, 'currentText'):
            return self.cb.currentText()
        elif hasattr(self.cb, 'text'):
            return self.cb.text()
        return ""

    def disable(self):
        self.cb.setDisabled(True)
        if self.cb_accum:
            self.cb_accum.setDisabled(True)

    def enable(self):
        self.cb.setDisabled(False)
        if self.cb_accum:
            self.cb_accum.setDisabled(False)

class PlotPage(QWidget):
    @property
    def AccumPlotMax(self) -> bool:
        return self.accum_plotmax.isChecked()

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header Panel
        lfra_head = QGroupBox(_L["TIME"], self)
        lfra_head_layout = QVBoxLayout(lfra_head)
        lfra_head_layout.setSpacing(0)
        lfra_head_layout.setContentsMargins(10, 3, 10, 3)

        # Time panel: Header Panel Elem 1
        panel_time = QWidget(lfra_head)
        panel_time_layout = QHBoxLayout(panel_time)
        panel_time_layout.setContentsMargins(0, 5, 0, 5)

        lb_time = QLabel(_L["START_TIME"], panel_time)
        panel_time_layout.addWidget(lb_time)

        self.entry_time = QLineEdit(panel_time)
        self.entry_time.setText("86400")
        self.entry_time.setFixedWidth(80)
        panel_time_layout.addWidget(self.entry_time)

        lb_end_time = QLabel(_L["END_TIME"], panel_time)
        panel_time_layout.addWidget(lb_end_time)

        self.entry_end_time = QLineEdit(panel_time)
        self.entry_end_time.setText("-1")
        self.entry_end_time.setFixedWidth(80)
        panel_time_layout.addWidget(self.entry_end_time)

        self.accum_plotmax = QCheckBox(_L["PLOT_MAX"], panel_time)
        panel_time_layout.addWidget(self.accum_plotmax)
        panel_time.setLayout(panel_time_layout)
        lfra_head_layout.addWidget(panel_time)

        # Config panel: Header Panel Elem 2
        panel_conf = QWidget(lfra_head)
        panel_conf_layout = QHBoxLayout(panel_conf)
        panel_conf_layout.setContentsMargins(0, 5, 0, 5)
        lb_conf = QLabel(_L["FILE_EXT"], panel_conf)
        panel_conf_layout.addWidget(lb_conf)
        self.cb_ext = QComboBox(panel_conf)
        self.cb_ext.addItems(["png", "jpg", "eps", "svg", "tiff"])
        self.cb_ext.setCurrentIndex(0)
        self.cb_ext.setFixedWidth(70)
        panel_conf_layout.addWidget(self.cb_ext)
        lb_dpi = QLabel(_L["IMAGE_DPI"], panel_conf)
        panel_conf_layout.addWidget(lb_dpi)
        self.entry_dpi = QComboBox(panel_conf)
        self.entry_dpi.addItems(['128', '192', '256', '300', '400', '600', '1200'])
        self.entry_dpi.setCurrentIndex(3)
        self.entry_dpi.setFixedWidth(70)
        panel_conf_layout.addWidget(self.entry_dpi)
        self.plot_title = QCheckBox(_L["PLOT_TITLE"], panel_conf)
        self.plot_title.setChecked(True)
        panel_conf_layout.addWidget(self.plot_title)
        panel_conf.setLayout(panel_conf_layout)
        lfra_head_layout.addWidget(panel_conf)
        lfra_head.setLayout(lfra_head_layout)
        main_layout.addWidget(lfra_head)

        # Grid for plot options
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(0, 10, 0, 10)
        # FCS
        self.plot_fcs = QCheckBox(_L["FCS_TITLE"], self)
        grid.addWidget(self.plot_fcs, 0, 0)
        self.panel_fcs = QFrame(self)
        self.panel_fcs.setFrameStyle(QFrame.Shape.Panel)
        self.panel_fcs.setLineWidth(1)
        panel_fcs_layout = QVBoxLayout(self.panel_fcs)
        self.fcs_opts = OptionBox(self.panel_fcs, {
            "wcnt": (_L["FCS_NVEH"], True),
            "load": (_L["FCS_PC"], True),
            "price": (_L["FCS_PRICE"], False),
        })
        panel_fcs_layout.addWidget(self.fcs_opts)
        self.fcs_pad = PlotPad(self.panel_fcs, True)
        panel_fcs_layout.addWidget(self.fcs_pad)
        self.panel_fcs.setLayout(panel_fcs_layout)
        grid.addWidget(self.panel_fcs, 1, 0)

        # SCS
        self.plot_scs = QCheckBox(_L["SCS_TITLE"], self)
        grid.addWidget(self.plot_scs, 2, 0)
        self.panel_scs = QFrame(self)
        self.panel_scs.setFrameStyle(QFrame.Shape.Panel)
        self.panel_scs.setLineWidth(1)
        panel_scs_layout = QVBoxLayout(self.panel_scs)
        self.scs_opts = OptionBox(self.panel_scs, {
            "wcnt": (_L["SCS_NVEH"], True),
            "cload": (_L["SCS_PC"], True),
            "dload": (_L["SCS_PD"], True),
            "netload": (_L["SCS_PPURE"], True),
            "v2gcap": (_L["SCS_PV2G"], True),
            "pricebuy": (_L["SCS_PBUY"], False),
            "pricesell": (_L["SCS_PSELL"], False),
        }, lcnt=4)
        panel_scs_layout.addWidget(self.scs_opts)
        self.scs_pad = PlotPad(self.panel_scs, True)
        panel_scs_layout.addWidget(self.scs_pad)
        self.panel_scs.setLayout(panel_scs_layout)
        grid.addWidget(self.panel_scs, 3, 0)

        # EV
        self.plot_ev = QCheckBox(_L["EV_TITLE"], self)
        grid.addWidget(self.plot_ev, 0, 1)
        self.panel_ev = QFrame(self)
        self.panel_ev.setFrameStyle(QFrame.Shape.Panel)
        self.panel_ev.setLineWidth(1)
        panel_ev_layout = QVBoxLayout(self.panel_ev)
        self.ev_opts = OptionBox(self.panel_ev, {
            "soc": (_L["SOC"], True),
            "status": (_L["EV_STA"], False),
            "cost": (_L["EV_COST"], True),
            "earn": (_L["EV_EARN"], True),
            "cpure": (_L["EV_NETCOST"], True),
        })
        panel_ev_layout.addWidget(self.ev_opts)
        self.ev_pad = PlotPad(self.panel_ev, useEntry=True)
        panel_ev_layout.addWidget(self.ev_pad)
        self.panel_ev.setLayout(panel_ev_layout)
        grid.addWidget(self.panel_ev, 1, 1)

        # BUS
        self.plot_bus = QCheckBox(_L["BUS_TITLE"], self)
        grid.addWidget(self.plot_bus, 2, 1)
        self.panel_bus = QFrame(self)
        self.panel_bus.setFrameStyle(QFrame.Shape.Panel)
        self.panel_bus.setLineWidth(1)
        panel_bus_layout = QVBoxLayout(self.panel_bus)
        self.bus_opts = OptionBox(self.panel_bus, {
            "activel": (_L["BUS_PD"], True),
            "reactivel": (_L["BUS_QD"], True),
            "volt": (_L["BUS_V"], True),
            "activeg": (_L["BUS_PG"], True),
            "reactiveg": (_L["BUS_QG"], True),
        }, lcnt=3)
        panel_bus_layout.addWidget(self.bus_opts)
        self.bus_pad = PlotPad(self.panel_bus, True, False, True)
        panel_bus_layout.addWidget(self.bus_pad)
        self.panel_bus.setLayout(panel_bus_layout)
        grid.addWidget(self.panel_bus, 3, 1)

        # GEN
        self.plot_gen = QCheckBox(_L["GEN_TITLE"], self)
        grid.addWidget(self.plot_gen, 4, 0)
        self.panel_gen = QFrame(self)
        self.panel_gen.setFrameStyle(QFrame.Shape.Panel)
        self.panel_gen.setLineWidth(1)
        panel_gen_layout = QVBoxLayout(self.panel_gen)
        self.gen_opts = OptionBox(self.panel_gen, {
            "active": (_L["ACTIVE_POWER"], True),
            "reactive": (_L["REACTIVE_POWER"], True),
            "costp": (_L["GEN_COST"], True),
        })
        panel_gen_layout.addWidget(self.gen_opts)
        self.gen_pad = PlotPad(self.panel_gen, True, False, True)
        panel_gen_layout.addWidget(self.gen_pad)
        self.panel_gen.setLayout(panel_gen_layout)
        grid.addWidget(self.panel_gen, 5, 0)

        # LINE
        self.plot_line = QCheckBox(_L["LINE_TITLE"], self)
        grid.addWidget(self.plot_line, 4, 1)
        self.panel_line = QFrame(self)
        self.panel_line.setFrameStyle(QFrame.Shape.Panel)
        self.panel_line.setLineWidth(1)
        panel_line_layout = QVBoxLayout(self.panel_line)
        self.line_opts = OptionBox(self.panel_line, {
            "active": (_L["ACTIVE_POWER"], True),
            "reactive": (_L["REACTIVE_POWER"], True),
            "current": (_L["LINE_CURRENT"], True),
        })
        panel_line_layout.addWidget(self.line_opts)
        self.line_pad = PlotPad(self.panel_line)
        panel_line_layout.addWidget(self.line_pad)
        self.panel_line.setLayout(panel_line_layout)
        grid.addWidget(self.panel_line, 5, 1)

        # PVW
        self.plot_pvw = QCheckBox(_L["PVW_TITLE"], self)
        grid.addWidget(self.plot_pvw, 6, 0)
        self.panel_pvw = QFrame(self)
        self.panel_pvw.setFrameStyle(QFrame.Shape.Panel)
        self.panel_pvw.setLineWidth(1)
        panel_pvw_layout = QVBoxLayout(self.panel_pvw)
        self.pvw_opts = OptionBox(self.panel_pvw, {
            "P": (_L["ACTIVE_POWER"], True),
            "cr": (_L["PVW_CR"], True),
        })
        panel_pvw_layout.addWidget(self.pvw_opts)
        self.pvw_pad = PlotPad(self.panel_pvw)
        panel_pvw_layout.addWidget(self.pvw_pad)
        self.panel_pvw.setLayout(panel_pvw_layout)
        grid.addWidget(self.panel_pvw, 7, 0)

        # ESS
        self.plot_ess = QCheckBox(_L["ESS_TITLE"], self)
        grid.addWidget(self.plot_ess, 6, 1)
        self.panel_ess = QFrame(self)
        self.panel_ess.setFrameStyle(QFrame.Shape.Panel)
        self.panel_ess.setLineWidth(1)
        panel_ess_layout = QVBoxLayout(self.panel_ess)
        self.ess_opts = OptionBox(self.panel_ess, {
            "P": (_L["ACTIVE_POWER"], True),
            "soc": (_L["SOC"], True),
        })
        panel_ess_layout.addWidget(self.ess_opts)
        self.ess_pad = PlotPad(self.panel_ess)
        panel_ess_layout.addWidget(self.ess_pad)
        self.panel_ess.setLayout(panel_ess_layout)
        grid.addWidget(self.panel_ess, 7, 1)

        main_layout.addLayout(grid)
        self.setLayout(main_layout)

    def getConfig(self):
        return {
            "btime": int(self.entry_time.text()),
            "etime": int(self.entry_end_time.text()),
            "plotmax": self.accum_plotmax.isChecked(),
            "fcs_accum": self.fcs_pad.cb_accum and self.fcs_pad.cb_accum.isChecked() and self.plot_fcs.isChecked(),
            "scs_accum": self.scs_pad.cb_accum and self.scs_pad.cb_accum.isChecked() and self.plot_scs.isChecked(),
            "bus_total": self.bus_pad.cb_accum and self.bus_pad.cb_accum.isChecked() and self.plot_bus.isChecked(),
            "gen_total": self.gen_pad.cb_accum and self.gen_pad.cb_accum.isChecked() and self.plot_gen.isChecked(),
            "fcs": self.fcs_opts.getValues() if self.plot_fcs.isChecked() else None,
            "scs": self.scs_opts.getValues() if self.plot_scs.isChecked() else None,
            "ev": self.ev_opts.getValues() if self.plot_ev.isChecked() else None,
            "gen": self.gen_opts.getValues() if self.plot_gen.isChecked() else None,
            "bus": self.bus_opts.getValues() if self.plot_bus.isChecked() else None,
            "line": self.line_opts.getValues() if self.plot_line.isChecked() else None,
            "pvw": self.pvw_opts.getValues() if self.plot_pvw.isChecked() else None,
            "ess": self.ess_opts.getValues() if self.plot_ess.isChecked() else None,
        }

    def getTime(self):
        return int(self.entry_time.text()), int(self.entry_end_time.text())

    def pars(self, key: str):
        ret = self.getConfig()[key]
        assert isinstance(ret, dict), f"{key} is not a dict: {ret}"
        ret.update({
            "tl": int(self.entry_time.text()),
            "tr": int(self.entry_end_time.text())
        })
        return ret

    def enable(self, items: Optional[List[str]] = None):
        if items is None:
            items = AVAILABLE_ITEMS
        else:
            for i in items:
                assert i in AVAILABLE_ITEMS
        for i in items:
            getattr(self, f"plot_{i}").setEnabled(True)
            getattr(self, f"{i}_opts").enable()
            getattr(self, f"{i}_pad").enable()

    def disable(self, items: List[str] = []):
        if len(items) == 0:
            items = AVAILABLE_ITEMS
        else:
            for i in items:
                assert i in AVAILABLE_ITEMS
        for i in items:
            getattr(self, f"plot_{i}").setEnabled(False)
            getattr(self, f"{i}_opts").disable()
            getattr(self, f"{i}_pad").disable()


class PlotBox(QMainWindow):
    _sta: ReadOnlyStatistics
    _npl: AdvancedPlot

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_L["TITLE"])
        self.setMinimumSize(1024, 840)
        self.original_image = None
        self.folder = None

        # Central widget and layout
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)

        # Tabs
        self.tab = QTabWidget(self)
        main_layout.addWidget(self.tab)

        # Curve Tab
        self.tab_curve = QWidget()
        self.tab.addTab(self.tab_curve, _L["TAB_CURVE"])
        curve_layout = QVBoxLayout(self.tab_curve)

        # Image and list
        fr_pic = QHBoxLayout()
        self.lb_pic = QLabel(_L["NO_IMAGE"])
        self.lb_pic.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) # type: ignore
        fr_pic.addWidget(self.lb_pic, 1)
        self.pic_list = QListWidget()
        self.pic_list.setMaximumWidth(180)
        self.pic_list.itemSelectionChanged.connect(self.on_file_select)
        fr_pic.addWidget(self.pic_list)
        curve_layout.addLayout(fr_pic)

        # PlotPage
        self._pp = PlotPage(self.tab_curve)
        curve_layout.addWidget(self._pp)

        # Draw button
        self.btn_draw = QPushButton(_L["BTN_PLOT"])
        self.btn_draw.clicked.connect(self.plotSelected)
        curve_layout.addWidget(self.btn_draw, alignment=Qt.AlignmentFlag.AlignRight)

        # Grid Tab
        self.tab_grid = QWidget()
        self.tab.addTab(self.tab_grid, _L["TAB_GRID"])
        grid_layout = QVBoxLayout(self.tab_grid)

        # Time input for grid
        panel_time2 = QHBoxLayout()
        self.lb_time2 = QLabel(_L["TIME_POINT"])
        panel_time2.addWidget(self.lb_time2)
        self.entry_time2 = QLineEdit()
        self.entry_time2.setText("86400")
        panel_time2.addWidget(self.entry_time2)
        self.btn_time2 = QPushButton(_L["GRID_COLLECT"])
        self.btn_time2.clicked.connect(self.collectgrid)
        panel_time2.addWidget(self.btn_time2)
        grid_layout.addLayout(panel_time2)

        # Bus Tree
        self.grbus = QTreeWidget()
        self.grbus.setHeaderLabels(["Bus", "Voltage/kV", "Active load/MW", "Reactive load/Mvar", "Active gen/MW", "Reactive gen/Mvar"])
        grid_layout.addWidget(self.grbus)

        # Line Tree
        self.grline = QTreeWidget()
        self.grline.setHeaderLabels(["Line", "Active pwr/MW", "Reactive pwr/Mvar", "Current/kA"])
        grid_layout.addWidget(self.grline)

        # Trip Tab
        self.tab_trip = TripsFrame(self.tab)
        self.tab.addTab(self.tab_trip, _L["TAB_TRIP"])

        # State Tab
        self.tab_state = QWidget()
        self.tab.addTab(self.tab_state, _L["TAB_STATE"])
        state_layout = QVBoxLayout(self.tab_state)

        # Query Frame
        self.query_fr = QGroupBox(_L["TAB_QUERIES"])
        query_layout = QGridLayout(self.query_fr)
        self.cb_fcs_query = QComboBox()
        query_layout.addWidget(self.cb_fcs_query, 0, 0)
        self.btn_fcs_query = QPushButton("Query FCS")
        self.btn_fcs_query.clicked.connect(self.queryFCS)
        query_layout.addWidget(self.btn_fcs_query, 0, 1)
        self.cb_scs_query = QComboBox()
        query_layout.addWidget(self.cb_scs_query, 1, 0)
        self.btn_scs_query = QPushButton("Query SCS")
        self.btn_scs_query.clicked.connect(self.querySCS)
        query_layout.addWidget(self.btn_scs_query, 1, 1)
        self.entry_ev_query = QLineEdit()
        query_layout.addWidget(self.entry_ev_query, 2, 0)
        self.btn_ev_query = QPushButton("Query EV")
        self.btn_ev_query.clicked.connect(self.queryEV)
        query_layout.addWidget(self.btn_ev_query, 2, 1)
        self.query_fr.setLayout(query_layout)
        state_layout.addWidget(self.query_fr)

        self.text_qres = QTextEdit()
        state_layout.addWidget(self.text_qres)

        # Status bar
        self._sbar = QLabel(_L["STA_READY"])
        main_layout.addWidget(self._sbar)

        # Menu
        menubar = self.menuBar()
        filemenu = menubar.addMenu(_L["MENU_FILE"])
        filemenu.addAction(_L["MENU_OPEN"], self.force_reload)
        filemenu.addSeparator()
        def _close(): self.close()
        filemenu.addAction(_L["MENU_EXIT"], _close)

        self._ava = {k: False for k in AVAILABLE_ITEMS}
        self._Q = Queue()
        self.disable_all()
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.resize_end)
        self.__inst = None

        self._upd_timer = QTimer(self)
        self._upd_timer.timeout.connect(self._upd)
        self._upd_timer.start(100)

        self.tab_curve.resizeEvent = self.on_resize

    def display_images(self, file_name: str):
        if self.folder is None:
            return
        img1_path = os.path.join(self.folder, file_name)
        try:
            if os.path.exists(img1_path):
                self.original_image = QPixmap(img1_path)
            else:
                self.original_image = None
        except Exception as e:
            QMessageBox.critical(self, _L["ERROR"], _L["LOAD_FAILED"].format(str(e)))
        self.resize()

    def resize(self, event=None):
        sz = QSize(self.width() - 200, self.height() // 2 - 20)
        if self.original_image is not None:
            scaled = self.original_image.scaled(
                sz, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.lb_pic.setPixmap(scaled)
            self.lb_pic.setText("")
        else:
            self.lb_pic.setPixmap(QPixmap())
            self.lb_pic.setText(_L["NO_IMAGE"])

    def on_resize(self, a0:QResizeEvent):
        self.resize_timer.start(100)

    def resize_end(self):
        self.resize()

    def on_file_select(self):
        selected = self.pic_list.currentItem()
        if selected:
            file_name = selected.text()
            self.display_images(file_name)

    def set_qres(self, text: str):
        self.text_qres.setPlainText(text)

    def __queryCS(self, cstype: Literal["fcs", "scs"], q: str):
        if self.__inst is None:
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        if q.strip() == "":
            self.set_qres(_L["EMPTY_QUERY"])
            return
        cslist = self.__inst[cstype]
        assert isinstance(cslist, CSList)
        try:
            cs = cslist[q]
            assert isinstance(cs, CS)
        except:
            res = "CS Not found: " + q
        else:
            if cs.supports_V2G:
                res = (
                    f"ID: {cs.name} (V2G)\nBus: {cs.node}\n  Pc_kW:{cs.Pc_kW}\n  Pd_kW: {cs.Pd_kW}\n  Pv2g_kW: {cs.Pv2g_kW}\n" +
                    f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n" +
                    f"Price:\n  Buy: {cs.pbuy}\n  Sell: {cs.psell}\n"
                )
            else:
                res = (
                    f"ID: {cs.name}\nBus: {cs.node}\n  Pc_kW:{cs.Pc_kW}\n" +
                    f"Slots: {cs.slots}\n  Count: {cs.veh_count()} total, {cs.veh_count(True)} charging\n" +
                    f"Price:\n  Buy: {cs.pbuy}\n"
                )
        self.set_qres(res)

    def queryFCS(self):
        self.__queryCS("fcs", self.cb_fcs_query.currentText())

    def querySCS(self):
        self.__queryCS("scs", self.cb_scs_query.currentText())

    def queryEV(self):
        if self.__inst is None:
            self.set_qres(_L["NO_SAVED_STATE"])
            return
        q = self.entry_ev_query.text()
        if q.strip() == "":
            self.set_qres(_L["EMPTY_QUERY"])
            return
        vehs = self.__inst["VEHs"]
        assert isinstance(vehs, EVDict)
        try:
            veh = vehs[q]
            assert isinstance(veh, EV)
        except:
            res = "EV Not found: " + q
        else:
            res = (
                f"ID: {veh.ID}\n  SoC: {veh.SOC*100:.4f}%\n  Status: {veh.status}\n  Distance(m): {veh.odometer}\n" +
                f"Params:\n  Omega: {veh.omega}\n  KRel: {veh.krel}\n  Kfc: {veh.kfc}  Ksc: {veh.ksc}  Kv2g: {veh.kv2g}\n" +
                f"Consump(Wh/m): {veh.consumption*1000}\n" +
                f"Money:\n  Charging cost: {veh._cost}\n  V2G earn: {veh._earn}\n  Net cost: {veh._cost-veh._earn}\n"
            )
        self.set_qres(res)

    def collectgrid(self):
        self.grbus.clear()
        self.grline.clear()
        try:
            t = int(self.entry_time2.text())
        except:
            self.set_status("Invalid time point!")
            return
        if not hasattr(self, '_sta') or self._sta is None:
            self.set_status(_L["NO_STATISTICS"])
            return
        for b in self._sta.bus_head:
            v = self._sta.bus_attrib_of(b, "V").value_at(t)
            pd = self._sta.bus_attrib_of(b, "Pd").value_at(t)
            qd = self._sta.bus_attrib_of(b, "Qd").value_at(t)
            pg = self._sta.bus_attrib_of(b, "Pg").value_at(t)
            qg = self._sta.bus_attrib_of(b, "Qg").value_at(t)
            QTreeWidgetItem(self.grbus, [str(b), str(v), str(pd), str(qd), str(pg), str(qg)])
        for l in self._sta.line_head:
            p = self._sta.line_attrib_of(l, "P").value_at(t)
            q = self._sta.line_attrib_of(l, "Q").value_at(t)
            i = self._sta.line_attrib_of(l, "I").value_at(t)
            QTreeWidgetItem(self.grline, [str(l), str(p), str(q), str(i)])
        self.set_status(_L["STA_READY"])

    def disable_all(self):
        self._pp.disable()
        self.btn_draw.setEnabled(False)

    def enable_all(self):
        self._pp.enable([p for p, ok in self._ava.items() if ok])
        self.btn_draw.setEnabled(True)

    def set_status(self, text: str):
        self._sbar.setText(text)

    def update_file_list(self):
        self.pic_list.clear()
        if self.folder and os.path.exists(self.folder):
            files = set(os.listdir(self.folder))
            for file in sorted(files):
                if file.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
                    self.pic_list.addItem(file)

    def _load_data(self, path: str):
        sta = ReadOnlyStatistics(path)
        npl = AdvancedPlot()
        npl.load_series(sta)
        self._Q.put(('L', sta, npl))
    
    def _upd(self):
        while not self._Q.empty():
            op, *par = self._Q.get()
            if op == 'L':
                assert isinstance(par[0], ReadOnlyStatistics)
                assert isinstance(par[1], AdvancedPlot)
                self._sta = par[0]
                self._npl = par[1]
                for x in AVAILABLE_ITEMS:
                    self._ava[x] = getattr(self._sta, f"has_{x.upper()}")()
                if self._sta.has_FCS():
                    self._pp.fcs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.FCS_head)
                    self.cb_fcs_query.clear()
                    self.cb_fcs_query.addItems(self._sta.FCS_head)
                    if self._sta.FCS_head:
                        self.cb_fcs_query.setCurrentIndex(0)
                if self._sta.has_SCS():
                    self._pp.scs_pad.setValues([ITEM_SUM, ITEM_ALL] + self._sta.SCS_head)
                    self.cb_scs_query.clear()
                    self.cb_scs_query.addItems(self._sta.SCS_head)
                    if self._sta.SCS_head:
                        self.cb_scs_query.setCurrentIndex(0)
                if self._sta.has_GEN():
                    self._pp.gen_pad.setValues([ITEM_ALL_G, ITEM_ALL_V2G, ITEM_ALL] + self._sta.gen_head)
                if self._sta.has_BUS():
                    self._pp.bus_pad.setValues([ITEM_ALL] + self._sta.bus_head)
                if self._sta.has_LINE():
                    self._pp.line_pad.setValues([ITEM_ALL] + self._sta.line_head)
                if self._sta.has_PVW():
                    self._pp.pvw_pad.setValues([ITEM_ALL] + self._sta.pvw_head)
                if self._sta.has_ESS():
                    self._pp.ess_pad.setValues([ITEM_ALL] + self._sta.ess_head)
                self.update_file_list()
                self.set_status(_L["STA_READY"])
                self.enable_all()
            elif op == 'I':
                self.set_status(par[0])
            elif op == 'E':
                self.set_status(par[0])
                self.enable_all()
            elif op == 'LE':
                self.set_status(par[0])
                break
            elif op == 'D':
                self.update_file_list()
                self.set_status(_L["STA_READY"])
                self.enable_all()
            elif op == 'Q':
                self.close()
            elif op == 'UC':
                getattr(self._pp, par[0]).setChecked(False)
            else:
                self.set_status(_L["INTERNAL_ERR"])
                break

    def askdir(self):
        p = os.path.join(os.getcwd(), "cases")
        os.makedirs(p, exist_ok=True)
        dlg = QFileDialog(self, _L["TITLE_SEL_FOLDER"], p)
        dlg.setFileMode(QFileDialog.FileMode.Directory)
        dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
        if dlg.exec_():
            return dlg.selectedFiles()[0]
        return ""

    def force_reload(self):
        res_path = self.askdir()
        if res_path == "":
            return
        self.reload(res_path)

    def reload(self, res_path):
        try:
            first = True
            while True:
                res_path = Path(res_path)
                if res_path.exists():
                    break
                else:
                    if not first:
                        QMessageBox.critical(self, _L["ERROR"], "Folder not found!")
                first = False
                res_path = self.askdir()
                if res_path == "":
                    self._Q.put(('Q', None))
                    return
            cproc = res_path / "cproc.clog"
            if cproc.exists():
                self.tab_trip.load(str(cproc))
                pass
            else:
                cproc = res_path / "results" / "cproc.clog"
                if cproc.exists():
                    res_path = res_path / "results"
                else:
                    QMessageBox.critical(self, _L["ERROR"], _L["NO_CPROC"])
                    return
            self.set_status(_L["LOADING"])
            self.folder = str(res_path.absolute() / "figures")
            self.setWindowTitle(f'{_L["TITLE"]} - {res_path.name}')
            self.disable_all()

            threading.Thread(
                target=self._load_data,
                args=(str(res_path),),
                daemon=True
            ).start()

            state_path = res_path / "saved_state" / "inst.gz"
            if state_path.exists():
                try:
                    with gzip.open(state_path, 'rb') as f:
                        self.__inst = pickle.load(f)
                except:
                    QMessageBox.critical(self, _L["ERROR"], _L["SAVED_STATE_LOAD_FAILED"])
                    self.__inst = None
        except Exception as e:
            self._Q.put(('LE', str(e)))

    def plotSelected(self):
        cfg = self._pp.getConfig()
        self.disable_all()
        self.set_status("Plotting all...")
        self._npl.pic_ext = self._pp.cb_ext.currentText()
        self._npl.plot_title = self._pp.plot_title.isChecked()
        try:
            self._npl.dpi = int(self._pp.entry_dpi.currentText())
        except:
            QMessageBox.critical(self, _L["ERROR"], _L["INVALID_DPI"])
            self.enable_all()
            return
        for a in AVAILABLE_ITEMS2:
            if cfg[a]:
                break
        else:
            QMessageBox.critical(self, _L["ERROR"], _L["NOTHING_PLOT"])
            self.enable_all()
            return

        def work():
            for a in AVAILABLE_ITEMS2:
                if cfg[a]:
                    getattr(self, "_plot_" + a)()
                    if "_" in a:
                        continue
                    self._Q.put(('UC',"plot_" + a))
            self._Q.put(('D', None))

        threading.Thread(
            target=work,
            daemon=True
        ).start()

    # The following plotting methods remain unchanged except for message boxes and UI calls

    def _plot_scs_accum(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_scs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)

    def _plot_fcs_accum(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_fcs_accum(tl, tr, self._pp.AccumPlotMax, res_path=self._sta.root)

    def _plot_fcs(self):
        t = self._pp.fcs_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            cs = self._sta.FCS_head
        elif t == ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i, c in enumerate(cs, start=1):
            self._Q.put(('I', f'({i} of {len(cs)})Plotting FCS graph...'))
            self._npl.quick_fcs(
                cs_name=c, res_path=self._sta.root,
                **self._pp.pars("fcs")
            )

    def _plot_scs(self):
        t = self._pp.scs_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            cs = self._sta.SCS_head
        elif t == ITEM_SUM:
            cs = ["<sum>"]
        else:
            cs = [x.strip() for x in t.split(',')]
        for i, c in enumerate(cs, start=1):
            self._Q.put(('I', f'({i} of {len(cs)})Plotting SCS graph...'))
            self._npl.quick_scs(
                cs_name=c, res_path=self._sta.root,
                **self._pp.pars("scs")
            )

    def _plot_ev(self):
        self._npl.tl = int(self._pp.entry_time.text())
        t = self._pp.ev_pad.get()
        evs = None if t.strip() == "" else [x.strip() for x in t.split(',')]
        if evs is None:
            self._Q.put(('E', 'ID of EV cannot be empty'))
            return
        for ev in evs:
            self._npl.quick_ev(ev_name=ev,
                res_path=self._sta.root,
                **self._pp.pars("ev")
            )

    def _plot_gen(self):
        t = self._pp.gen_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            gen = self._sta.gen_head
        elif t == ITEM_ALL_G:
            gen = [x for x in self._sta.gen_head if not x.startswith("V2G")]
        elif t == ITEM_ALL_V2G:
            gen = [x for x in self._sta.gen_head if x.startswith("V2G")]
        else:
            gen = [x.strip() for x in t.split(',')]
        for i, g in enumerate(gen, start=1):
            self._Q.put(('I', f'({i}/{len(gen)})Plotting generators...'))
            self._npl.quick_gen(
                gen_name=g, res_path=self._sta.root,
                **self._pp.pars("gen")
            )

    def _plot_bus(self):
        t = self._pp.bus_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            bus = self._sta.bus_head
        else:
            bus = [x.strip() for x in t.split(',')]
        for i, g in enumerate(bus, start=1):
            self._Q.put(('I', f'({i}/{len(bus)})Plotting buses...'))
            self._npl.quick_bus(
                bus_name=g, res_path=self._sta.root,
                **self._pp.pars("bus")
            )

    def _plot_gen_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_gen_tot(tl, tr, True, True, True, res_path=self._sta.root)

    def _plot_bus_total(self):
        tl, tr = self._pp.getTime()
        self._npl.quick_bus_tot(tl, tr, True, True, True, True, res_path=self._sta.root)

    def _plot_line(self):
        t = self._pp.line_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            line = self._sta.line_head
        else:
            line = [x.strip() for x in t.split(',')]
        for i, g in enumerate(line, start=1):
            self._Q.put(('I', f'({i}/{len(line)})Plotting lines...'))
            self._npl.quick_line(
                line_name=g, res_path=self._sta.root,
                **self._pp.pars("line")
            )

    def _plot_pvw(self):
        t = self._pp.pvw_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            pvw = self._sta.pvw_head
        else:
            pvw = [x.strip() for x in t.split(',')]
        for i, g in enumerate(pvw, start=1):
            self._Q.put(('I', f'({i}/{len(pvw)})Plotting PV & Wind...'))
            self._npl.quick_pvw(
                pvw_name=g, res_path=self._sta.root,
                **self._pp.pars("pvw")
            )

    def _plot_ess(self):
        t = self._pp.ess_pad.get()
        if t.strip() == "" or t == ITEM_ALL:
            ess = self._sta.ess_head
        else:
            ess = [x.strip() for x in t.split(',')]
        for i, g in enumerate(ess, start=1):
            self._Q.put(('I', f'({i}/{len(ess)})Plotting ESS...'))
            self._npl.quick_ess(
                ess_name=g, res_path=self._sta.root,
                **self._pp.pars("ess")
            )
    
if __name__ == "__main__":
    from version_checker_qt import check_requirements_gui
    check_requirements_gui()
    app = QApplication(sys.argv)
    win = PlotBox()
    win.show()
    sys.exit(app.exec_())