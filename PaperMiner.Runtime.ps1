Set-StrictMode -Version 2.0

function Add-PaperMinerCandidate {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    try {
        $fullPath = [System.IO.Path]::GetFullPath(
            [Environment]::ExpandEnvironmentVariables($Path))
    }
    catch {
        return
    }

    foreach ($existing in $List) {
        if ([string]::Equals(
                $existing,
                $fullPath,
                [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }

    $List.Add($fullPath)
}

function Get-PaperMinerRuntimeConfig {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $configPath = Join-Path $ProjectRoot '.paperminer-runtime.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-PaperMinerCondaHintFiles {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $files = New-Object 'System.Collections.Generic.List[string]'
    $hintFileOverride = [string]$env:PAPERMINER_CONDA_HINT_FILE
    if (-not [string]::IsNullOrWhiteSpace($hintFileOverride)) {
        try {
            $files.Add([System.IO.Path]::GetFullPath(
                [Environment]::ExpandEnvironmentVariables($hintFileOverride)))
        }
        catch {}
    }
    else {
        $localAppData = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::LocalApplicationData)
        if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
            $files.Add((Join-Path $localAppData 'PaperMiner\conda-root.txt'))
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
        try {
            $files.Add((Join-Path -Path ([System.IO.Path]::GetFullPath($ProjectRoot)) `
                -ChildPath '.paperminer-conda-root'))
        }
        catch {}
    }

    return $files
}

function Get-PaperMinerCondaHintRoots {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $roots = New-Object 'System.Collections.Generic.List[string]'
    foreach ($hintFile in Get-PaperMinerCondaHintFiles -ProjectRoot $ProjectRoot) {
        if (-not (Test-Path -LiteralPath $hintFile -PathType Leaf)) {
            continue
        }

        try {
            $hint = (Get-Content -LiteralPath $hintFile -Raw -Encoding UTF8).Trim()
            if (-not [string]::IsNullOrWhiteSpace($hint)) {
                Add-PaperMinerCandidate -List $roots -Path $hint
            }
        }
        catch {}
    }

    return $roots
}

function Save-PaperMinerCondaHint {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$CondaRoot
    )

    if ([string]::IsNullOrWhiteSpace($CondaRoot)) {
        return
    }

    try {
        $fullRoot = [System.IO.Path]::GetFullPath(
            [Environment]::ExpandEnvironmentVariables($CondaRoot)).TrimEnd('\')
        $hintFiles = @(Get-PaperMinerCondaHintFiles -ProjectRoot $ProjectRoot)
        if ($hintFiles.Count -eq 0) {
            return
        }

        # Keep a per-user hint outside the install directory so a failed first
        # setup can still be repaired by a later Setup.exe in another folder.
        $hintPath = $hintFiles[0]
        $hintDirectory = Split-Path -Parent $hintPath
        if (-not (Test-Path -LiteralPath $hintDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $hintDirectory -Force | Out-Null
        }
        $temporaryPath = '{0}.tmp.{1}' -f $hintPath, $PID
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $fullRoot + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporaryPath -Destination $hintPath -Force
    }
    catch {
        # A hint is an optimization only; never make dependency setup fail
        # because the user profile is read-only or being cleaned concurrently.
    }
}

function Get-PaperMinerInstalledProjectRoots {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $roots = New-Object 'System.Collections.Generic.List[string]'
    Add-PaperMinerCandidate -List $roots -Path $ProjectRoot

    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_PROJECT_ROOT)) {
        Add-PaperMinerCandidate -List $roots -Path $env:PAPERMINER_PROJECT_ROOT
    }

    foreach ($registryPath in @(
            'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PaperMiner',
            'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PaperMiner',
            'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\PaperMiner')) {
        try {
            $entry = Get-ItemProperty -LiteralPath $registryPath -ErrorAction Stop
            if ($null -ne $entry.PSObject.Properties['InstallLocation']) {
                Add-PaperMinerCandidate `
                    -List $roots `
                    -Path ([string]$entry.InstallLocation)
            }
        }
        catch {}
    }

    $localAppData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData)
    if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
        Add-PaperMinerCandidate `
            -List $roots `
            -Path (Join-Path $localAppData 'Programs\PaperMiner')
    }

    return $roots
}

function Get-PaperMinerSetupCondaRoots {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $candidates = New-Object 'System.Collections.Generic.List[string]'

    # Setup detection intentionally has a short, deterministic priority list:
    # explicit paths first, then PaperMiner's persisted configuration. It does
    # not silently crawl disks; the GUI offers a separate full-disk search.
    foreach ($path in @(
            $env:PAPERMINER_CONDA_INSTALL_ROOT,
            $env:PAPERMINER_CONDA_ROOT)) {
        Add-PaperMinerCandidate -List $candidates -Path $path
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_CONDA_COMMAND)) {
        $commandDirectory = Split-Path -Parent $env:PAPERMINER_CONDA_COMMAND
        if ((Split-Path -Leaf $commandDirectory) -in @('Scripts', 'condabin')) {
            Add-PaperMinerCandidate `
                -List $candidates `
                -Path (Split-Path -Parent $commandDirectory)
        }
    }

    foreach ($installedRoot in Get-PaperMinerInstalledProjectRoots `
            -ProjectRoot $ProjectRoot) {
        $config = Get-PaperMinerRuntimeConfig -ProjectRoot $installedRoot
        if ($null -ne $config -and $config.PSObject.Properties['CondaRoot']) {
            Add-PaperMinerCandidate `
                -List $candidates `
                -Path ([string]$config.CondaRoot)
        }
    }

    foreach ($hintRoot in Get-PaperMinerCondaHintRoots -ProjectRoot $ProjectRoot) {
        Add-PaperMinerCandidate -List $candidates -Path $hintRoot
    }

    return $candidates
}

function Find-PaperMinerCondaAtRoot {
    param([Parameter(Mandatory = $true)][string]$Root)

    $roots = New-Object 'System.Collections.Generic.List[string]'
    Add-PaperMinerCandidate -List $roots -Path $Root
    foreach ($candidate in $roots) {
        $condaBat = Join-Path $candidate 'condabin\conda.bat'
        $condaExe = Join-Path $candidate 'Scripts\conda.exe'
        if (Test-Path -LiteralPath $condaBat -PathType Leaf) {
            return [pscustomobject]@{ Root = $candidate; Command = $condaBat }
        }
        if (Test-Path -LiteralPath $condaExe -PathType Leaf) {
            return [pscustomobject]@{ Root = $candidate; Command = $condaExe }
        }
    }

    return $null
}

function Find-PaperMinerSetupConda {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    foreach ($root in Get-PaperMinerSetupCondaRoots -ProjectRoot $ProjectRoot) {
        $conda = Find-PaperMinerCondaAtRoot -Root $root
        if ($null -ne $conda) {
            return $conda
        }
    }

    return $null
}

function Get-PaperMinerCondaRoots {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $config = Get-PaperMinerRuntimeConfig -ProjectRoot $ProjectRoot

    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_CONDA_INSTALL_ROOT)) {
        Add-PaperMinerCandidate -List $candidates -Path $env:PAPERMINER_CONDA_INSTALL_ROOT
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_CONDA_ROOT)) {
        Add-PaperMinerCandidate -List $candidates -Path $env:PAPERMINER_CONDA_ROOT
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_CONDA_COMMAND)) {
        $commandDirectory = Split-Path -Parent $env:PAPERMINER_CONDA_COMMAND
        if ((Split-Path -Leaf $commandDirectory) -in @('Scripts', 'condabin')) {
            Add-PaperMinerCandidate -List $candidates -Path (
                Split-Path -Parent $commandDirectory)
        }
    }

    if ($null -ne $config -and $config.PSObject.Properties['CondaRoot']) {
        Add-PaperMinerCandidate -List $candidates -Path ([string]$config.CondaRoot)
    }

    foreach ($hintRoot in Get-PaperMinerCondaHintRoots -ProjectRoot $ProjectRoot) {
        Add-PaperMinerCandidate -List $candidates -Path $hintRoot
    }

    if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
        $prefix = $env:CONDA_PREFIX
        if ((Split-Path -Leaf $prefix) -ieq 'MinerU') {
            $prefix = Split-Path -Parent (Split-Path -Parent $prefix)
        }
        Add-PaperMinerCandidate -List $candidates -Path $prefix
    }

    if (-not [string]::IsNullOrWhiteSpace($env:CONDA_EXE)) {
        $condaExeDirectory = Split-Path -Parent $env:CONDA_EXE
        if ((Split-Path -Leaf $condaExeDirectory) -ieq 'Scripts') {
            Add-PaperMinerCandidate -List $candidates -Path (Split-Path -Parent $condaExeDirectory)
        }
    }

    foreach ($commandName in @('conda.exe', 'conda.bat')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) {
            $commandDirectory = Split-Path -Parent $command.Source
            if ((Split-Path -Leaf $commandDirectory) -in @('Scripts', 'condabin')) {
                Add-PaperMinerCandidate -List $candidates -Path (Split-Path -Parent $commandDirectory)
            }
        }
    }

    foreach ($path in @(
            (Join-Path $env:USERPROFILE 'miniconda3'),
            (Join-Path $env:USERPROFILE 'miniconda'),
            (Join-Path $env:USERPROFILE 'anaconda3'),
            (Join-Path $env:USERPROFILE 'anaconda'),
            (Join-Path $env:LOCALAPPDATA 'miniconda3'),
            (Join-Path $env:LOCALAPPDATA 'miniconda'),
            (Join-Path $env:LOCALAPPDATA 'anaconda3'),
            (Join-Path $env:LOCALAPPDATA 'anaconda'),
            (Join-Path $env:ProgramData 'miniconda3'),
            (Join-Path $env:ProgramData 'miniconda'),
            (Join-Path $env:ProgramData 'anaconda3'),
            (Join-Path $env:ProgramData 'anaconda'))) {
        Add-PaperMinerCandidate -List $candidates -Path $path
    }

    foreach ($registryPath in @(
            'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        foreach ($entry in @(Get-ItemProperty `
                -Path $registryPath `
                -ErrorAction SilentlyContinue)) {
            if ($null -eq $entry.PSObject.Properties['DisplayName'] -or
                $null -eq $entry.PSObject.Properties['InstallLocation']) {
                continue
            }
            $displayName = [string]$entry.DisplayName
            if ($displayName -notmatch '(?i)(ana|mini)conda') {
                continue
            }
            Add-PaperMinerCandidate `
                -List $candidates `
                -Path ([string]$entry.InstallLocation)
        }
    }

    $userNames = New-Object 'System.Collections.Generic.List[string]'
    foreach ($name in @($env:USERNAME, 'admin')) {
        if (-not [string]::IsNullOrWhiteSpace($name) -and
            -not $userNames.Contains($name)) {
            $userNames.Add($name)
        }
    }

    foreach ($drive in Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue) {
        foreach ($distribution in @('miniconda3', 'miniconda', 'anaconda3', 'anaconda')) {
            Add-PaperMinerCandidate -List $candidates -Path (Join-Path $drive.Root $distribution)
            foreach ($programDirectory in @('Program Files', 'Program Files (x86)')) {
                Add-PaperMinerCandidate -List $candidates -Path (
                    Join-Path $drive.Root (Join-Path $programDirectory $distribution))
            }
            foreach ($name in $userNames) {
                Add-PaperMinerCandidate -List $candidates -Path (
                    Join-Path $drive.Root (Join-Path 'soft' (Join-Path $name $distribution)))
            }
        }
    }

    return $candidates
}

function Find-PaperMinerConda {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    foreach ($root in Get-PaperMinerCondaRoots -ProjectRoot $ProjectRoot) {
        $condaBat = Join-Path $root 'condabin\conda.bat'
        $condaExe = Join-Path $root 'Scripts\conda.exe'
        if (Test-Path -LiteralPath $condaBat -PathType Leaf) {
            return [pscustomobject]@{ Root = $root; Command = $condaBat }
        }
        if (Test-Path -LiteralPath $condaExe -PathType Leaf) {
            return [pscustomobject]@{ Root = $root; Command = $condaExe }
        }
    }

    return $null
}

function Get-PaperMinerCondaEnvironmentPaths {
    param([Parameter(Mandatory = $true)][string]$CondaCommand)

    $environments = New-Object 'System.Collections.Generic.List[string]'
    if (-not (Test-Path -LiteralPath $CondaCommand -PathType Leaf)) {
        return $environments
    }

    try {
        $rawOutput = @(& $CondaCommand env list --json 2>$null)
        if ($LASTEXITCODE -ne 0) {
            return $environments
        }

        $jsonText = ($rawOutput -join [Environment]::NewLine).Trim()
        $jsonStart = $jsonText.IndexOf('{')
        $jsonEnd = $jsonText.LastIndexOf('}')
        if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
            return $environments
        }

        $payload = $jsonText.Substring(
            $jsonStart,
            $jsonEnd - $jsonStart + 1) | ConvertFrom-Json
        if ($null -eq $payload -or
            -not $payload.PSObject.Properties['envs']) {
            return $environments
        }

        foreach ($environment in @($payload.envs)) {
            Add-PaperMinerCandidate -List $environments -Path ([string]$environment)
        }
    }
    catch {
        return $environments
    }

    return $environments
}

function Get-PaperMinerDefaultEnvironmentPath {
    param(
        [Parameter(Mandatory = $true)][string]$CondaCommand,
        [Parameter(Mandatory = $true)][string]$CondaRoot,
        [string]$EnvironmentName = 'MinerU'
    )

    try {
        $rawOutput = @(& $CondaCommand info --json 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $info = ($rawOutput -join "`n") | ConvertFrom-Json
            foreach ($environmentRoot in @($info.envs_dirs)) {
                if (-not [string]::IsNullOrWhiteSpace([string]$environmentRoot)) {
                    return Join-Path ([string]$environmentRoot) $EnvironmentName
                }
            }
        }
    }
    catch {}

    return Join-Path (Join-Path $CondaRoot 'envs') $EnvironmentName
}

