from tkinter import Menu
from tkinter import messagebox as MB
from v2sim import Lang
from v2sim.locale.lang import CustomLocaleLib

_L = CustomLocaleLib(["zh_CN","en"])
_L.SetLanguageLib("zh_CN",
    MB_INFO = "信息",
    MENU_LANG = "语言",
    MENU_LANG_AUTO = "(自动检测)",
    LANG_RESTART = "语言已更改，请重启程序以应用更改。",
)

_L.SetLanguageLib("en",
    MB_INFO = "Information",
    MENU_LANG = "Language",
    MENU_LANG_AUTO = "(Auto Detect)",
    LANG_RESTART = "Language has been changed. Please restart the application to apply the changes.",
)

def setLang(lang_code:str):
    def _f():
        _L.DefaultLanguage = lang_code
        Lang.load(lang_code)
        Lang.save_lang_code(lang_code == "<auto>")
        MB.showinfo(_L["MB_INFO"],_L["LANG_RESTART"])
    return _f

def add_lang_menu(parent: Menu):
    menuLang = Menu(parent, tearoff=False)
    parent.add_cascade(label=_L["MENU_LANG"], menu=menuLang)
    menuLang.add_command(label=_L["MENU_LANG_AUTO"], command=setLang("<auto>"))
    menuLang.add_command(label="English", command=setLang("en"))
    menuLang.add_command(label="简体中文", command=setLang("zh_CN"))
