from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import _ps

FAMILIES = {
    ("0710", "0100"): "Keel (Zune 30)",
    ("0710", "0200"): "Scorpius (Zune 4/8/16)",
    ("0710", "0300"): "Draco (Zune 80/120)",
    ("063E", "0100"): "Pavo (Zune HD)",
}

# SHA-256 of CABs verified as Microsoft-signed, for checking without PowerShell.
KNOWN_CABS = {
    "0aaa0fe19d261cef741cba4fa51876a112378e056679ad227efcd35604d5bb8e": "KeelBaseline.cab 3.30",
    "614221a6eb8b0850b180ef0ce63b4baedc98ca4d429949fe30ff40151f33f371": "ScorpiusBaseline.cab 3.30",
    "51231d7659b9b2b96b4ffcdca69a1d77f76682d2860befa38ef64b9d4ad7ed22": "DracoBaseline.cab 3.30",
    "f674a79af0db514aa934e4a630ee385f0445f9fab33bfe632da328fe55fd1702": "PavoBaseline.cab 4.5 (114)",
}

MANIFEST_PATH = "firmware/v4_5/zuneprod.xml"


@dataclass
class FirmwareUpdate:
    family: str
    hardware_id: str
    version: str
    url: str
    upgrade_from: list[str] = field(default_factory=list)

    @property
    def cab_name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


def load_manifest(path: Path) -> list[FirmwareUpdate]:
    root = ET.parse(path).getroot()
    out = []
    for fu in root.iter("FirmwareUpdate"):
        hwid = fu.get("HardwareID", "")
        pid = _hwid_part(hwid, "Pid_")
        rev = _hwid_part(hwid, "Rev_")
        out.append(FirmwareUpdate(
            family=FAMILIES.get((pid, rev), f"unknown ({hwid})"),
            hardware_id=hwid,
            version=fu.get("Version", ""),
            url=fu.get("URL", ""),
            upgrade_from=[u.get("Version", "") for u in fu.iter("UpgradeFrom")],
        ))
    return out


def _hwid_part(hwid: str, key: str) -> str:
    low = hwid.lower()
    i = low.find(key.lower())
    return hwid[i + len(key):i + len(key) + 4].upper() if i >= 0 else ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CabCheck:
    path: Path
    sha256: str
    known_as: str | None
    signature: str | None  # "Valid", "NotSigned", "HashMismatch", ... or None if not checked
    signer: str | None

    @property
    def trusted(self) -> bool:
        if self.signature is not None:
            return self.signature == "Valid" and "Microsoft Corporation" in (self.signer or "")
        return self.known_as is not None


def check_cabs(paths: list[Path]) -> list[CabCheck]:
    sigs = _authenticode([p for p in paths])
    out = []
    for p in paths:
        digest = sha256(p)
        status, signer = sigs.get(str(p.resolve()).lower(), (None, None))
        out.append(CabCheck(p, digest, KNOWN_CABS.get(digest), status, signer))
    return out


def _authenticode(paths: list[Path]) -> dict:
    if not paths:
        return {}
    script = (
        "$ErrorActionPreference='Stop';"
        "@($env:MUNE_PATHS -split \"`n\") | ForEach-Object { $s = Get-AuthenticodeSignature -LiteralPath $_;"
        " [pscustomobject]@{p=$_; s=[string]$s.Status; n=$s.SignerCertificate.Subject} }"
        " | ConvertTo-Json -Compress"
    )
    env = dict(os.environ, MUNE_PATHS="\n".join(str(p.resolve()) for p in paths))
    try:
        proc = _ps.run(script, env=env, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    rows = json.loads(proc.stdout)
    if isinstance(rows, dict):
        rows = [rows]
    return {r["p"].lower(): (r["s"], r["n"]) for r in rows}
