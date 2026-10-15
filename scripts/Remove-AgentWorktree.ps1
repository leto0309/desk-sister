#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Path,[string]$Repository=(Split-Path $PSScriptRoot -Parent),[string]$CompletedRef='main',[switch]$DiscardIgnored)
. (Join-Path $PSScriptRoot 'Common.ps1')
$repo = Invoke-Git $Repository @('rev-parse','--show-toplevel') -Capture
$repo = [IO.Path]::GetFullPath($repo)
$target = Assert-ChildPath $Path (Join-Path $repo '.factory/worktrees')
if (-not (Test-Path -LiteralPath $target)) { throw 'Worktree does not exist' }
$registry = Get-WorktreeRegistry $repo
$entries = @(Get-ChildItem -LiteralPath $registry -Filter '*.json' | Where-Object {
    $data = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    [IO.Path]::GetFullPath($data.path) -eq $target
})
if ($entries.Count -ne 1) { throw 'This is not a uniquely registered factory worktree' }
$data = Get-Content -LiteralPath $entries[0].FullName -Raw | ConvertFrom-Json
$actual = Invoke-Git $target @('rev-parse','--show-toplevel') -Capture
if ([IO.Path]::GetFullPath($actual) -ne $target) { throw 'Target is not the exact worktree root' }
$status = @(((Invoke-Git $target @('status','--porcelain','--untracked-files=all','--ignored') -Capture) -split "`n") | Where-Object { $_ })
if (@($status | Where-Object { -not $_.StartsWith('!! ') }).Count) { throw 'Worktree contains modified or untracked files. Preserve them before removal.' }
if ($status.Count -and -not $DiscardIgnored) { throw 'Worktree contains ignored files. Preserve them, or pass -DiscardIgnored to delete regenerable ignored output.' }
if ($status.Count) {
    # Opt-in deletion is limited to regenerable output: secrets and nested repositories are never discarded.
    $ignored = @(((Invoke-Git $target @('-c','core.quotePath=false','ls-files','-z','--others','--ignored','--exclude-standard') -Capture) -split "`0") | Where-Object { $_ })
    $kept = @($ignored | Where-Object { $_.EndsWith('/') -or (Test-SensitiveFileName $_) })
    # Bare repositories have no .git entry and may keep parts of themselves tracked, packed or in alternates elsewhere,
    # so names in the ignored list cannot identify them. Every HEAD file on disk is checked instead; Get-ChildItem does
    # not descend into links without -FollowSymlink. Git's exit code 128 also covers damaged repositories (for example a
    # broken config), so repository structure next to HEAD is refused on its own, without asking Git.
    $git = Get-RequiredCommand git
    $kept += @(Get-ChildItem -LiteralPath $target -Recurse -File -Force -Filter 'HEAD' -ErrorAction Stop | ForEach-Object {
        $directory = $_.DirectoryName
        $structure = @('objects','refs','packed-refs','config' | Where-Object { Test-Path -LiteralPath (Join-Path $directory $_) }).Count
        if ($structure -or (Invoke-FactoryCommand $git @('--git-dir',$directory,'rev-parse','--git-dir') $target -AllowedExitCodes 0,128 -PassThruExitCode) -eq 0) {
            "$([IO.Path]::GetRelativePath($target,$directory).Replace('\','/'))/ (Git repository)"
        }
    })
    if ($kept.Count) { throw "Refusing to discard sensitive files or nested repositories: $($kept -join ', '). Move them out of the worktree first." }
    Write-Host "Discarding $($ignored.Count) ignored file(s)."
}
$head = Invoke-Git $target @('rev-parse','HEAD') -Capture
$mergeState = Get-MergeState $repo $head $CompletedRef
if ($mergeState -eq 'unmerged') { throw "Changes on $($data.branch) are not in $CompletedRef. Merge them first or pass the ref that contains them; nothing was removed." }
$branch = Invoke-Git $target @('branch','--show-current') -Capture
if ($branch -ne $data.branch) { throw 'Registered branch differs from the current worktree branch' }
Invoke-Git $repo @('worktree','remove',$target)
Remove-Item -LiteralPath $entries[0].FullName
Write-Host "[REMOVED] $target ($mergeState into $CompletedRef; branch preserved: $branch)"
