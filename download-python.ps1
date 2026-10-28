# TGU Navigator - downloads portable Python with a visible progress bar.
# Called from run.bat. ASCII-only on purpose (Windows codepages).
#
# Compatibility notes (bug history):
#   * System.Net.Http.HttpClient is NOT available in Windows PowerShell 5.1
#     (.NET Framework) unless its assemblies are loaded explicitly, and even
#     then it can fail to resolve on stripped-down systems. That was the
#     "Ne udalos' nayti tip [System.Net.Http.HttpClient]" error.
#   * This version uses only types guaranteed to exist in PS 2.0+:
#       System.Net.HttpWebRequest / HttpWebResponse + plain file streams.
#     No external assemblies, no TLS tricks beyond a best-effort attempt.
$ErrorActionPreference = 'Stop'

# Best-effort TLS 1.2 (needed for github.com on old .NET; harmless if it fails)
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch { }

$url = 'https://github.com/indygreg/python-build-standalone/releases/download/20240814/cpython-3.11.9+20240814-x86_64-pc-windows-msvc-shared-install_only.tar.gz'
$out = Join-Path $env:TEMP 'tgu-py.tar.gz'

try {
    $req = [System.Net.HttpWebRequest]::Create($url)
    $req.UserAgent = 'tgu-navigator-installer'
    $req.Timeout = 30000              # connect/read timeout per chunk, ms
    $req.ReadWriteTimeout = 60000
    $resp = $req.GetResponse()

    $total = $resp.ContentLength      # -1 when the server hides it
    if ($total -lt 0) { $total = 0 }

    $stream = $resp.GetResponseStream()
    $fs = [System.IO.File]::Create($out)
    $buf = New-Object byte[] 65536
    $cumulative = [int64]0
    $startTime = Get-Date
    $lastPrint = [DateTime]::MinValue

    while ($true) {
        $read = $stream.Read($buf, 0, $buf.Length)
        if ($read -le 0) { break }
        $fs.Write($buf, 0, $read)
        $cumulative += [int64]$read

        $now = Get-Date
        if (($now - $lastPrint).TotalMilliseconds -lt 250 -and ($total -eq 0 -or $cumulative -lt $total)) { continue }
        $lastPrint = $now

        $pct = 0
        if ($total -gt 0) { $pct = [math]::Min(100, [int](100 * $cumulative / $total)) }
        $mb = [math]::Round($cumulative / 1MB, 1)
        $secs = [math]::Max(0.1, ($now - $startTime).TotalSeconds)
        $speed = [math]::Round($cumulative / 1MB / $secs, 1)
        $barLen = 30
        $filled = 0
        if ($total -gt 0) {
            $filled = [int]($barLen * $cumulative / $total)
            if ($filled -gt $barLen) { $filled = $barLen }
        } else {
            $filled = [int]$secs % ($barLen + 1)
        }
        $bar = ('#' * $filled).PadRight($barLen, '.')
        if ($total -gt 0) {
            $eta = [math]::Max(0, [int](($total - $cumulative) / 1MB / [math]::Max($speed, 0.1)))
            $line = "  [" + $bar + "] " + $pct.ToString().PadLeft(3) + "%  " + $mb + "/" + [math]::Round($total / 1MB, 1) + " MB  " + $speed + " MB/s  eta " + $eta + "s"
        } else {
            $line = "  [" + $bar + "] " + $mb + " MB  " + $speed + " MB/s"
        }
        Write-Host $line -NoNewline -ForegroundColor Cyan
        Write-Host "`r" -NoNewline
    }

    Write-Host ""
    $fs.Close()
    $stream.Close()
    $resp.Close()

    $size = (Get-Item $out).Length
    if ($size -lt 1MB) { throw "Downloaded file is too small ($size bytes), something went wrong." }
    exit 0
} catch {
    Write-Host ""
    Write-Host ("  Download problem: " + $_.Exception.Message) -ForegroundColor Yellow
    exit 1
}
