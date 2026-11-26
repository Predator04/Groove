$ErrorActionPreference = 'Continue'
Write-Output "=== Groove processes before ==="
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'Groove.exe' } | ForEach-Object {
    Write-Output ("  pid=" + $_.ProcessId + " path=" + $_.ExecutablePath + " started=" + $_.CreationDate)
}
Write-Output "=== killing all Groove.exe ==="
Get-Process -Name Groove -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$left = Get-Process -Name Groove -ErrorAction SilentlyContinue
if ($left) { Write-Output ("STILL RUNNING: " + ($left.Id -join ',')) } else { Write-Output "all Groove processes stopped" }

Write-Output "=== deploying new exe ==="
Copy-Item 'C:\Users\Admin\Desktop\Groove\dist\Groove.exe' 'C:\Users\Admin\Groove\Groove.exe' -Force
if ($?) { Write-Output "copy OK" } else { Write-Output "copy FAILED"; exit 1 }

Write-Output "=== starting Groove ==="
Start-Process 'C:\Users\Admin\Groove\Groove.exe'
Start-Sleep -Seconds 4
$now = Get-Process -Name Groove -ErrorAction SilentlyContinue
if ($now) { Write-Output ("Groove running, pid=" + ($now.Id -join ',')) } else { Write-Output "Groove did NOT start" }
