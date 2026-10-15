#requires -Version 7.2
[CmdletBinding()]
param([string]$ProjectPath=(Split-Path $PSScriptRoot -Parent),[Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$')][string]$Repository,[Parameter(Mandatory)][string]$Title,[Parameter(Mandatory)][string]$BodyFile,[string]$BaseBranch='main',[string]$Branch,[string]$CommitMessage='feat: implement approved AI task',[switch]$CreatePrivateRepository,[switch]$DraftOnTestFailure,[switch]$ApproveExternalWrite)
. (Join-Path $PSScriptRoot 'Common.ps1')
if (-not $ApproveExternalWrite) { throw 'External writes require -ApproveExternalWrite after reviewing changes and PR body.' }
$root = (Resolve-Path -LiteralPath $ProjectPath).Path
Assert-RepositoryRoot $root
if (Test-Path -LiteralPath (Join-Path $root '.initialization-failed')) { throw 'Project initialization has not completed. Resolve its diagnostic marker before publishing.' }
$body = (Resolve-Path -LiteralPath $BodyFile).Path
Assert-SafeToStage $root
$gh = Get-RequiredCommand gh
Invoke-FactoryCommand $gh @('auth','status','--hostname','github.com') $root
if ($Title.Length -gt 200) { throw 'PR title too long' }
foreach ($heading in @('任务说明','变更摘要','测试结果','潜在风险','文档更新')) {
    if ([IO.File]::ReadAllText($body) -notmatch [regex]::Escape($heading)) { throw "PR body missing: $heading" }
}
& (Join-Path $PSScriptRoot 'Scan-Secrets.ps1') -ProjectPath $root
$testsPassed=$true
try { Invoke-ProjectScript (Join-Path $root 'scripts/verify.ps1') $root }
catch { if (-not $DraftOnTestFailure) { throw }; $testsPassed=$false; Write-Warning 'Tests failed; explicit draft mode used. The PR must not be merged.' }
$current = Invoke-Git $root @('branch','--show-current') -Capture
if (-not $current) { throw 'Detached HEAD; select a feature branch first' }
$status = Invoke-Git $root @('status','--short') -Capture
if ($status) { Write-Host $status }
$remotes = Invoke-Git $root @('remote') -Capture
$remoteCreated = $false
if ($remotes -split "`n" -contains 'origin') {
    $remote = Invoke-Git $root @('remote','get-url','origin') -Capture
    if ($remote -notin @("https://github.com/$Repository.git","https://github.com/$Repository","git@github.com:$Repository.git")) { throw 'origin does not match requested GitHub repository; no remote overwritten.' }
    $details = Invoke-FactoryCommand $gh @('repo','view',$Repository,'--json','isPrivate,nameWithOwner') $root -Capture | ConvertFrom-Json
    if (-not $details.isPrivate -or $details.nameWithOwner -ne $Repository) { throw 'This publisher requires the exact private repository.' }
} else {
    if ($remotes) { throw 'Existing non-origin remote found; inspect manually before publishing.' }
    if (-not $CreatePrivateRepository) { throw 'No origin. Use -CreatePrivateRepository only after authorization.' }
    # gh refuses existing names; it never replaces a remote repository.
    Invoke-FactoryCommand $gh @('repo','create',$Repository,'--private') $root
    Invoke-Git $root @('remote','add','origin',"https://github.com/$Repository.git")
    $remoteCreated=$true
}
if ($Branch) {
    Invoke-Git $root @('check-ref-format','--branch',$Branch) -Capture | Out-Null
    if ($Branch -in @('main','master',$BaseBranch)) { throw 'Feature branch must differ from base/main/master' }
    if ($current -ne $Branch) { Invoke-Git $root @('switch','-c',$Branch); $current=$Branch }
} elseif ($current -in @('main','master',$BaseBranch)) {
    $current='feature/ai-task-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
    Invoke-Git $root @('switch','-c',$current)
}
$name = Invoke-Git $root @('config','user.name') -Capture
$email = Invoke-Git $root @('config','user.email') -Capture
if (-not $name -or -not $email) { throw 'Git author identity missing. Set repository-local user.name and user.email.' }
if ($status) {
    Assert-SafeToStage $root
    Invoke-Git $root @('add','--all')
    & (Join-Path $PSScriptRoot 'Scan-Secrets.ps1') -ProjectPath $root
    Invoke-Git $root @('diff','--cached','--check')
    Invoke-Git $root @('commit','-m',$CommitMessage)
}
# Earlier scans ran before the commit existed; the history scan must also see it before anything is pushed.
& (Join-Path $PSScriptRoot 'Scan-Secrets.ps1') -ProjectPath $root
if ($remoteCreated) {
    Invoke-Git $root @('rev-parse','--verify',"$BaseBranch^{commit}") -Capture | Out-Null
    Invoke-Git $root @('push','origin',"$BaseBranch`:$BaseBranch")
}
Invoke-Git $root @('status','--short') -Capture | Out-Null
Invoke-Git $root @('push','--set-upstream','origin',$current)
$localSha = Invoke-Git $root @('rev-parse','HEAD') -Capture
$remoteSha = Invoke-Git $root @('ls-remote','origin',"refs/heads/$current") -Capture
if (-not $remoteSha.StartsWith($localSha)) { throw 'Remote SHA does not match local HEAD' }
$args = @('pr','create','--repo',$Repository,'--base',$BaseBranch,'--head',$current,'--title',$Title,'--body-file',$body)
if (-not $testsPassed) { $args += '--draft' }
$url = Invoke-FactoryCommand $gh $args $root -Capture
Write-Output $url
Write-Host 'PR created. Review CI and obtain human approval before merge/release.'
