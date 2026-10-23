<#
Builds dist/DeskSister-Setup.exe: a PyInstaller one-folder build of the app, wrapped by Inno Setup.

    ./devtools/build_installer.ps1                 # version from pyproject.toml
    ./devtools/build_installer.ps1 -Version 0.1.16
    ./devtools/build_installer.ps1 -AppId '{{...}'  # a test build that never touches the real install's entry

Needs Inno Setup 6 (ISCC.exe): from PATH, its per-user or its machine-wide install folder, or -Iscc.
The single-file dist/desk-sister.exe is still made by scripts/package.ps1; this script does not touch it.
#>
param(
    [string]$Version,
    [string]$Iscc,
    [string]$AppId,
    [string]$Python,
    [switch]$FailForTest,  # a test build whose install fails after copying, to check the old version comes back
    [switch]$CancelForTest  # a test build that gives up before installing
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if (-not $Version) {
    $match = Select-String -LiteralPath (Join-Path $root 'pyproject.toml') -Pattern '^version = "([^"]+)"' | Select-Object -First 1
    if (-not $match) { throw 'No version in pyproject.toml' }
    $Version = $match.Matches[0].Groups[1].Value
}
# The same versions release.yml accepts; Windows' file version takes only the numbers.
if ($Version -notmatch '^([0-9]+\.[0-9]+\.[0-9]+)(-[0-9A-Za-z.-]+)?$') { throw "Invalid version: $Version" }
$numeric = $Matches[1]

if (-not $Python) {
    $venv = Join-Path $root '.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $venv) { $venv } else { 'python' }
}
if (-not $Iscc) {
    $candidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $Iscc = $candidates | Select-Object -First 1
    if (-not $Iscc) { throw 'Inno Setup 6 (ISCC.exe) not found; install it or pass -Iscc' }
}

$build = Join-Path $root 'build\onedir'
$app = Join-Path $build 'desk-sister'
if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
$icon = Join-Path $root 'assets\icon.ico'
& $Python -m PyInstaller --noconfirm --onedir --windowed --paths (Join-Path $root 'src') --name desk-sister `
    --distpath $build --workpath (Join-Path $root 'build\pyinstaller-onedir') --specpath (Join-Path $root 'build\onedir-spec') `
    --icon $icon (Join-Path $root 'app.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

# The one-folder build must pass the same self-test as the single-file exe.
$selfTest = Start-Process -FilePath (Join-Path $app 'desk-sister.exe') -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow
if ($selfTest.ExitCode -ne 0) { throw "One-folder self-test failed ($($selfTest.ExitCode))" }

$arguments = @("/DVersion=$Version", "/DNumericVersion=$numeric", "/DSourceDir=$app")
if ($AppId) { $arguments += "/DAppIdValue=$AppId" }
if ($FailForTest) { $arguments += '/DFailForTest' }
if ($CancelForTest) { $arguments += '/DCancelForTest' }
$arguments += (Join-Path $root 'installer\desk-sister.iss')
& $Iscc @arguments
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
$setup = Join-Path $root 'dist\DeskSister-Setup.exe'
Get-Item -LiteralPath $setup | Select-Object Name, Length
