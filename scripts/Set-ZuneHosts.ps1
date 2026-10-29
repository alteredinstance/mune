#Requires -RunAsAdministrator
<#
.SYNOPSIS
Points resources.zune.net at this PC (-Local) for 'mune firmware serve', or removes the entry (-Remove).
Backs up the hosts file first. Use -WhatIf to preview.
#>
[CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Local')]
param(
    [Parameter(ParameterSetName = 'Local')][switch]$Local,
    [Parameter(ParameterSetName = 'Remove', Mandatory)][switch]$Remove
)
$ErrorActionPreference = 'Stop'
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$lines = @(Get-Content -LiteralPath $hosts)
$kept = $lines | Where-Object { $_ -notmatch '^\s*[^#\s]+\s+resources\.zune\.net\b' }
$removed = $lines | Where-Object { $_ -match '^\s*[^#\s]+\s+resources\.zune\.net\b' }
$new = if ($Remove) { $kept } else { @($kept) + '127.0.0.1 resources.zune.net' }

$removed | ForEach-Object { Write-Host "remove  $_" }
if (-not $Remove) { Write-Host "add     127.0.0.1 resources.zune.net" }

if ($PSCmdlet.ShouldProcess($hosts, 'Rewrite hosts file')) {
    $backup = "$hosts.mune-$(Get-Date -Format yyyyMMdd-HHmmss).bak"
    Copy-Item -LiteralPath $hosts -Destination $backup
    Set-Content -LiteralPath $hosts -Value $new -Encoding ascii
    ipconfig /flushdns | Out-Null
    Write-Host "Saved. Backup: $backup"
}
