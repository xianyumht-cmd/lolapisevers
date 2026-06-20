Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
batPath = FSO.BuildPath(scriptDir, "run_server.bat")

' 0 means hide window
WshShell.Run "cmd /c """ & batPath & """", 0, False

Set FSO = Nothing
Set WshShell = Nothing
