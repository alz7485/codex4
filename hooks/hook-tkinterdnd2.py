"""Include Tcl scripts and native tkdnd libraries in the onedir distribution."""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tkinterdnd2")
