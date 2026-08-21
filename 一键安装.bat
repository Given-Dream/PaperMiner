@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "INSTALL_EXIT_CODE=0"

echo ========================================
echo PaperMiner - One-Click Installer
echo ========================================
echo.

cd /d "%~dp0"
set "ENV_NAME=MinerU"

:: ----------------------------------------
:: Find Conda
:: ----------------------------------------
set "CONDA_BAT="
set "CONDA_TEST="
for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
    if not defined CONDA_TEST set "CONDA_TEST=%%~fI"
)
if defined CONDA_TEST (
    for %%F in ("!CONDA_TEST!") do (
        for %%R in ("%%~dpF..") do set "CONDA_BAT=%%~fR\condabin\conda.bat"
    )
)

if not defined CONDA_BAT (
    for %%P in (
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\Miniconda3"
        "%USERPROFILE%\Anaconda3"
        "C:\ProgramData\miniconda3"
        "C:\ProgramData\anaconda3"
        "C:\ProgramData\Miniconda3"
        "C:\ProgramData\Anaconda3"
        "%LOCALAPPDATA%\miniconda3"
        "%LOCALAPPDATA%\anaconda3"
        "D:\miniconda3"
        "D:\anaconda3"
        "D:\Miniconda3"
        "D:\Anaconda3"
        "E:\miniconda3"
        "E:\anaconda3"
        "E:\Miniconda3"
        "E:\Anaconda3"
        "D:\soft\%USERNAME%\miniconda3"
        "D:\soft\%USERNAME%\anaconda3"
        "E:\soft\%USERNAME%\miniconda3"
        "E:\soft\%USERNAME%\anaconda3"
        "D:\soft\admin\miniconda3"
        "D:\soft\admin\anaconda3"
        "E:\soft\admin\miniconda3"
        "E:\soft\admin\anaconda3"
    ) do (
        if exist "%%~P\condabin\conda.bat" (
            set "CONDA_BAT=%%~P\condabin\conda.bat"
        )
    )
)

:: Still not found? Let user input manually
:conda_manual
if not defined CONDA_BAT (
    if /i "%PAPERMINER_SETUP_MODE%"=="1" (
        echo [ERROR] Conda was not found automatically.
        echo Close Setup and make Conda available, then run Setup.exe again.
        goto :failed
    )
    echo [WARNING] Conda not found automatically.
    echo.
    echo If Conda is installed, please enter the path.
    echo Example: D:\Anaconda3  or  C:\Users\YourName\miniconda3
    echo.
    echo Enter "q" to quit.
    echo.
    set /p "CONDA_INPUT=Conda install path: "
    if /i "!CONDA_INPUT!"=="q" goto :done
    if "!CONDA_INPUT!"=="" goto :done
    if exist "!CONDA_INPUT!\condabin\conda.bat" (
        set "CONDA_BAT=!CONDA_INPUT!\condabin\conda.bat"
    ) else (
        echo.
        echo   conda.bat not found at: !CONDA_INPUT!\condabin\conda.bat
        echo   Please check the path and try again.
        echo.
        set "CONDA_BAT="
        goto :conda_manual
    )
)

if not defined CONDA_BAT (
    echo.
    echo Conda not found. Please install Miniconda first:
    echo   https://docs.conda.io/en/latest/miniconda.html
    echo.
    goto :failed
)

echo Found Conda: %CONDA_BAT%
echo.

:: ----------------------------------------
:: Find environment
:: ----------------------------------------
set "ENV_PATH=%PAPERMINER_ENV_PATH%"
if not defined ENV_PATH (
    for /f "tokens=1,2*" %%a in ('call "%CONDA_BAT%" env list 2^>nul ^| findstr /C:"%ENV_NAME%"') do (
        if "%%a"=="%ENV_NAME%" (
            if "%%b"=="*" (
                set "ENV_PATH=%%c"
            ) else (
                set "ENV_PATH=%%b"
            )
        )
    )
)

if not defined ENV_PATH goto :create_env
set "PYTHON_EXE=%ENV_PATH%\python.exe"
if not exist "%PYTHON_EXE%" goto :create_env

:: Setup PATH and env vars BEFORE checking imports (torch needs DLLs in PATH)
set "PATH=%ENV_PATH%;%ENV_PATH%\Scripts;%ENV_PATH%\Library\bin;%ENV_PATH%\Library\usr\bin;%PATH%"
set "KMP_DUPLICATE_LIB_OK=TRUE"
set "OMP_NUM_THREADS=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"

