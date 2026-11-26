# OTA FW Merger (Android)

**Latest Release:** v2.0  
**Publisher:** JKurtz  
**Platform:** Android 9+ (`arm64-v8a`)  
**License:** GNU GPL-3.0

A standalone, self-contained Android APK built for **ColorOS** devices, with **experimental support for most A/B `payload.bin` Android devices** (including Nothing OS, Lenovo Legion, Motorola, Xiaomi HyperOS, and Google Pixel). Inspired by [koaaN/OTAFirmwareMerger](https://github.com/koaaN/OTAFirmwareMerger) and built with **Python + PySide6 (Qt 6.12)** and a **Real Android 12+ Monet Dynamic Color (Material 3)** UI, everything needed to download, extract, merge, verify, package, and fastboot-flash firmware runs directly on-device with no PC required.

> **Independent Community Port & Testing Note:**  
> This Android port is an independent community project and is **not affiliated with or supported by Jonas Salo (`koaaN`)**. Please direct all bug reports and questions to this repository's Issues tab.  
> The Android port, Material 3 UI, universal recovery/fastboot generator, and on-device Termux build pipeline were created with AI assistance and tested on-device on a rooted North American OnePlus 15 (`CPH2749`).

---

## Features

- **Full + Incremental OTA Merging:** Accepts Full OTA URLs/ZIPs, pre-extracted Full OTA folders, existing `MergedOTAFlasher` / `RegionalHybrid` / `SuperHybrid` base ZIPs, and chained Incremental OTA ZIPs/URLs.
- **Universal Custom Recovery + Fastboot Flashable ZIP (`MergedOTAFlasher_*.zip`):**
  - Built for **ColorOS** devices (OnePlus, Oppo, Realme — Snapdragon & MediaTek), with **experimental support for compiling recovery + fastboot flashable ZIPs for most A/B `payload.bin` Android devices** (Qualcomm `qti_dynamic_partitions`, MediaTek `main`, and Tensor `google_dynamic_partitions` fallbacks).
  - Packs merged images into `OS_FILES_HERE/` alongside a dynamic `META-INF/com/google/android/update-binary` (for **AERA** and **OrangeFox** recovery with `--virtual-ab` and 4 pre-flight safety guards) plus hardened companion PC fastboot scripts (`MergedOTAFlasher.sh` / `.bat` with `fastboot snapshot-update cancel`).
  - **This Device vs. Another Device** target prompt: enriches `META-INF` with live host metadata and auto-pulls missing EDL/regional images (`system_dlkm_oki`, `system_dlkm_gki`, `my_company`, `my_preload`) for the host device, or compiles strictly from the OTA ZIP's own metadata when building for another device.
  - Backward-compatible auto-ingestion for older `OOS_FILES_HERE` and `COS_FILES_HERE` ZIPs.
- **USB-OTG `Flasher` Tab** *(inspired by MIT-licensed [Jefino9488/Fastboot-Flasher](https://github.com/Jefino9488/Fastboot-Flasher))*: Bundles static `arm64-v8a` AOSP **`fastboot` and `adb`** directly inside the APK (`libfastboot.so` / `libadb.so`) so you can flash another device connected via USB-C OTG using a `MergedOTAFlasher` ZIP, image folder, or single `.img` (`boot`, `init_boot`, `recovery`, `vbmeta`), with Verity, Both-Slots, Wipe Data, Auto-Reboot toggles, and quick Bootloader/FastbootD/Reboot buttons.
- **Dump Entire System Image (Root):** For ARB-cautious / North American builds without downloadable Full OTAs, dumps all active-slot physical firmware partitions and raw dm-linear `super` slices (skipping `-verity`/`-cow` so AVB footers stay intact), with stock override pickers (`boot.img`, `init_boot.img`, `recovery.img`, plus any extra root-modified `.img`).
- **Internal CrAU v2 SHA-256 Verification + Optional Skip Toggle:** Pure-Python `DeltaArchiveManifest` protobuf verifier checks pre-merge base images (auto-trimming padded raw block dumps), post-merge OTA images (verified 65/65 on `CPH2749_17.0.0.102` -> `17.0.0.105`), and repacked Fake OTA `payload.bin` outputs — plus an optional **Skip Hash Check** toggle (with warning confirmation) to speed up merges when you know all images are unaltered.
- **Build "Fake" OTA:** Repacks merged `.img` files into a `testkey`-signed `payload.bin` ZIP (`payload.bin`, `payload_properties.txt`, `META-INF`) for chaining future incremental OTAs.
- **Device-Specific OTA Watcher:** 24-hour `JobScheduler` background checks + manual queries via `OplusUpdater v1.0.5` with model-based auto-routing, **Force Latest Incremental**, and **Root System Update Capture** for North American Google GOTA links.
- **Dynamic GitHub Binary Updater (Top-Right Refresh Pill):** Pulls updated upstream `arm64-v8a` binaries (`payload-dumper-rust`, `delta_generator`, `aria2c`, `adb`, `fastboot`) into `/data/local/tmp/otafwmerger_bins/` via root (with bundled `cacert.pem` + Android Conscrypt PEM TLS verification and 1-tap reset to bundled APK binaries).
- **Material You (Material 3) UI:** Real Android 12+ Monet wallpaper colors, pill buttons, 3-tab bottom bar (`Merger` / `Flasher` / `OTA Watcher`), smooth ping-pong marquee file picker with right-side checkboxes, and auto-collapsed 2-line live console previews.

---

## Required Permissions

1. **All Files Access (`MANAGE_EXTERNAL_STORAGE`) — Required**  
   Required so the picker and merge engine can read OTA ZIPs/folders and write outputs to `/storage/emulated/0/Download/OTAFirmwareMerger/output/`.
   - **Standard (No Root):** **Settings -> Apps -> Special app access -> All files access -> OTA FW Merger -> Allow**
   - **Via PC ADB (No Root):**
     ```bash
     adb shell appops set com.jkurtz.otafwmerger MANAGE_EXTERNAL_STORAGE allow
     ```
   - **Via Rooted Termux:**
     ```bash
     su -c 'appops set com.jkurtz.otafwmerger MANAGE_EXTERNAL_STORAGE allow'
     ```
2. **Notifications (`POST_NOTIFICATIONS`) — Optional**  
   Only needed if you enable the daily 24-hour background **OTA Watcher** push notifications.
3. **Storage Space:** Keep **20–30+ GB** of free internal storage for full OTA merges and custom recovery ZIP packaging.

---

## Root Is Optional

**Root is NOT required** to install or use the core OTA merger:

| Feature | Without Root | With Root (`su`) |
| :--- | :---: | :---: |
| Merge Full + Incremental OTA ZIPs / URLs / Folders | ✅ | ✅ |
| Internal CrAU v2 SHA-256 Verification & Skip Toggle | ✅ | ✅ |
| Build "Fake" `testkey`-Signed OTA ZIPs | ✅ | ✅ |
| Build Universal `MergedOTAFlasher` Recovery + Fastboot ZIPs (from OTA ZIPs/folders) | ✅ | ✅ |
| OTA Watcher for CN / EU / IN / GLO (`OplusUpdater`) | ✅ | ✅ |
| Dump Entire System Image from Live Device (`device://dump`) | ❌ | ✅ |
| Auto-Pull Missing EDL / Regional Images (`system_dlkm_oki`/`gki`, `my_company`, `my_preload`) | ❌ | ✅ |
| Live Host Device `META-INF` Probing | ❌ *(uses OTA metadata)* | ✅ |
| Capture NA Google GOTA URLs from System Update | ❌ | ✅ |
| USB-OTG Phone-to-Phone `Flasher` Tab (`fastboot`) | ❌ | ✅ |
| Dynamic GitHub Binary Updater (`/data/local/tmp/`) | ❌ *(uses bundled APK binaries)* | ✅ |

---

## Installation & Obtainium Auto-Updates

### Option A — Direct Download
1. Download the latest `OTAFWMerger-v2.0-JKurtz-arm64-v8a.apk` from [Releases](https://github.com/JKurtz97/OTA-FW-Merger-Android/releases) and install it. *(Signed with a debug key — tap **Install anyway** if Play Protect prompts.)*
2. Grant **All files access** using one of the methods above.

### Option B — Automatic Updates via [Obtainium](https://github.com/ImranR98/Obtainium)
1. Open **Obtainium** -> tap **Add App**.
2. Paste this repository URL:
   ```text
   https://github.com/JKurtz97/OTA-FW-Merger-Android
   ```
3. Tap **Add** — Obtainium will automatically track new GitHub Releases and install the latest `arm64-v8a` APK.

### Output Location
```text
/storage/emulated/0/Download/OTAFirmwareMerger/output/
```

---

## Important Disclaimers

- **Always back up** important data and keep a working stock `boot.img` / `init_boot.img` before flashing.
- **Custom Recovery Requirement:** Universal `MergedOTAFlasher` recovery ZIPs target **AERA** or **OrangeFox** recovery with an unlocked bootloader. Non-ColorOS device support is experimental — recovery logs and feedback are welcome.
- **Fake OTA ZIPs** are signed with AOSP `testkey.key` for chaining future incremental merges, **not** direct stock Local Install.

---

## Credits & Upstream Projects

- **[koaaN (Jonas Salo)](https://github.com/koaaN)** — Original desktop [OTAFirmwareMerger](https://github.com/koaaN/OTAFirmwareMerger) and [Universal_Flasher](https://github.com/koaaN/Universal_Flasher) (`docnok63`, Daniel, `FTH PHONE 1902`, `Venkayy`)
- **[Google / Android SDK Platform-Tools](https://developer.android.com/tools/adb)** — Official AOSP `adb` & `fastboot` (Apache-2.0)
- **[lzhiyong/android-sdk-tools](https://github.com/lzhiyong/android-sdk-tools)** & **[lzhiyong/termux-ndk](https://github.com/lzhiyong/termux-ndk)** — Static `aarch64` Android builds of AOSP `adb`/`fastboot` and on-device NDK (Apache-2.0)
- **[Jefino9488/Fastboot-Flasher](https://github.com/Jefino9488/Fastboot-Flasher)** — Fastboot Flasher workflow inspiration (MIT)
- **[Houvven/OplusUpdater](https://pkg.go.dev/github.com/Houvven/OplusUpdater)** — OPLUS/OPPO/OnePlus/Realme OTA query engine (`v1.0.5`, GPL-3.0)
- **[rhythmcache/payload-dumper-rust](https://github.com/rhythmcache/payload-dumper-rust)** — Static `aarch64` Android payload extractor (`v0.8.4`, Apache-2.0)
- **[snowwolf725/Payload_Repack_Tool](https://github.com/snowwolf725/Payload_Repack_Tool)** — `delta_generator_aarch64` payload repacking workflow (MIT)
- **[aria2/aria2](https://github.com/aria2/aria2)** — Multi-connection download engine (`1.37.0`, GPL-2.0+)
- **[luk1337/oplus_archive](https://github.com/luk1337/oplus_archive)** & **[R0rt1z2/realme-ota](https://github.com/R0rt1z2/realme-ota)** — OPLUS OTA pipeline references
- **[EchterAlsFake/PySide6-to-Android](https://github.com/EchterAlsFake/PySide6-to-Android)** & **[PySide6 / Qt](https://pypi.org/project/PySide6/)** — Qt 6 Android packaging & UI framework (LGPL-3.0 / GPL-3.0)

See `THIRD_PARTY_NOTICES.md` for full licensing details.
