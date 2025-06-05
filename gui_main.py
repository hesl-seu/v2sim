import multiprocessing as mp
from tkinter import Tk, PhotoImage, Label
from pathlib import Path

class WelcomeBox(Tk):
    def __init__(self, chd_pipe):
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
        self.__pipe = chd_pipe
    
    def _checkdone(self):
        if self.__pipe.recv() == "close":
            self.destroy()
        else:
            self.after(100, self._checkdone)
    
    def show(self):
        self.update()
        self.deiconify()
        self.after(1000, self._checkdone)
        self.mainloop()

def welcome(chd_pipe):
    wb = WelcomeBox(chd_pipe)
    wb.show()

def main(par):
    from fgui.mainbox import MainBox
    win = MainBox()
    par.send("close")
    win.mainloop()

if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()
    par, chd = mp.Pipe()
    mp.Process(target=welcome, args=(chd,)).start()
    main(par)