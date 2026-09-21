# clash-royale-battle-analyzer 定期収集タスクの登録解除
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File scripts\unregister_task.ps1

param(
    [string]$TaskName = "ClashRoyaleBattleAnalyzer"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "タスク '$TaskName' は登録されていません。"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "タスク '$TaskName' を削除しました。" -ForegroundColor Green
Write-Host "収集は停止しますが、蓄積済みのデータはそのまま残ります。"
