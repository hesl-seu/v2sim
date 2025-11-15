from pathlib import Path
from feasytools import ArgChecker
from v2simux_gui.viewerbox import ViewerBox
    
if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()

    args = ArgChecker()
    dir = args.pop_str("d", "")
    if dir != "" and not Path(dir).is_dir():
        raise FileNotFoundError(f"{dir} is not a directory.")
    
    win = ViewerBox(dir)
    win.mainloop()