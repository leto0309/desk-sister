#requires -Version 7.2
[CmdletBinding()]
param([string]$ProjectPath = (Split-Path $PSScriptRoot -Parent),[ValidateRange(1,7200)][int]$TimeoutSec=600)
try { . (Join-Path $PSScriptRoot 'ProjectAdapter.ps1'); Invoke-ProjectAction 'build' $ProjectPath $TimeoutSec }
catch { Write-Error $_ -ErrorAction Continue; exit 1 }
