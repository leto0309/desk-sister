#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('codex','claude')][string]$Agent,[Parameter(Mandatory)][string]$Task,[string]$Repository = (Split-Path $PSScriptRoot -Parent),[string]$BaseRef='HEAD')
. (Join-Path $PSScriptRoot 'Common.ps1')
$repo = Invoke-Git $Repository @('rev-parse','--show-toplevel') -Capture
$repo = [IO.Path]::GetFullPath($repo)
Invoke-Git $repo @('rev-parse','--verify',"$BaseRef^{commit}") -Capture | Out-Null
$identity = Get-AgentWorktreeIdentity $Agent $Task
$branch = $identity.Branch
Invoke-Git $repo @('check-ref-format','--branch',$branch) -Capture | Out-Null
$branches = @(Invoke-Git $repo @('branch','--list',$branch) -Capture)
if (($branches -join '').Trim()) { throw "Branch already exists: $branch" }
$managedRoot = Join-Path $repo '.factory/worktrees'
Assert-NoLink $repo
Initialize-FactoryExclusion $repo @(".factory/worktrees/$($identity.Folder)/")
New-Item -ItemType Directory -Path $managedRoot -Force | Out-Null
$path = Assert-ChildPath (Join-Path $managedRoot $identity.Folder) $managedRoot
if (Test-Path -LiteralPath $path) { throw "Worktree path already exists: $path" }
$registry = Get-WorktreeRegistry $repo
# Checked before anything is created: a link anywhere above the registry must not receive a new directory.
$entry = Assert-ChildPath (Join-Path $registry $identity.Entry) $registry
New-Item -ItemType Directory -Path $registry -Force | Out-Null
$lock = [IO.File]::Open($entry,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {
    Invoke-Git $repo @('worktree','add','-b',$branch,$path,$BaseRef)
    $json = @{root=$repo;path=$path;branch=$branch;agent=$Agent;task=$Task} | ConvertTo-Json
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $lock.Write($bytes,0,$bytes.Length)
} catch { $lock.Dispose(); Remove-Item -LiteralPath $entry; throw }
finally { $lock.Dispose() }
Write-Host "[WORKTREE] $path"
[PSCustomObject]@{Path=$path;Branch=$branch;Agent=$Agent}
