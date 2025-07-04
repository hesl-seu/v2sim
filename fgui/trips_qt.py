import os
from pathlib import Path
from typing import List
import matplotlib
matplotlib.use("agg")
from matplotlib import pyplot as plt
from queue import Queue
import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QFileDialog, QMessageBox
)
from PyQt5.QtCore import QTimer
from v2sim import CustomLocaleLib, TripsReader, TripLogItem

_loc = CustomLocaleLib(["zh_CN","en"])
_loc.SetLanguageLib("zh_CN",
    GUI_EVANA_TITLE = "EV和行程分析",
    GUI_EVANA_ALL = "(全部)",
    GUI_EVANA_START_TIME = "起始时间",
    GUI_EVANA_END_TIME = "结束时间",
    GUI_EVANA_VEH = "车辆",
    GUI_EVANA_TRIP = "行程",
    GUI_EVANA_FILTER = "过滤",
    GUI_EVANA_SAVE = "保存",
    GUI_EVANA_PARAMSSTA = "统计",
    GUI_EVANA_PARAMSPLOT = "阈值曲线",
    GUI_EVANA_TIME = "时间",
    GUI_EVANA_TYPE = "类型",
    GUI_EVANA_SOC = "SoC",
    GUI_EVANA_SOC_THRE = "SoC阈值",
    GUI_EVANA_MSGBOX_STA_INVALID_THRE = "无效的阈值",
    GUI_EVANA_PARAMS = "参数",
    GUI_EVANA_INFO = "信息",
    GUI_EVANA_MSGBOX_STA_TITLE = "统计参数",
    GUI_EVANA_MSGBOX_STA_MSG = "SoC阈值: {0}，大于阈值的比例: {1}，总数: {2}",
    GUI_EVANA_SAVEAS = "另存为",
    GUI_EVANA_CSV_FILE = "CSV文件",
    GUI_EVANA_SEL_CLOG = "选择cproc.clog",
)

_loc.SetLanguageLib("en",
    GUI_EVANA_TITLE = "EV & Trips Analysis",
    GUI_EVANA_ALL = "(All)",
    GUI_EVANA_START_TIME = "Start Time",
    GUI_EVANA_END_TIME = "End Time",
    GUI_EVANA_VEH = "Vehicle",
    GUI_EVANA_TRIP = "Trip",
    GUI_EVANA_FILTER = "Filter",
    GUI_EVANA_SAVE = "Save",
    GUI_EVANA_PARAMSSTA = "Statistics",
    GUI_EVANA_PARAMSPLOT = "Threshold Curve",
    GUI_EVANA_TIME = "Time",
    GUI_EVANA_TYPE = "Type",
    GUI_EVANA_SOC = "SoC",
    GUI_EVANA_SOC_THRE = "SoC Threshold",
    GUI_EVANA_MSGBOX_STA_INVALID_THRE = "Invalid threshold",
    GUI_EVANA_PARAMS = "Parameters",
    GUI_EVANA_INFO = "Information",
    GUI_EVANA_MSGBOX_STA_TITLE = "Statistics",
    GUI_EVANA_MSGBOX_STA_MSG = "SoC threshold: {0}. Proportion greater than threshold: {1}. Total: {2}",
    GUI_EVANA_SAVEAS = "Save as",
    GUI_EVANA_CSV_FILE = "CSV file",
    GUI_EVANA_SEL_CLOG = "Select cproc.clog",
)

