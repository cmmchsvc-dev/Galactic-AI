Set WshShell = CreateObject("WScript.Shell")
' Run the python script silently (0 means hide window)
WshShell.Run "pythonw.exe ""galactic_desktop.py""", 0, False
