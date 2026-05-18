param(
  [string]$PythonVersion = "3.13.13",
  [switch]$SkipPythonDownload
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-ProjectRoot {
  if (!(Test-Path ".\main.py") -or !(Test-Path ".\dashboard.py") -or !(Test-Path ".\requirements.txt")) {
    throw "Run this from C:\Users\tyler\OneDrive\Documents\New project"
  }
}

function Get-Python313 {
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      $path = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $path) {
        return $path.Trim()
      }
    } finally {
      $ErrorActionPreference = $oldPreference
    }
  }

  $localPython = Join-Path (Get-Location) ".python313\python.exe"
  if (Test-Path $localPython) {
    return $localPython
  }

  $commonPaths = @(
    "C:\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "C:\Program Files\Python313\python.exe"
  )
  foreach ($candidate in $commonPaths) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return ""
}

function Download-PythonInstaller {
  param([string]$Version)

  $installerDir = Join-Path (Get-Location) ".installers"
  New-Item -ItemType Directory -Force -Path $installerDir | Out-Null

  $installer = Join-Path $installerDir "python-$Version-amd64.exe"
  if (Test-Path $installer) {
    return $installer
  }

  $url = "https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"
  Write-Step "Downloading Python $Version from python.org"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

  try {
    Invoke-WebRequest -Uri $url -OutFile $installer
  } catch {
    Write-Host "Invoke-WebRequest failed. Trying curl.exe..." -ForegroundColor Yellow
    curl.exe -L $url -o $installer
  }

  if (!(Test-Path $installer)) {
    throw "Python installer download failed. Download it manually from https://www.python.org/downloads/latest/python3.13/ and save it to $installer"
  }

  return $installer
}

function Install-LocalPython {
  param([string]$Installer)

  $target = Join-Path (Get-Location) ".python313"
  New-Item -ItemType Directory -Force -Path $target | Out-Null

  Write-Step "Installing Python locally into $target"
  $args = @(
    "/quiet",
    "InstallAllUsers=0",
    "TargetDir=$target",
    "Include_launcher=0",
    "PrependPath=0",
    "AssociateFiles=0",
    "Include_test=0",
    "Include_doc=0",
    "Include_pip=1"
  )

  $process = Start-Process -FilePath $Installer -ArgumentList $args -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    throw "Python installer failed with exit code $($process.ExitCode)"
  }

  $python = Join-Path $target "python.exe"
  if (!(Test-Path $python)) {
    throw "Local Python install did not create $python"
  }

  return $python
}

function Reset-VenvIfWrongPython {
  param([string]$Python)

  if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    return
  }

  $venvVersion = & .\.venv\Scripts\python.exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($venvVersion -eq "3.13" -or $venvVersion -eq "3.12") {
    return
  }

  Write-Host ""
  Write-Host ".venv exists but uses Python $venvVersion. CrewAI needs Python 3.13 or 3.12." -ForegroundColor Yellow
  $answer = Read-Host "Remove and recreate .venv now? Type YES"
  if ($answer -eq "YES") {
    Remove-Item -Recurse -Force ".\.venv"
  } else {
    throw "Stopped before changing .venv."
  }
}

Assert-ProjectRoot

Write-Step "Checking for Python 3.13"
$python = Get-Python313

if (!$python -and !$SkipPythonDownload) {
  $installer = Download-PythonInstaller -Version $PythonVersion
  $python = Install-LocalPython -Installer $installer
}

if (!$python) {
  throw "Python 3.13 was not found. Install it manually, then rerun this script."
}

Write-Host "Using Python: $python" -ForegroundColor Green
& $python --version

Reset-VenvIfWrongPython -Python $python

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Step "Creating .venv"
  & $python -m venv .venv
}

Write-Step "Installing Python packages"
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Step "Running smoke test"
& .\.venv\Scripts\python.exe main.py --dry-run --smoke-test

Write-Host ""
Write-Host "Setup complete. Start the dashboard with:" -ForegroundColor Green
Write-Host 'python dashboard.py 8787'
