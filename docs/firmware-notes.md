# Firmware notes

From `KeelBaseline.cab` (Zune 30, 3.30.00039.00-00435), sha256 `0aaa0fe1…5bb8e`, Authenticode-signed by Microsoft.

| File | Format | Load / entry | Notes |
|---|---|---|---|
| `EBoot.bin` | B000FF, 12 records | 0x80000000 / 0x80002000 | bootloader, no ROMHDR |
| `recovery.bin` | B000FF, 22 records | 0x80080000 / 0x80081000 | recovery image, no ROMHDR at +0x40 |
| `nk.bin` | B000FF, 109 records | 0x88200000 / 0x88201000 | Windows CE OS, 128 modules, 26 files, ARM Thumb |
| `Games.cab` | CAB | | XNA games |

All record checksums verify.

## Hardware (from driver modules in nk.bin)

- Freescale i.MX31 SoC: `pmc_atapi_mx31.dll`, `ipu_base.dll`, `mx32_vpu_dec_dshow.dll`
- Wolfson WM8978 codec: `wavedev_wm8978.dll`
- Freescale "Atlas" PMIC: `pmicPdk_atlas.dll`, `battdrvr_atlas.dll`
- Wi-Fi KS7010 over SDIO: `ks7010sd.dll`, `ks7010sd.rom`
- FM tuner: `FMTuner.dll`

## Audio decoders

`mp3_dec_dmo.dll`, `aac_dec_dmo.dll` + `mp4parser.dll`, `wmadmod.dll` / `wmadmods.dll`, `audible.dll`. No FLAC, Vorbis or Opus, so `mune audio` converts those to MP3.

## Trust chain

`zuneroots.p7b`, `zuneca.p7b`, `devcerttemplate.dat`, `keyvault.dll`, `KvCrypt.dll`, `wmdrm.dll`. These are the likely pieces behind firmware and content signature checks. Unverified: whether EBoot checks the signature on nk.bin, and where. That's the first question for custom firmware.

## Open questions

- Does EBoot.bin verify nk.bin, and is any pre-EBoot ROM stage involved?
- Contents of `recovery.bin` (no ROMHDR at the usual offset).
- The Zune 30 is close to the Toshiba Gigabeat S (also i.MX31), which Rockbox supports. How much of that port applies?
