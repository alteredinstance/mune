#Requires -RunAsAdministrator
<#
.SYNOPSIS
Installs the Zune 4.8 device driver on Windows 10/11.

.DESCRIPTION
The Zune co-installer needs ZuneCoInst.dll.mui in System32\<language>, which the
driver package never puts there on modern Windows. Copies it from the staged
driver package, then installs Zune.inf. Use -WhatIf to preview.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Inf = "$env:ProgramFiles\Zune\Drivers\Zune\Zune.inf"
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Inf)) { throw "Zune.inf not found at $Inf. Install the Zune 4.8 software first." }

$repo = "$env:SystemRoot\System32\DriverStore\FileRepository"
$store = Get-ChildItem $repo -Directory -Filter 'zune.inf_*' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $store) {
    if ($PSCmdlet.ShouldProcess($Inf, 'Stage driver package')) { pnputil /add-driver "$Inf" | Out-Host }
    $store = Get-ChildItem $repo -Directory -Filter 'zune.inf_*' | Select-Object -First 1
    if (-not $store -and -not $WhatIfPreference) { throw "Driver package did not stage; see pnputil output above." }
}

$langs = @('en-US', (Get-UICulture).Name) | Select-Object -Unique
foreach ($lang in $langs) {
    $dst = "$env:SystemRoot\System32\$lang\ZuneCoInst.dll.mui"
    if (Test-Path $dst) { Write-Host "ok    $dst already present"; continue }
    $src = @("$($store.FullName)\$lang\ZuneCoInst.dll.mui", "$($store.FullName)\$lang\$lang-ZuneCoInst.dll.mui") |
           Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $src) { Write-Host "skip  no $lang resources in driver package"; continue }
    if (-not (Test-Path (Split-Path $dst))) { Write-Host "skip  $lang not installed on this system"; continue }
    if ($PSCmdlet.ShouldProcess($dst, "Copy $src")) {
        Copy-Item -LiteralPath $src -Destination $dst
        Write-Host "copy  $dst"
    }
}

if ($PSCmdlet.ShouldProcess($Inf, 'Install driver')) {
    pnputil /add-driver "$Inf" /install | Out-Host
    Write-Host "Done. Power on the Zune and plug it in; run 'mune doctor' to confirm."
}
