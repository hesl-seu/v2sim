from feasytools import ArgChecker
from v2sim.gui.welcomebox import WelcomeBox


def main():
    args = ArgChecker()
    to_open = args.pop_str("d", "")
    
    wb = WelcomeBox(to_open)
    msg = wb.show()

    if msg[0] == "close":
        exit(0)
    elif msg[0] == "main" and msg[1] != "":
        from v2sim.gui.mainbox import MainBox
        win = MainBox()
        win.folder = msg[1]
        win._load()
        win.mainloop()
    elif msg[0] == "res" and msg[1] != "":
        from v2sim.gui.viewerbox import ViewerBox
        win = ViewerBox(msg[1])
        win.mainloop()
    elif msg[0] == "para":
        from v2sim.gui.parabox import ParaBox
        win = ParaBox()
        win.mainloop()
    elif msg[0] == "cmp":
        from v2sim.gui.cmpbox import CmpBox
        win = CmpBox()
        win.mainloop()

if __name__ == "__main__":
    main()