:: ----------------------------------------
:: Quick check: already installed?
:: ----------------------------------------
echo Checking existing installation...
"%PYTHON_EXE%" -m pip show mineru torch pandas ttkbootstrap >nul 2>nul
if not !errorlevel!==0 goto :install_deps
"%PYTHON_EXE%" -c "import importlib.metadata as m; v=tuple(int(x) for x in m.version('ttkbootstrap').split('.')[:3]); raise SystemExit(0 if (2,2,2) <= v < (3,0,0) else 1)" >nul 2>nul
if not !errorlevel!==0 goto :install_deps

echo.
echo ========================================
echo Already installed!
echo ========================================
echo.
echo   Conda env: %ENV_NAME%
echo   Python:    %PYTHON_EXE%
echo.
echo All core dependencies are present.
echo.
if /i "%PAPERMINER_SETUP_MODE%"=="1" (
    echo Setup mode will keep the existing environment and finish configuration.
    goto :configure
)
set /p "FORCE_REINSTALL=Reinstall? (y/N): "
if /i "!FORCE_REINSTALL!"=="y" goto :install_deps
echo.
echo No reinstall needed.
echo Use the launcher script to start PaperMiner.
goto :done

:: ----------------------------------------
:: Create environment
:: ----------------------------------------
:create_env
echo.
echo [Step 1] Creating %ENV_NAME% environment (Python 3.12)...
echo This may take a few minutes...
echo.
call "%CONDA_BAT%" create -n %ENV_NAME% python=3.12 -y
if errorlevel 1 (
    echo [ERROR] Failed to create environment!
    goto :failed
)

for /f "tokens=1,2*" %%a in ('call "%CONDA_BAT%" env list 2^>nul ^| findstr /C:"%ENV_NAME%"') do (
    if "%%a"=="%ENV_NAME%" set "ENV_PATH=%%b"
)
set "PYTHON_EXE=%ENV_PATH%\python.exe"

:: ----------------------------------------
:: Install dependencies
:: ----------------------------------------
:install_deps
:: Ensure PATH is set (needed when jumping here from :create_env)
if not defined PYTHONIOENCODING (
    set "PATH=%ENV_PATH%;%ENV_PATH%\Scripts;%ENV_PATH%\Library\bin;%ENV_PATH%\Library\usr\bin;%PATH%"
    set "KMP_DUPLICATE_LIB_OK=TRUE"
    set "OMP_NUM_THREADS=1"
    set "PYTHONIOENCODING=utf-8"
    set "PYTHONNOUSERSITE=1"
)

:: Force pip to install into conda env, not user site-packages
:: Force pip to install into the Conda environment, even if pip user config says --user.
set "PIP_USER=0"
set "PIP_NO_USER=1"
set "PIP_CMD=%PYTHON_EXE% -m pip"

:: Check write permission to conda env directory
echo __test__ > "%ENV_PATH%\__permtest__" 2>nul
if exist "%ENV_PATH%\__permtest__" (
    del "%ENV_PATH%\__permtest__" >nul 2>nul
) else (
    echo.
    echo ========================================
    echo [WARNING] No write permission!
    echo ========================================
    echo   Conda env is at: %ENV_PATH%
    echo   This script cannot install packages there.
    echo.
    echo   Please RIGHT-CLICK this script and
    echo   select "Run as administrator", then try again.
    echo.
    goto :failed
)

:: ----------------------------------------
:: PyTorch
:: ----------------------------------------
echo.
echo [Step 2] Detecting GPU and CUDA driver...
set "HAS_GPU=0"
set "CUDA_VER="
set "DRIVER_VER="
set "NVIDIA_SMI="

:: Resolve nvidia-smi explicitly. A GUI-launched batch can have a reduced PATH.
for /f "delims=" %%s in ('where nvidia-smi.exe 2^>nul') do if not defined NVIDIA_SMI set "NVIDIA_SMI=%%s"
if not defined NVIDIA_SMI if exist "%SystemRoot%\System32\nvidia-smi.exe" set "NVIDIA_SMI=%SystemRoot%\System32\nvidia-smi.exe"

