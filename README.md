# mune

Community tools for Microsoft Zune players on modern Windows.

```
pip install -e .
mune doctor                          # drivers, software, device, firmware redirect
mune audio scan  F:\ZUNE\Music       # what the Zune won't play cleanly
mune audio fix   F:\ZUNE\Music --yes # fix it (dry run without --yes)
mune firmware verify <dir>           # check CAB signatures
mune firmware serve  <dir>           # serve official firmware locally
mune firmware inspect nk.bin --list  # list a ROM image's modules and files
```

Re-encoding and FLAC/Opus/Ogg conversion need ffmpeg on PATH (`winget install Gyan.FFmpeg`).

## Windows 11 setup

1. Install Zune software 4.8.2345.
2. Elevated PowerShell: `scripts\Install-ZuneDriver.ps1`
3. Optional, for firmware updates: `scripts\Set-ZuneHosts.ps1 -Local` and `mune firmware serve <dir>`, where `<dir>` holds the `*Baseline.cab` files and `firmware\v4_5\zuneprod.xml`.

Firmware is Microsoft's and is not distributed here. See [docs/firmware-notes.md](docs/firmware-notes.md).

## License

MIT
