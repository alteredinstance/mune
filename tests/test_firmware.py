import struct

import pytest

from conftest import make_b000ff
from mune.firmware import b000ff, manifest


def test_parse_records_and_entry(tmp_path):
    p = tmp_path / "eboot.bin"
    p.write_bytes(make_b000ff([(0x80000000, b"\x01\x02\x03"), (0x80000100, b"abc")]))
    img = b000ff.parse(p)
    assert img.entry_point == 0x80001000
    assert len(img.records) == 2 and not img.bad_records
    assert img.read(0x80000101, 2) == b"bc"
    assert img.romhdr is None


def test_bad_checksum_detected(tmp_path):
    raw = bytearray(make_b000ff([(0x80000000, b"\x10\x20")]))
    raw[15 + 12] ^= 0xFF
    p = tmp_path / "nk.bin"
    p.write_bytes(bytes(raw))
    assert len(b000ff.parse(p).bad_records) == 1


def test_romhdr_and_toc(tmp_path):
    base = 0x88200000
    romhdr_at, name_at = base + 0x100, base + 0x200
    hdr = list(struct.unpack(b000ff.ROMHDR_FMT, bytes(struct.calcsize(b000ff.ROMHDR_FMT))))
    hdr[4], hdr[12], hdr[17] = 1, 0, 0x01C2
    toc = struct.pack(b000ff.TOC_ENTRY_FMT, 0, bytes(8), 1234, name_at, 0, 0, 0)
    image = bytearray(0x300)
    image[0x40:0x48] = struct.pack("<II", b000ff.ROM_SIGNATURE, romhdr_at)
    blob = struct.pack(b000ff.ROMHDR_FMT, *hdr) + toc
    image[0x100:0x100 + len(blob)] = blob
    image[0x200:0x208] = b"nk.exe\0\0"
    p = tmp_path / "nk.bin"
    p.write_bytes(make_b000ff([(base, bytes(image))], start=base))
    img = b000ff.parse(p)
    assert img.romhdr["cpu_type"] == 0x01C2
    assert [(e.name, e.size) for e in img.entries] == [("nk.exe", 1234)]


def test_not_b000ff(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"MZ")
    with pytest.raises(b000ff.B000FFError):
        b000ff.parse(p)


def test_manifest_families(tmp_path):
    xml = tmp_path / "zuneprod.xml"
    xml.write_text(
        '<FirmwareUpdates><FirmwareUpdate HardwareID="USB\\Vid_045e&amp;Pid_0710&amp;Rev_0100" '
        'Version="03.30" URL="http://resources.zune.net/KeelBaseline.cab">'
        '<SupportedUpgradeBaseVersions><UpgradeFrom Version="01.04"/></SupportedUpgradeBaseVersions>'
        '</FirmwareUpdate></FirmwareUpdates>')
    [u] = manifest.load_manifest(xml)
    assert u.family.startswith("Keel")
    assert u.cab_name == "KeelBaseline.cab"
    assert u.upgrade_from == ["01.04"]


def test_unknown_unsigned_cab_untrusted(tmp_path, monkeypatch):
    cab = tmp_path / "Evil.cab"
    cab.write_bytes(b"MSCF")
    monkeypatch.setattr(manifest, "_authenticode", lambda paths: {})
    [c] = manifest.check_cabs([cab])
    assert not c.trusted
