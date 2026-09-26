@echo off
rem Step 8 phase B (P-8.04 Q9): the weekly chain - behavioral, site, commit, push
rem P-8.09: UTF-8 console and Python I/O; stdin from nul; a plain exit ends cmd.exe itself
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d D:\projects\stable_dashboard
if not exist out\logs\scheduler mkdir out\logs\scheduler
"C:\Users\aminm\AppData\Roaming\Python\Python314\Scripts\uv.exe" run python -m factory.chain --weekly < nul >> out\logs\scheduler\wrapper.log 2>&1
set RC=%ERRORLEVEL%
exit %RC%
