from v2sim.gui.com_no_vx import *
from v2sim.gui.langhelper import *

import os
from PIL import Image, ImageTk


_ = LangLib.Load(__file__)


class CmpBox(Tk):
    def __init__(self):
        super().__init__()

        self.title(_("TITLE"))
        self.geometry("1024x768")
        self.bind("<Configure>", self.on_resize)

        self.folder1 = None
        self.folder2 = None
        self.original_image1 = None
        self.original_image2 = None
        self.folder_buf = "./results"

        self.create_widgets()

    def create_widgets(self):
        self.menu = Menu(self)
        self.config(menu=self.menu)
        self.filemenu = Menu(self.menu, tearoff=0)
        self.filemenu.add_command(label=_("OPEN_FOLDER1"), command=self.open_folder1)
        self.filemenu.add_command(label=_("OPEN_FOLDER2"), command=self.open_folder2)
        self.filemenu.add_separator()
        self.filemenu.add_command(label=_("EXIT"), command=self.destroy)
        self.menu.add_cascade(label=_("FILE"), menu=self.filemenu)
        add_lang_menu(self.menu)

        self.sidebar = Frame(self)
        self.sidebar.pack(side=LEFT, fill=Y)

        self.folder1_button = Button(self.sidebar, text=_("OPEN_FOLDER1"), command=self.open_folder1)
        self.folder1_button.pack(pady=10)

        self.folder2_button = Button(self.sidebar, text=_("OPEN_FOLDER2"), command=self.open_folder2)
        self.folder2_button.pack(pady=10)

        self.folder1_label = Label(self.sidebar, text=_("LB_FOLDER1").format(_("TO_BE_SELECTED")))
        self.folder1_label.pack(pady=10)

        self.folder2_label = Label(self.sidebar, text=_("LB_FOLDER2").format(_("TO_BE_SELECTED")))
        self.folder2_label.pack(pady=10)

        self.file_listbox = Listbox(self.sidebar)
        self.file_listbox.pack(fill=BOTH, expand=True, pady=10)
        self.file_listbox.bind("<<ListboxSelect>>", self.on_file_select)

        self.image_frame = Frame(self)
        self.image_frame.pack(side=RIGHT, fill=X, expand=True)

        self.image1_label = Label(self.image_frame)
        self.image1_label.pack(side=TOP, padx=10, pady=10)

        self.image2_label = Label(self.image_frame)
        self.image2_label.pack(side=TOP, padx=10, pady=10)

    def open_folder1(self):
        new_folder = filedialog.askdirectory(initialdir=self.folder_buf, title=_("AD_TITLE1"))
        if new_folder:
            folder_fig = os.path.join(new_folder, "figures")
            if os.path.exists(folder_fig):
                self.folder1 = folder_fig
                self.folder1_label.config(text=_("LB_FOLDER1").format(os.path.basename(new_folder)))
                self.update_file_list()
                self.folder_buf = str(Path(new_folder).parent)
            else:
                MB.showerror(_("ERROR"), _("NO_FIG"))

    def open_folder2(self):
        new_folder = filedialog.askdirectory(initialdir=self.folder_buf, title=_("AD_TITLE2"))
        if new_folder:
            folder_fig = os.path.join(new_folder, "figures")
            if os.path.exists(folder_fig):
                self.folder2 = folder_fig
                self.folder2_label.config(text=_("LB_FOLDER2").format(os.path.basename(new_folder)))
                self.update_file_list()
                self.folder_buf = str(Path(new_folder).parent)
            else:
                MB.showerror(_("ERROR"), _("NO_FIG"))

    def update_file_list(self):
        self.file_listbox.delete(0, END)
        if self.folder1 and self.folder2:
            files1 = set(os.listdir(self.folder1))
            files2 = set(os.listdir(self.folder2))
            common_files = files1.union(files2)
            for file in sorted(common_files):
                if file.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):  # 只列出图片文件
                    self.file_listbox.insert(END, file)

    def on_file_select(self, event):
        selected_index = self.file_listbox.curselection()
        if selected_index:
            file_name = self.file_listbox.get(selected_index)
            self.display_images(file_name)

    def resize(self):
        sz = (self.winfo_width() - 200, self.winfo_height() // 2 - 20)
        if self.original_image1 is not None:
            resized_image1 = self.original_image1.copy()
            resized_image1.thumbnail(sz)
            image1 = ImageTk.PhotoImage(resized_image1)

            self.image1_label.config(image=image1,text="")
            self.image1 = image1
        else:
            self.image1_label.config(image='',text=_("NO_IMAGE"))
            self.image1 = None

        if self.original_image2 is not None:
            resized_image2 = self.original_image2.copy()
            resized_image2.thumbnail(sz)
            image2 = ImageTk.PhotoImage(resized_image2)

            self.image2_label.config(image=image2,text="")
            self.image2 = image2
        else:
            self.image2_label.config(image='',text=_("NO_IMAGE"))
            self.image2 = None


    def on_resize(self, event):
        self.resize()
        
    def display_images(self, file_name:str):
        if self.folder1 is None: return
        img1_path = os.path.join(self.folder1, file_name)
        if self.folder2 is None: return
        img2_path = os.path.join(self.folder2, file_name)
        
        try:
            if os.path.exists(img1_path):
                self.original_image1 = Image.open(img1_path)
            else:
                self.original_image1 = None
            if os.path.exists(img2_path):
                self.original_image2 = Image.open(img2_path)
            else:
                self.original_image2 = None
        except Exception as e:
            MB.showerror(_("ERROR"), _("LOAD_FAILED").format(str(e)))
        
        self.resize()