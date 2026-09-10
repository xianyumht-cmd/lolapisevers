# LOLDataSystem local runtime discovery — Issue #103

- Generated (UTC): `2026-09-10T06:19:59.3539037Z`
- Read-only diagnostic: **yes**
- Secrets/config/environment captured: **no**
- Windows: `Microsoft Windows 10 专业版` `10.0.19045` build `19045`
- Windows PowerShell: `5.1.19041.3803`
- Listener port: `5001`
- Listener PID(s): `6000`
- Resolved runtime root: `D:\project2\lolapisevers`
- Resolution confidence: **high** (score 850)
- Evidence sources: `nssm_app_directory, nssm_app_parameters, process_listener_command, process_parent-1_executable, process_parent-1_command, process_parent-2_command, process_parent-3_executable, process_parent-3_command, service_LOLDataSystem, scheduled_task_LOLDataSystem-KeepAlive_args, known_candidate, d_project2_marker_scan`
- Matches old assumption `D:\project2\lolapisevers`: **True**

## NSSM / service topology

- NSSM parameters key exists: **True**
- NSSM Application: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
- NSSM AppDirectory: `D:\project2\lolapisevers`
- NSSM parameter path tokens: `D:\project2\lolapisevers\ops\run_service.ps1`
- Service `LOLDataSystem`: state=`Running` pid=`2904` paths=`D:\project2\lolapisevers\tools\nssm-2.24\win64\nssm.exe`

## Listener process chain

- `listener` PID=6000, parent=5996, name=`python.exe`, exe=`C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`, command-paths=`D:\project2\lolapisevers\.venv\Scripts\python.exe`
- `parent-1` PID=5996, parent=3376, name=`python.exe`, exe=`D:\project2\lolapisevers\.venv\Scripts\python.exe`, command-paths=`D:\project2\lolapisevers\.venv\Scripts\python.exe`
- `parent-2` PID=3376, parent=2904, name=`powershell.exe`, exe=`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`, command-paths=`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe | D:\project2\lolapisevers\ops\run_service.ps1`
- `parent-3` PID=2904, parent=936, name=`nssm.exe`, exe=`D:\project2\lolapisevers\tools\nssm-2.24\win64\nssm.exe`, command-paths=`D:\project2\lolapisevers\tools\nssm-2.24\win64\nssm.exe`
- `parent-4` PID=936, parent=720, name=`services.exe`, exe=``, command-paths=``

## Candidate repositories

- `D:\project2\lolapisevers`: git=True, branch=``, commit=``, tracked_dirty=False, origin=``, app.py=True, run_service=True
- `D:\project2\lolapisevers-main-clean`: git=False, branch=``, commit=``, tracked_dirty=, origin=``, app.py=True, run_service=True

## Path probe warnings

- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Leaf): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Leaf): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Any): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Leaf): `System.UnauthorizedAccessException`
- `D:\project2\lolapisevers\.venv\Scripts\python.exe` (Leaf): `System.UnauthorizedAccessException`

## Safe endpoint probes

- `/health`: ok=True, HTTP=200, fields=`{"status":"ok","ready":true,"mysql":"up","so1_browser":"up"}`
- `/lol/patch-status?date=2026-09-10`: ok=False, HTTP=404, fields=`{}`

## Safety note

This report intentionally excludes raw config files, environment variables, tokens, cookies, passwords, raw command lines, and credential material. It is temporary evidence for Issue #103 and should be removed or summarized before merge.
