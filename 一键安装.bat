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
set "CONDA_BAT=%PAPERMINER_CONDA_COMMAND%"
if defined CONDA_BAT if not exist "%CONDA_BAT%" set "CONDA_BAT="
if not defined CONDA_BAT if defined PAPERMINER_CONDA_ROOT (
    if exist "%PAPERMINER_CONDA_ROOT%\condabin\conda.bat" set "CONDA_BAT=%PAPERMINER_CONDA_ROOT%\condabin\conda.bat"
    if not defined CONDA_BAT if exist "%PAPERMINER_CONDA_ROOT%\Scripts\conda.exe" set "CONDA_BAT=%PAPERMINER_CONDA_ROOT%\Scripts\conda.exe"
)
set "CONDA_TEST="
if not defined CONDA_BAT (
    for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
        if not defined CONDA_TEST set "CONDA_TEST=%%~fI"
    )
    if defined CONDA_TEST (
        for %%F in ("!CONDA_TEST!") do (
            for %%R in ("%%~dpF..") do set "CONDA_BAT=%%~fR\condabin\conda.bat"
        )
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
        echo [ERROR] Setup did not provide a usable Conda command.
        echo Review the earlier automatic Anaconda bootstrap messages.
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
"%PYTHON_EXE%" -m pip show mineru torch pandas ttkbootstrap pypdf >nul 2>nul
if not !errorlevel!==0 goto :install_deps
"%PYTHON_EXE%" -c "import importlib.metadata as m,re; p=[int(x) for x in re.findall(r'\d+',m.version('mineru'))[:2]]; raise SystemExit(0 if tuple(p)>=(3,1) and tuple(p)<(4,0) else 1)" >nul 2>nul
if not !errorlevel!==0 goto :install_deps
"%PYTHON_EXE%" -c "import importlib.metadata as m; v=tuple(int(x) for x in m.version('ttkbootstrap').split('.')[:3]); raise SystemExit(0 if (2,2,2) <= v < (3,0,0) else 1)" >nul 2>nul
if not !errorlevel!==0 goto :install_deps
if not exist "scripts\torch_runtime_policy.py" goto :install_deps
"%PYTHON_EXE%" "scripts\torch_runtime_policy.py" verify-auto --quiet >nul 2>nul
if not !errorlevel!==0 (
    echo Existing PyTorch does not match this GPU or failed a real CUDA kernel test.
    echo Setup will replace the incompatible wheel instead of keeping it.
    goto :install_deps
)

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
echo Using conda-forge with --override-channels to avoid unaccepted Anaconda default-channel terms.
if defined ENV_PATH (
    call "%CONDA_BAT%" create --prefix "%ENV_PATH%" --override-channels -c conda-forge python=3.12 -y
) else (
    call "%CONDA_BAT%" create -n %ENV_NAME% --override-channels -c conda-forge python=3.12 -y
)
if errorlevel 1 (
    echo [ERROR] Failed to create environment!
    goto :failed
)

if not defined ENV_PATH (
    for /f "tokens=1,2*" %%a in ('call "%CONDA_BAT%" env list 2^>nul ^| findstr /C:"%ENV_NAME%"') do (
        if "%%a"=="%ENV_NAME%" set "ENV_PATH=%%b"
    )
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
set PIP_CMD="%PYTHON_EXE%" -m pip --isolated
set "PIP_INDEX_URL=https://pypi.org/simple"
set "PIP_SOURCE_NAME=PyPI official (fallback)"
set "PIP_PROBE_MIBPS=0"
set "PIP_SOURCE_FILE=%TEMP%\paperminer_pip_source_%RANDOM%_%RANDOM%.txt"
if exist "scripts\select_pip_source.py" (
    "%PYTHON_EXE%" "scripts\select_pip_source.py" --output "!PIP_SOURCE_FILE!"
    if exist "!PIP_SOURCE_FILE!" (
        for /f "usebackq tokens=1,* delims==" %%a in ("!PIP_SOURCE_FILE!") do (
            if /i "%%a"=="PIP_SOURCE_NAME" set "PIP_SOURCE_NAME=%%b"
            if /i "%%a"=="PIP_INDEX_URL" set "PIP_INDEX_URL=%%b"
            if /i "%%a"=="PIP_PROBE_MIBPS" set "PIP_PROBE_MIBPS=%%b"
        )
        del "!PIP_SOURCE_FILE!" >nul 2>nul
    )
) else (
    echo [WARNING] PyPI source selector is missing; using official PyPI.
)
set "PIP_COMMON_ARGS=--index-url !PIP_INDEX_URL! --timeout 60 --retries 4 --prefer-binary"
set "PIP_OFFICIAL_ARGS=--index-url https://pypi.org/simple --timeout 90 --retries 5 --prefer-binary"
echo   General Python package source: !PIP_SOURCE_NAME! [!PIP_INDEX_URL!]
echo   Probe speed: !PIP_PROBE_MIBPS! MiB/s

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
set "GPU_NAME="
set "GPU_COUNT=0"

:: Resolve nvidia-smi explicitly. A GUI-launched batch can have a reduced PATH.
for /f "delims=" %%s in ('where nvidia-smi.exe 2^>nul') do if not defined NVIDIA_SMI set "NVIDIA_SMI=%%s"
if not defined NVIDIA_SMI if exist "%SystemRoot%\System32\nvidia-smi.exe" set "NVIDIA_SMI=%SystemRoot%\System32\nvidia-smi.exe"

:: Write the result first to avoid FOR /F corrupting nvidia-smi arguments.
set "GPU_DETECT_FILE=%TEMP%\paperminer_gpu_%RANDOM%_%RANDOM%.txt"
if defined NVIDIA_SMI "%NVIDIA_SMI%" --query-gpu=index,name,driver_version,memory.total --format="csv,noheader,nounits" >"%GPU_DETECT_FILE%" 2>nul
if exist "%GPU_DETECT_FILE%" (
    for /f "usebackq tokens=1,2,3,4 delims=," %%i in ("%GPU_DETECT_FILE%") do (
        set /a GPU_COUNT+=1
        echo   GPU %%i: %%j, memory %%l MiB, driver %%k
        if not defined DRIVER_VER (
            set "GPU_NAME=%%j"
            set "DRIVER_VER=%%k"
            for /f "tokens=*" %%v in ("!GPU_NAME!") do set "GPU_NAME=%%v"
            for /f "tokens=*" %%v in ("!DRIVER_VER!") do set "DRIVER_VER=%%v"
            set "HAS_GPU=1"
        )
    )
    del "%GPU_DETECT_FILE%" >nul 2>nul
)

if "!HAS_GPU!"=="0" (
    set "NVIDIA_ADAPTER_FILE=%TEMP%\paperminer_nvidia_adapter_%RANDOM%_%RANDOM%.txt"
    powershell.exe -NoProfile -Command "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'NVIDIA' } | Select-Object -ExpandProperty Name" >"!NVIDIA_ADAPTER_FILE!" 2>nul
    if exist "!NVIDIA_ADAPTER_FILE!" (
        for /f "usebackq delims=" %%g in ("!NVIDIA_ADAPTER_FILE!") do if not defined GPU_NAME set "GPU_NAME=%%g"
        del "!NVIDIA_ADAPTER_FILE!" >nul 2>nul
    )
)

:: Resolve architecture-aware wheel policy. This distinguishes Blackwell/RTX 50
:: from older GPUs; driver-only selection can incorrectly install cu126 for sm_120.
set "POLICY_CUDA_INDEX="
set "POLICY_TORCH_PACKAGE_SPEC="
set "POLICY_REASON="
set "POLICY_BLACKWELL_PRESENT=0"
set "POLICY_GPU_FAMILIES="
set "POLICY_MINIMUM_DRIVER="
set "POLICY_FORCE_CPU_REPAIR=0"
set "POLICY_GPU_COUNT="
set "POLICY_GPU_NAME="
set "POLICY_DRIVER_VER="
set "GPU_POLICY_FILE=%TEMP%\paperminer_torch_policy_%RANDOM%_%RANDOM%.txt"
if exist "scripts\torch_runtime_policy.py" (
    if defined NVIDIA_SMI (
        "%PYTHON_EXE%" "scripts\torch_runtime_policy.py" select --nvidia-smi "!NVIDIA_SMI!" >"!GPU_POLICY_FILE!" 2>nul
    ) else (
        "%PYTHON_EXE%" "scripts\torch_runtime_policy.py" select >"!GPU_POLICY_FILE!" 2>nul
    )
    if !errorlevel!==0 if exist "!GPU_POLICY_FILE!" (
        for /f "usebackq tokens=1,* delims==" %%a in ("!GPU_POLICY_FILE!") do (
            if /i "%%a"=="GPU_COUNT" set "POLICY_GPU_COUNT=%%b"
            if /i "%%a"=="GPU_NAME" set "POLICY_GPU_NAME=%%b"
            if /i "%%a"=="DRIVER_VER" set "POLICY_DRIVER_VER=%%b"
            if /i "%%a"=="BLACKWELL_PRESENT" set "POLICY_BLACKWELL_PRESENT=%%b"
            if /i "%%a"=="GPU_FAMILIES" set "POLICY_GPU_FAMILIES=%%b"
            if /i "%%a"=="MINIMUM_DRIVER" set "POLICY_MINIMUM_DRIVER=%%b"
            if /i "%%a"=="CUDA_INDEX" set "POLICY_CUDA_INDEX=%%b"
            if /i "%%a"=="TORCH_PACKAGE_SPEC" set "POLICY_TORCH_PACKAGE_SPEC=%%b"
            if /i "%%a"=="POLICY_REASON" set "POLICY_REASON=%%b"
        )
    )
)
if exist "!GPU_POLICY_FILE!" del "!GPU_POLICY_FILE!" >nul 2>nul
if defined POLICY_GPU_COUNT if not "!POLICY_GPU_COUNT!"=="0" (
    set "HAS_GPU=1"
    set "GPU_COUNT=!POLICY_GPU_COUNT!"
    if defined POLICY_GPU_NAME set "GPU_NAME=!POLICY_GPU_NAME!"
    if defined POLICY_DRIVER_VER set "DRIVER_VER=!POLICY_DRIVER_VER!"
)

:: Determine best CUDA version based on architecture and driver. The legacy
:: driver-only branch is retained only if the policy helper cannot run.
set "CUDA_INDEX="
set "TORCH_PACKAGE_SPEC=torch torchvision torchaudio"
if "!HAS_GPU!"=="1" (
    echo   NVIDIA CUDA environment detected: !GPU_COUNT! GPU^(s^), driver !DRIVER_VER!
    set "DRIVER_MAJOR=0"
    for /f "tokens=1 delims=." %%m in ("!DRIVER_VER!") do set /a DRIVER_MAJOR=%%m
    if defined POLICY_CUDA_INDEX (
        set "CUDA_INDEX=!POLICY_CUDA_INDEX!"
        if defined POLICY_TORCH_PACKAGE_SPEC set "TORCH_PACKAGE_SPEC=!POLICY_TORCH_PACKAGE_SPEC!"
        if defined POLICY_GPU_FAMILIES echo   GPU generation: !POLICY_GPU_FAMILIES!
        echo   Architecture policy: !POLICY_REASON!
        if defined POLICY_MINIMUM_DRIVER echo   Driver baseline for this policy: !POLICY_MINIMUM_DRIVER!
    ) else (
        if !DRIVER_MAJOR! GEQ 561 (
            set "CUDA_INDEX=cu126"
        ) else if !DRIVER_MAJOR! GEQ 532 (
            set "CUDA_INDEX=cu121"
        ) else if !DRIVER_MAJOR! GEQ 521 (
            set "CUDA_INDEX=cu118"
        ) else (
            set "CUDA_INDEX=cpu"
        )
    )
    if "!CUDA_INDEX!"=="cpu" (
        if defined POLICY_GPU_COUNT if not "!POLICY_GPU_COUNT!"=="0" set "POLICY_FORCE_CPU_REPAIR=1"
        echo   [NOTICE] Driver/GPU combination cannot use a supported CUDA wheel.
        echo   Setup will replace any incompatible CUDA PyTorch build with the CPU build.
        if defined POLICY_MINIMUM_DRIVER echo   Update the NVIDIA driver to !POLICY_MINIMUM_DRIVER! or newer, then run Repair to enable GPU.
        set "HAS_GPU=0"
    ) else (
        echo   Selected PyTorch CUDA version: !CUDA_INDEX!
        if "!POLICY_BLACKWELL_PRESENT!"=="1" echo   Blackwell/RTX 50 compatibility mode is active.
        echo   Standalone CUDA Toolkit and cuDNN are not required for this binary installation.
        echo   The official PyTorch wheel supplies the matching CUDA user-mode runtime and cuDNN.
    )
) else (
    if defined GPU_NAME (
        echo   NVIDIA display adapter found: !GPU_NAME!
        echo   The NVIDIA driver or nvidia-smi is not ready. PaperMiner will install CPU PyTorch for now.
        echo   Install or update the driver from: https://www.nvidia.com/Download/index.aspx
        echo   Then run PaperMiner repair to switch to CUDA acceleration.
    ) else if defined NVIDIA_SMI (
        echo   nvidia-smi found, but no CUDA-capable GPU was reported.
    ) else (
        echo   No NVIDIA adapter with a usable driver was found.
    )
    echo   No NVIDIA GPU detected, will use CPU version.
    set "CUDA_INDEX=cpu"
)

:: Check if torch is already installed AND matches GPU status
set "TORCH_OK=0"
"%PYTHON_EXE%" -m pip show torch >nul 2>nul
if !errorlevel!==0 (
    if "!HAS_GPU!"=="1" (
        :: A CUDA-visible device is not enough. Verify the wheel family and run
        :: float32/float16 kernels on every device before keeping this install.
        set "EXISTING_TORCH_VERIFY_FILE=%TEMP%\paperminer_existing_torch_%RANDOM%_%RANDOM%.txt"
        if exist "scripts\torch_runtime_policy.py" (
            "%PYTHON_EXE%" "scripts\torch_runtime_policy.py" verify --expected "!CUDA_INDEX!" >"!EXISTING_TORCH_VERIFY_FILE!" 2>&1
        ) else (
            "%PYTHON_EXE%" -c "import torch; assert torch.cuda.is_available(); [(torch.arange(1,17,device=f'cuda:{i}').to(torch.float16).mul(2).sum().item(),torch.cuda.synchronize(i)) for i in range(torch.cuda.device_count())]" >"!EXISTING_TORCH_VERIFY_FILE!" 2>&1
        )
        set "EXISTING_TORCH_VERIFY_EXIT=!errorlevel!"
        if "!EXISTING_TORCH_VERIFY_EXIT!"=="0" (
            set "TORCH_OK=1"
            echo   PyTorch wheel matches !CUDA_INDEX! and real CUDA kernels passed; skipping.
        ) else (
            echo   Existing PyTorch is incompatible with the detected GPU policy.
            if exist "!EXISTING_TORCH_VERIFY_FILE!" type "!EXISTING_TORCH_VERIFY_FILE!"
            echo   Removing the incompatible wheel before installing !CUDA_INDEX!...
            %PIP_CMD% uninstall torch torchvision torchaudio -y
            if errorlevel 1 (
                echo   [ERROR] Failed to remove the incompatible PyTorch packages.
                goto :failed
            )
        )
        if exist "!EXISTING_TORCH_VERIFY_FILE!" del "!EXISTING_TORCH_VERIFY_FILE!" >nul 2>nul
    ) else (
        if "!POLICY_FORCE_CPU_REPAIR!"=="1" (
            :: A supported GPU was found, but its current driver cannot safely
            :: run the required wheel. Do not retain an incompatible CUDA build.
            set "CPU_TORCH_VERIFY_FILE=%TEMP%\paperminer_cpu_torch_%RANDOM%_%RANDOM%.txt"
            if exist "scripts\torch_runtime_policy.py" (
                "%PYTHON_EXE%" "scripts\torch_runtime_policy.py" verify --expected cpu --require-cpu-wheel >"!CPU_TORCH_VERIFY_FILE!" 2>&1
            ) else (
                "%PYTHON_EXE%" -c "import torch; raise SystemExit(0 if torch.version.cuda is None else 1)" >"!CPU_TORCH_VERIFY_FILE!" 2>&1
            )
            set "CPU_TORCH_VERIFY_EXIT=!errorlevel!"
            if "!CPU_TORCH_VERIFY_EXIT!"=="0" (
                set "TORCH_OK=1"
                echo   Compatible CPU PyTorch already installed, skipping.
            ) else (
                echo   Existing CUDA PyTorch is incompatible with the current GPU/driver policy.
                if exist "!CPU_TORCH_VERIFY_FILE!" type "!CPU_TORCH_VERIFY_FILE!"
                echo   Removing it before installing the safe CPU build...
                %PIP_CMD% uninstall torch torchvision torchaudio -y
                if errorlevel 1 (
                    echo   [ERROR] Failed to remove the incompatible PyTorch packages.
                    goto :failed
                )
            )
            if exist "!CPU_TORCH_VERIFY_FILE!" del "!CPU_TORCH_VERIFY_FILE!" >nul 2>nul
        ) else (
            :: No NVIDIA GPU: any working torch wheel remains usable on CPU.
            set "TORCH_OK=1"
            echo   PyTorch already installed, skipping.
        )
    )
)

if "!TORCH_OK!"=="1" goto :install_mineru

echo.
echo   Installing common PyTorch dependencies from !PIP_SOURCE_NAME!...
%PIP_CMD% install filelock typing-extensions sympy networkx jinja2 fsspec numpy pillow !PIP_COMMON_ARGS!
if errorlevel 1 if /i not "!PIP_INDEX_URL!"=="https://pypi.org/simple" (
    echo   Selected source failed for PyTorch dependencies; retrying official PyPI...
    %PIP_CMD% install filelock typing-extensions sympy networkx jinja2 fsspec numpy pillow !PIP_OFFICIAL_ARGS!
)
if errorlevel 1 (
    echo   [WARNING] Some common PyTorch dependencies were not prefetched.
    echo   The official PyTorch install will make one final attempt.
)

if "!HAS_GPU!"=="1" (
    echo.
    echo   Installing CUDA version of PyTorch [!CUDA_INDEX!]...
    echo   NOTE: Must download from official PyTorch source (~2.5GB^)
    echo   Package set: !TORCH_PACKAGE_SPEC!
    echo.
    %PIP_CMD% install --upgrade !TORCH_PACKAGE_SPEC! --index-url https://download.pytorch.org/whl/!CUDA_INDEX! --timeout 300 --retries 10 --prefer-binary

    :: Verify the installed wheel family and execute real float16 kernels.
    echo.
    echo   Verifying PyTorch CUDA runtime and real kernels...
    set "GPU_VERIFY_FILE=%TEMP%\paperminer_gpu_verify_%RANDOM%_%RANDOM%.txt"
    if exist "scripts\torch_runtime_policy.py" (
        "%PYTHON_EXE%" "scripts\torch_runtime_policy.py" verify --expected "!CUDA_INDEX!" >"!GPU_VERIFY_FILE!" 2>&1
    ) else (
        "%PYTHON_EXE%" -c "import torch; assert torch.cuda.is_available(); print('PyTorch: '+torch.__version__); print('CUDA runtime: '+str(torch.version.cuda)); print('cuDNN: '+str(torch.backends.cudnn.version())); [(torch.arange(1,17,device=f'cuda:{i}').to(torch.float16).mul(2).sum().item(),torch.cuda.synchronize(i)) for i in range(torch.cuda.device_count())]" >"!GPU_VERIFY_FILE!" 2>&1
    )
    set "CUDA_VERIFY_EXIT=!errorlevel!"
    if exist "!GPU_VERIFY_FILE!" type "!GPU_VERIFY_FILE!"
    if exist "!GPU_VERIFY_FILE!" del "!GPU_VERIFY_FILE!" >nul 2>nul
    if "!CUDA_VERIFY_EXIT!"=="0" (
        echo   PyTorch CUDA runtime and kernel verification passed!
    ) else (
        echo.
        echo   [WARNING] CUDA verification failed!
        echo   The installed wheel or GPU driver (v!DRIVER_VER!^) did not pass !CUDA_INDEX! validation.
        if "!POLICY_BLACKWELL_PRESENT!"=="1" (
            echo   [ERROR] Blackwell/RTX 50 requires a verified CUDA wheel.
            echo   Setup will not silently report success with an incompatible GPU runtime.
            echo   Update the NVIDIA driver if requested, then run Setup again.
            goto :failed
        )
        echo   Falling back to CPU version...
        echo.
        %PIP_CMD% uninstall torch torchvision torchaudio -y
        if errorlevel 1 goto :failed
        %PIP_CMD% install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --timeout 300 --retries 10 --prefer-binary
        if errorlevel 1 goto :failed
        echo.
        echo   CPU version installed. PDF processing will still work,
        echo   but will be slower without GPU acceleration.
    )
) else (
    echo.
    echo   Installing CPU version of PyTorch...
    echo.
    %PIP_CMD% install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu --timeout 300 --retries 10 --prefer-binary
    if errorlevel 1 goto :failed
)

:: ----------------------------------------
:: MinerU
:: ----------------------------------------
:install_mineru
echo.
"%PYTHON_EXE%" -c "import importlib.metadata as m,re; p=[int(x) for x in re.findall(r'\d+',m.version('mineru'))[:2]]; raise SystemExit(0 if tuple(p)>=(3,1) and tuple(p)<(4,0) else 1)" >nul 2>nul
if !errorlevel!==0 (
    echo [Step 3] Compatible MinerU already installed, skipping.
    goto :install_other
)

echo [Step 3] Installing or upgrading MinerU (>=3.1.0,<4.0)...
"%PYTHON_EXE%" -m pip show mineru >nul 2>nul
if !errorlevel!==0 (
    echo   Unsupported installed MinerU version detected. Upgrade is required.
)
%PIP_CMD% install -U "mineru[core]>=3.1.0,<4.0" !PIP_COMMON_ARGS!
if errorlevel 1 if /i not "!PIP_INDEX_URL!"=="https://pypi.org/simple" (
    echo   Selected PyPI source failed or is not synchronized; retrying official PyPI...
    %PIP_CMD% install -U "mineru[core]>=3.1.0,<4.0" !PIP_OFFICIAL_ARGS!
)
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
    %PIP_CMD% install --upgrade "packages\ttkbootstrap-2.2.2-py3-none-any.whl" !PIP_COMMON_ARGS!
)
if exist "requirements.txt" (
    %PIP_CMD% install -r requirements.txt !PIP_COMMON_ARGS!
    if errorlevel 1 if /i not "!PIP_INDEX_URL!"=="https://pypi.org/simple" (
        echo   Selected PyPI source failed for remaining dependencies; retrying official PyPI...
        %PIP_CMD% install -r requirements.txt !PIP_OFFICIAL_ARGS!
    )
) else (
    %PIP_CMD% install "ttkbootstrap>=2.2.2,<3.0" pandas openpyxl beautifulsoup4 python-docx lxml "pypdf>=5.0.0,<7.0" requests python-dotenv !PIP_COMMON_ARGS!
    if errorlevel 1 if /i not "!PIP_INDEX_URL!"=="https://pypi.org/simple" (
        echo   Selected PyPI source failed for remaining dependencies; retrying official PyPI...
        %PIP_CMD% install "ttkbootstrap>=2.2.2,<3.0" pandas openpyxl beautifulsoup4 python-docx lxml "pypdf>=5.0.0,<7.0" requests python-dotenv !PIP_OFFICIAL_ARGS!
    )
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
