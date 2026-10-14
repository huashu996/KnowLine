# Only prepare verified DLLs shipped with this installation. User data is never unblocked.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [switch]$SelfTest,
    [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
$state = Join-Path $root 'resource\.knowledge'
$startupLog = Join-Path $state 'startup.log'
$report = Join-Path $state 'desktop-startup-check.json'

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose(); $stream.Dispose() }
}

function Get-PackageFile([string]$RelativePath) {
    if ($RelativePath -notmatch '^app/(Knowline/|dist/)' -or
        $RelativePath -match '(^|/)\.\.?(/|$)|[:\\]') {
        throw "Invalid runtime path in release manifest: $RelativePath"
    }
    $target = [IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Runtime path is outside this installation.'
    }
    $item = Get-Item -LiteralPath $target -Force
    if ($item.PSIsContainer) { throw "Expected a file: $RelativePath" }
    $ancestor = $item
    while ($null -ne $ancestor -and $ancestor.FullName.Length -ge $root.Length) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Linked runtime paths are not supported: $RelativePath"
        }
        if ($ancestor -is [IO.FileInfo]) { $ancestor = $ancestor.Directory }
        else { $ancestor = $ancestor.Parent }
    }
    return $item
}

try {
    $manifestPath = Join-Path $root 'app\docs\RELEASE_MANIFEST.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $required = @('app/Knowline/Knowline.exe', 'app/dist/index.html',
        'app/Knowline/_internal/pythonnet/runtime/Python.Runtime.dll',
        'app/Knowline/_internal/webview/lib/Microsoft.Web.WebView2.Core.dll',
        'app/Knowline/_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll')
    $entries = @($manifest.files | Where-Object {
        $_.path -in $required -or $_.path -match '^app/Knowline/_internal/.+\.dll$'
    })
    foreach ($relative in $required) {
        if (@($entries | Where-Object path -eq $relative).Count -ne 1) {
            throw "Missing or duplicate release manifest entry: $relative"
        }
    }
    $blocked = @()
    # Validate every selected file before changing any download-origin marker.
    foreach ($entry in $entries) {
        $item = Get-PackageFile $entry.path
        if ($item.Length -ne $entry.bytes -or
            (Get-Sha256 $item.FullName) -ne $entry.sha256) {
            throw "Release file is incomplete or changed: $($entry.path). Please extract a fresh GitHub ZIP."
        }
        if ($item.Extension -ieq '.dll' -and
            (Get-Item -LiteralPath $item.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue)) {
            $blocked += $item.FullName
        }
    }
    foreach ($path in $blocked) { Unblock-File -LiteralPath $path }
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    $audit = [ordered]@{
        release = $manifest.release
        verified_files = $entries.Count
        unblocked_packaged_dlls = $blocked.Count
        started_at = [DateTimeOffset]::Now.ToString('o')
        status = 'runtime_ready'
    }
    $audit | ConvertTo-Json | Set-Content -LiteralPath $startupLog -Encoding UTF8
    if ($PrepareOnly) { $audit | ConvertTo-Json; exit 0 }

    $exe = Join-Path $root 'app\Knowline\Knowline.exe'
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $exe
    $startInfo.WorkingDirectory = $root
    $startInfo.UseShellExecute = $false
    $startInfo.Arguments = '--project "' + $root + '"'
    if ($SelfTest) {
        if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
        $startInfo.Arguments += ' --self-test-report "' + $report + '"'
    }
    $process = [Diagnostics.Process]::Start($startInfo)
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) {
            if ($SelfTest -and (Test-Path -LiteralPath $report)) {
                $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($process.ExitCode -eq 0 -and $result.passed) {
                    $audit.status = 'desktop_self_test_passed'
                    $audit | ConvertTo-Json | Set-Content -LiteralPath $startupLog -Encoding UTF8
                    Get-Content -LiteralPath $report -Raw -Encoding UTF8
                    exit 0
                }
                throw "Desktop self-test failed: $($result.error). Report: $report"
            }
            throw "Desktop exited before opening (code $($process.ExitCode)). Run StartKnowline.cmd -SelfTest for details. Check Microsoft Edge WebView2 Runtime is installed."
        }
        if (-not $SelfTest -and $process.MainWindowHandle -ne [IntPtr]::Zero -and
            $process.MainWindowTitle -like 'Knowline*') {
            $audit.status = 'desktop_opened'
            $audit.process_id = $process.Id
            $audit | ConvertTo-Json | Set-Content -LiteralPath $startupLog -Encoding UTF8
            exit 0
        }
        Start-Sleep -Milliseconds 250
    }
    if ($SelfTest -and -not $process.HasExited) { $process.Kill() }
    throw "Desktop did not open within 60 seconds. Check $startupLog and run StartKnowline.cmd -SelfTest."
} catch {
    $message = $_.Exception.Message
    try {
        New-Item -ItemType Directory -Path $state -Force | Out-Null
        ('Startup failed: ' + $message) | Set-Content -LiteralPath $startupLog -Encoding UTF8
    } catch { }
    [Console]::Error.WriteLine('Knowline: ' + $message)
    exit 1
}
