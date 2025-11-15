from pathlib import Path
from feasytools import ArgChecker
from v2simux.gui.viewerbox import ViewerBox
    
if __name__ == "__main__":
    args = ArgChecker()
    dir = args.pop_str("d", "")
    if dir != "" and not Path(dir).is_dir():
        raise FileNotFoundError(f"{dir} is not a directory.")
    
    win = ViewerBox(dir)
    win.mainloop()