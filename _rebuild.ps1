$ErrorActionPreference = 'Continue'
Write-Output "=== checking for a build already running ==="
$busy = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pyinstaller.exe') -and $_.CommandLine -match 'PyInstaller|Groove.spec' }
if ($busy) { Write-Output "WARN: a build appears to be running:"; $busy | ForEach-Object { Write-Output ("  " + $_.Name + " pid=" + $_.ProcessId) } }

Set-Location 'C:\Users\Admin\Desktop\Groove'

$candidates = @(
    'C:\Program Files\Python312\python.exe',
    'C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe',
    'C:\Program Files\Python313\python.exe'
)
$python = $null
foreach ($c in $candidates) {
    if (Test-Path $c) {
        $v = & $c -m PyInstaller --version 2>&1
        if ($LASTEXITCODE -eq 0) { $python = $c; Write-Output ("PyInstaller found via " + $c + " (v" + ($v -join ' ') + ")"); break }
    }
}
if (-not $python) {
    $v = & py -m PyInstaller --version 2>&1
    if ($LASTEXITCODE -eq 0) { $python = 'py'; Write-Output ("PyInstaller found via py launcher (v" + ($v -join ' ') + ")") }
}
if (-not $python) { Write-Output "NO PYINSTALLER FOUND"; exit 1 }

Write-Output "=== rebuilding Groove.exe (this takes 1-3 min) ==="
& $python -m PyInstaller Groove.spec --noconfirm --clean 2>&1 | Select-Object -Last 20

if (Test-Path 'dist\Groove.exe') {
    $sz = (Get-Item 'dist\Groove.exe').Length
    Write-Output ("build OK, dist\Groove.exe = " + $sz + " bytes")
    Copy-Item 'dist\Groove.exe' 'C:\Users\Admin\Groove\Groove.exe' -Force
    Write-Output "deployed to C:\Users\Admin\Groove\Groove.exe"
    Start-Process 'C:\Users\Admin\Groove\Groove.exe'
    Write-Output "Groove.exe restarted"
} else {
    Write-Output "BUILD FAILED - no dist\Groove.exe produced"
    exit 1
}
