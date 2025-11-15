from v2simux_gui.cmpbox import CmpBox

    
if __name__ == "__main__":
    from version_checker import check_requirements_gui
    check_requirements_gui()
    app = CmpBox()
    app.mainloop()