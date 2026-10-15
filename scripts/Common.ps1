#requires -Version 7.2
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Match the UTF-8 readers even when a Windows caller uses a legacy code page.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
function Resolve-FactoryRoot {
    $candidate = Split-Path $PSScriptRoot -Parent
    while ($candidate) {
        if ((Test-Path -LiteralPath (Join-Path $candidate 'scripts/Enter-Factory.ps1')) -and (Test-Path -LiteralPath (Join-Path $candidate 'templates/python'))) { return $candidate }
        $parent = Split-Path $candidate -Parent
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
    if ($env:AI_FACTORY_ROOT -and (Test-Path -LiteralPath "$env:AI_FACTORY_ROOT/scripts/Enter-Factory.ps1")) { return $env:AI_FACTORY_ROOT }
    return $null
}
$sharedFactory = Resolve-FactoryRoot
if ($sharedFactory) { . (Join-Path $sharedFactory 'scripts/Enter-Factory.ps1') -NoLocation }
function Get-RequiredCommand([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { throw "Missing dependency: $Name. See docs/setup-windows.md." }
    return $command.Source
}
function Invoke-FactoryCommand {
    param([Parameter(Mandatory)][string]$File, [string[]]$Arguments = @(), [string]$WorkingDirectory = (Get-Location).Path, [ValidateRange(1,7200)][int]$TimeoutSec = 600, [switch]$Capture, [switch]$CaptureError, [int[]]$AllowedExitCodes = @(0), [switch]$PassThruExitCode, [string]$InputText)
    if ([IO.Path]::GetExtension($File) -in @('.cmd','.bat','.ps1')) { throw 'Use native executable + ArgumentList; shell scripts are not accepted here.' }
    Write-Host "[run] $([IO.Path]::GetFileName($File)) $($Arguments -join ' ')"
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $File
    $info.WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    # Long input (such as a review prompt) goes through stdin; the command line is limited to about 32K characters.
    if ($PSBoundParameters.ContainsKey('InputText')) { $info.RedirectStandardInput = $true; $info.StandardInputEncoding = [Text.UTF8Encoding]::new($false) }
    $info.Environment['PYTHONUTF8'] = '1'
    if ($env:AI_FACTORY_TEMP) {
        foreach ($name in @('TEMP','TMP','TMPDIR')) { $info.Environment[$name] = $env:AI_FACTORY_TEMP }
    }
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { throw 'Process did not start' }
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
        # Both pipes are read in raw chunks: returned text stays exactly as written (CRLF, NUL-separated git output),
        # while complete lines are printed as they arrive so long tests and builds show progress. Captured stdout is not printed.
        $streams = @(
            [PSCustomObject]@{Reader=$process.StandardOutput;Print=(-not $Capture);Raw=[Text.StringBuilder]::new();Line=[Text.StringBuilder]::new();Chunk=[char[]]::new(4096);Pending=$null;SkipLF=$false}
            [PSCustomObject]@{Reader=$process.StandardError;Print=$true;Raw=[Text.StringBuilder]::new();Line=[Text.StringBuilder]::new();Chunk=[char[]]::new(4096);Pending=$null;SkipLF=$false}
        )
        foreach ($stream in $streams) { $stream.Pending = $stream.Reader.ReadAsync($stream.Chunk, 0, $stream.Chunk.Length) }
        # Written asynchronously while the output pipes are drained, then closed so the child sees end of input.
        $inputWrite = if ($info.RedirectStandardInput) { $process.StandardInput.WriteAsync($InputText) } else { $null }
        while ($true) {
            if ($inputWrite -and $inputWrite.IsCompleted) {
                # A child that exits without reading its input breaks the pipe; its exit code reports the real outcome.
                try { $process.StandardInput.Close() } catch [IO.IOException] { }
                $inputWrite = $null
            }
            # Checked on every pass: a command that never stops printing, or a child that keeps a pipe open, still times out.
            if ([DateTime]::UtcNow -gt $deadline) { $process.Kill($true); $process.WaitForExit(); throw "Timeout after $TimeoutSec seconds: $File" }
            $active = @($streams | Where-Object { $null -ne $_.Pending })
            if (-not $active.Count) { break }
            $index = [Threading.Tasks.Task]::WaitAny([Threading.Tasks.Task[]]@($active.Pending), 200)
            if ($index -lt 0) { continue }
            $stream = $active[$index]
            $count = $stream.Pending.Result
            if ($count -eq 0) {
                if ($stream.Print -and $stream.Line.Length) { Write-Host $stream.Line.ToString() }
                $stream.Pending = $null
                continue
            }
            [void]$stream.Raw.Append($stream.Chunk, 0, $count)
            if ($stream.Print) {
                # CRLF, a lone CR (progress output) and LF all end a displayed line. A CR at the end of a chunk is shown
                # at once; a LF that begins the next chunk then completes that CRLF instead of adding an empty line.
                [void]$stream.Line.Append($stream.Chunk, 0, $count)
                $text = $stream.Line.ToString()
                if ($stream.SkipLF -and $text.StartsWith("`n")) { $text = $text.Substring(1) }
                $stream.SkipLF = $text.EndsWith("`r")
                $parts = [regex]::Split($text, "\r\n|\r|\n")
                for ($i = 0; $i -lt $parts.Count - 1; $i++) { Write-Host $parts[$i] }
                [void]$stream.Line.Clear().Append($parts[-1])
            }
            $stream.Pending = $stream.Reader.ReadAsync($stream.Chunk, 0, $stream.Chunk.Length)
        }
        if ($inputWrite) {
            # The child closed both output pipes before reading all of its input: finish writing, then close stdin.
            $remaining = [Math]::Max(0, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
            try { $written = $inputWrite.Wait($remaining) } catch [AggregateException] { $written = $true }
            if (-not $written) { $process.Kill($true); $process.WaitForExit(); throw "Timeout after $TimeoutSec seconds: $File" }
            try { $process.StandardInput.Close() } catch [IO.IOException] { }
            $inputWrite = $null
        }
        $remaining = [Math]::Max(0, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
        if (-not $process.WaitForExit($remaining)) { $process.Kill($true); $process.WaitForExit(); throw "Timeout after $TimeoutSec seconds: $File" }
        $out = $streams[0].Raw.ToString()
        $err = $streams[1].Raw.ToString()
        if ($process.ExitCode -notin $AllowedExitCodes) {
            # Printed stdout is already on screen, so the message repeats only stderr and never-shown captured stdout.
            # The last lines of everything stay in Exception.Data for failure records such as .initialization-failed.
            $tailOf = { param($text) @(($text -split '\r?\n') | Where-Object { $_ } | Select-Object -Last 20) -join "`n" }
            $unseen = & $tailOf $(if ($Capture) { "$out`n$err" } else { $err })
            $exception = [InvalidOperationException]::new("Command failed (exit $($process.ExitCode)): $File" + $(if ($unseen) { "`n$unseen" } else { '' }))
            $exception.Data['OutputTail'] = & $tailOf "$out`n$err"
            throw $exception
        }
        if ($PassThruExitCode) { return $process.ExitCode }
        if ($Capture) { if ($CaptureError) { return ($out + $err).TrimEnd() }; return $out.TrimEnd() }
    } finally { $process.Dispose() }
}
function Invoke-Git {
    param([string]$Repository, [string[]]$Arguments, [switch]$Capture)
    Invoke-FactoryCommand -File (Get-RequiredCommand git) -Arguments (@('-C',$Repository) + $Arguments) -WorkingDirectory $Repository -Capture:$Capture
}
function Invoke-Npm {
    param([string]$Project, [string[]]$Arguments, [int]$TimeoutSec=600)
    $node = Get-RequiredCommand node
    $npmCli = Join-Path (Split-Path $node -Parent) 'node_modules/npm/bin/npm-cli.js'
    if (-not (Test-Path -LiteralPath $npmCli)) { throw 'npm not found next to Node. Install official Node.js LTS including npm.' }
    Invoke-FactoryCommand -File $node -Arguments (@($npmCli) + $Arguments) -WorkingDirectory $Project -TimeoutSec $TimeoutSec
}
function Get-ProjectPython([string]$Project) {
    foreach ($relative in @('.venv/Scripts/python.exe','.venv/bin/python')) {
        $path = Join-Path $Project $relative
        if (Test-Path -LiteralPath $path) { return $path }
    }
    if ($env:AI_FACTORY_PYTHON -and (Test-Path -LiteralPath $env:AI_FACTORY_PYTHON)) { return $env:AI_FACTORY_PYTHON }
    return Get-RequiredCommand python
}
function Assert-NoLink([string]$Path) {
    # Missing targets are still checked through every existing ancestor, so a junction higher up cannot redirect a later write.
    # FileInfo reports the link's own attributes, including dangling links, and -1 for paths that do not exist.
    $current = [IO.Path]::TrimEndingDirectorySeparator([IO.Path]::GetFullPath($Path))
    while ($current) {
        $attributes = [IO.FileInfo]::new($current).Attributes
        if ([int]$attributes -ne -1 -and ($attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Refusing symlink/junction path: $current" }
        $parent = Split-Path $current -Parent
        if ($parent -eq $current -or -not $parent) { break }
        $current = $parent
    }
}
function Assert-ChildPath([string]$Child, [string]$Parent) {
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    $target = [IO.Path]::GetFullPath($Child)
    if (-not $target.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes managed root: $target" }
    Assert-NoLink $target
    return $target
}
function Test-GitIgnored([string]$Repository, [string]$RelativePath) {
    # check-ignore consults the index and would start a configured fsmonitor hook; ignore rules never need it.
    $code = Invoke-FactoryCommand -File (Get-RequiredCommand git) -Arguments @('-C',$Repository,'-c','core.fsmonitor=false','check-ignore','-q','--',$RelativePath) -WorkingDirectory $Repository -AllowedExitCodes 0,1 -PassThruExitCode
    return $code -eq 0
}
function Initialize-FactoryExclusion([string]$Repository, [string[]]$Paths = @()) {
    # Existing repositories may not ignore .factory/; a local exclude keeps task state and nested worktrees out of commits without editing tracked files.
    # Check the directory itself and every path about to be created: one ignored path does not prove the rest of .factory/ is ignored.
    $checks = @('.factory/') + $Paths
    if (-not @($checks | Where-Object { -not (Test-GitIgnored $Repository $_) }).Count) { return }
    $exclude = Invoke-Git $Repository @('rev-parse','--git-path','info/exclude') -Capture
    if (-not [IO.Path]::IsPathRooted($exclude)) { $exclude = Join-Path $Repository $exclude }
    $exclude = [IO.Path]::GetFullPath($exclude)
    Assert-NoLink $exclude
    New-Item -ItemType Directory -Path (Split-Path $exclude -Parent) -Force | Out-Null
    $existing = if (Test-Path -LiteralPath $exclude) { [IO.File]::ReadAllText($exclude) } else { '' }
    if (($existing -split '\r?\n') -notcontains '/.factory/') {
        $prefix = if ($existing -and -not $existing.EndsWith("`n")) { "`n" } else { '' }
        [IO.File]::AppendAllText($exclude, "$prefix/.factory/`n", [Text.UTF8Encoding]::new($false))
    }
    $exposed = @($checks | Where-Object { -not (Test-GitIgnored $Repository $_) })
    if ($exposed.Count) { throw "Repository ignore rules re-include factory state ($($exposed -join ', ')); refusing to create files that could be committed." }
}
function Assert-SafeToStage([string]$Repository) {
    # git add --all would record untracked repositories and worktrees as gitlinks; ls-files lists them with a trailing slash.
    $untracked = (Invoke-Git $Repository @('-c','core.quotePath=false','ls-files','-z','--others','--exclude-standard') -Capture) -split "`0"
    $blocked = @($untracked | Where-Object { $_ -and ($_.EndsWith('/') -or $_ -match '^\.factory(/|$)') })
    if ($blocked.Count) { throw "Refusing to stage nested Git repositories, worktrees or factory state: $($blocked -join ', '). Ignore or move them before publishing." }
}
function Assert-RepositoryRoot([string]$Path) {
    # Pathspec-limited checks would only cover a subdirectory while repository-wide commands still act on everything.
    $top = Invoke-Git $Path @('rev-parse','--show-toplevel') -Capture
    if ([IO.Path]::GetFullPath($top) -ne [IO.Path]::GetFullPath($Path)) { throw "Path must be the repository root ($top), not a subdirectory: $Path" }
}
function Test-SensitiveFileName([string]$RelativePath) {
    return ($RelativePath -match '(^|/)(\.env($|\.)|credentials[^/]*\.json$)|\.(pem|key|pfx)$' -and $RelativePath -notmatch '(^|/)\.env\.example$')
}
function Get-FactoryManagedScripts {
    # Project path => factory source. Generated projects receive these copies; Update-AIProject keeps them current.
    $scripts = [ordered]@{}
    foreach ($name in @('Common.ps1','ProjectAdapter.ps1','New-AgentWorktree.ps1','Remove-AgentWorktree.ps1','Publish-AIProject.ps1','Scan-Secrets.ps1')) { $scripts["scripts/$name"] = "scripts/$name" }
    foreach ($name in @('verify.ps1','build.ps1','package.ps1')) { $scripts["scripts/$name"] = "templates/shared/scripts/$name" }
    return $scripts
}
function Get-FactoryVersion([string]$Factory) {
    # Source archives have no Git metadata; never report the commit of an unrelated enclosing repository.
    try { $top = Invoke-Git $Factory @('rev-parse','--show-toplevel') -Capture } catch { return 'unknown' }
    if ([IO.Path]::GetFullPath($top) -ne [IO.Path]::GetFullPath($Factory)) { return 'unknown' }
    return (Invoke-Git $Factory @('rev-parse','HEAD') -Capture)
}
function Find-FactoryTool([string]$Relative) {
    # Worktrees have no tools/ of their own; they use the checkout above them that holds the installed tools.
    $dir = $env:AI_FACTORY_ROOT
    while ($dir) {
        $candidate = Join-Path $dir "tools/$Relative"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        $parent = Split-Path $dir -Parent
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}
function Get-AgentWorktreeIdentity([string]$Agent, [string]$Task) {
    # The one definition of an agent task's branch, folder and registry entry, shared by creation and restore.
    if ($Agent -notin @('codex','claude')) { throw "Unknown agent: $Agent" }
    $slug = [regex]::Replace($Task.ToLowerInvariant(),'[^a-z0-9]+','-').Trim('-')
    if (-not $slug) { $slug='task' }
    if ($slug.Length -gt 40) { $slug=$slug.Substring(0,40).TrimEnd('-') }
    $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Task))).Substring(0,8).ToLowerInvariant()
    return [PSCustomObject]@{Hash=$hash;Branch="agent/$Agent/$slug-$hash";Folder="$Agent-$slug-$hash";Entry="$Agent-$hash.json"}
}
function Get-WorktreeRegistry([string]$Repository) {
    $common = Invoke-Git $Repository @('rev-parse','--git-common-dir') -Capture
    if (-not [IO.Path]::IsPathRooted($common)) { $common = Join-Path $Repository $common }
    return (Join-Path $common 'ai-factory')
}
function Get-MergeState([string]$Repository, [string]$Head, [string]$CompletedRef) {
    $git = Get-RequiredCommand git
    $completed = Invoke-Git $Repository @('rev-parse','--verify',"$CompletedRef^{commit}") -Capture
    if ((Invoke-FactoryCommand $git @('-C',$Repository,'merge-base','--is-ancestor',$Head,$completed) $Repository -AllowedExitCodes 0,1 -PassThruExitCode) -eq 0) { return 'merged' }
    # Squash and rebase merges rewrite commits; accept them only when CompletedRef holds the branch version of every path it changed.
    $base = Invoke-Git $Repository @('merge-base',$Head,$completed) -Capture
    $changed = @(((Invoke-Git $Repository @('-c','core.quotePath=false','diff','--no-renames','--name-only','-z',$base,$Head) -Capture) -split "`0") | Where-Object { $_ })
    if (-not $changed.Count) { return 'content-merged' }
    $code = Invoke-FactoryCommand $git (@('-C',$Repository,'--literal-pathspecs','diff','--quiet','--no-renames',$completed,$Head,'--') + $changed) $Repository -AllowedExitCodes 0,1 -PassThruExitCode
    if ($code -eq 0) { return 'content-merged' }
    return 'unmerged'
}
function Invoke-ProjectScript([string]$Script, [string]$Project, [int]$TimeoutSec=600) {
    Invoke-FactoryCommand -File (Get-RequiredCommand pwsh) -Arguments @('-NoProfile','-File',$Script,'-ProjectPath',$Project,'-TimeoutSec',"$TimeoutSec") -WorkingDirectory $Project -TimeoutSec ($TimeoutSec+30)
}
