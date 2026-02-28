@echo off
echo Starting SSHD Archipelago Client...
echo.

REM Try standalone exe first (no Python needed)
if exist "%~dp0ArchipelagoSSHDClient.exe" (
    echo Using standalone client...
    "%~dp0ArchipelagoSSHDClient.exe" %*
    goto :done
)

REM Check Archipelago directory for the exe
if exist "C:\ProgramData\Archipelago\ArchipelagoSSHDClient\ArchipelagoSSHDClient.exe" (
    echo Using standalone client from Archipelago folder...
    "C:\ProgramData\Archipelago\ArchipelagoSSHDClient\ArchipelagoSSHDClient.exe" %*
    goto :done
)

REM Check Archipelago directory for the exe
if exist "C:\ProgramData\Archipelago\ArchipelagoSSHDClient.exe" (
    echo Using standalone client from Archipelago folder...
    "C:\ProgramData\Archipelago\ArchipelagoSSHDClient.exe" %*
    goto :done
)

REM Fallback: Use Python (legacy method)
echo Standalone exe not found, falling back to Python...
python "C:\ProgramData\Archipelago\launch_sshd_wrapper.py" %*

:done
echo.
echo Client closed.
pause
