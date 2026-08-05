$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = (Get-Location).Path
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $true
$watcher.Filter = "*.*"

$lastRun = Get-Date

Register-ObjectEvent $watcher Changed -Action {
    $now = Get-Date

    # Prevent multiple commits from the same save event
    if (($now - $global:lastRun).TotalSeconds -lt 2) {
        return
    }

    $global:lastRun = $now

    Start-Sleep -Milliseconds 500

    git add .

    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        return
    }

    $msg = "Auto commit $($now.ToString('yyyy-MM-dd HH:mm:ss'))"
    git commit -m $msg
    git push

    Write-Host "Committed and pushed at $msg"
}

Write-Host "Watching for file changes..."
while ($true) {
    Start-Sleep -Seconds 1
}