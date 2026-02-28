# backup.ps1 — AI阪口源太 バージョン管理スクリプト
# 使い方: .\scripts\backup.ps1
# 効果: 現在のコードをタイムスタンプ付きでバックアップし、7日以上古いものを自動削除

$BackupRoot = "c:\Users\genta\anno-ai-avatar-main\backup"
$SourceDir  = "c:\Users\genta\anno-ai-avatar-main\ai-sakguchi-deploy"
$Timestamp  = Get-Date -Format "yyyyMMddHHmm"
$TargetDir  = Join-Path $BackupRoot $Timestamp

# 1. バックアップ作成
New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

$filesToBackup = @(
    "app.py", "core_ai_worker.py", "brain.py", "tts.py",
    "youtube_monitor.py", "core_paths.py", "requirements.txt"
)

foreach ($f in $filesToBackup) {
    $src = Join-Path $SourceDir $f
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $TargetDir
    }
}

# staticフォルダもコピー
$staticSrc = Join-Path $SourceDir "static"
if (Test-Path $staticSrc) {
    Copy-Item -Path $staticSrc -Destination (Join-Path $TargetDir "static") -Recurse
}

Write-Host "✅ Backup created: $TargetDir" -ForegroundColor Green

# 2. 7日以上古いバックアップを自動削除 (ディレクトリ名がyyyyMMddHHmmの形式)
$cutoff = (Get-Date).AddDays(-7)
Get-ChildItem -Path $BackupRoot -Directory | ForEach-Object {
    try {
        $dirDate = [DateTime]::ParseExact($_.Name, "yyyyMMddHHmm", $null)
        if ($dirDate -lt $cutoff) {
            Remove-Item -Path $_.FullName -Recurse -Force
            Write-Host "🗑️ Deleted old backup: $($_.Name)" -ForegroundColor Yellow
        }
    } catch {
        # ディレクトリ名がタイムスタンプ形式でない場合はスキップ
    }
}

# 3. 残っているバックアップを一覧表示
Write-Host "`n📦 Available backups:" -ForegroundColor Cyan
Get-ChildItem -Path $BackupRoot -Directory | Sort-Object Name -Descending | ForEach-Object {
    Write-Host "  $($_.Name)" -ForegroundColor White
}
