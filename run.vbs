' Launch run.bat with no visible console window.
' Pin a shortcut to THIS file on the taskbar/desktop for a clean one-click start.
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\run.bat""", 0, False
