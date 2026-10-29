from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import (APIC, ID3, TALB, TCON, TIT2, TPE1, TPE2, TPOS, TRCK,
                         TYER, Encoding, ID3NoHeaderError)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from . import compat
from .compat import Action, Report

try:
    from mutagen.apev2 import APEv2
except ImportError:  # pragma: no cover
    APEv2 = None

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except ImportError:  # pragma: no cover
    Image = None

ART_JPEG_QUALITY = 85
ARTIST_SPLIT_RE = re.compile(r"\s*(?:;|\x00| / )\s*")
TRACK_PREFIX_RE = re.compile(r"^\s*(\d{1,3})\s*[-._)\]]?\s+")


@dataclass
class Options:
    bitrate: str = "256k"
    sample_rate: int = 44100
    delete_original: bool = False
    overwrite: bool = False
    first_artist_only: bool = True


@dataclass
class Meta:
    title: str = ""
    artist: str = ""
    albumartist: str = ""
    album: str = ""
    year: str = ""
    track: str = ""
    disc: str = ""
    genre: str = ""
    art: bytes | None = None


class SanitizeError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    return os.environ.get("MUNE_FFMPEG") or shutil.which("ffmpeg")


def fix(report: Report, opts: Options = Options()) -> Path | None:
    src = report.path
    if report.action in (Action.OK, Action.UNSUPPORTED):
        return None

    meta = read_meta(src)
    if report.action is Action.CONVERT:
        dst = src.with_suffix(".mp3")
        if dst.exists() and not opts.overwrite:
            raise SanitizeError(f"{dst.name} already exists (use --overwrite)")
    else:
        dst = src

    tmp = dst.with_name(f".{dst.stem}.mune-tmp{dst.suffix}")
    try:
        if report.action in (Action.CONVERT, Action.REENCODE):
            transcode(src, tmp, opts)
        else:
            shutil.copy2(src, tmp)

        if tmp.suffix.lower() == ".mp3":
            write_clean_id3(tmp, meta, opts)
        elif tmp.suffix.lower() in (".m4a", ".mp4"):
            fix_mp4_art(tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()

    if report.action is Action.CONVERT and opts.delete_original:
        src.unlink()
    return dst


def transcode(src: Path, dst: Path, opts: Options) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SanitizeError("ffmpeg not found; install it or set MUNE_FFMPEG")
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-map", "0:a:0", "-map_metadata", "-1", "-vn",
           "-c:a", "libmp3lame", "-b:a", opts.bitrate,
           "-ar", str(opts.sample_rate), "-ac", "2", "-f", "mp3", str(dst)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if proc.returncode != 0:
        raise SanitizeError(f"ffmpeg failed: {proc.stderr.strip()[-400:]}")



def read_meta(path: Path) -> Meta:
    m = Meta()
    if path.suffix.lower() == ".mp3":
        _read_id3(path, m)
    else:
        _read_generic(path, m)

    m.title = m.title or _title_from_filename(path)
    m.album = m.album or path.parent.name or "Unknown Album"
    m.artist = m.artist or m.albumartist or "Unknown Artist"
    m.albumartist = m.albumartist or m.artist
    if not m.track:
        hit = TRACK_PREFIX_RE.match(path.stem)
        if hit and 0 < int(hit.group(1)) < 1000:
            m.track = str(int(hit.group(1)))
    return m


def _first(tags, key) -> str:
    fr = tags.get(key) if tags is not None else None
    if fr is None:
        return ""
    vals = getattr(fr, "text", fr)
    if isinstance(vals, (list, tuple)):
        vals = [str(v) for v in vals if str(v).strip()]
        return " / ".join(vals) if key in ("TPE1", "TPE2") else (vals[0] if vals else "")
    return str(vals).strip()


def _read_id3(path: Path, m: Meta) -> None:
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = None
    if tags is not None:
        m.title = _first(tags, "TIT2")
        m.artist = _first(tags, "TPE1")
        m.albumartist = _first(tags, "TPE2")
        m.album = _first(tags, "TALB")
        m.track = _first(tags, "TRCK")
        m.disc = _first(tags, "TPOS")
        m.genre = _first(tags, "TCON")
        m.year = _year(_first(tags, "TYER") or _first(tags, "TDRC"))
        apics = tags.getall("APIC")
        front = [a for a in apics if a.type == 3]
        if apics:
            m.art = (front or apics)[0].data
    if not (m.title and m.artist and m.album):
        v1 = _read_id3v1(path)
        m.title = m.title or v1.get("title", "")
        m.artist = m.artist or v1.get("artist", "")
        m.album = m.album or v1.get("album", "")
        m.year = m.year or _year(v1.get("year", ""))


def _read_id3v1(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            f.seek(-128, 2)
            tail = f.read(128)
    except OSError:
        return {}
    if len(tail) != 128 or tail[:3] != b"TAG":
        return {}
    clean = lambda b: b.decode("latin-1", "replace").rstrip("\x00 ").strip()
    return {"title": clean(tail[3:33]), "artist": clean(tail[33:63]),
            "album": clean(tail[63:93]), "year": clean(tail[93:97])}


def _read_generic(path: Path, m: Meta) -> None:
    try:
        easy = MutagenFile(str(path), easy=True)
    except Exception:
        easy = None
    if easy is not None and easy.tags is not None:
        get = lambda k: next((str(v).strip() for v in easy.tags.get(k, []) if str(v).strip()), "")
        m.title, m.album, m.genre = get("title"), get("album"), get("genre")
        m.artist = " / ".join(str(v) for v in easy.tags.get("artist", []) if str(v).strip())
        m.albumartist = get("albumartist") or get("album artist")
        m.track, m.disc = get("tracknumber"), get("discnumber")
        m.year = _year(get("date") or get("year"))

    try:
        full = MutagenFile(str(path))
    except Exception:
        full = None
    if isinstance(full, FLAC) and full.pictures:
        m.art = full.pictures[0].data
    elif isinstance(full, MP4):
        m.art = compat._mp4_art(full)
    elif full is not None and full.tags is not None and "metadata_block_picture" in full.tags:
        import base64
        from mutagen.flac import Picture
        try:
            m.art = Picture(base64.b64decode(full.tags["metadata_block_picture"][0])).data
        except Exception:
            pass


def _year(s: str) -> str:
    hit = re.search(r"(\d{4})", s or "")
    return hit.group(1) if hit else ""


def _title_from_filename(path: Path) -> str:
    base = TRACK_PREFIX_RE.sub("", path.stem)
    return re.sub(r"\s+", " ", base.replace("_", " ")).strip() or "Untitled"


def _artist(value: str, first_only: bool) -> str:
    if not first_only:
        return value
    parts = [p for p in ARTIST_SPLIT_RE.split(value) if p.strip()]
    return parts[0] if parts else value



def strip_tags(path: Path) -> None:
    try:
        ID3(str(path)).delete(str(path), delete_v1=True, delete_v2=True)
    except ID3NoHeaderError:
        pass
    if APEv2 is not None:
        try:
            APEv2(str(path)).delete(str(path))
        except Exception:
            pass
    _strip_lyrics3(path)


def _strip_lyrics3(path: Path) -> None:
    with open(path, "r+b") as f:
        f.seek(0, 2)
        size = f.tell()
        if size < 15:
            return
        f.seek(-9, 2)
        if f.read(9) != b"LYRICS200":
            return
        f.seek(-15, 2)
        length = int(f.read(6) or b"0")
        start = size - 15 - length
        f.seek(start)
        if f.read(11) == b"LYRICSBEGIN":
            f.truncate(start)


def write_clean_id3(path: Path, meta: Meta, opts: Options) -> None:
    strip_tags(path)
    tags = ID3()
    u16 = Encoding.UTF16
    tags.add(TIT2(encoding=u16, text=meta.title))
    tags.add(TPE1(encoding=u16, text=_artist(meta.artist, opts.first_artist_only)))
    tags.add(TPE2(encoding=u16, text=_artist(meta.albumartist, opts.first_artist_only)))
    tags.add(TALB(encoding=u16, text=meta.album))
    if meta.year:
        tags.add(TYER(encoding=u16, text=meta.year))
    if meta.track:
        tags.add(TRCK(encoding=u16, text=meta.track))
    if meta.disc:
        tags.add(TPOS(encoding=u16, text=meta.disc))
    if meta.genre:
        tags.add(TCON(encoding=u16, text=meta.genre))
    art = normalize_art(meta.art) if meta.art else None
    if art:
        tags.add(APIC(encoding=u16, mime="image/jpeg", type=3, desc="", data=art))
    tags.save(str(path), v2_version=3, v1=2)


def normalize_art(data: bytes) -> bytes | None:
    if compat.art_problem(data) is None:
        return data
    if Image is None:
        return None
    try:
        with Image.open(BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((compat.ART_MAX_PX, compat.ART_MAX_PX), Image.LANCZOS)
            out = BytesIO()
            im.save(out, format="JPEG", quality=ART_JPEG_QUALITY, optimize=True, progressive=False)
            return out.getvalue()
    except Exception:
        return None


def fix_mp4_art(path: Path) -> None:
    audio = MP4(str(path))
    art = compat._mp4_art(audio)
    if not art:
        return
    fixed = normalize_art(art)
    if fixed is None:
        del audio.tags["covr"]
    elif fixed is not art:
        audio.tags["covr"] = [MP4Cover(fixed, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()
