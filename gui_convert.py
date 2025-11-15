from v2simux_gui.convertbox import *


if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()
    app = ConvertBox()
    app.mainloop()