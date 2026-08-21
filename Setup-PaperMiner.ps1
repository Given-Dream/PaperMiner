param(
    [switch]$CheckOnly,
    [switch]$Bootstrap
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

try { $Host.UI.RawUI.WindowTitle = 'PaperMiner Setup' } catch {}

. (Join-Path $projectRoot 'PaperMiner.Runtime.ps1')

$installerName = ([string][char]0x4E00) + [char]0x952E + [char]0x5B89 + [char]0x88C5 + '.bat'
$installer = Join-Path $projectRoot $installerName
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Installer payload not found: $installer"
}

if ($CheckOnly) {
    Write-Output 'CHECK_OK=SETUP_PAYLOAD'
    exit 0
}

$logDirectory = Join-Path $projectRoot 'logs'
if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $logDirectory | Out-Null
}
$logPath = Join-Path $logDirectory (
    'Setup_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Write-SetupLog {
    param([string]$Message)
    Write-Host $Message
    $Message | Out-File -LiteralPath $logPath -Encoding utf8 -Append
}

try {
    Write-SetupLog '========================================'
    Write-SetupLog 'PaperMiner Setup'
    Write-SetupLog 'This setup installs or repairs dependencies only.'
    Write-SetupLog 'The PaperMiner GUI will not be started automatically.'
    Write-SetupLog ('Log: {0}' -f $logPath)
    Write-SetupLog '========================================'

    $existingRuntime = Find-PaperMinerRuntime -ProjectRoot $projectRoot
    if ($null -ne $existingRuntime) {
        $env:PAPERMINER_ENV_PATH = $existingRuntime.EnvironmentPath
        Write-SetupLog ('Conda JSON selected environment: {0}' -f $existingRuntime.EnvironmentPath)
    }

    $env:PAPERMINER_SETUP_MODE = '1'
    $command = '/d /c call "{0}"' -f $installer
    $exitCode = Invoke-PaperMinerProcess `
        -FileName $env:ComSpec `
        -Arguments $command `
        -WorkingDirectory $projectRoot `
        -LogPath $logPath

    $runtime = Find-PaperMinerRuntime -ProjectRoot $projectRoot
    if ($null -eq $runtime) {
        throw (
            'Setup completed, but `conda env list --json` did not report a usable MinerU runtime. ' +
            ('Dependency exit code: {0}' -f $exitCode))
    }

    $configPath = Save-PaperMinerRuntimeConfig -ProjectRoot $projectRoot -Runtime $runtime
    Write-SetupLog ('Runtime environment: {0}' -f $runtime.EnvironmentPath)
    Write-SetupLog ('Runtime Python: {0}' -f $runtime.PythonExe)
    Write-SetupLog ('Runtime recorded: {0}' -f $configPath)

    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'PaperMiner.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $projectRoot 'PaperMiner.exe'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'PaperMiner 1.4.2'
    $shortcut.Save()
    Write-SetupLog ('Desktop shortcut: {0}' -f $shortcutPath)

    Write-SetupLog 'Setup completed. Close this window, then start PaperMiner.exe.'
    if (-not $Bootstrap) {
        Read-Host 'Press Enter to close'
    }
    exit 0
}
catch {
    Write-SetupLog ('SETUP ERROR: {0}' -f $_.Exception.Message)
    Write-SetupLog 'PaperMiner.exe was not started.'
    if (-not $Bootstrap) {
        Read-Host 'Press Enter to close'
    }
    exit 1
}
