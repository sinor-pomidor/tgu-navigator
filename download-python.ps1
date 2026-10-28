# TGU Navigator - downloads portable Python with a visible progress bar.
# Called from run.bat. ASCII-only on purpose (Windows codepages).
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$url = 'https://github.com/indygreg/python-build-standalone/releases/download/20240814/cpython-3.11.9+20240814-x86_64-pc-windows-msvc-shared-install_only.tar.gz'
$out = Join-Path $env:TEMP 'tgu-py.tar.gz'

try {
    # Get total size first (best effort; some servers hide it)
    $total = 0
    try {
        $head = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 15
        $total = [int64]$head.Headers['Content-Length']
    } catch { $total = 0 }

    $wc = New-Object System.Net.WebClient
    $done = [int64]0
    $startTime = Get-Date
    $lastPrint = 0
    $finished = $false
    $failMsg = ''

    $downloadedHandler = {
        param($s, $e)
        $script:done = $e.ProgressBytesReceived + $script:baseOffset
    }

    # Use BITS-free approach: read stream in chunks for accurate progress
    $req = [System.Net.Http.HttpClient]::new()
    $req.Timeout = [TimeSpan]::FromMinutes(10)
    $respTask = $req.GetStreamAsync($url)
    while (-not $respTask.IsCompleted) { Start-Sleep -Milliseconds 200 }
    if ($respTask.IsFaulted) { throw $respTask.Exception.InnerException }
    $stream = $respTask.Result

    $fs = [System.IO.File]::Create($out)
    $buf = New-Object byte[] 65536
    $read = 0
    $cumulative = [int64]0
    while (($read = $stream.Read($buf, 0, $buf.Length)) -gt 0) {
        $fs.Write($buf, 0, $read)
        $cumulative += $read
        $pct = 0
        if ($total -gt 0) { $pct = [math]::Min(100, [int](100 * $cumulative / $total)) }
        $mb = [math]::Round($cumulative / 1MB, 1)
        $barLen = 30
        $filled = 0
        if ($total -gt 0) { $filled = [int]($barLen * $cumulative / $total); if ($filled -gt $barLen) { $filled = $barLen } }
        else { $filled = [int]((Get-Date) - $startTime).TotalSeconds % ($barLen + 1) }
        $bar = ('#' * $filled).PadRight($barLen, '.')
        if ($total -gt 0) {
            Write-Host ("  [" + $bar + "] " + $pct + "%  " + $mb + " MB of " + [math]::Round($total / 1MB, 1) + " MB") `
                -NoNewline -ForegroundColor Cyan
            Write-Host "`r" -NoNewline
        } else {
            Write-Host ("  [" + $bar + "] " + $mb + " MB downloaded...") `
                -NoNewline -ForegroundColor Cyan
            Write-Host "`r" -NoNewline
        }
    }
    Write-Host ""
    $fs.Close()
    $stream.Close()
    $req.Dispose()

    $size = (Get-Item $out).Length
    if ($size -lt 1MB) { throw "Downloaded file is too small ($size bytes), something went wrong." }
    exit 0
} catch {
    Write-Host ""
    Write-Host ("  Download problem: " + $_.Exception.Message) -ForegroundColor Yellow
    exit 1
}
