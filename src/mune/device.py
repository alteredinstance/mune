from __future__ import annotations

import json
from dataclasses import dataclass

from . import _ps
from .audio.sanitize import find_ffmpeg
from .firmware.manifest import FAMILIES

_PROBE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$sw = Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*,
                       HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* |
      Where-Object DisplayName -eq 'Zune' | Select-Object -First 1
$store = Get-ChildItem "$env:SystemRoot\System32\DriverStore\FileRepository" -Directory -Filter 'zune.inf_*' |
         Select-Object -First 1
$dev = Get-PnpDevice | Where-Object InstanceId -match 'VID_045E&PID_(0710|063E)' |
       Select-Object Status, Present, FriendlyName, InstanceId, Class
$hw = foreach ($d in $dev) { (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Device_HardwareIds).Data }
$hosts = Get-Content "$env:SystemRoot\System32\drivers\etc\hosts" |
         Where-Object { $_ -match '^\s*[^#].*\bresources\.zune\.net\b' } | ForEach-Object { [string]$_ }
[pscustomobject]@{
  software       = $sw.DisplayVersion
  driverStore    = $store.FullName
  muiPresent     = Test-Path "$env:SystemRoot\System32\en-US\ZuneCoInst.dll.mui"
  devices        = @($dev)
  hardwareIds    = @($hw)
  hostsLines     = @($hosts)
} | ConvertTo-Json -Depth 4 -Compress
"""


@dataclass
class Check:
    name: str
    ok: bool | None  # None = informational
    detail: str


def run_probe() -> dict:
    proc = _ps.run(_PROBE)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or "PowerShell probe returned nothing")
    return json.loads(proc.stdout)


def doctor() -> list[Check]:
    p = run_probe()
    checks = [
        Check("Zune software", bool(p.get("software")),
              p.get("software") or "not installed (4.8.2345 is the final release)"),
        Check("Driver package in store", bool(p.get("driverStore")),
              p.get("driverStore") or "zune.inf not staged - run scripts/Install-ZuneDriver.ps1"),
        Check("ZuneCoInst.dll.mui in System32\\en-US", p.get("muiPresent"),
              "present" if p.get("muiPresent") else "missing - the Zune co-installer fails on Windows 11 without it"),
    ]

    devices = [d for d in (p.get("devices") or []) if d]
    present = [d for d in devices if d.get("Present")]
    if present:
        for d in present:
            checks.append(Check(f"Device: {d.get('FriendlyName')}", d.get("Status") == "OK",
                                f"{d.get('Status')}  {d.get('Class')}  {d.get('InstanceId')}"))
    else:
        checks.append(Check("Device connected", False,
                            "no Zune on USB (it only enumerates when powered on)"
                            + (f"; {len(devices)} previous install(s) remembered" if devices else "")))

    families = set()
    for hwid in p.get("hardwareIds") or []:
        for h in (hwid if isinstance(hwid, list) else [hwid]):
            u = str(h).upper()
            for (pid, rev), fam in FAMILIES.items():
                if f"PID_{pid}&REV_{rev}" in u:
                    families.add(fam)
    if families:
        checks.append(Check("Hardware family", None, ", ".join(sorted(families))))

    lines = p.get("hostsLines") or []
    if not lines:
        checks.append(Check("resources.zune.net redirect", None, "none (firmware updates disabled)"))
    for line in lines:
        local = line.split()[0] in ("127.0.0.1", "::1")
        checks.append(Check("resources.zune.net redirect", local,
                            line.strip() + ("" if local else "  <- third-party server; mune can serve firmware locally instead")))

    ff = find_ffmpeg()
    checks.append(Check("ffmpeg (for re-encoding/conversion)", bool(ff),
                        ff or "not found - tag/art fixes work, re-encoding does not"))
    return checks
