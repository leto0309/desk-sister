#requires -Version 7.2
[CmdletBinding()]
param([string]$ProjectPath=(Split-Path $PSScriptRoot -Parent))
. (Join-Path $PSScriptRoot 'Common.ps1')
$files = (Invoke-Git $ProjectPath @('-c','core.quotePath=false','ls-files','-z','--cached','--others','--exclude-standard') -Capture) -split "`0"
$blocked = @()
foreach ($relative in $files) {
    if (-not $relative) { continue }
    if (Test-SensitiveFileName $relative) { $blocked += $relative; continue }
    $path = Join-Path $ProjectPath $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    # Like Git, treat a NUL byte in the first 8000 bytes as binary; binaries keep the file-name check only.
    # UTF-16/UTF-32 text is full of NUL bytes, so a byte-order mark marks the file as text that ReadAllText decodes.
    $stream = [IO.File]::OpenRead($path)
    try { $head = [byte[]]::new(8000); $read = $stream.Read($head,0,$head.Length) } finally { $stream.Dispose() }
    $unicodeBom = ($read -ge 2 -and (($head[0] -eq 0xFF -and $head[1] -eq 0xFE) -or ($head[0] -eq 0xFE -and $head[1] -eq 0xFF))) -or ($read -ge 4 -and $head[0] -eq 0 -and $head[1] -eq 0 -and $head[2] -eq 0xFE -and $head[3] -eq 0xFF)
    if (-not $unicodeBom -and [Array]::IndexOf($head,[byte]0,0,$read) -ge 0) { continue }
    if ((Get-Item -LiteralPath $path).Length -gt 2000000) { throw "Text file too large for automatic secret check: $relative" }
    $content = [IO.File]::ReadAllText($path)
    # AWS and Google key prefixes are case-sensitive; matching them case-insensitively would flag ordinary words.
    if ($content -match '(sk-(proj-|ant-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|(?-i:(AKIA|ASIA)[0-9A-Z]{16})|(?-i:AIza[0-9A-Za-z_-]{35})|xox[abprs]-[0-9A-Za-z-]{10,}|(sk|rk)_live_[0-9A-Za-z]{24,}|-----BEGIN (RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY( BLOCK)?-----)') { $blocked += $relative }
}
if ($blocked.Count) { throw "Possible secret-bearing files (content withheld): $($blocked -join ', ')" }
Write-Host '[PASS] Basic secret and sensitive-file scan (manual diff review is still required).'
# The scan above sees only current files; gitleaks also checks every commit, so a secret removed later is still caught.
# Only the factory's installed gitleaks is trusted, and only when the executable matches the SHA256 in the tool lock.
$gitleaks = Find-FactoryTool 'gitleaks/gitleaks.exe'
if (-not $gitleaks) { Write-Host '[NOT RUN] gitleaks is not installed in the factory; Git history was not scanned.'; return }
$lockPath = Join-Path $env:AI_FACTORY_ROOT 'docs/tools-lock.json'
$locked = if (Test-Path -LiteralPath $lockPath) { (Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json).gitleaks } else { $null }
if (-not $locked -or -not $locked.PSObject.Properties['exeSha256'] -or (Get-FileHash -LiteralPath $gitleaks -Algorithm SHA256).Hash -ne $locked.exeSha256) {
    throw "gitleaks at $gitleaks does not match the SHA256 locked in docs/tools-lock.json; reinstall it with Install-FactoryTools.ps1."
}
# Any branch or tag may hold history even when HEAD is an unborn (orphan) branch.
if (-not (Invoke-Git $ProjectPath @('rev-list','--all','--max-count=1') -Capture)) { Write-Host '[NOT RUN] No commits yet; Git history scan skipped.'; return }
if ((Invoke-Git $ProjectPath @('rev-parse','--is-shallow-repository') -Capture) -eq 'true') { throw 'Shallow clone: Git history is incomplete. Run git fetch --unshallow, then scan again.' }
# --redact keeps matched values out of the output; --all covers every branch and tag.
$code = Invoke-FactoryCommand $gitleaks @('git','--no-banner','--redact','--exit-code','1','--log-level','warn','--log-opts=--all',$ProjectPath) $ProjectPath -AllowedExitCodes 0,1 -PassThruExitCode
if ($code -ne 0) { throw 'gitleaks found possible secrets in Git history (values redacted). Revoke them and rewrite history before publishing.' }
Write-Host '[PASS] gitleaks Git history scan'
