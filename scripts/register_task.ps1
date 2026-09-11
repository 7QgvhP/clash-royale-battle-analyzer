# clash-royale-battle-analyzer 定期収集タスクの登録
#
# Windowsタスクスケジューラに、対戦履歴を定期収集するタスクを登録する。
# バトルログは直近の数十戦しか取得できないため、定期実行が必須となる。
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -IntervalMinutes 30
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Publish -DailyAt 23:00

param(
    [int]$IntervalMinutes = 60,
    # "23:00" のように指定すると、毎日その時刻に1回だけ実行する。
    # 指定した場合 -IntervalMinutes は使われない。
    [string]$DailyAt = "",
    [string]$TaskName = "ClashRoyaleBattleAnalyzer",
    # スリープ中も収集するため、既定でスリープを解除して実行する。
    # 解除させたくない場合は -NoWake を付ける。
    [switch]$NoWake,
    # 収集に加えて静的サイトの書き出しと公開まで行う。
    [switch]$Publish
)

$ErrorActionPreference = "Stop"

# プロジェクトのルートディレクトリを求める
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 使用するPythonを特定する
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Host "python が見つかりません。PATH を確認してください。" -ForegroundColor Red
    exit 1
}

Write-Host "プロジェクト : $ProjectRoot"
Write-Host "Python       : $Python"
if ($DailyAt) {
    Write-Host "実行タイミング: 毎日 $DailyAt"
} else {
    Write-Host "実行タイミング: $IntervalMinutes 分おき"
}
Write-Host ("スリープ解除 : {0}" -f $(if ($NoWake) { "しない" } else { "する（AC電源接続時のみ有効）" }))
Write-Host "タスク名     : $TaskName"
Write-Host ("動作         : {0}" -f $(if ($Publish) { "収集＋公開" } else { "収集のみ" }))
Write-Host ""

# 既存の同名タスクがあれば削除する
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "既存のタスクを削除します。"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# -Publish を付けた場合は、収集から公開までを一括で行うコマンドを登録する。
$Module = if ($Publish) { "src.exporter.publish" } else { "src.collector.collect" }

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m $Module" `
    -WorkingDirectory $ProjectRoot

# -DailyAt を指定した場合は毎日1回、そうでなければ指定間隔で繰り返す。
if ($DailyAt) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
} else {
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
}

# ノートPCでもバッテリー駆動中に停止しないようにする。
# WakeToRun はスリープからPCを復帰させて収集するための設定。
# ただしAC電源に接続していないと、スリープ解除タイマー自体が無効化される。
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun:(-not $NoWake) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $(if ($Publish) { 30 } else { 10 }))

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "クラッシュロワイヤルの対戦履歴を定期収集する" | Out-Null

Write-Host "登録しました。" -ForegroundColor Green
Write-Host ""
Write-Host "確認  : Get-ScheduledTask -TaskName $TaskName"
Write-Host "手動実行: Start-ScheduledTask -TaskName $TaskName"
Write-Host "解除  : powershell -ExecutionPolicy Bypass -File scripts\unregister_task.ps1"
Write-Host ""
Write-Host "収集ログは data\logs\collect.log に出力されます。"
Write-Host ""
if ($DailyAt) {
    Write-Host "1日1回の収集では、その日に30戦以上プレイすると取りこぼします。" -ForegroundColor Yellow
    Write-Host "対戦数が増えてきたら -IntervalMinutes での間隔指定に戻してください。"
    Write-Host ""
}
if (-not $NoWake) {
    Write-Host "スリープ中もPCを復帰させて収集します。" -ForegroundColor Yellow
    Write-Host "AC電源に接続していない場合は動作しません（Windowsの既定動作）。"
    Write-Host "復帰時に画面が点灯することがあります。不要なら -NoWake を付けて登録し直してください。"
}
