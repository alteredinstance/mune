import shutil

from mutagen.apev2 import APEv2
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK

from conftest import make_image
from mune.audio import compat, sanitize
from mune.audio.compat import Action


def _tag(path, *, v=3, art=None, **frames):
    t = ID3()
    t.add(TIT2(text=frames.get("title", "Song")))
    t.add(TPE1(text=frames.get("artist", ["Band"])))
    t.add(TALB(text=frames.get("album", "Record")))
    if "track" in frames:
        t.add(TRCK(text=frames["track"]))
    if art:
        t.add(APIC(encoding=3, mime="image/x", type=3, desc="", data=art))
    t.save(str(path), v2_version=v)


def test_clean_file_is_ok(mp3):
    p = mp3()
    _tag(p, art=make_image())
    assert compat.probe(p).action is Action.OK


def test_retag_fixes_v24_multiartist_png_and_ape(mp3):
    p = mp3()
    _tag(p, v=4, artist=["A", "B"], track="7/12", art=make_image("PNG", (900, 900)))
    ape = APEv2()
    ape["Title"] = "x"
    ape.save(str(p))
    audio_before = p.read_bytes()[p.read_bytes().find(b"\xff\xfb"):][:4000]

    rep = compat.probe(p)
    assert rep.action is Action.RETAG
    assert sanitize.fix(rep) == p

    tags = ID3(str(p))
    assert tags.version[:2] == (2, 3)
    assert tags["TPE1"].text == ["A"]
    assert str(tags["TPE2"]) == "A"
    assert str(tags["TRCK"]) == "7/12"
    assert tags.getall("APIC")[0].data[:2] == b"\xff\xd8"
    assert compat.probe(p).action is Action.OK
    assert audio_before in p.read_bytes()
    assert not list(p.parent.glob(".*mune-tmp*"))


def test_missing_tags_derived_from_path(tmp_path, mp3):
    album = tmp_path / "Some Album"
    album.mkdir()
    p = mp3("Some Album/03 - Cool Song.mp3")
    rep = compat.probe(p)
    assert rep.action is Action.RETAG
    sanitize.fix(rep)
    tags = ID3(str(p))
    assert str(tags["TIT2"]) == "Cool Song"
    assert str(tags["TALB"]) == "Some Album"
    assert str(tags["TRCK"]) == "3"


def test_lyrics3_is_stripped(mp3):
    p = mp3()
    lyr = b"LYRICSBEGIN" + b"IND0000210"
    p.write_bytes(p.read_bytes() + lyr + b"%06d" % len(lyr) + b"LYRICS200")
    _tag(p)
    sanitize.strip_tags(p)
    assert b"LYRICS" not in p.read_bytes()


def test_bad_streams_need_reencode(mp3):
    assert compat.probe(mp3("a.mp3", sample_rate=48000)).action is Action.REENCODE
    assert compat.probe(mp3("b.mp3", channels=1)).action is Action.REENCODE
    assert compat.probe(mp3("c.mp3", sample_rate=48000), sample_rates={44100, 48000}).action is not Action.REENCODE


def test_formats_without_decoder_convert(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"fLaC")
    assert compat.probe(p).action is Action.CONVERT


def test_reencode_keeps_tags(mp3, monkeypatch):
    p = mp3(sample_rate=48000)
    _tag(p, title="Keep Me", art=make_image())
    monkeypatch.setattr(sanitize, "transcode", lambda src, dst, opts: shutil.copy(src, dst))
    sanitize.fix(compat.probe(p))
    assert str(ID3(str(p))["TIT2"]) == "Keep Me"


def test_convert_refuses_to_clobber(tmp_path, mp3, monkeypatch):
    src = tmp_path / "t.flac"
    src.write_bytes(b"fLaC")
    mp3("t.mp3")
    monkeypatch.setattr(sanitize, "transcode", lambda *a: None)
    try:
        sanitize.fix(compat.probe(src))
    except sanitize.SanitizeError:
        pass
    else:
        raise AssertionError("expected SanitizeError")
    assert src.exists()
