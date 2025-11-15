from v2simux_gui.com_no_vx import *

_ = LangLib(["zh_CN", "en_US"])
_.SetLangLib("zh_CN",
    MB_INFO = "信息",
    MENU_LANG = "语言",
    MENU_LANG_AUTO = "(自动检测)",
    LANG_RESTART = "语言已更改，请重启程序以应用更改。",
)

_.SetLangLib("en_US",
    MB_INFO = "Information",
    MENU_LANG = "Language",
    MENU_LANG_AUTO = "(Auto Detect)",
    LANG_RESTART = "Language has been changed. Please restart the application to apply the changes.",
)

def setLang(lang_code:str):
    title = _["MB_INFO"]
    info = _["LANG_RESTART"]
    def _f():
        nonlocal lang_code, title, info
        LangConfig.SetLangCode(lang_code)
        MB.showinfo(title, info)
    return _f

def add_lang_menu(parent: Menu):
    menuLang = Menu(parent, tearoff=False)
    parent.add_cascade(label=_["MENU_LANG"], menu=menuLang)
    menuLang.add_command(label=_["MENU_LANG_AUTO"], command=setLang("<auto>"))
    menuLang.add_command(label="English (United States)", command=setLang("en_US"))
    menuLang.add_command(label="中文 (简体)", command=setLang("zh_CN"))

__all__ = ["add_lang_menu"]
