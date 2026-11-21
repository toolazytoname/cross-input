param(
    [Parameter(Mandatory = $true)][string]$ResultFile,
    [Parameter(Mandatory = $true)][string]$ReadyFile,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Cross Input keyboard acceptance'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(700, 220)
$form.TopMost = $true
$textBox = New-Object System.Windows.Forms.TextBox
$textBox.Multiline = $true
$textBox.Dock = 'Fill'
$textBox.Font = New-Object System.Drawing.Font('Consolas', 14)
$form.Controls.Add($textBox)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = $TimeoutSeconds * 1000
$timer.add_Tick({ $form.Close() })
$form.add_Shown({
    $textBox.Focus()
    [IO.File]::WriteAllText($ReadyFile, '{"ready":true}')
    $timer.Start()
})
$form.ShowDialog()
[Console]::Out.WriteLine((@{ captured_text = $textBox.Text } | ConvertTo-Json -Compress))
if ($null -ne $ResultFile) {
    [IO.File]::WriteAllText($ResultFile, $textBox.Text, (New-Object System.Text.UTF8Encoding($false)))
}
