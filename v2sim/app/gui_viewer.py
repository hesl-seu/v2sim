from pathlib import Path
from feasytools import ArgChecker
from v2sim.gui.viewerbox import ViewerBox
    
def main():
    args = ArgChecker()
    dir = args.pop_str("d", "")
    if dir != "" and not Path(dir).is_dir():
        raise FileNotFoundError(f"{dir} is not a directory.")
    
    win = ViewerBox(dir)
    win.mainloop()


if __name__ == "__main__":
    main()