$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $projectRoot "Start_Dashboard.bat"

if (!(Test-Path $target)) {
  throw "Start_Dashboard.bat was not found in $projectRoot"
}

$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if (!$desktop) {
  $desktop = Join-Path $env:USERPROFILE "Desktop"
}
if (!(Test-Path $desktop)) {
  $oneDriveDesktop = Join-Path $env:OneDrive "Desktop"
  if ($env:OneDrive -and (Test-Path $oneDriveDesktop)) {
    $desktop = $oneDriveDesktop
  }
}
if (!(Test-Path $desktop)) {
  throw "Could not find Desktop folder."
}
$shortcutPath = Join-Path $desktop "1L Lead Engine Dashboard.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Open the 1L Lead Engine Dashboard"
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$shortcut.Save()

Write-Host "Created desktop shortcut:"
Write-Host $shortcutPath
