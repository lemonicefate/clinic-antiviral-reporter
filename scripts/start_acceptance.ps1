$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ClinicReporterAcceptance\case-queue-v1'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
function Get-AcceptanceUrl {
    $metadataPath = Join-Path $runtimeRoot 'current.json'
    if (Test-Path -LiteralPath $metadataPath) {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
        $uri = [Uri]$metadata.url
        if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1') { throw 'Invalid local acceptance address.' }
        try {
            $status = Invoke-RestMethod -Uri ($metadata.url + 'status') -TimeoutSec 2
            if ($null -ne $status.running) { return $metadata.url }
        } catch { return $null }
    }
    return $null
}
$url = Get-AcceptanceUrl
if (-not $url) {
    $process = Start-Process -FilePath (Join-Path $repository '.venv\Scripts\python.exe') `
        -ArgumentList @('-m', 'scripts.acceptance_environment') -WorkingDirectory $repository `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeRoot 'stdout.log') `
        -RedirectStandardError (Join-Path $runtimeRoot 'stderr.log')
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 250
        $url = Get-AcceptanceUrl
        if ($url) { break }
        if ($process.HasExited) { throw 'Acceptance environment failed to start.' }
    }
    if (-not $url) { throw 'Acceptance startup timed out.' }
}
Write-Output "Synthetic acceptance ready: $url"
Start-Process $url