class TripsFrame(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file = None
        self._disp: List[TripLogItem] = []
        self._Q = Queue()

        # 主布局
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # 表格
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            _loc["GUI_EVANA_TIME"], _loc["GUI_EVANA_TYPE"], _loc["GUI_EVANA_VEH"],
            _loc["GUI_EVANA_SOC"], _loc["GUI_EVANA_TRIP"], _loc["GUI_EVANA_PARAMS"], _loc["GUI_EVANA_INFO"]
        ])
        main_layout.addWidget(self.table)

        # 第一行控件
        fr1 = QHBoxLayout()
        self.type_combo = QComboBox()
        self.TYPES = [_loc["GUI_EVANA_ALL"]]
        self.TYPES.extend(f"{k}:{v}" for k, v in TripLogItem.OP_NAMEs.items())
        self.type_combo.addItems(self.TYPES)
        fr1.addWidget(self.type_combo)

        fr1.addWidget(QLabel(_loc["GUI_EVANA_START_TIME"]))
        self.entryST = QLineEdit()
        self.entryST.setFixedWidth(60)
        fr1.addWidget(self.entryST)

        fr1.addWidget(QLabel(_loc["GUI_EVANA_END_TIME"]))
        self.entryED = QLineEdit()
        self.entryED.setFixedWidth(60)
        fr1.addWidget(self.entryED)

        fr1.addWidget(QLabel(_loc["GUI_EVANA_VEH"]))
        self.entryVeh = QLineEdit()
        self.entryVeh.setFixedWidth(60)
        fr1.addWidget(self.entryVeh)

        fr1.addWidget(QLabel(_loc["GUI_EVANA_TRIP"]))
        self.entryTrip = QLineEdit()
        self.entryTrip.setFixedWidth(60)
        fr1.addWidget(self.entryTrip)

        self.btnFilter = QPushButton(_loc["GUI_EVANA_FILTER"])
        self.btnFilter.clicked.connect(lambda: self._Q.put(('F', None)))
        fr1.addWidget(self.btnFilter)

        self.btnSave = QPushButton(_loc["GUI_EVANA_SAVE"])
        self.btnSave.clicked.connect(self.save)
        fr1.addWidget(self.btnSave)

        main_layout.addLayout(fr1)

        # 第二行控件
        fr2 = QHBoxLayout()
        fr2.addWidget(QLabel(_loc["GUI_EVANA_SOC_THRE"]))
        self.entrysocthre = QLineEdit("0.8")
        self.entrysocthre.setFixedWidth(60)
        fr2.addWidget(self.entrysocthre)

        self.btnStat = QPushButton(_loc["GUI_EVANA_PARAMSSTA"])
        self.btnStat.clicked.connect(self.params_calc)
        fr2.addWidget(self.btnStat)

        self.btnStatPlot = QPushButton(_loc["GUI_EVANA_PARAMSPLOT"])
        self.btnStatPlot.clicked.connect(self.params_plot)
        fr2.addWidget(self.btnStatPlot)

        main_layout.addLayout(fr2)

        # 定时器替代after
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._upd)
        self.timer.start(100)

    def _upd(self):
        cnt = 0
        while not self._Q.empty() and cnt < 50:
            op, val = self._Q.get()
            cnt += 1
            if op == 'L':
                assert isinstance(val, TripsReader)
                self._data: TripsReader = val
                self._disp = [m for _, m, _ in self._data.filter()]
                self._Q.put(('S', None))
            elif op == 'S':
                self.table.setRowCount(0)
                for item in self._disp:
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    for col, value in enumerate(item.to_tuple(conv=True)):
                        self.table.setItem(row, col, QTableWidgetItem(str(value)))
            elif op == 'F':
                ftype = self.type_combo.currentText()
                if ftype == self.TYPES[0]:
                    factions = None
                else:
                    factions = [ftype.split(":")[0]]
                fveh = self.entryVeh.text()
                if fveh == "":
                    fveh = None
                ftrip = self.entryTrip.text().strip()
                if len(ftrip) == 0:
                    ftrip_id = None
                else:
                    ftrip_id = int(ftrip)
                st_time_str = self.entryST.text().strip()
                if len(st_time_str) == 0:
                    st_time = None
                else:
                    st_time = int(st_time_str)
                ed_time_str = self.entryED.text().strip()
                if len(ed_time_str) == 0:
                    ed_time = None
                else:
                    ed_time = int(ed_time_str)
                if hasattr(self, "_data"):
                    self._disp = [m for _, m, _ in self._data.filter(
                        time=(st_time, ed_time), action=factions, veh=fveh, trip_id=ftrip_id
                    )]
                self._Q.put(('S', None))

    def __params_calc(self, tau: float):
        okcnt = 0
        cnt = 0
        for item in self._disp:
            if item.op_raw != "D":
                continue
            soc = float(item.veh_soc.rstrip("%")) / 100
            if soc > tau:
                okcnt += 1
            cnt += 1
        return okcnt, cnt

    def params_calc(self):
        try:
            tau = float(self.entrysocthre.text())
        except ValueError:
            QMessageBox.critical(self, _loc["GUI_EVANA_MSGBOX_STA_TITLE"], _loc["GUI_EVANA_MSGBOX_STA_INVALID_THRE"])
            return
        okcnt, cnt = self.__params_calc(tau)
        if cnt == 0:
            QMessageBox.information(self, _loc["GUI_EVANA_MSGBOX_STA_TITLE"],
                _loc["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, "N/A", cnt))
        else:
            QMessageBox.information(self, _loc["GUI_EVANA_MSGBOX_STA_TITLE"],
                _loc["GUI_EVANA_MSGBOX_STA_MSG"].format(tau, f"{okcnt / cnt * 100:.2f}%", cnt))

    def params_plot(self):
        y = []
        for i in range(1, 100 + 1):
            tau = i / 100
            okcnt, cnt = self.__params_calc(tau)
            if cnt == 0:
                y.append(0)
            else:
                y.append(okcnt / cnt)
        plt.title("SoC Threshold vs. Proportion")
        plt.xlabel("SoC Threshold")
        plt.ylabel("Proportion")
        plt.plot(range(1, 100 + 1), y)
        if self._file is not None:
            p = Path(self._file).parent / "figures"
        else:
            p = Path("figures")
        p.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(p / "thre_curve.png"))
        QMessageBox.information(self, "Threshold Curve", "Threshold curve saved to figures/thre_curve.png")

    def save(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, _loc["GUI_EVANA_SAVEAS"], os.getcwd(), f"{_loc['GUI_EVANA_CSV_FILE']} (*.csv)"
        )
        if not filename:
            return
        with open(filename, "w", encoding="utf-8") as fp:
            fp.write(f'{_loc["GUI_EVANA_TIME"]},{_loc["GUI_EVANA_TYPE"]},{_loc["GUI_EVANA_VEH"]},{_loc["GUI_EVANA_SOC"]},{_loc["GUI_EVANA_TRIP"]},{_loc["GUI_EVANA_INFO"]}\n')
            for item in self._disp:
                addinfo = ','.join(f"{k} = {v}".replace(',', ' ') for k, v in item.additional.items())
                fp.write(f"{item.simT},{item.op},{item.veh},{item.veh_soc},{item.trip_id},{addinfo}\n")

    def load(self, filename: str):
        self._file = filename
        def thload(filename: str):
            fh = TripsReader(filename)
            self._Q.put(('L', fh))
        threading.Thread(target=thload, args=(filename,)).start()
