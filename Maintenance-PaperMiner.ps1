param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Reinstall', 'Uninstall')]
    [string]$Mode,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

try { $Host.UI.RawUI.WindowTitle = 'PaperMiner Maintenance' } catch {}

. (Join-Path $projectRoot 'PaperMiner.Runtime.ps1')

if ($CheckOnly) {
    Write-Output ('CHECK_OK={0}' -f $Mode.ToUpperInvariant())
    exit 0
}

$logDirectory = Join-Path $projectRoot 'logs'
if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}
$logPath = Join-Path $logDirectory (
    'Maintenance_{0}_{1}.log' -f $Mode, (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Write-MaintenanceLog {
    param([string]$Message)
    Write-Host $Message
    $Message | Out-File -LiteralPath $logPath -Encoding utf8 -Append
}

function Remove-PaperMinerShortcut {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PaperMiner.lnk'
    if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) { return }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $expectedTarget = Join-Path $projectRoot 'PaperMiner.exe'
    if ([string]::Equals(
            [System.IO.Path]::GetFullPath($shortcut.TargetPath),
            [System.IO.Path]::GetFullPath($expectedTarget),
            [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $shortcutPath -Force
        Write-MaintenanceLog ('Removed shortcut: {0}' -f $shortcutPath)
    }
    else {
        Write-MaintenanceLog ('Kept unrelated shortcut: {0}' -f $shortcutPath)
    }
}

try {
    Write-MaintenanceLog '========================================'
    Write-MaintenanceLog ('PaperMiner maintenance mode: {0}' -f $Mode)
    Write-MaintenanceLog 'User input/output, project files, and model caches are preserved.'
    Write-MaintenanceLog ('Log: {0}' -f $logPath)

    $conda = Find-PaperMinerConda -ProjectRoot $projectRoot
    $runtime = Find-PaperMinerRuntime -ProjectRoot $projectRoot
    if ($null -ne $runtime) {
        Write-MaintenanceLog ('Detected environment: {0}' -f $runtime.EnvironmentPath)
    }

    if ($null -ne $conda -and $null -ne $runtime) {
        $actualEnvironment = [System.IO.Path]::GetFullPath($runtime.EnvironmentPath).TrimEnd('\')
        $environmentRoot = [System.IO.Path]::GetPathRoot($actualEnvironment).TrimEnd('\')
        if ((Split-Path -Leaf $actualEnvironment) -ine 'MinerU' -or
            [string]::Equals(
                $actualEnvironment,
                $environmentRoot,
                [StringComparison]::OrdinalIgnoreCase)) {
            throw ('Safety check refused an invalid MinerU environment path: {0}' -f $actualEnvironment)
        }
        if (-not (Test-PaperMinerCondaEnvironmentRegistration `
                -CondaCommand $conda.Command `
                -EnvironmentPath $actualEnvironment)) {
            throw ('Safety check refused an environment not registered by Conda: {0}' -f $actualEnvironment)
        }

        Write-MaintenanceLog ('Removing only the registered MinerU prefix: {0}' -f $actualEnvironment)
        if ([System.IO.Path]::GetExtension($conda.Command) -ieq '.bat') {
            $command = '/d /c call "{0}" env remove --prefix "{1}" --yes' -f `
                $conda.Command, $actualEnvironment
            $exitCode = Invoke-PaperMinerProcess -FileName $env:ComSpec -Arguments $command `
                -WorkingDirectory $projectRoot -LogPath $logPath
        }
        else {
            $exitCode = Invoke-PaperMinerProcess -FileName $conda.Command `
                -Arguments ('env remove --prefix "{0}" --yes' -f $actualEnvironment) `
                -WorkingDirectory $projectRoot -LogPath $logPath
        }

        if ($exitCode -ne 0) {
            throw ('Conda environment removal failed with exit code {0}.' -f $exitCode)
        }
    }
    elseif ($null -eq $runtime) {
        Write-MaintenanceLog 'MinerU environment is already absent.'
    }
    else {
        throw 'Conda could not be located, so no environment was removed.'
    }

    $runtimeConfig = Join-Path $projectRoot '.paperminer-runtime.json'
    if (Test-Path -LiteralPath $runtimeConfig -PathType Leaf) {
        Remove-Item -LiteralPath $runtimeConfig -Force
        Write-MaintenanceLog ('Removed runtime record: {0}' -f $runtimeConfig)
    }

    if ($Mode -eq 'Uninstall') {
        Remove-PaperMinerShortcut
        $uninstallRegistry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PaperMiner'
        if (Test-Path -LiteralPath $uninstallRegistry) {
            Remove-Item -LiteralPath $uninstallRegistry -Recurse -Force
            Write-MaintenanceLog 'Removed the PaperMiner Windows uninstall registration.'
        }
        Write-MaintenanceLog 'Uninstall completed.'
        Write-MaintenanceLog 'The application folder, models, input, and output were intentionally preserved.'
        Write-MaintenanceLog 'Delete the application folder manually only after reviewing the preserved data.'
    }
    else {
        $setupScript = Join-Path $projectRoot 'Setup-PaperMiner.ps1'
        if (-not (Test-Path -LiteralPath $setupScript -PathType Leaf)) {
            throw "Setup stage not found: $setupScript"
        }
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        Write-MaintenanceLog 'Cleanup completed. Starting the installed setup stage...'
        Start-Process -FilePath $powershell `
            -ArgumentList @(
                '-NoLogo',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                ('"{0}"' -f $setupScript)) `
            -WorkingDirectory $projectRoot
    }

    Read-Host 'Press Enter to close'
    exit 0
}
catch {
    Write-MaintenanceLog ('MAINTENANCE ERROR: {0}' -f $_.Exception.Message)
    Write-MaintenanceLog 'No project data or model cache was removed.'
    Read-Host 'Press Enter to close'
    exit 1
}
