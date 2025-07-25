import os
from pathlib import Path
from v2sim import CustomLocaleLib

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QFileDialog, QMessageBox, QAction, QSplitter
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

_ = CustomLocaleLib.LoadFromFolder("resources/gui_cmp")

class ImageComparerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("TITLE"))
        self.resize(1024, 768)

        self.folder1 = None
        self.folder2 = None
        self.original_image1 = None
        self.original_image2 = None
        self.folder_buf = "./results"

        self.init_ui()

    def init_ui(self):
        self.setSizePolicy(QWidget().sizePolicy())
        self.setMinimumSize(800, 600)
        self.setMaximumSize(16777215, 16777215)
        # Menu
        menubar = self.menuBar()
        file_menu = menubar.addMenu(_("FILE"))

        open_folder1_action = QAction(_("OPEN_FOLDER1"), self)
        open_folder1_action.triggered.connect(self.open_folder1)
        file_menu.addAction(open_folder1_action)

        open_folder2_action = QAction(_("OPEN_FOLDER2"), self)
        open_folder2_action.triggered.connect(self.open_folder2)
        file_menu.addAction(open_folder2_action)

        file_menu.addSeparator()
        exit_action = QAction(_("EXIT"), self)
        def connect_close():
            self.close()
        exit_action.triggered.connect(connect_close)
        file_menu.addAction(exit_action)

        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Sidebar
        sidebar = QVBoxLayout()
        self.folder1_btn = QPushButton(_("OPEN_FOLDER1"))
        self.folder1_btn.clicked.connect(self.open_folder1)
        sidebar.addWidget(self.folder1_btn)

        self.folder2_btn = QPushButton(_("OPEN_FOLDER2"))
        self.folder2_btn.clicked.connect(self.open_folder2)
        sidebar.addWidget(self.folder2_btn)

        self.folder1_label = QLabel(_("LB_FOLDER1").format(_("TO_BE_SELECTED")))
        sidebar.addWidget(self.folder1_label)

        self.folder2_label = QLabel(_("LB_FOLDER2").format(_("TO_BE_SELECTED")))
        sidebar.addWidget(self.folder2_label)

        self.file_listbox = QListWidget()
        self.file_listbox.itemSelectionChanged.connect(self.on_file_select)
        sidebar.addWidget(self.file_listbox, stretch=1)

        sidebar_widget = QWidget()
        sidebar_widget.setLayout(sidebar)

        # Image display area
        image_area = QVBoxLayout()
        self.image1_label = QLabel(_("NO_IMAGE"))
        self.image1_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image2_label = QLabel(_("NO_IMAGE"))
        self.image2_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_area.addWidget(self.image1_label, stretch=1)
        image_area.addWidget(self.image2_label, stretch=1)

        image_widget = QWidget()
        image_widget.setLayout(image_area)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar_widget)
        splitter.addWidget(image_widget)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def open_folder1(self):
        new_folder = QFileDialog.getExistingDirectory(self, _("AD_TITLE1"), self.folder_buf)
        if new_folder:
            folder_fig = os.path.join(new_folder, "figures")
            if os.path.exists(folder_fig):
                self.folder1 = folder_fig
                self.folder1_label.setText(_("LB_FOLDER1").format(os.path.basename(new_folder)))
                self.update_file_list()
                self.folder_buf = str(Path(new_folder).parent)
            else:
                QMessageBox.critical(self, _("ERROR"), _("NO_FIG"))

    def open_folder2(self):
        new_folder = QFileDialog.getExistingDirectory(self, _("AD_TITLE2"), self.folder_buf)
        if new_folder:
            folder_fig = os.path.join(new_folder, "figures")
            if os.path.exists(folder_fig):
                self.folder2 = folder_fig
                self.folder2_label.setText(_("LB_FOLDER2").format(os.path.basename(new_folder)))
                self.update_file_list()
                self.folder_buf = str(Path(new_folder).parent)
            else:
                QMessageBox.critical(self, _("ERROR"), _("NO_FIG"))

    def update_file_list(self):
        self.file_listbox.clear()
        if self.folder1 and self.folder2:
            files1 = set(os.listdir(self.folder1))
            files2 = set(os.listdir(self.folder2))
            common_files = files1.union(files2)
            for file in sorted(common_files):
                if file.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
                    self.file_listbox.addItem(file)

    def on_file_select(self):
        selected_items = self.file_listbox.selectedItems()
        if selected_items:
            file_name = selected_items[0].text()
            self.display_images(file_name)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_images()

    def resize_images(self):
        if self.original_image1 is not None:
            self.image1_label.setPixmap(self.original_image1)
            self.image1_label.setText("")
            label_size = self.image1_label.size()
            if not self.original_image1.isNull():
                scaled_pixmap = self.original_image1.scaled(
                    label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.image1_label.setPixmap(scaled_pixmap)
            
        else:
            self.image1_label.setPixmap(QPixmap())
            self.image1_label.setText(_("NO_IMAGE"))

        if self.original_image2 is not None:
            self.image2_label.setPixmap(self.original_image2)
            self.image2_label.setText("")
            if not self.original_image2.isNull():
                scaled_pixmap = self.original_image2.scaled(
                    label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.image2_label.setPixmap(scaled_pixmap)
        else:
            self.image2_label.setPixmap(QPixmap())
            self.image2_label.setText(_("NO_IMAGE"))

    def display_images(self, file_name: str):
        if self.folder1 is None or self.folder2 is None:
            return
        img1_path = os.path.join(self.folder1, file_name)
        img2_path = os.path.join(self.folder2, file_name)
        try:
            if os.path.exists(img1_path):
                self.original_image1 = QPixmap(img1_path)
            else:
                self.original_image1 = None
            if os.path.exists(img2_path):
                self.original_image2 = QPixmap(img2_path)
            else:
                self.original_image2 = None
        except Exception as e:
            QMessageBox.critical(self, _("ERROR"), _("LOAD_FAILED").format(str(e)))
            self.original_image1 = None
            self.original_image2 = None
        self.resize_images()

if __name__ == "__main__":
    import sys
    from version_checker_qt import check_requirements_gui
    check_requirements_gui()
    app = QApplication(sys.argv)
    win = ImageComparerApp()
    win.show()
    sys.exit(app.exec_())