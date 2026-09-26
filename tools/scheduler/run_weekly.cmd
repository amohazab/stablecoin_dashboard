@echo off
rem Step 8 phase B (P-8.04 Q9): the weekly chain - behavioral, site, commit, push
cd /d D:\projects\stable_dashboard
if not exist out\logs\scheduler mkdir out\logs\scheduler
"C:\Users\aminm\AppData\Roaming\Python\Python314\Scripts\uv.exe" run python -m factory.chain --weekly >> out\logs\scheduler\wrapper.log 2>&1
exit /b %ERRORLEVEL%
