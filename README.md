# OTA FW Merger (Android)

**Version:** 1.6  
**Publisher:** JKurtz  
**Platform:** Android 9+ (`arm64-v8a`)  
**License:** GNU GPL-3.0

A standalone, self-contained Android APK port inspired by [koaaN/OTAFirmwareMerger](https://github.com/koaaN/OTAFirmwareMerger), built with **Python + PySide6 (Qt 6.12)** and a **Real Android 12+ Monet Dynamic Color (Material 3)** interface. Download, extract, merge, verify, and package ColorOS / OxygenOS OTA firmware directly on-device.

> **Independent Community Port & Testing Note:**  
> This Android port is an independent community project and is **not affiliated with or supported by Jonas Salo (`koaaN`)**. Please direct all bug reports and questions to this repository's Issues tab.  
> The Android port, Material 3 UI, universal recovery generator, and on-device Termux build pipeline were created with AI assistance and tested on-device on a rooted North American OnePlus 15 (`CPH2749`).

---

## Features (v1.6)

- **Full + Incremental OTA Merging:** Supports Full OTA URLs/ZIPs, pre-extracted Full OTA folders, existing RegionalHybrid / SuperHybrid base ZIPs, and chained Incremental OTA ZIPs/URLs.
- **Universal ColorOS & OxygenOS Custom Recovery Flashable ZIPs:**
  - **RegionalHybrid (`OOS_FILES_HERE`)** and **SuperHybrid (`COS_FILES_HERE`)** modes — both generate dynamic universal `META-INF/com/google/android/update-binary` recovery flashers (for **Aera** and **OrangeFox** recovery) plus companion PC `fastboot`/`fastbootd` scripts (`Regional_Flasher.sh`/`.bat` or `SuperHybrid_Flasher.sh`/`.bat`).
  - Live root device metadata probing (`ro.product.model`, `ro.product.device`, `ro.board.platform`, `super` dynamic partition group, and raw `/dev/block/mapper/` logical partitions) with initial OTA ZIP metadata priority.
  - Built-in **4 pre-flight safety guards** before touching disk: recovery tool check (`lpmake`, `simg2img`, `blockdev`, `unzip`), `/sdcard` free-space check, per-partition block-size bounds check, and core `super` completeness check (`--virtual-ab` enabled).
  - **Auto-Pull All 3 From Device (Root):** One-tap root pull for `my_company.img`, `my_preload.img`, and `system_dlkm_oki.img` in RegionalHybrid mode.
- **Dump Entire System Image (Root):** For devices without a downloadable Full OTA (such as ARB-cautious North American builds), dumps all active-slot physical firmware partitions and raw dm-linear `super` slices (skipping `-verity`/`-cow`), with stock override pickers for root-modified images (`boot.img`, `init_boot.img`, `recovery.img`, plus custom `.img`s).
- **Internal CrAU v2 SHA-256 Hash Verification:** Pure-Python `DeltaArchiveManifest` protobuf verifier checks pre-merge base images (with raw-block auto-trim), post-merge OTA images (verified 65/65 on `CPH2749_17.0.0.102` -> `17.0.0.105`), and repacked Fake OTA `payload.bin` outputs.
- **Build "Fake" OTA:** Repacks merged `.img` files into a `testkey`-signed `payload.bin` ZIP for chaining future incremental OTAs.
- **Device-Specific OTA Watcher:** 24-hour `JobScheduler` background checks + manual queries via `OplusUpdater v1.0.5` with model-based auto-routing and Magisk / KernelSU Next **Root System Update Capture** for North American Google GOTA URLs.
- **Real Android 12+ Monet Dynamic Color UI:** Native `MonetInitProvider.java` exports live wallpaper palette tokens and Dark/Light mode, paired with a 2-tab Material 3 bottom bar and 120fps touch-scroll file picker with right-side checkboxes.

---

## Installation & Permissions

1. Download `OTAFWMerger-v1.6-JKurtz-arm64-v8a.apk` from **Releases** and install it.
2. Grant **All files access (`MANAGE_EXTERNAL_STORAGE`)**:
   - **Settings -> Apps -> Special app access -> All files access -> OTA FW Merger -> Allow**
   - Or via rooted Termux / ADB:
     ```bash
     su -c 'appops set com.jkurtz.otafwmerger MANAGE_EXTERNAL_STORAGE allow'
     ```
3. Keep **20–30+ GB** of free internal storage for full merges and recovery ZIP packaging.

### Output Directory
```text
/storage/emulated/0/Download/OTAFirmwareMerger/output/
```

---

## Important Disclaimers

- **Always back up** important data and keep a working stock `boot.img` / `init_boot.img` before flashing.
- **Custom Recovery Requirement:** Universal RegionalHybrid / SuperHybrid ZIPs target **Aera** or **OrangeFox** recovery with an unlocked bootloader. Non-OnePlus 15 devices are currently **community beta** — feedback and recovery logs are welcome!
- **Fake OTA ZIPs** are signed with AOSP `testkey.key` and are meant for chaining future incremental merges, **not** direct stock Local Install.

---

## Credits & Upstream Projects

- **[koaaN (Jonas Salo)](https://github.com/koaaN)** — Original desktop `OTAFirmwareMerger` concept and Regional Flasher pioneering work (alongside `docnok63`, Daniel, `FTH PHONE 1902`, and `Venkayy`)
- **[Houvven/OplusUpdater](https://pkg.go.dev/github.com/Houvven/OplusUpdater)** — OPLUS/OPPO/OnePlus/Realme OTA query engine (`v1.0.5`, GPL-3.0)
- **[rhythmcache/payload-dumper-rust](https://github.com/rhythmcache/payload-dumper-rust)** — Static `aarch64` Android payload extractor (`v0.8.4`, Apache-2.0)
- **[snowwolf725/Payload_Repack_Tool](https://github.com/snowwolf725/Payload_Repack_Tool)** — `delta_generator_aarch64` payload repacking workflow (MIT)
- **[aria2/aria2](https://github.com/aria2/aria2)** — Multi-connection download engine (`1.37.0`, GPL-2.0+)
- **[luk1337/oplus_archive](https://github.com/luk1337/oplus_archive)** & **[R0rt1z2/realme-ota](https://github.com/R0rt1z2/realme-ota)** — OPLUS OTA pipeline references
- **[lzhiyong/termux-ndk](https://github.com/lzhiyong/termux-ndk)** & **[EchterAlsFake/PySide6-to-Android](https://github.com/EchterAlsFake/PySide6-to-Android)** — On-device Android NDK & PySide6 build tooling

See `THIRD_PARTY_NOTICES.md` for full licensing details.
