import struct
import sys
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# MPEG-1 Layer III, 128 kbps, no CRC. Byte 2 picks the sample rate, byte 3 the channel mode.
_HEADERS = {
    (44100, 2): (b"\xff\xfb\x90\x44", 417),
    (48000, 2): (b"\xff\xfb\x94\x44", 384),
    (44100, 1): (b"\xff\xfb\x90\xc4", 417),
}


def make_mp3(path: Path, sample_rate=44100, channels=2, frames=40) -> Path:
    header, size = _HEADERS[(sample_rate, channels)]
    path.write_bytes((header + b"\x00" * (size - 4)) * frames)
    return path


def make_image(fmt="JPEG", size=(100, 100), progressive=False) -> bytes:
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt, progressive=progressive)
    return out.getvalue()


def make_b000ff(records, start=0x80000000, entry=0x80001000) -> bytes:
    body = b"B000FF\n" + struct.pack("<II", start, sum(len(d) for _, d in records))
    for addr, data in records:
        body += struct.pack("<III", addr, len(data), sum(data) & 0xFFFFFFFF) + data
    return body + struct.pack("<III", 0, entry, 0)


@pytest.fixture
def mp3(tmp_path):
    return lambda name="t.mp3", **kw: make_mp3(tmp_path / name, **kw)
