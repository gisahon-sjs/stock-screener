param(
    [string]$Title = "Stock Screener 실패",
    [string]$Body = "스캔이 실패했습니다. 로그를 확인하세요."
)
Add-Type -AssemblyName System.Windows.Forms
$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Warning
$icon.Visible = $true
$icon.ShowBalloonTip(15000, $Title, $Body, [System.Windows.Forms.ToolTipIcon]::Warning)
Start-Sleep -Seconds 16
$icon.Dispose()
