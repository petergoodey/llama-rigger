@echo off
rem ===========================================================================
rem  start-llama.cmd - start llama-server (router mode) from a preset .ini
rem
rem  Usage:  start-llama.cmd [preset.ini] [--here] [--dry-run] [extra args...]
rem
rem    <preset.ini>  OPTIONAL. Defaults to %LLAMA_PRESET%, else local\models.ini,
rem                  else models.example.ini; used when it is omitted or the first
rem                  argument starts with "-":
rem                    start-llama            start-llama --here
rem                  Otherwise an ini in llama-server --models-preset format. A
rem                  bare name is also looked up in local\ and next to this script,
rem                  and the ".ini" can be left off:  start-llama other-preset
rem    --here        run in this window instead of opening a new one
rem    --dry-run     print the command line and exit
rem    extra args    passed to llama-server AFTER the defaults, so they win:
rem                  start-llama models.ini --models-max 2 --port 8080
rem
rem  Defaults: --host 127.0.0.1 --port 9931. Models auto-unload: with
rem  LLAMA_MODELS_MEMORY_MARGIN set, --models-memory-margin N --models-max 0 (evict
rem  least-recently-used models by memory); without it, --models-max 1 (one model
rem  at a time; requesting another swaps it in).
rem  Override with env vars LLAMA_HOST / LLAMA_PORT / LLAMA_MODELS_MAX /
rem  LLAMA_MODELS_MEMORY_MARGIN, per session or in local\env.cmd.
rem
rem  Model settings (ngl, fa, load-mode, spec-type, ...) belong in the ini, not
rem  here. Presets are only validated when the first request spawns the model,
rem  so send one request after editing an ini.
rem ===========================================================================
setlocal EnableExtensions DisableDelayedExpansion

if /i "%~1"=="-h"     goto :usage
if /i "%~1"=="--help" goto :usage
if "%~1"=="/?"     goto :usage

rem ---- machine defaults -----------------------------------------------------
rem local\env.cmd (optional) runs first, so it can set any LLAMA_* variable,
rem LLAMA_PRESET included; session env vars win when it only sets variables that
rem are "not defined". start-llama.sh sources local/env.sh at the same point.
if exist "%~dp0local\env.cmd" call "%~dp0local\env.cmd"

rem ---- resolve the ini ------------------------------------------------------
rem No first argument, or a first argument that is an option (starts with "-"):
rem use the default preset, and keep the argument as an option. Default, first
rem found: %LLAMA_PRESET%, local\models.ini (your private repo),
rem models.example.ini (the public sample). A set LLAMA_PRESET that does not
rem exist is an error, never a silent fallback.
set "DEFAULT_INI="
if defined LLAMA_PRESET set "DEFAULT_INI=%LLAMA_PRESET%"
if not defined DEFAULT_INI if exist "%~dp0local\models.ini" set "DEFAULT_INI=%~dp0local\models.ini"
if not defined DEFAULT_INI if exist "%~dp0models.example.ini" set "DEFAULT_INI=%~dp0models.example.ini"
if not defined DEFAULT_INI set "DEFAULT_INI=%~dp0local\models.ini"
set "FIRST=%~1"
set "KEEPFIRST="
if "%FIRST%"=="" (
    set "INI=%DEFAULT_INI%"
) else if "%FIRST:~0,1%"=="-" (
    set "INI=%DEFAULT_INI%"
    set "KEEPFIRST=1"
) else (
    rem First FILE that matches wins; folders are skipped (a bare "models" must
    rem find local\models.ini, not the models\ weights folder).
    set "INI="
    call :tryini "%FIRST%"
    call :tryini "%~dp0local\%FIRST%.ini"
    call :tryini "%~dp0local\%FIRST%"
    call :tryini "%~dp0%FIRST%.ini"
    call :tryini "%~dp0%FIRST%"
)
if not defined INI set "INI=%FIRST%"
rem a folder is never a preset (exist "x\*" is true only for folders)
if exist "%INI%\*" (
    echo [start-llama] ERROR: %INI% is a folder, not a preset .ini
    exit /b 1
)
if not exist "%INI%" (
    echo [start-llama] ERROR: preset not found: %INI%
    echo                   Copy models.example.ini to local\models.ini and edit it,
    echo                   or pass a preset path / set LLAMA_PRESET.
    exit /b 1
)
for %%F in ("%INI%") do (
    set "INI=%%~fF"
    set "NAME=%%~nF"
)

