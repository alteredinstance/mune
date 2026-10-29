"""WinCE B000FF image: magic, u32 start, u32 length, then records of
(u32 addr, u32 len, u32 byte-sum, data) ending with addr=0, csum=0, len=entry.
ROMHDR pointer sits at start+0x44 when start+0x40 holds "ECEC"."""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"B000FF\n"
ROM_SIGNATURE = 0x43454345  # "ECEC" little-endian
ROMHDR_FMT = "<17I2H3I"
TOC_ENTRY_FMT = "<I8sIIIII"
FILES_ENTRY_FMT = "<I8sIIII"


class B000FFError(ValueError):
    pass


@dataclass
class Record:
    address: int
    length: int
    checksum: int
    file_offset: int  # offset of the data in the .bin file
    checksum_ok: bool


@dataclass
class RomEntry:
    name: str
    size: int
    attributes: int
    kind: str  # "module" or "file"


@dataclass
class B000FFImage:
    path: Path
    image_start: int
    image_length: int
    entry_point: int | None
    records: list[Record]
    trailing_bytes: int
    romhdr: dict | None = None
    entries: list[RomEntry] = field(default_factory=list)
    _data: bytes = field(default=b"", repr=False)
    _starts: list[int] = field(default_factory=list, repr=False)

    @property
    def bad_records(self) -> list[Record]:
        return [r for r in self.records if not r.checksum_ok]

    def read(self, address: int, size: int) -> bytes | None:
        i = bisect.bisect_right(self._starts, address) - 1
        if i < 0:
            return None
        rec = self.records[i]
        off = address - rec.address
        if off + size > rec.length:
            return None
        start = rec.file_offset + off
        return self._data[start:start + size]

    def read_cstring(self, address: int, limit: int = 260) -> str | None:
        i = bisect.bisect_right(self._starts, address) - 1
        if i < 0:
            return None
        rec = self.records[i]
        off = address - rec.address
        if not 0 <= off < rec.length:
            return None
        start = rec.file_offset + off
        end = min(rec.file_offset + rec.length, start + limit)
        raw = self._data[start:end].split(b"\0", 1)[0]
        return raw.decode("ascii", "replace")


def parse(path: str | Path) -> B000FFImage:
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise B000FFError(f"{path.name}: not a B000FF image")

    image_start, image_length = struct.unpack_from("<II", data, 7)
    pos = 15
    records: list[Record] = []
    entry_point = None
    while pos + 12 <= len(data):
        addr, length, csum = struct.unpack_from("<III", data, pos)
        pos += 12
        if addr == 0 and csum == 0:
            entry_point = length
            break
        if pos + length > len(data):
            raise B000FFError(f"{path.name}: record at 0x{addr:08X} runs past end of file")
        ok = (sum(data[pos:pos + length]) & 0xFFFFFFFF) == csum
        records.append(Record(addr, length, csum, pos, ok))
        pos += length

    records.sort(key=lambda r: r.address)
    img = B000FFImage(
        path=path,
        image_start=image_start,
        image_length=image_length,
        entry_point=entry_point,
        records=records,
        trailing_bytes=len(data) - pos,
        _data=data,
        _starts=[r.address for r in records],
    )
    _parse_romhdr(img)
    return img


def _parse_romhdr(img: B000FFImage) -> None:
    sig = img.read(img.image_start + 0x40, 8)
    if not sig:
        return
    signature, ptoc = struct.unpack("<II", sig)
    if signature != ROM_SIGNATURE:
        return
    raw = img.read(ptoc, struct.calcsize(ROMHDR_FMT))
    if not raw:
        return
    v = struct.unpack(ROMHDR_FMT, raw)
    names = ("dllfirst", "dlllast", "physfirst", "physlast", "nummods", "ramstart",
             "ramfree", "ramend", "copy_entries", "copy_offset", "profile_len",
             "profile_offset", "numfiles", "kernel_flags", "fsram_percent",
             "drivglob_start", "drivglob_len", "cpu_type", "misc_flags",
             "extensions", "tracking_start", "tracking_len")
    img.romhdr = dict(zip(names, v))

    pos = ptoc + len(raw)
    toc_size = struct.calcsize(TOC_ENTRY_FMT)
    for _ in range(min(img.romhdr["nummods"], 4096)):
        e = img.read(pos, toc_size)
        if not e:
            break
        attrs, _ft, size, name_ptr, *_ = struct.unpack(TOC_ENTRY_FMT, e)
        img.entries.append(RomEntry(img.read_cstring(name_ptr) or "?", size, attrs, "module"))
        pos += toc_size

    files_size = struct.calcsize(FILES_ENTRY_FMT)
    for _ in range(min(img.romhdr["numfiles"], 16384)):
        e = img.read(pos, files_size)
        if not e:
            break
        attrs, _ft, real_size, _comp, name_ptr, _load = struct.unpack(FILES_ENTRY_FMT, e)
        img.entries.append(RomEntry(img.read_cstring(name_ptr) or "?", real_size, attrs, "file"))
        pos += files_size


CPU_TYPES = {0x01C0: "ARM", 0x01C2: "ARM Thumb", 0x014C: "x86", 0x0166: "MIPS"}


def describe(img: B000FFImage) -> str:
    lines = [
        f"{img.path.name}",
        f"  image start   0x{img.image_start:08X}",
        f"  image length  0x{img.image_length:08X} ({img.image_length:,} bytes)",
        f"  entry point   " + (f"0x{img.entry_point:08X}" if img.entry_point is not None else "none"),
        f"  records       {len(img.records)} ({len(img.bad_records)} bad checksums)",
    ]
    if img.trailing_bytes:
        lines.append(f"  trailing data {img.trailing_bytes} bytes after terminator (possible signature block)")
    if img.romhdr:
        h = img.romhdr
        cpu = CPU_TYPES.get(h["cpu_type"], f"0x{h['cpu_type']:04X}")
        lines += [
            f"  ROMHDR        {h['nummods']} modules, {h['numfiles']} files, CPU {cpu}",
            f"  RAM           0x{h['ramstart']:08X}-0x{h['ramend']:08X}",
        ]
    else:
        lines.append("  ROMHDR        not found (normal for bootloaders)")
    return "\n".join(lines)
