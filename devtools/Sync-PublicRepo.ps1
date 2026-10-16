#requires -Version 7.2
<#
.SYNOPSIS
Publishes the file tree of the private repository's main branch to the public repository (desk-sister).

.DESCRIPTION
Only the tree travels; the private history (and the author e-mail in it) never does. All work happens in
a temporary bare repository: the public history and the private tree are fetched into it, a new commit is
made with `git commit-tree` (so paths, letter case, file modes and file/folder changes match exactly),
checked and scanned with gitleaks. The public checkout then fetches just that commit (its parent is the
public history, so no private commit comes along) and pushes it with its own `origin` settings, exactly
as a manual `git push` would, before fast-forwarding. The temporary repository is deleted at the end.

Without -Push this is a dry run that lists what would change.

.EXAMPLE
./devtools/Sync-PublicRepo.ps1
./devtools/Sync-PublicRepo.ps1 -Push -Message "Add the exe icon"
#>
[CmdletBinding()]
param(
    [string]$PrivateRepo = (Split-Path $PSScriptRoot -Parent),
    [string]$PublicRepo,
    [string]$SourceRef = 'main',
    [string]$Message = 'Sync from the development repository',
    [switch]$Push
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)  # git prints non-ASCII file names as UTF-8
$PrivateRepo = (Resolve-Path -LiteralPath $PrivateRepo).Path
if (-not $PublicRepo) { $PublicRepo = Join-Path (Split-Path $PrivateRepo -Parent) 'desk-sister' }
$PublicRepo = (Resolve-Path -LiteralPath $PublicRepo).Path

function Invoke-Git([string]$Repo, [string[]]$Arguments) {
    $output = & git -C $Repo -c core.quotePath=false @Arguments
    if ($LASTEXITCODE) { throw "git $($Arguments -join ' ') failed in $Repo" }
    return $output
}

function Assert-NoIgnoredCollision([string]$Work, [string]$Tree) {
    # A fast-forward silently replaces ignored files; refuse if one sits where the new tree puts a file or folder.
    $ignored = @(Invoke-Git $PublicRepo @('status', '--porcelain', '--ignored', '--untracked-files=all') |
        Where-Object { $_.StartsWith('!! ') } | ForEach-Object { $_.Substring(3).Trim('"').TrimEnd('/') })
    if (-not $ignored.Count) { return }
    $paths = @(Invoke-Git $Work @('ls-tree', '-r', '--name-only', $Tree))
    $hits = foreach ($i in $ignored) {
        foreach ($p in $paths) {
            # same path, an ignored folder above a new file, or an ignored file where a new folder goes (case-insensitive: Windows)
            if ($p -ieq $i -or $p.StartsWith("$i/", [StringComparison]::OrdinalIgnoreCase) -or
                $i.StartsWith("$p/", [StringComparison]::OrdinalIgnoreCase)) { $i; break }
        }
    }
    if ($hits) { throw "Refused: ignored local files would be overwritten: $(@($hits) -join ', ')." }
}

# ---- the public repository must be a clean, current copy of origin/main with a noreply identity
if ((Invoke-Git $PublicRepo @('branch', '--show-current')) -ne 'main') { throw 'Refused: the public repository is not on main.' }
if (Invoke-Git $PublicRepo @('status', '--porcelain', '--untracked-files=all')) {
    throw 'Refused: the public repository has uncommitted or untracked files.'
}
$name = Invoke-Git $PublicRepo @('config', 'user.name')
$email = Invoke-Git $PublicRepo @('config', 'user.email')
if ($email -notmatch '^[^@\s]+@users\.noreply\.github\.com$') {
    throw "Refused: the public repository must commit with a GitHub noreply e-mail, not '$email'."
}
Invoke-Git $PublicRepo @('fetch', '--quiet', 'origin') | Out-Null
$head = Invoke-Git $PublicRepo @('rev-parse', 'HEAD')
if ($head -ne (Invoke-Git $PublicRepo @('rev-parse', 'origin/main'))) {
    throw 'Refused: the public repository is not in step with origin/main; pull or inspect it first.'
}
$sourceSha = Invoke-Git $PrivateRepo @('rev-parse', '--verify', "$SourceRef^{commit}")