:: Write the result first to avoid FOR /F corrupting nvidia-smi arguments.
set "GPU_DETECT_FILE=%TEMP%\paperminer_gpu_%RANDOM%_%RANDOM%.txt"
if defined NVIDIA_SMI "%NVIDIA_SMI%" --query-gpu=driver_version --format="csv,noheader,nounits" >"%GPU_DETECT_FILE%" 2>nul
if exist "%GPU_DETECT_FILE%" (
    for /f "usebackq tokens=1" %%v in ("%GPU_DETECT_FILE%") do (
        for /f "tokens=1 delims=." %%m in ("%%v") do (
            echo %%m| findstr /r /x "[0-9][0-9]*" >nul
            if !errorlevel!==0 if not defined DRIVER_VER (
                set "DRIVER_VER=%%v"
                set "HAS_GPU=1"
            )
        )
    )
    del "%GPU_DETECT_FILE%" >nul 2>nul
)

:: Determine best CUDA version based on driver
:: Driver >= 560 -> cu126, >= 525 -> cu121, >= 520 -> cu118, else CPU
set "CUDA_INDEX="
if "!HAS_GPU!"=="1" (
    echo   NVIDIA GPU detected, driver version: !DRIVER_VER!
    set "DRIVER_MAJOR=0"
    for /f "tokens=1 delims=." %%m in ("!DRIVER_VER!") do set /a DRIVER_MAJOR=%%m
    if !DRIVER_MAJOR! GEQ 560 (
        set "CUDA_INDEX=cu126"
    ) else if !DRIVER_MAJOR! GEQ 525 (
        set "CUDA_INDEX=cu121"
    ) else if !DRIVER_MAJOR! GEQ 520 (
        set "CUDA_INDEX=cu118"
    ) else (
        set "CUDA_INDEX=cpu"
    )
    if "!CUDA_INDEX!"=="cpu" (
        echo   Driver version too old for CUDA PyTorch, will use CPU version.
        set "HAS_GPU=0"
    ) else (
        echo   Selected PyTorch CUDA version: !CUDA_INDEX!
    )
) else (
    if defined NVIDIA_SMI (echo   nvidia-smi found, but no GPU was reported.) else (echo   nvidia-smi.exe not found; check the NVIDIA driver installation.)
    echo   No NVIDIA GPU detected, will use CPU version.
    set "CUDA_INDEX=cpu"
)

:: Check if torch is already installed AND matches GPU status
set "TORCH_OK=0"
"%PYTHON_EXE%" -m pip show torch >nul 2>nul
if !errorlevel!==0 (
    if "!HAS_GPU!"=="1" (
        :: GPU present: check if installed torch has CUDA support
        "%PYTHON_EXE%" -c "import torch;exit(0 if torch.cuda.is_available() else 1)" 2>nul
        if !errorlevel!==0 (
            set "TORCH_OK=1"
            echo   PyTorch with CUDA already installed and working, skipping.
        ) else (
            echo   PyTorch installed but CUDA not available - will reinstall.
            %PIP_CMD% uninstall torch torchvision torchaudio -y >nul 2>nul
        )
    ) else (
        :: No GPU: any torch is fine
        set "TORCH_OK=1"
        echo   PyTorch already installed, skipping.
    )
)

if "!TORCH_OK!"=="1" goto :install_mineru

if "!HAS_GPU!"=="1" (
    echo.
    echo   Installing CUDA version of PyTorch [!CUDA_INDEX!]...
    echo   NOTE: Must download from official PyTorch source (~2.5GB^)
    echo.
    %PIP_CMD% install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/!CUDA_INDEX!

    :: Verify CUDA actually works after installation
    echo.
    echo   Verifying PyTorch CUDA support...
    "%PYTHON_EXE%" -c "import torch;cuda_ok=torch.cuda.is_available();name=torch.cuda.get_device_name(0) if cuda_ok else '';print(f'GPU: {name}' if cuda_ok else 'FAIL')" 2>nul | findstr "GPU:" >nul
    if !errorlevel!==0 (
        echo   PyTorch CUDA verification passed!
        for /f "tokens=*" %%g in ('"%PYTHON_EXE%" -c "import torch;print(torch.cuda.get_device_name(0))" 2^>nul') do (
            echo   GPU device: %%g
        )
    ) else (
        echo.
        echo   [WARNING] CUDA verification failed!
        echo   Your GPU driver (v!DRIVER_VER!^) may not fully support !CUDA_INDEX!.
        echo   Falling back to CPU version...
        echo.
        %PIP_CMD% uninstall torch torchvision torchaudio -y >nul 2>nul
        %PIP_CMD% install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
        echo.
        echo   CPU version installed. PDF processing will still work,
        echo   but will be slower without GPU acceleration.
    )
) else (
    echo.
    echo   Installing CPU version of PyTorch...
    echo.
    %PIP_CMD% install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
)

