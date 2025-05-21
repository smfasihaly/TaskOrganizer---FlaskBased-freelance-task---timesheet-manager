Option Explicit

Dim WshShell, exePath
Set WshShell = CreateObject("WScript.Shell")

' Full path to your bundled exe
exePath = "D:\random codes\taskorganizer\dist\taskorganizer.exe"

' 0 = hidden window, False = run asynchronously
WshShell.Run Chr(34) & exePath & Chr(34), 0, False