function Test-PaperMinerCondaEnvironmentRegistration {
    param(
        [Parameter(Mandatory = $true)][string]$CondaCommand,
        [Parameter(Mandatory = $true)][string]$EnvironmentPath
    )

    try {
        $expected = [System.IO.Path]::GetFullPath($EnvironmentPath).TrimEnd('\')
    }
    catch {
        return $false
    }

    foreach ($registered in Get-PaperMinerCondaEnvironmentPaths -CondaCommand $CondaCommand) {
        if ([string]::Equals(
                $expected,
                ([System.IO.Path]::GetFullPath($registered).TrimEnd('\')),
                [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

function Find-PaperMinerRuntime {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $config = Get-PaperMinerRuntimeConfig -ProjectRoot $ProjectRoot
    if ($null -ne $config -and $config.PSObject.Properties['PythonExe']) {
        $configuredPython = [string]$config.PythonExe
        if (Test-Path -LiteralPath $configuredPython -PathType Leaf) {
            $environmentPath = Split-Path -Parent $configuredPython
            $condaRoot = $null
            if ($config.PSObject.Properties['CondaRoot']) {
                $condaRoot = [string]$config.CondaRoot
            }
            return [pscustomobject]@{
                PythonExe = $configuredPython
                EnvironmentPath = $environmentPath
                CondaRoot = $condaRoot
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX) -and
        (Split-Path -Leaf $env:CONDA_PREFIX) -ieq 'MinerU') {
        $activePython = Join-Path $env:CONDA_PREFIX 'python.exe'
        if (Test-Path -LiteralPath $activePython -PathType Leaf) {
            return [pscustomobject]@{
                PythonExe = $activePython
                EnvironmentPath = $env:CONDA_PREFIX
                CondaRoot = Split-Path -Parent (Split-Path -Parent $env:CONDA_PREFIX)
            }
        }
    }

    $conda = Find-PaperMinerConda -ProjectRoot $ProjectRoot
    if ($null -ne $conda) {
        foreach ($environmentPath in Get-PaperMinerCondaEnvironmentPaths `
                -CondaCommand $conda.Command) {
            if ((Split-Path -Leaf $environmentPath) -ine 'MinerU') {
                continue
            }

            $registeredPython = Join-Path $environmentPath 'python.exe'
            if (Test-Path -LiteralPath $registeredPython -PathType Leaf) {
                return [pscustomobject]@{
                    PythonExe = $registeredPython
                    EnvironmentPath = $environmentPath
                    CondaRoot = $conda.Root
                }
            }
        }
    }

    foreach ($root in Get-PaperMinerCondaRoots -ProjectRoot $ProjectRoot) {
        $python = Join-Path $root 'envs\MinerU\python.exe'
        if (Test-Path -LiteralPath $python -PathType Leaf) {
            return [pscustomobject]@{
                PythonExe = $python
                EnvironmentPath = Split-Path -Parent $python
                CondaRoot = $root
            }
        }
    }

    return $null
}

function Save-PaperMinerRuntimeConfig {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)]$Runtime
    )

    $configPath = Join-Path $ProjectRoot '.paperminer-runtime.json'
    $payload = [ordered]@{
        SchemaVersion = 1
        EnvironmentName = 'MinerU'
        PythonExe = [string]$Runtime.PythonExe
        EnvironmentPath = [string]$Runtime.EnvironmentPath
        CondaRoot = [string]$Runtime.CondaRoot
        UpdatedAt = (Get-Date).ToString('o')
    }

    $payload | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
    return $configPath
}

function Initialize-PaperMinerProcessPump {
    if ('PaperMinerProcessPump' -as [type]) {
        return
    }

    $source = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Text;

public static class PaperMinerProcessPump
{
    public static int Run(string executable, string arguments, string workingDirectory, string logPath)
    {
        object gate = new object();
        UTF8Encoding utf8 = new UTF8Encoding(false);

        using (StreamWriter writer = new StreamWriter(logPath, true, utf8))
        using (Process process = new Process())
        {
            writer.AutoFlush = true;
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = executable;
            info.Arguments = arguments;
            info.WorkingDirectory = workingDirectory;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = utf8;
            info.StandardErrorEncoding = utf8;
            process.StartInfo = info;

            DataReceivedEventHandler writeLine = delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data == null)
                {
                    return;
                }

                lock (gate)
                {
                    Console.WriteLine(eventArgs.Data);
                    writer.WriteLine(eventArgs.Data);
                }
            };

            process.OutputDataReceived += writeLine;
            process.ErrorDataReceived += writeLine;
            if (!process.Start())
            {
                throw new InvalidOperationException("The child process did not start.");
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            process.WaitForExit();
            return process.ExitCode;
        }
    }
}
'@

    Add-Type -TypeDefinition $source -Language CSharp
}

function Invoke-PaperMinerProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FileName,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    Initialize-PaperMinerProcessPump
    return [PaperMinerProcessPump]::Run(
        $FileName,
        $Arguments,
        $WorkingDirectory,
        $LogPath)
}