:: ----------------------------------------
:: MinerU
:: ----------------------------------------
:install_mineru
echo.
"%PYTHON_EXE%" -m pip show mineru >nul 2>nul
if !errorlevel!==0 (
    echo [Step 3] MinerU already installed, skipping.
    goto :install_other
)

echo [Step 3] Installing MinerU (>=3.1.0)...
%PIP_CMD% install -U "mineru[core]>=3.1.0,<4.0"
if errorlevel 1 (
    echo [WARNING] MinerU install may have issues. Continue anyway...
)

:: ----------------------------------------
:: Other dependencies
:: ----------------------------------------
:install_other
echo.
echo [Step 4] Installing other dependencies...
if exist "packages\ttkbootstrap-2.2.2-py3-none-any.whl" (
    echo   Installing bundled ttkbootstrap 2.2.2 UI package...
    %PIP_CMD% install --upgrade "packages\ttkbootstrap-2.2.2-py3-none-any.whl"
)
if exist "requirements.txt" (
    %PIP_CMD% install -r requirements.txt
) else (
    %PIP_CMD% install "ttkbootstrap>=2.2.2,<3.0" pandas openpyxl beautifulsoup4 python-docx lxml requests python-dotenv
)

:: ----------------------------------------
:: Model source configuration (MinerU 3.0+)
:: ----------------------------------------
echo.
echo [Step 5] Configuring model source...
echo.
echo   MinerU 3.0+ auto-downloads models on first run.
echo   Select default model source:
echo     1. ModelScope (recommended for China)
echo     2. HuggingFace (international)
echo.
if /i "%PAPERMINER_SETUP_MODE%"=="1" (
    set "MODEL_SOURCE=1"
    echo   Setup mode selected ModelScope automatically.
) else (
    set /p "MODEL_SOURCE=  Enter choice (1/2, default 1): "
)
if "!MODEL_SOURCE!"=="2" (
    set "SELECTED_SOURCE=huggingface"
) else (
    set "SELECTED_SOURCE=modelscope"
)
echo   Model source set to: !SELECTED_SOURCE!
echo   (Models will auto-download on first run)

:: ----------------------------------------
:: Configure
:: ----------------------------------------
:configure
echo.
echo [Step 6] Configuring environment...

echo   Verifying the complete runtime...
"%PYTHON_EXE%" "scripts\verify_runtime.py"
if errorlevel 1 (
    echo [ERROR] Runtime verification failed. Review the package installation output above.
    goto :failed
)
echo   Runtime verification passed

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo   Created .env config file
    )
)

if not exist "input" mkdir "input"
if not exist "output" mkdir "output"
if not exist "output\raw" mkdir "output\raw"
if not exist "output\extract" mkdir "output\extract"
echo   Directory structure ready

:: Setup.exe owns shortcut creation.  In setup mode, do not create the
:: legacy run.bat shortcut and do not launch the application.
if /i "%PAPERMINER_SETUP_MODE%"=="1" goto :install_done

echo.
set /p "CREATE_SHORTCUT=Create desktop shortcut? (Y/n): "
if /i "!CREATE_SHORTCUT!"=="n" goto :install_done

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$sc=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\PaperMiner.lnk');$sc.TargetPath='%~dp0run.bat';$sc.WorkingDirectory='%~dp0';$sc.Description='PaperMiner';$sc.Save()" 2>nul
if exist "%USERPROFILE%\Desktop\PaperMiner.lnk" (
    echo   Desktop shortcut created!
) else (
    echo   Shortcut creation failed, please create manually.
)

:install_done
echo.
echo ========================================
echo Installation complete!
echo ========================================
echo.
echo Usage:
echo   1. Put PDF files in the "input" folder
echo   2. Start PaperMiner.exe or use the desktop shortcut
echo   3. Select options and click Start
echo.
echo Optional: Configure DeepSeek API Key in
echo   app Settings to improve section extraction.
echo   Get API Key: https://platform.deepseek.com/
echo.
goto :done

:failed
set "INSTALL_EXIT_CODE=1"

:done
echo.
if /i "%PAPERMINER_SETUP_MODE%"=="1" exit /b %INSTALL_EXIT_CODE%
pause
exit /b %INSTALL_EXIT_CODE%
