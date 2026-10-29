from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3, BitrateMode
from mutagen.mp4 import MP4

try:
    from mutagen.apev2 import APEv2, APENoHeaderError
except ImportError:  # pragma: no cover
    APEv2 = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

PLAYABLE = {".mp3", ".m4a", ".mp4", ".wma"}
CONVERTIBLE = {".flac", ".ogg", ".oga", ".opus", ".wav", ".aif", ".aiff", ".ape", ".wv", ".alac"}

ART_MAX_PX = 600
GOOD_SAMPLE_RATES = {44100}


class Action(Enum):
    OK = "ok"
    RETAG = "retag"          # tags/art only, audio untouched
    REENCODE = "reencode"    # MP3 the Zune chokes on -> CBR MP3
    CONVERT = "convert"      # format the Zune has no decoder for -> MP3
    UNSUPPORTED = "unsupported"


@dataclass
class Report:
    path: Path
    action: Action
    issues: list[str] = field(default_factory=list)

    def add(self, action: Action, issue: str) -> None:
        self.issues.append(issue)
        order = list(Action)
        if order.index(action) > order.index(self.action):
            self.action = action


def probe(path: Path, *, sample_rates=GOOD_SAMPLE_RATES, reencode_vbr: bool = True) -> Report:
    ext = path.suffix.lower()
    rep = Report(path, Action.OK)

    if ext in CONVERTIBLE:
        rep.add(Action.CONVERT, f"{ext} has no decoder on the Zune")
        return rep
    if ext not in PLAYABLE:
        rep.add(Action.UNSUPPORTED, f"unknown audio type {ext}")
        return rep

    try:
        audio = MutagenFile(str(path))
    except Exception as e:
        rep.add(Action.UNSUPPORTED, f"unreadable: {e}")
        return rep
    if audio is None:
        rep.add(Action.UNSUPPORTED, "unreadable: not recognised as audio")
        return rep

    if isinstance(audio, MP3):
        _probe_mp3(path, audio, rep, sample_rates, reencode_vbr)
    elif isinstance(audio, MP4):
        codec = getattr(audio.info, "codec", "") or ""
        if codec and not codec.startswith("mp4a"):
            rep.add(Action.CONVERT, f"MP4 codec {codec} (e.g. ALAC) is not AAC")
        _check_art_bytes(_mp4_art(audio), rep)
    return rep


def _probe_mp3(path: Path, audio: MP3, rep: Report, sample_rates, reencode_vbr: bool) -> None:
    info = audio.info
    if info.version != 1:
        rep.add(Action.REENCODE, f"MPEG-{info.version:g} audio (low sample rate stream)")
    if info.layer != 3:
        rep.add(Action.REENCODE, f"MPEG layer {info.layer}, not layer III")
    if info.sample_rate not in sample_rates:
        rep.add(Action.REENCODE, f"sample rate {info.sample_rate} Hz")
    if info.channels != 2:
        rep.add(Action.REENCODE, f"{info.channels} channel(s)")
    if info.bitrate and info.bitrate > 320_000:
        rep.add(Action.REENCODE, f"bitrate {info.bitrate // 1000} kbps exceeds 320")
    if reencode_vbr and info.bitrate_mode in (BitrateMode.VBR, BitrateMode.ABR):
        rep.add(Action.REENCODE, f"{info.bitrate_mode.name} encoding")

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = None
    if tags is None:
        rep.add(Action.RETAG, "no ID3v2 tag")
    else:
        if tags.version[1] != 3:
            rep.add(Action.RETAG, f"ID3v2.{tags.version[1]} (Zune wants v2.3)")
        for key in ("TIT2", "TPE1", "TALB"):
            if not str(tags.get(key, "")).strip():
                rep.add(Action.RETAG, f"missing {key}")
        for key in ("TPE1", "TPE2"):
            fr = tags.get(key)
            if fr is not None and len(fr.text) > 1:
                rep.add(Action.RETAG, f"multi-value {key}")
        apics = tags.getall("APIC")
        if len(apics) > 1:
            rep.add(Action.RETAG, f"{len(apics)} embedded pictures")
        if apics:
            _check_art_bytes(apics[0].data, rep)

    if APEv2 is not None:
        try:
            APEv2(str(path))
            rep.add(Action.RETAG, "APEv2 tag present")
        except Exception:
            pass
    if _has_lyrics3(path):
        rep.add(Action.RETAG, "Lyrics3 tag present")


def _has_lyrics3(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(-128 - 9, 2)
            tail = f.read(9)
        return tail in (b"LYRICS200", b"LYRICSEND")
    except OSError:
        return False


def _mp4_art(audio: MP4) -> bytes | None:
    covr = (audio.tags or {}).get("covr")
    return bytes(covr[0]) if covr else None


def art_problem(data: bytes) -> str | None:
    if Image is None:
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format != "JPEG":
                return f"cover art is {im.format}, not JPEG"
            if im.info.get("progressive") or im.info.get("progression"):
                return "cover art is progressive JPEG"
            if im.mode not in ("RGB", "L"):
                return f"cover art colour mode {im.mode}"
            if max(im.size) > ART_MAX_PX:
                return f"cover art {im.size[0]}x{im.size[1]} larger than {ART_MAX_PX}px"
    except Exception:
        return "cover art is unreadable"
    return None


def _check_art_bytes(data: bytes | None, rep: Report) -> None:
    if data:
        problem = art_problem(data)
        if problem:
            rep.add(Action.RETAG, problem)
