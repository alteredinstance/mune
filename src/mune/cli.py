"""mune - community tools for Microsoft Zune players."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__


def _audio_files(root: Path):
    from .audio.compat import CONVERTIBLE, PLAYABLE
    exts = PLAYABLE | CONVERTIBLE
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts and ".mune-tmp" not in p.name:
            yield p


def cmd_doctor(args) -> int:
    from .device import doctor
    marks = {True: "ok ", False: "!! ", None: "-- "}
    failed = 0
    for c in doctor():
        print(f"{marks[c.ok]} {c.name}: {c.detail}")
        failed += c.ok is False
    return 1 if failed else 0


def cmd_audio(args) -> int:
    from .audio import compat, sanitize
    from .audio.compat import Action

    rates = {int(r) for r in args.sample_rates.split(",")}
    opts = sanitize.Options(bitrate=args.bitrate, sample_rate=min(rates),
                            delete_original=args.delete_original, overwrite=args.overwrite,
                            first_artist_only=not args.keep_all_artists)
    fixing = args.audio_cmd == "fix"
    if fixing and not args.yes:
        print("Dry run: showing what would change. Re-run with --yes to modify files.\n")

    needs_ffmpeg = sanitize.find_ffmpeg() is None
    tally, errors = Counter(), 0
    for path in _audio_files(Path(args.path)):
        rep = compat.probe(path, sample_rates=rates, reencode_vbr=not args.keep_vbr)
        tally[rep.action] += 1
        if rep.action is Action.OK:
            if args.verbose:
                print(f"ok        {path}")
            continue
        print(f"{rep.action.value:<9} {path}")
        for issue in rep.issues:
            print(f"            - {issue}")
        if not (fixing and args.yes):
            continue
        if rep.action in (Action.REENCODE, Action.CONVERT) and needs_ffmpeg:
            print("            skipped: needs ffmpeg")
            continue
        try:
            out = sanitize.fix(rep, opts)
            if out:
                print(f"            fixed -> {out.name}")
        except Exception as e:
            errors += 1
            print(f"            ERROR: {e}")

    print("\nSummary: " + ", ".join(f"{a.value} {n}" for a, n in sorted(tally.items(), key=lambda x: list(Action).index(x[0]))))
    if needs_ffmpeg and (tally[Action.REENCODE] or tally[Action.CONVERT]):
        print("ffmpeg was not found, so re-encode/convert items can't be fixed yet (winget install Gyan.FFmpeg).")
    return 1 if errors else 0


def cmd_fw_inspect(args) -> int:
    from .firmware import b000ff
    for f in args.files:
        img = b000ff.parse(f)
        print(b000ff.describe(img))
        if args.list:
            for e in img.entries:
                print(f"    {e.kind:<6} {e.size:>10,}  {e.name}")
        print()
    return 0


def cmd_fw_verify(args) -> int:
    from .firmware.manifest import MANIFEST_PATH, check_cabs, load_manifest
    root = Path(args.dir)
    manifest = root / MANIFEST_PATH
    if manifest.exists():
        print(f"Catalogue {manifest}:")
        for u in load_manifest(manifest):
            print(f"  {u.family:<24} {u.version:<42} {u.cab_name}")
        print()
    bad = 0
    for c in check_cabs(sorted(root.glob("*.cab"))):
        state = "TRUSTED  " if c.trusted else "UNTRUSTED"
        bad += not c.trusted
        print(f"{state} {c.path.name}")
        print(f"          sha256 {c.sha256}")
        print(f"          signature {c.signature or 'not checked'}  {c.signer or ''}".rstrip())
        if c.known_as:
            print(f"          matches known {c.known_as}")
    return 1 if bad else 0


def cmd_fw_serve(args) -> int:
    from .firmware.server import serve
    serve(Path(args.dir), host=args.host, port=args.port, allow_untrusted=args.allow_untrusted)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mune", description=__doc__)
    ap.add_argument("--version", action="version", version=f"mune {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="check drivers, software, device and firmware redirect (read-only)")
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("audio", help="find and fix files the Zune won't play cleanly")
    asub = a.add_subparsers(dest="audio_cmd", required=True)
    for name, helptext in (("scan", "report problems (never modifies files)"),
                           ("fix", "rewrite tags/art, re-encode or convert (dry run unless --yes)")):
        p = asub.add_parser(name, help=helptext)
        p.add_argument("path", help="file or folder, e.g. F:\\ZUNE\\Music")
        p.add_argument("-v", "--verbose", action="store_true", help="also list files that are fine")
        p.add_argument("--sample-rates", default="44100", help="acceptable MP3 sample rates (default 44100)")
        p.add_argument("--keep-vbr", action="store_true", help="don't re-encode VBR MP3s")
        p.add_argument("--bitrate", default="256k", help="CBR bitrate for re-encoded MP3 (default 256k)")
        p.add_argument("--keep-all-artists", action="store_true", help="don't collapse 'A; B' to 'A'")
        p.add_argument("--delete-original", action="store_true", help="remove FLAC/Opus/etc after converting")
        p.add_argument("--overwrite", action="store_true", help="replace an existing .mp3 when converting")
        p.add_argument("--yes", action="store_true", help=argparse.SUPPRESS if name == "scan" else "actually modify files")
        p.set_defaults(func=cmd_audio)

    f = sub.add_parser("firmware", help="study, verify and serve official firmware")
    fsub = f.add_subparsers(dest="fw_cmd", required=True)
    p = fsub.add_parser("inspect", help="parse WinCE B000FF images (nk.bin, EBoot.bin, recovery.bin)")
    p.add_argument("files", nargs="+")
    p.add_argument("--list", action="store_true", help="list every module and file in the ROM")
    p.set_defaults(func=cmd_fw_inspect)
    p = fsub.add_parser("verify", help="check CAB signatures and hashes in a firmware folder")
    p.add_argument("dir")
    p.set_defaults(func=cmd_fw_verify)
    p = fsub.add_parser("serve", help="serve verified firmware locally as resources.zune.net")
    p.add_argument("dir", help="folder containing *.cab and firmware/v4_5/zuneprod.xml")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=80)
    p.add_argument("--allow-untrusted", action="store_true", help="serve CABs that fail verification (dangerous)")
    p.set_defaults(func=cmd_fw_serve)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
