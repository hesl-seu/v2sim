import sys
import os
import time
import multiprocessing as mp
from feasytools import ArgChecker
from pathlib import Path
from v2simux_gui.welcomebox import WelcomeBox


def welcome(chd_pipe, to_open):
    wb = WelcomeBox(chd_pipe, to_open)
    wb.show()


if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()

    args = ArgChecker()
    to_open = args.pop_str("d", "")
    
    Q = mp.Queue()
    mp.Process(target=welcome, args=(Q, to_open)).start()

    try:
        from v2simux_gui.mainbox import MainBox
        win = MainBox()
        success = True
    except Exception as e:
        import traceback
        print("Failed to start the main window:")
        print(traceback.format_exc())
        Q.put_nowait("error")
        success = False
    
    if success:
        Q.put_nowait("done")
        time.sleep(0.1)  # Give some time for the welcome box to show up
        msg = Q.get()
        if msg[0] == "close":
            win.quit()
            win.destroy()
            exit(0)
        elif msg[0] == "main" and msg[1] != "":
            win.folder = msg[1]
            win._load()
            win.wm_attributes('-topmost', 1)
            win.after(100, lambda: win.wm_attributes('-topmost', 0))
            win.mainloop()
        elif msg[0] == "res" and msg[1] != "":
            os.system(f'{sys.executable} {Path(__file__).parent}/gui_viewer.py -d="{msg[1]}"')
        elif msg[0] == "conv":
            os.system(f'{sys.executable} {Path(__file__).parent}/gui_convert.py')