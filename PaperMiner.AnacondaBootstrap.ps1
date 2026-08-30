Set-StrictMode -Version 2.0

function Write-PaperMinerAnacondaLog {
    param(
        [scriptblock]$LogAction,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if ($null -ne $LogAction) {
        & $LogAction $Message | Out-Null
    }
    else {
        Write-Host $Message
    }
}

function Get-PaperMinerSelectedAnacondaRoot {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    if ([string]::IsNullOrWhiteSpace($env:PAPERMINER_CONDA_INSTALL_ROOT)) {
        throw 'Setup did not provide the user-selected Anaconda installation directory.'
    }

    $installRoot = [System.IO.Path]::GetFullPath(
        [Environment]::ExpandEnvironmentVariables(
            $env:PAPERMINER_CONDA_INSTALL_ROOT)).TrimEnd('\')
    if ($installRoot.IndexOfAny([char[]]'!%') -ge 0) {
        throw 'The Anaconda installation directory cannot contain ! or % characters.'
    }
    $driveRoot = [System.IO.Path]::GetPathRoot($installRoot).TrimEnd('\')
    if ([string]::Equals(
            $installRoot,
            $driveRoot,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A drive root cannot be used as the Anaconda installation directory.'
    }

    $projectPath = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $projectBoundary = $projectPath + '\'
    $anacondaBoundary = $installRoot + '\'
    if ([string]::Equals(
            $installRoot,
            $projectPath,
            [StringComparison]::OrdinalIgnoreCase) -or
        $installRoot.StartsWith(
            $projectBoundary,
            [StringComparison]::OrdinalIgnoreCase) -or
        $projectPath.StartsWith(
            $anacondaBoundary,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'PaperMiner and Anaconda must use separate, non-overlapping directories.'
    }

    return $installRoot
}

function Get-PaperMinerAnacondaBootstrapConfig {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $version = '2026.07-1'
    $installerName = 'Anaconda3-{0}-Windows-x86_64.exe' -f $version
    $installRoot = Get-PaperMinerSelectedAnacondaRoot -ProjectRoot $ProjectRoot
    $runtimeRoot = Split-Path -Parent $installRoot

    $localInstaller = $null
    if (-not [string]::IsNullOrWhiteSpace($env:PAPERMINER_ANACONDA_INSTALLER)) {
        $localInstaller = [System.IO.Path]::GetFullPath(
            [Environment]::ExpandEnvironmentVariables(
                $env:PAPERMINER_ANACONDA_INSTALLER))
    }

    return [pscustomobject]@{
        Version = $version
        InstallerName = $installerName
        ExpectedSha256 = 'b545f4bd8ab3bf32d99002a0779a887668ebfe479ee32ecbf060375670d5ee09'
        ExpectedBytes = [int64]1112492048
        DownloadSources = [object[]]@(
            [pscustomobject]@{
                Name = 'Tsinghua mirror'
                Uri = ('https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/' + $installerName)
                Order = 1
            }
            [pscustomobject]@{
                Name = 'BFSU mirror'
                Uri = ('https://mirrors.bfsu.edu.cn/anaconda/archive/' + $installerName)
                Order = 2
            }
            [pscustomobject]@{
                Name = 'NJU mirror'
                Uri = ('https://mirror.nju.edu.cn/anaconda/archive/' + $installerName)
                Order = 3
            }
            [pscustomobject]@{
                Name = 'Anaconda official'
                Uri = ('https://repo.anaconda.com/archive/' + $installerName)
                Order = 4
            }
        )
        InstallRoot = $installRoot
        CacheRoot = Join-Path $runtimeRoot 'PaperMinerDownloads'
        LocalInstallerPath = $localInstaller
    }
}

function Test-PaperMinerSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return [string]::Equals(
        $actual,
        $ExpectedSha256,
        [StringComparison]::OrdinalIgnoreCase)
}

function Measure-PaperMinerAnacondaSource {
    param(
        [Parameter(Mandatory = $true)]$Source,
        [scriptblock]$LogAction
    )

    $client = $null
    $request = $null
    $response = $null
    $stream = $null
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $sampleBytes = 1MB
    $downloaded = [int64]0
    try {
        $client = New-Object System.Net.Http.HttpClient
        $client.Timeout = [TimeSpan]::FromSeconds(10)
        $client.DefaultRequestHeaders.UserAgent.ParseAdd('PaperMiner/1.4.16')
        $request = New-Object System.Net.Http.HttpRequestMessage(
            [System.Net.Http.HttpMethod]::Get,
            [string]$Source.Uri)
        $request.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue(
            [int64]0,
            [int64]($sampleBytes - 1))
        $response = $client.SendAsync(
            $request,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        [void]$response.EnsureSuccessStatusCode()
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $buffer = New-Object byte[] 65536
        while ($downloaded -lt $sampleBytes -and $watch.Elapsed.TotalSeconds -lt 8) {
            $remaining = [Math]::Min(
                $buffer.Length,
                [int]($sampleBytes - $downloaded))
            $waitMilliseconds = [Math]::Max(
                250,
                [int]((8 - $watch.Elapsed.TotalSeconds) * 1000))
            $readTask = $stream.ReadAsync($buffer, 0, $remaining)
            if (-not $readTask.Wait($waitMilliseconds)) {
                break
            }
            $read = $readTask.Result
            if ($read -le 0) {
                break
            }
            $downloaded += $read
        }
        if ($downloaded -le 0) {
            throw 'No probe data was received.'
        }

        $seconds = [Math]::Max($watch.Elapsed.TotalSeconds, 0.001)
        $mibPerSecond = ($downloaded / 1MB) / $seconds
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Anaconda source probe: {0} = {1:N2} MiB/s ({2:N0} KiB sampled)' -f
            $Source.Name, $mibPerSecond, ($downloaded / 1KB))
        return [pscustomobject]@{
            Name = [string]$Source.Name
            Uri = [string]$Source.Uri
            Order = [int]$Source.Order
            Available = $true
            MiBPerSecond = [double]$mibPerSecond
        }
    }
    catch {
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Anaconda source probe unavailable: {0} ({1})' -f
            $Source.Name, $_.Exception.Message)
        return [pscustomobject]@{
            Name = [string]$Source.Name
            Uri = [string]$Source.Uri
            Order = [int]$Source.Order
            Available = $false
            MiBPerSecond = [double]0
        }
    }
    finally {
        $watch.Stop()
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $request) { $request.Dispose() }
        if ($null -ne $client) { $client.Dispose() }
    }
}

function Get-PaperMinerRankedAnacondaSources {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [scriptblock]$LogAction
    )

    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Testing {0} Anaconda download sources, including the official source...' -f
        @($Configuration.DownloadSources).Count)
    $measurements = @(
        foreach ($source in @($Configuration.DownloadSources)) {
            Measure-PaperMinerAnacondaSource -Source $source -LogAction $LogAction
        }
    )
    $ranked = @($measurements | Sort-Object `
        @{ Expression = { if ($_.Available) { 1 } else { 0 } }; Descending = $true }, `
        @{ Expression = { $_.MiBPerSecond }; Descending = $true }, `
        @{ Expression = { $_.Order }; Descending = $false })
    if ($ranked.Count -gt 0) {
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Fastest available Anaconda source: {0} ({1:N2} MiB/s probe)' -f
            $ranked[0].Name, $ranked[0].MiBPerSecond)
    }
    return $ranked
}

function Invoke-PaperMinerMirrorDownload {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [scriptblock]$LogAction
    )

    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $sources = @(Get-PaperMinerRankedAnacondaSources `
        -Configuration $Configuration `
        -LogAction $LogAction)
    $attempt = 0
    $errors = New-Object 'System.Collections.Generic.List[string]'
    foreach ($source in $sources) {
        $attempt += 1
        $uri = [string]$source.Uri
        $partialPath = '{0}.part.{1}.{2}' -f $DestinationPath, $PID, $attempt
        $client = $null
        $response = $null
        $downloadStream = $null
        $fileStream = $null

        try {
            Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                'Downloading Anaconda from source {0}/{1} [{2}; probe {3:N2} MiB/s]: {4}' -f
                $attempt, $sources.Count, $source.Name,
                $source.MiBPerSecond, $uri)

            $client = New-Object System.Net.Http.HttpClient
            $client.Timeout = [TimeSpan]::FromHours(4)
            $client.DefaultRequestHeaders.UserAgent.ParseAdd('PaperMiner/1.4.16')
            $response = $client.GetAsync(
                [string]$uri,
                [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
            ).GetAwaiter().GetResult()
            [void]$response.EnsureSuccessStatusCode()

            $contentLength = $response.Content.Headers.ContentLength
            if ($null -ne $contentLength -and
                [int64]$Configuration.ExpectedBytes -gt 0 -and
                [int64]$contentLength -ne [int64]$Configuration.ExpectedBytes) {
                throw ('Unexpected Content-Length: {0}; expected {1}.' -f
                    $contentLength, $Configuration.ExpectedBytes)
            }

            $downloadStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $fileStream = New-Object System.IO.FileStream(
                $partialPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None,
                1048576,
                [System.IO.FileOptions]::SequentialScan)
            $buffer = New-Object byte[] 1048576
            $downloaded = [int64]0
            $nextPercent = 5
            $lastByteReport = [int64]0
            $downloadWatch = [System.Diagnostics.Stopwatch]::StartNew()

            while (($read = $downloadStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $fileStream.Write($buffer, 0, $read)
                $downloaded += $read
                if ($null -ne $contentLength -and [int64]$contentLength -gt 0) {
                    $percent = [int][Math]::Floor(
                        ($downloaded * 100.0) / [int64]$contentLength)
                    if ($percent -ge $nextPercent) {
                        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                            'Anaconda download progress: {0}% ({1:N1}/{2:N1} MiB; average {3:N2} MiB/s)' -f
                            $percent, ($downloaded / 1MB),
                            ([int64]$contentLength / 1MB),
                            (($downloaded / 1MB) /
                                [Math]::Max($downloadWatch.Elapsed.TotalSeconds, 0.001)))
                        while ($nextPercent -le $percent) {
                            $nextPercent += 5
                        }
                    }
                }
                elseif (($downloaded - $lastByteReport) -ge 128MB) {
                    $lastByteReport = $downloaded
                    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                        'Anaconda downloaded: {0:N1} MiB' -f ($downloaded / 1MB))
                }
                if ($attempt -lt $sources.Count -and
                    $downloadWatch.Elapsed.TotalSeconds -ge 30 -and
                    (($downloaded / 1MB) /
                        [Math]::Max($downloadWatch.Elapsed.TotalSeconds, 0.001)) -lt 0.125) {
                    throw ('Sustained speed below 0.125 MiB/s; switching from {0} to the next source.' -f
                        $source.Name)
                }
            }
            $downloadWatch.Stop()

            $fileStream.Flush()
            $fileStream.Dispose()
            $fileStream = $null
            $downloadStream.Dispose()
            $downloadStream = $null

            if ([int64]$Configuration.ExpectedBytes -gt 0 -and
                $downloaded -ne [int64]$Configuration.ExpectedBytes) {
                throw ('Downloaded size mismatch: {0}; expected {1}.' -f
                    $downloaded, $Configuration.ExpectedBytes)
            }

            Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                'Verifying Anaconda SHA-256: {0}' -f $Configuration.ExpectedSha256)
            if (-not (Test-PaperMinerSha256 `
                    -Path $partialPath `
                    -ExpectedSha256 $Configuration.ExpectedSha256)) {
                throw 'Anaconda SHA-256 verification failed.'
            }

            Move-Item -LiteralPath $partialPath -Destination $DestinationPath
            Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                'Verified Anaconda installer: {0}' -f $DestinationPath)
            return $DestinationPath
        }
        catch {
            $message = 'Download source failed: {0} ({1})' -f $uri, $_.Exception.Message
            $errors.Add($message)
            Write-PaperMinerAnacondaLog -LogAction $LogAction -Message $message
        }
        finally {
            if ($null -ne $fileStream) { $fileStream.Dispose() }
            if ($null -ne $downloadStream) { $downloadStream.Dispose() }
            if ($null -ne $response) { $response.Dispose() }
            if ($null -ne $client) { $client.Dispose() }
            if (Test-Path -LiteralPath $partialPath -PathType Leaf) {
                Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
            }
        }
    }

    throw ('All configured Anaconda download sources failed. {0}' -f ($errors -join ' | '))
}

function Get-PaperMinerVerifiedAnacondaInstaller {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [scriptblock]$LogAction
    )

    if (-not [string]::IsNullOrWhiteSpace(
            [string]$Configuration.LocalInstallerPath)) {
        $localPath = [string]$Configuration.LocalInstallerPath
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Using local Anaconda installer override: {0}' -f $localPath)
        if (-not (Test-PaperMinerSha256 `
                -Path $localPath `
                -ExpectedSha256 $Configuration.ExpectedSha256)) {
            throw 'The local Anaconda installer failed SHA-256 verification.'
        }
        return $localPath
    }

    if (-not (Test-Path -LiteralPath $Configuration.CacheRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $Configuration.CacheRoot | Out-Null
    }
    $destination = Join-Path $Configuration.CacheRoot $Configuration.InstallerName
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Checking cached Anaconda installer: {0}' -f $destination)
        if (Test-PaperMinerSha256 `
                -Path $destination `
                -ExpectedSha256 $Configuration.ExpectedSha256) {
            Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
                'Reusing verified cached Anaconda installer.')
            return $destination
        }

        $invalidPath = '{0}.invalid.{1}' -f
            $destination, (Get-Date -Format 'yyyyMMdd_HHmmss')
        Move-Item -LiteralPath $destination -Destination $invalidPath
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Preserved invalid cached installer for inspection: {0}' -f $invalidPath)
    }

    return Invoke-PaperMinerMirrorDownload `
        -Configuration $Configuration `
        -DestinationPath $destination `
        -LogAction $LogAction
}

function Install-PaperMinerAnaconda {
    param(
        [Parameter(Mandatory = $true)]$Configuration,
        [scriptblock]$LogAction
    )

    $installRoot = [System.IO.Path]::GetFullPath(
        [string]$Configuration.InstallRoot)
    $condaBat = Join-Path $installRoot 'condabin\conda.bat'
    $condaExe = Join-Path $installRoot 'Scripts\conda.exe'
    if (Test-Path -LiteralPath $condaBat -PathType Leaf) {
        return [pscustomobject]@{ Root = $installRoot; Command = $condaBat }
    }
    if (Test-Path -LiteralPath $condaExe -PathType Leaf) {
        return [pscustomobject]@{ Root = $installRoot; Command = $condaExe }
    }

    if (Test-Path -LiteralPath $installRoot -PathType Container) {
        $existingItems = @(Get-ChildItem -LiteralPath $installRoot -Force -ErrorAction Stop)
        if ($existingItems.Count -gt 0) {
            throw ('Automatic Anaconda destination is not empty and does not contain Conda: {0}' -f
                $installRoot)
        }
    }
    else {
        $parent = Split-Path -Parent $installRoot
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Path $parent | Out-Null
        }
    }

    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Conda was not found. PaperMiner will install Anaconda {0} for the current user.' -f
        $Configuration.Version)
    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Anaconda destination: {0}' -f $installRoot)
    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Download size: approximately 1.04 GiB. The verified installer is kept for retry.')
    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Anaconda terms: https://www.anaconda.com/legal/terms/terms-of-service')

    $installer = Get-PaperMinerVerifiedAnacondaInstaller `
        -Configuration $Configuration `
        -LogAction $LogAction

    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Authenticode status: {0}' -f $signature.Status)
    }
    catch {
        Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
            'Authenticode inspection was unavailable; SHA-256 verification already passed.')
    }

    $arguments = '/InstallationType=JustMe /RegisterPython=0 /S /D={0}' -f
        $installRoot
    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Installing Anaconda silently. This can take several minutes...')
    $startedAt = Get-Date
    $process = Start-Process `
        -FilePath $installer `
        -ArgumentList $arguments `
        -Wait `
        -PassThru
    $elapsed = (Get-Date) - $startedAt
    Write-PaperMinerAnacondaLog -LogAction $LogAction -Message (
        'Anaconda installer exit code: {0}; elapsed: {1:hh\:mm\:ss}' -f
        $process.ExitCode, $elapsed)
    if ($process.ExitCode -ne 0) {
        throw ('Anaconda silent installation failed with exit code {0}.' -f
            $process.ExitCode)
    }

    if (Test-Path -LiteralPath $condaBat -PathType Leaf) {
        return [pscustomobject]@{ Root = $installRoot; Command = $condaBat }
    }
    if (Test-Path -LiteralPath $condaExe -PathType Leaf) {
        return [pscustomobject]@{ Root = $installRoot; Command = $condaExe }
    }
    throw ('Anaconda reported success, but Conda was not found under {0}.' -f
        $installRoot)
}
