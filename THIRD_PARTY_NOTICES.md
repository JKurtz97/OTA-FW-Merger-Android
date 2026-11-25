# Third-Party Open-Source Notices

OTA FW Merger for Android bundles or invokes the following open-source components. Each component remains governed by its respective upstream license.

| Component | Bundled As | Version | License | Upstream Source |
| :--- | :--- | :--- | :--- | :--- |
| **aria2** | `libaria2c.so` | 1.37.0 | GPL-2.0-or-later (OpenSSL exception) | https://github.com/aria2/aria2 |
| **OplusUpdater** | `liboplus_updater.so` | v1.0.5 | GPL-3.0 | https://pkg.go.dev/github.com/Houvven/OplusUpdater |
| **payload-dumper-rust** | `libota_extractor.so` | 0.8.4 | Apache-2.0 | https://github.com/rhythmcache/payload-dumper-rust |
| **Payload_Repack_Tool** (`delta_generator`) | `libdelta_generator.so` | aarch64 | MIT / Apache-2.0 (AOSP `update_engine`) | https://github.com/snowwolf725/Payload_Repack_Tool |
| **PySide6 / Qt 6** | Python/Qt runtime `.so` | 6.12.0 | LGPL-3.0 / GPL-3.0 | https://pypi.org/project/PySide6/ |

## Corresponding Source
- Upstream source code for every GPL/LGPL component above is available at the respective upstream URLs and release tags listed in the table.
- This repository is released under **GNU GPL-3.0** (`LICENSE`).
