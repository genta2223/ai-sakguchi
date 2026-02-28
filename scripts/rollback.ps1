# rollback.ps1 — AI阪口源太 ロールバックスクリプト
# 使い方: .\scripts\rollback.ps1 202602282201
# 効果: 指定したバックアップのコードで現在のファイルを上書きし、git push

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupName
)

$BackupRoot = "c:\Users\genta\anno-ai-avatar-main\backup"
$SourceDir  = "c:\Users\genta\anno-ai-avatar-main\ai-sakguchi-deploy"
$BackupDir  = Join-Path $BackupRoot $BackupName

if (-not (Test-Path $BackupDir)) {
    Write-Host "❌ Backup not found: $BackupDir" -ForegroundColor Red
    Write-Host "Available backups:" -ForegroundColor Cyan
    Get-ChildItem -Path $BackupRoot -Directory | Sort-Object Name -Descending | ForEach-Object {
        Write-Host "  $($_.Name)" -ForegroundColor White
    }
    exit 1
}

# 主要ファイルを上書き
$filesToRestore = @(
    "app.py", "core_ai_worker.py", "brain.py", "tts.py",
    "youtube_monitor.py", "core_paths.py", "requirements.txt"
)

foreach ($f in $filesToRestore) {
    $src = Join-Path $BackupDir $f
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $SourceDir $f) -Force
        Write-Host "  Restored: $f" -ForegroundColor Green
    }
}

# staticフォルダを復元
$staticBackup = Join-Path $BackupDir "static"
if (Test-Path $staticBackup) {
    Copy-Item -Path $staticBackup -Destination (Join-Path $SourceDir "static") -Recurse -Force
    Write-Host "  Restored: static/" -ForegroundColor Green
}

Write-Host "`n✅ Rollback to $BackupName complete." -ForegroundColor Green
Write-Host "Run the following to push:" -ForegroundColor Cyan
Write-Host "  cd $SourceDir" -ForegroundColor White
Write-Host "  git add -A; git commit -m 'rollback: Revert to $BackupName'; git push origin main" -ForegroundColor White
