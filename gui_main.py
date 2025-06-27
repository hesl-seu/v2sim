from tkinter import Tk, PhotoImage, Label
from pathlib import Path
import platform
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)

class WelcomeBox(Tk):
    def __init__(self):
        super().__init__()
        self.wm_attributes('-topmost',1)
        self.overrideredirect(True)
        self.update_idletasks()
        width = 600
        height = 300
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        
        self.resizable(False, False)

        self.image = PhotoImage(file=str(Path(__file__).parent / "fgui/v2sim.png"))
        self.image_label = Label(self, image=self.image)
        self.image_label.place(x=0, y=0, relwidth=1, relheight=1)

if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()

    wb = WelcomeBox()
    def main():
        from fgui.mainbox import MainBox
        win = MainBox()
        wb.destroy()
        win.mainloop()

    wb.after(100, main)
    wb.mainloop()