rem ---- defaults (env overrides) ---------------------------------------------
if not defined LLAMA_HOST       set "LLAMA_HOST=127.0.0.1"
if not defined LLAMA_PORT       set "LLAMA_PORT=9931"
rem Auto-unload needs a limit: llama-server's own margin default is 0 (disabled).
rem With a memory margin, evict by memory (no count limit); without one, keep one
rem model at a time, so requesting another one swaps it in.
if not defined LLAMA_MODELS_MAX if defined LLAMA_MODELS_MEMORY_MARGIN set "LLAMA_MODELS_MAX=0"
if not defined LLAMA_MODELS_MAX set "LLAMA_MODELS_MAX=1"
rem The memory margin (MiB kept free; the router unloads least-recently-used
rem models until a new one fits) depends on the machine, so there is no default
rem here: without LLAMA_MODELS_MEMORY_MARGIN, llama-server's own default applies.
rem Set it to (GPU memory heap MiB - the budget you want for models), e.g. in
rem local\env.cmd (called above).
set "MARGIN_ARG="
if defined LLAMA_MODELS_MEMORY_MARGIN set "MARGIN_ARG= --models-memory-margin %LLAMA_MODELS_MEMORY_MARGIN%"

rem ---- remaining args -------------------------------------------------------
set "HERE="
set "DRY="
set "EXTRA="
if defined KEEPFIRST goto :argloop
:args
shift
:argloop
if "%~1"=="" goto :argsdone
if /i "%~1"=="--here"    set "HERE=1" & goto :args
if /i "%~1"=="--dry-run" set "DRY=1"  & goto :args
set "EXTRA=%EXTRA% %1"
goto :args
:argsdone

set CMDLINE=llama-server --models-preset "%INI%" --host %LLAMA_HOST% --port %LLAMA_PORT% --models-max %LLAMA_MODELS_MAX%%MARGIN_ARG%%EXTRA%

if defined DRY (
    echo %CMDLINE%
    exit /b 0
)

rem ---- sanity checks --------------------------------------------------------
where llama-server >nul 2>&1 || (
    echo [start-llama] ERROR: llama-server not on PATH. winget install ggml.llamacpp
    exit /b 1
)
netstat -ano -p TCP | findstr /r /c:":%LLAMA_PORT% .*LISTENING" >nul && (
    echo [start-llama] ERROR: port %LLAMA_PORT% is already in use - is a server already running?
    echo                   Stop it, or pass --port N / set LLAMA_PORT=N.
    exit /b 1
)

echo [start-llama] %CMDLINE%
if defined HERE (
    %CMDLINE%
    exit /b %errorlevel%
)
rem New window via "cmd /k" so it STAYS OPEN if llama-server exits or fails to start,
rem and you can still read the error. Close it with Ctrl+C then "exit", or the X button.
start "llama: %NAME% (:%LLAMA_PORT%)" cmd /k %CMDLINE%
exit /b 0

:tryini
rem Set INI to %1 if INI is still unset and %1 is an existing file (not a folder).
if defined INI exit /b 0
if exist "%~1" if not exist "%~1\*" set "INI=%~1"
exit /b 0

:usage
echo Usage: %~nx0 [preset.ini] [--here] [--dry-run] [extra llama-server args...]
echo.
echo   preset.ini is optional: with none (or when the first argument starts with "-")
echo   it uses %%LLAMA_PRESET%%, else local\models.ini, else models.example.ini.
echo     %~nx0              new window, default preset
echo     %~nx0 --here       run in this window
echo     %~nx0 --dry-run    just print the command
echo.
echo   Starts llama-server --models-preset ^<ini^> --host %%LLAMA_HOST%% --port %%LLAMA_PORT%%
echo   --models-max %%LLAMA_MODELS_MAX%% --models-memory-margin %%LLAMA_MODELS_MEMORY_MARGIN%%
echo   (defaults 127.0.0.1 / 9931; models-max 0 with a margin set, e.g. in local\env.cmd,
echo   else 1 = one model at a time, swapped on request).
echo   Extra args come last and override the defaults.
echo.
echo   Presets found:
for %%I in ("%~dp0local\*.ini" "%~dp0*.ini") do echo     %%~nxI
exit /b 0
