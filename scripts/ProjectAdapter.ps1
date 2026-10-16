. (Join-Path $PSScriptRoot 'Common.ps1')
function Test-RuffConfigured([string]$Python, [string]$Root) {
    # Parsed, not pattern-matched: [tool.ruff_extra] or text inside strings must not enable ruff; quoted keys and
    # subtables must. A pyproject that does not parse fails verification.
    $code = Invoke-FactoryCommand $Python @('-c','import sys, tomllib; data = tomllib.load(open("pyproject.toml", "rb")); tool = data.get("tool"); sys.exit(0 if isinstance(tool, dict) and isinstance(tool.get("ruff"), dict) else 3)') $Root 120 -AllowedExitCodes 0,3 -PassThruExitCode
    return $code -eq 0
}
function Invoke-ProjectAction {
    param([ValidateSet('verify','build','package')][string]$Action,[string]$ProjectPath,[int]$TimeoutSec=600)
    $root = (Resolve-Path -LiteralPath $ProjectPath).Path
    $manifestPath = Join-Path $root '.ai-factory.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Missing .ai-factory.json; project structure is not a supported factory project.' }
    $config = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($config.name -notmatch '^[a-z][a-z0-9-]{0,47}$') { throw 'Unsafe project name in manifest' }
    if ($Action -eq 'package') {
        Invoke-ProjectAction verify $root $TimeoutSec
        Invoke-ProjectAction build $root $TimeoutSec
        New-Item -ItemType Directory -Path (Join-Path $root 'dist') -Force | Out-Null
    }
    switch ($config.type) {
        'python' {
            $python = Get-ProjectPython $root
            if (-not (Test-Path -LiteralPath (Join-Path $root 'pyproject.toml'))) { throw 'Missing pyproject.toml' }
            if ($Action -eq 'verify') {
                Invoke-FactoryCommand $python @('-m','pytest','-q','tests') $root $TimeoutSec
                Invoke-FactoryCommand $python @('-m','compileall','-q','src') $root $TimeoutSec
                # Opt-in per project: generated projects carry [tool.ruff]; older projects keep verifying unchanged.
                if (Test-RuffConfigured $python $root) { Invoke-FactoryCommand $python @('-m','ruff','check','--no-cache','.') $root $TimeoutSec }
                Invoke-FactoryCommand $python @('app.py','--self-test') $root $TimeoutSec
            } elseif ($Action -eq 'build') {
                Invoke-FactoryCommand $python @('-m','build','--no-isolation','--sdist','--wheel','--outdir','build') $root $TimeoutSec
            } else {
                $arguments = @('-m','PyInstaller','--noconfirm','--onefile','--paths','src','--name',$config.name,'--distpath','dist','--workpath','build/pyinstaller','--specpath','build')
                if ($config.windowsGui) { $arguments += '--windowed' }
                if ($config.icon) {
                    # Absolute path: PyInstaller resolves a relative --icon against --specpath (build/).
                    $icon = [IO.Path]::GetFullPath((Join-Path $root $config.icon))
                    if (-not $icon.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $icon -PathType Leaf)) {
                        throw "Icon not found inside the project: $($config.icon)"
                    }
                    $arguments += @('--icon', $icon)
                }
                $arguments += 'app.py'
                Invoke-FactoryCommand $python $arguments $root $TimeoutSec
            }
        }
        'node' {
            if (-not (Test-Path -LiteralPath (Join-Path $root 'package.json'))) { throw 'Missing package.json' }
            if ($Action -eq 'verify') {
                Invoke-Npm $root @('test') $TimeoutSec
                # Tests only load the modules they import; syntax-check every source file so unused ones cannot rot.
                $node = Get-RequiredCommand node
                $sources = @(foreach ($folder in @('src','scripts')) {
                    $path = Join-Path $root $folder
                    if (Test-Path -LiteralPath $path) { Get-ChildItem -LiteralPath $path -Recurse -File | Where-Object { $_.Extension -in '.js','.mjs','.cjs' } }
                })
                foreach ($source in $sources) { Invoke-FactoryCommand $node @('--check',$source.FullName) $root $TimeoutSec }
            }
            elseif ($Action -eq 'build') { Invoke-Npm $root @('run','build') $TimeoutSec }
            else { Compress-Archive -LiteralPath (Join-Path $root 'build/app'),(Join-Path $root 'package.json'),(Join-Path $root 'README.md') -DestinationPath (Join-Path $root "dist/$($config.name).zip") -Force }
        }
        { $_ -in 'c','cpp' } {
            $cmake = Get-RequiredCommand cmake
            if (-not (Test-Path -LiteralPath (Join-Path $root 'CMakeLists.txt'))) { throw 'Missing CMakeLists.txt' }
            if (-not (Test-Path -LiteralPath (Join-Path $root 'build/CMakeCache.txt'))) {
                $arguments = @('-S','.','-B','build','-DCMAKE_BUILD_TYPE=Release')
                if ((Get-Command ninja -ErrorAction SilentlyContinue) -and (Get-Command gcc -ErrorAction SilentlyContinue)) { $arguments += @('-G','Ninja',"-DCMAKE_C_COMPILER=$(Get-RequiredCommand gcc)","-DCMAKE_CXX_COMPILER=$(Get-RequiredCommand g++)") }
                Invoke-FactoryCommand $cmake $arguments $root $TimeoutSec
            }
            Invoke-FactoryCommand $cmake @('--build','build','--config','Release') $root $TimeoutSec
            if ($Action -eq 'verify') {
                Invoke-FactoryCommand (Get-RequiredCommand ctest) @('--test-dir','build','-C','Release','--output-on-failure','--no-tests=error') $root $TimeoutSec
                $binary = Join-Path $root 'build/app'
                if ($IsWindows) { $binary += '.exe' }
                if (-not (Test-Path -LiteralPath $binary)) { $binary = Join-Path $root 'build/Release/app.exe' }
                Invoke-FactoryCommand $binary @() $root $TimeoutSec
            } elseif ($Action -eq 'package') {
                Invoke-FactoryCommand $cmake @('--install','build','--config','Release','--prefix','dist/runtime') $root $TimeoutSec
                Compress-Archive -LiteralPath (Join-Path $root 'dist/runtime') -DestinationPath (Join-Path $root "dist/$($config.name).zip") -Force
            }
        }
        'dotnet' {
            $dotnet = Get-RequiredCommand dotnet
            $sdks = Invoke-FactoryCommand $dotnet @('--list-sdks') $root $TimeoutSec -Capture
            if (-not $sdks) { throw '.NET executable exists but SDK is missing. Install .NET 8 SDK on demand.' }
            if ($Action -eq 'verify') {
                Invoke-FactoryCommand $dotnet @('test','tests/App.Tests.csproj','--configuration','Release') $root $TimeoutSec
                Invoke-FactoryCommand $dotnet @('run','--project','src/App.csproj','--configuration','Release','--','--self-test') $root $TimeoutSec
            } elseif ($Action -eq 'build') { Invoke-FactoryCommand $dotnet @('build','src/App.csproj','--configuration','Release') $root $TimeoutSec }
            else { Invoke-FactoryCommand $dotnet @('publish','src/App.csproj','--configuration','Release','--runtime','win-x64','--self-contained','true','-o','dist/app') $root $TimeoutSec; Compress-Archive -LiteralPath (Join-Path $root 'dist/app') -DestinationPath (Join-Path $root "dist/$($config.name)-win-x64.zip") -Force }
        }
        default { throw "Unsupported adapter: $($config.type)" }
    }
    Write-Host "[PASS] $Action : $($config.name)"
}