# ---- everything else happens in a throw-away bare repository
$work = Join-Path ([IO.Path]::GetTempPath()) ("desk-sister-sync-" + [guid]::NewGuid().ToString('N'))
$result = $null
try {
    & git init --quiet --bare $work
    if ($LASTEXITCODE) { throw "cannot create $work" }
    Invoke-Git $work @('fetch', '--quiet', '--no-tags', '--recurse-submodules=no', $PublicRepo, 'main:refs/heads/main') | Out-Null
    Invoke-Git $work @('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', '--recurse-submodules=no', $PrivateRepo, $SourceRef) | Out-Null
    $tree = Invoke-Git $work @('rev-parse', '--verify', "$sourceSha^{tree}")
    $changes = @(Invoke-Git $work @('diff', '--name-status', '--no-renames', $head, $tree))
    "Source: $SourceRef ($($sourceSha.Substring(0, 7))) in $PrivateRepo"
    "Target: $PublicRepo"
    $changes | ForEach-Object { "  $_" }
    if (-not $changes.Count) {
        $result = 'Already in sync.'
    } elseif (-not $Push) {
        $result = 'Dry run: nothing was changed. Run again with -Push to commit and push.'
    } else {
        Assert-NoIgnoredCollision $work $tree
        $gitleaks = Get-Command gitleaks -ErrorAction SilentlyContinue
        if (-not $gitleaks) { throw 'Refused: gitleaks is required before anything is pushed (not found on PATH).' }

        # The commit: exactly the private tree, on top of the public history, with the verified identity.
        $saved = @{}
        foreach ($var in 'GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_AUTHOR_DATE', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL', 'GIT_COMMITTER_DATE') {
            $saved[$var] = [Environment]::GetEnvironmentVariable($var)
            [Environment]::SetEnvironmentVariable($var, $null)
        }
        try {
            $env:GIT_AUTHOR_NAME = $name; $env:GIT_AUTHOR_EMAIL = $email
            $env:GIT_COMMITTER_NAME = $name; $env:GIT_COMMITTER_EMAIL = $email
            $commit = Invoke-Git $work @('commit-tree', $tree, '-p', $head, '-m', $Message)
        } finally {
            foreach ($var in $saved.Keys) { [Environment]::SetEnvironmentVariable($var, $saved[$var]) }
        }
        if ((Invoke-Git $work @('rev-parse', "$commit^{tree}")) -ne $tree) { throw 'Not pushed: the new commit does not carry the private tree.' }
        $identity = Invoke-Git $work @('log', '-1', '--format=%ae%n%ce', $commit)
        if (@($identity | Where-Object { $_ -ne $email }).Count) { throw "Not pushed: the new commit is not signed by $email." }
        # The new commit and the whole public history behind it (all that origin/main will contain).
        & $gitleaks.Source git --no-banner --redact --log-level warn "--log-opts=$commit" $work
        if ($LASTEXITCODE) { throw 'Not pushed: gitleaks reported possible secrets.' }

        # Hand over just this commit (parent: public history), then push it with the public checkout's own
        # origin settings (push URL, SSH aliases, relative paths): only main, never a tag.
        Invoke-Git $work @('update-ref', 'refs/heads/publish', $commit) | Out-Null
        Invoke-Git $PublicRepo @('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', '--recurse-submodules=no',
            $work, 'refs/heads/publish') | Out-Null
        Invoke-Git $PublicRepo @('push', '--quiet', '--no-follow-tags', 'origin', "$($commit):refs/heads/main") | Out-Null
        Invoke-Git $PublicRepo @('merge', '--quiet', '--ff-only', '--no-overwrite-ignore', $commit) | Out-Null
        $result = "Pushed $($commit.Substring(0, 7)) to origin/main."
    }
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $work) {
        throw "Cleanup failed: delete the temporary repository $work by hand (it holds private objects; nothing of it was pushed)."
    }
}
$result
