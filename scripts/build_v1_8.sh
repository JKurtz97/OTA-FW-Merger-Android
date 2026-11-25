#!/usr/bin/env bash
set -eo pipefail
source ~/.bashrc 2>/dev/null || true
source ~/pyside-build-venv/bin/activate 2>/dev/null || true
cd ~/build/OTAFirmwareMerger

BUILD_LOG="/sdcard/Download/build_v1_8.log"
: > "$BUILD_LOG"
exec > >(tee -a "$BUILD_LOG") 2>&1

export GRADLE_OPTS="-Xmx1536m -XX:MaxMetaspaceSize=512m"
DIST_ROOT=".buildozer/android/platform/build-arm64-v8a/dists/otafwmerger"

echo "=== 1. PATCH main.py (UNIVERSAL COLOROS/OOS REGIONALHYBRID & SUPERHYBRID + LIVE ROOT META + FULL DUMP + SHA-256) ==="
python3 - << 'PYEOF'
import json
import re
from pathlib import Path

mp = Path("main.py")
txt = mp.read_text()
txt = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "1.8"', txt, count=1)

# Ensure hashlib and struct are imported
if "import hashlib" not in txt:
    txt = txt.replace("import json", "import hashlib\nimport json\nimport struct", 1)
elif "import struct" not in txt:
    txt = txt.replace("import hashlib", "import hashlib\nimport struct", 1)

# ---------------------------------------------------------------------------
# 1a. Helpers: Universal META-INF/fastboot generators + CrAU v2 SHA-256 parser
# ---------------------------------------------------------------------------
superhybrid_helpers = r'''
DEFAULT_LOGICAL_PARTITIONS = {
    "system", "system_ext", "product", "vendor", "odm",
    "system_dlkm", "system_dlkm_oki", "system_dlkm_gki", "vendor_dlkm", "odm_dlkm",
    "my_bigball", "my_carrier", "my_company", "my_engineering",
    "my_heytap", "my_manifest", "my_preload", "my_product",
    "my_region", "my_stock", "my_version",
}

EARLY_BOOT_PARTITIONS = [
    "boot", "dtbo", "init_boot", "modem", "recovery",
    "vbmeta", "vbmeta_system", "vbmeta_vendor", "vendor_boot",
]

# Non-OTA / user / calibration partitions to NEVER dump from /dev/block/by-name/
DUMP_EXCLUDE_PARTITIONS = {
    "super", "userdata", "metadata", "cache", "persist", "frp", "misc",
    "keystore", "ddr", "cdt", "ssd", "fsc", "fsg", "modemst1", "modemst2",
    "modemdump", "rawdump", "minidump", "last_kmsg", "oops", "param",
    "oplusreserve1", "oplusreserve2", "oplusreserve3", "oplusreserve4",
    "oplusreserve5", "reserve1", "reserve2", "reserve3", "reserve4",
    "expdb", "seccfg", "nvram", "nvdata", "nvcfg", "protect1", "protect2",
    "proinfo", "otp", "flashinfo", "pgpt", "sgpt", "boot_para",
}


def is_default_logical_name(part_name: str) -> bool:
    p = part_name.lower()
    return p in DEFAULT_LOGICAL_PARTITIONS or p.startswith("my_") or p.startswith("system_dlkm") or p.endswith("_dlkm")


# --- Pure-Python CrAU v2 payload.bin DeltaArchiveManifest SHA-256 parser ---
def _pb_read_varint(buf: bytes, pos: int):
    val, shift = 0, 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
    raise ValueError("Truncated protobuf varint")


def _pb_iter_fields(buf: bytes):
    pos, n = 0, len(buf)
    while pos < n:
        tag, pos = _pb_read_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:
            val, pos = _pb_read_varint(buf, pos)
            yield field_num, wire_type, val
        elif wire_type == 1:
            yield field_num, wire_type, buf[pos:pos + 8]
            pos += 8
        elif wire_type == 2:
            ln, pos = _pb_read_varint(buf, pos)
            yield field_num, wire_type, buf[pos:pos + ln]
            pos += ln
        elif wire_type == 5:
            yield field_num, wire_type, buf[pos:pos + 4]
            pos += 4
        else:
            break


def _pb_parse_part_info(buf: bytes):
    size, digest = None, None
    for fnum, wt, val in _pb_iter_fields(buf):
        if fnum == 1 and wt == 0:
            size = int(val)
        elif fnum == 2 and wt == 2:
            digest = val.hex()
    return size, digest


def parse_payload_partition_hashes(payload_path: str) -> dict:
    """Return {part_name: {'old_size', 'old_sha256', 'new_size', 'new_sha256'}} from CrAU v2 payload.bin."""
    out = {}
    try:
        with open(payload_path, "rb") as fp:
            magic = fp.read(4)
            if magic != b"CrAU":
                return out
            ver, manifest_size = struct.unpack(">QQ", fp.read(16))
            if ver != 2 or manifest_size <= 0 or manifest_size > 64 * 1024 * 1024:
                return out
            _meta_sig_size = struct.unpack(">I", fp.read(4))[0]
            manifest_bytes = fp.read(manifest_size)
        for fnum, wt, val in _pb_iter_fields(manifest_bytes):
            if fnum == 13 and wt == 2:
                pname = ""
                old_sz = old_h = new_sz = new_h = None
                for pf, pwt, pval in _pb_iter_fields(val):
                    if pf == 1 and pwt == 2:
                        pname = pval.decode("utf-8", "replace")
                    elif pf == 6 and pwt == 2:
                        old_sz, old_h = _pb_parse_part_info(pval)
                    elif pf == 7 and pwt == 2:
                        new_sz, new_h = _pb_parse_part_info(pval)
                if pname:
                    out[pname] = {
                        "old_size": old_sz,
                        "old_sha256": old_h,
                        "new_size": new_sz,
                        "new_sha256": new_h,
                    }
    except Exception:
        pass
    return out


def sha256_file(path: str, max_bytes: int = None) -> str:
    h = hashlib.sha256()
    rem = max_bytes
    with open(path, "rb") as fp:
        while True:
            chunk_sz = 4 * 1024 * 1024 if rem is None else min(4 * 1024 * 1024, rem)
            if chunk_sz <= 0:
                break
            data = fp.read(chunk_sz)
            if not data:
                break
            h.update(data)
            if rem is not None:
                rem -= len(data)
    return h.hexdigest()


def extract_ota_zip_metadata(zf) -> dict:
    """Parse META-INF/com/android/metadata, dynamic_partitions_info.txt, or hybrid_meta.json."""
    meta = {
        "source": "fallback",
        "device": "",
        "model": "",
        "fingerprint": "",
        "ota_version": "",
        "ota_type": "AB",
        "super_group": "",
        "logical_partitions": [],
    }
    names = set(zf.namelist())

    for mj in ("META-INF/hybrid_meta.json", "META-INF/superhybrid_meta.json"):
        if mj in names:
            try:
                saved = json.loads(zf.read(mj).decode("utf-8", "replace"))
                if isinstance(saved, dict):
                    meta.update({k: v for k, v in saved.items() if v})
                    meta["source"] = "hybrid_zip"
            except Exception:
                pass
            break

    if "META-INF/com/android/metadata" in names:
        try:
            raw = zf.read("META-INF/com/android/metadata").decode("utf-8", "replace")
            kv = {}
            for line in raw.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip()
            dev = kv.get("post-device") or kv.get("pre-device") or kv.get("ota-device") or ""
            if dev:
                meta["device"] = dev
            if kv.get("post-build"):
                meta["fingerprint"] = kv["post-build"]
            if kv.get("ota-version") or kv.get("post-build-incremental"):
                meta["ota_version"] = kv.get("ota-version") or kv.get("post-build-incremental")
            if kv.get("ota-type"):
                meta["ota_type"] = kv["ota-type"]
            meta["source"] = "ota_zip"
        except Exception:
            pass

    for dpi_cand in ("dynamic_partitions_info.txt", "META-INF/com/android/dynamic_partitions_info.txt"):
        if dpi_cand in names:
            try:
                raw = zf.read(dpi_cand).decode("utf-8", "replace")
                kv = {}
                for line in raw.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        kv[k.strip()] = v.strip()
                groups = kv.get("super_partition_groups", "").split()
                if groups:
                    grp = groups[0]
                    meta["super_group"] = grp
                    plist = kv.get(f"super_{grp}_partition_list", "").split()
                    if plist:
                        meta["logical_partitions"] = plist
                meta["source"] = "ota_zip"
            except Exception:
                pass
            break

    return meta


def detect_hybrid_zip(path: str):
    """Return (mode, found_reqs, meta) where mode is 'regional', 'super', or None."""
    if not path or not os.path.isfile(path) or not path.lower().endswith(".zip"):
        return None, [], {}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            oos_imgs, cos_imgs = [], []
            for name in zf.namelist():
                norm = name.replace("\\", "/")
                parts = norm.split("/")
                if len(parts) >= 2 and parts[-1].lower().endswith(".img"):
                    parent = parts[-2].upper()
                    if parent == "OOS_FILES_HERE":
                        oos_imgs.append(parts[-1])
                    elif parent in ("OS_FILES_HERE", "COS_FILES_HERE"):
                        cos_imgs.append(parts[-1])
            if cos_imgs:
                meta = extract_ota_zip_metadata(zf)
                lower_map = {fn.lower(): fn for fn in cos_imgs}
                found_req = [req for req in REQUIRED_HYBRID_IMGS if req.lower() in lower_map]
                return "super", found_req, meta
            if oos_imgs:
                meta = extract_ota_zip_metadata(zf)
                lower_map = {fn.lower(): fn for fn in oos_imgs}
                found_req = [req for req in REQUIRED_HYBRID_IMGS if req.lower() in lower_map]
                return "regional", found_req, meta
            return None, [], {}
    except Exception:
        return None, [], {}


def is_regional_hybrid_zip(path: str):
    mode, reqs, _ = detect_hybrid_zip(path)
    return (mode == "regional"), reqs


def build_universal_update_binary(files_dir: str = "OS_FILES_HERE", label: str = "MergedOTAFlasher") -> str:
    tpl = r"""#!/sbin/sh
# __LABEL__ Universal ColorOS / OxygenOS Custom Recovery Flasher
# Supports Aera & OrangeFox recoveries on any ColorOS / OxygenOS device (Snapdragon & MediaTek)
# Generated dynamically by OTA FW Merger (JKurtz)
OUTFD="$2"
ZIPFILE="$3"
FILES_DIR="__FILES_DIR__"

ui_print() {
    echo "ui_print $1" > "/proc/self/fd/$OUTFD"
    echo "ui_print" > "/proc/self/fd/$OUTFD"
}

abort() {
    ui_print "! ERROR: $1"
    rm -rf "$WORKDIR" "$STAGE_DIR" /sdcard/super_new.img 2>/dev/null
    exit 1
}

WORKDIR="/tmp/hybrid_meta"
STAGE_DIR="/sdcard/hybrid_super_out"
rm -rf "$WORKDIR" "$STAGE_DIR" /sdcard/super_new.img 2>/dev/null
mkdir -p "$WORKDIR" "$STAGE_DIR"

unzip -o "$ZIPFILE" "META-INF/hybrid_meta.env" -d "$WORKDIR" >/dev/null 2>&1 || true
if [ -f "$WORKDIR/META-INF/hybrid_meta.env" ]; then
    . "$WORKDIR/META-INF/hybrid_meta.env"
fi

ui_print "**************************************************"
ui_print "  __LABEL__ Universal ColorOS / OOS Flasher"
ui_print "  Image Folder   : $FILES_DIR"
ui_print "  Metadata Source: ${META_SOURCE:-fallback}"
[ -n "$TARGET_MODEL" ]  && ui_print "  Target Model   : $TARGET_MODEL"
[ -n "$TARGET_DEVICE" ] && ui_print "  Target Device  : $TARGET_DEVICE"
[ -n "$OTA_VERSION" ]   && ui_print "  Build Version  : $OTA_VERSION"
ui_print "**************************************************"

# --- GUARD 1: Pre-flight Recovery & Tool Check (Aera / OrangeFox) ---
LPMAKE="$(command -v lpmake || echo /system/bin/lpmake)"
[ ! -x "$LPMAKE" ] && [ -x "/vendor/bin/lpmake" ] && LPMAKE="/vendor/bin/lpmake"
SIMG2IMG="$(command -v simg2img || echo /system/bin/simg2img)"
BLOCKDEV="$(command -v blockdev || echo /system/bin/blockdev)"

command -v unzip >/dev/null 2>&1 || abort "Recovery is missing unzip"
[ -x "$BLOCKDEV" ] || abort "Recovery is missing blockdev (use Aera or OrangeFox)"
[ -x "$LPMAKE" ]   || abort "Recovery is missing lpmake (use Aera or OrangeFox)"
[ -x "$SIMG2IMG" ] || abort "Recovery is missing simg2img (use Aera or OrangeFox)"

# Device / Platform safety check (Aera/OrangeFox often report marketing name/codename like "OnePlus 15" / "infiniti" while ColorOS reports "CPH2749" / "OP611FL1")
if [ ! -f "/sdcard/superhybrid_force" ] && { [ -n "$TARGET_DEVICE" ] || [ -n "$TARGET_MODEL" ] || [ -n "$TARGET_PLATFORM" ]; }; then
    CUR_DEV="$(getprop ro.product.device 2>/dev/null)"
    CUR_MOD="$(getprop ro.product.model 2>/dev/null)"
    CUR_PRD="$(getprop ro.build.product 2>/dev/null)"
    CUR_VDEV="$(getprop ro.product.vendor.device 2>/dev/null)"
    CUR_PLAT="$(getprop ro.board.platform 2>/dev/null)"
    MATCHED=0
    for c in "$CUR_DEV" "$CUR_MOD" "$CUR_PRD" "$CUR_VDEV"; do
        [ -z "$c" ] && continue
        if [ "$c" = "$TARGET_DEVICE" ] || [ "$c" = "$TARGET_MODEL" ] || { [ -n "$TARGET_MARKET" ] && [ "$c" = "$TARGET_MARKET" ]; }; then
            MATCHED=1
            break
        fi
    done
    if [ "$MATCHED" = "0" ] && [ -n "$TARGET_PLATFORM" ] && [ -n "$CUR_PLAT" ] && [ "$CUR_PLAT" = "$TARGET_PLATFORM" ]; then
        ui_print "- Platform verified: $CUR_PLAT (recovery reports $CUR_MOD / $CUR_DEV)"
        MATCHED=1
    fi
    if [ -n "$CUR_DEV" ] && [ "$MATCHED" = "0" ]; then
        ui_print "! Device mismatch: phone is $CUR_MOD ($CUR_DEV / $CUR_PLAT), ZIP targets ${TARGET_MODEL:-$TARGET_DEVICE} ($TARGET_PLATFORM)."
        ui_print "! Create /sdcard/superhybrid_force to override for cross-region flashing."
        abort "Device mismatch (no partitions modified)"
    fi
fi

# Detect A/B slot support
IS_AB=0
if [ -e "/dev/block/by-name/boot_a" ] || [ -e "/dev/block/by-name/init_boot_a" ]; then
    IS_AB=1
fi

# Collect live logical partition names: lpdump (if present) -> /dev/block/mapper/ fallback
LIVE_LOGICAL=""
if [ -e "/dev/block/by-name/super" ] && command -v lpdump >/dev/null 2>&1; then
    LIVE_LOGICAL="$(lpdump /dev/block/by-name/super 2>/dev/null | awk '/Name:/{gsub(/_a$|_b$/,"",$2); print $2}' | sort -u | tr '\n' ' ')"
fi
if [ -z "$LIVE_LOGICAL" ] && [ -d "/dev/block/mapper" ]; then
    for m in /dev/block/mapper/*; do
        [ -e "$m" ] || continue
        bn="$(basename "$m")"
        case "$bn" in
            control|userdata*|metadata*|*-cow|*-verity|*_verity) continue ;;
        esac
        bn="$(echo "$bn" | sed -E 's/(_a|_b)$//')"
        LIVE_LOGICAL="$LIVE_LOGICAL $bn"
    done
fi

is_in_list() {
    case " $2 " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

is_logical_part() {
    p="$1"
    if [ -n "$META_LOGICAL_PARTS" ] && is_in_list "$p" "$META_LOGICAL_PARTS"; then
        return 0
    fi
    if [ -n "$LIVE_LOGICAL" ] && is_in_list "$p" "$LIVE_LOGICAL"; then
        return 0
    fi
    case "$p" in
        system|system_ext|product|vendor|odm|system_dlkm*|vendor_dlkm*|odm_dlkm*|my_*)
            return 0 ;;
    esac
    return 1
}

# Enumerate ${FILES_DIR}/*.img inside the ZIP
IMG_LIST="$(unzip -l "$ZIPFILE" 2>/dev/null | awk '{print $NF}' | grep -E "^${FILES_DIR}/[^/]+\.img$" | sort)"
[ -z "$IMG_LIST" ] && abort "No ${FILES_DIR}/*.img entries found in ZIP"

# --- GUARD 2 & GUARD 4: Pre-flight /sdcard free space + super completeness check BEFORE writing ---
PLANNED_LOGICAL=""
for entry in $IMG_LIST; do
    fn="${entry#${FILES_DIR}/}"
    part="${fn%.img}"
    if [ "$IS_AB" = "1" ] && [ -e "/dev/block/by-name/${part}_a" ]; then
        continue
    elif [ -e "/dev/block/by-name/${part}" ] && [ "$part" != "super" ]; then
        continue
    elif is_logical_part "$part"; then
        PLANNED_LOGICAL="$PLANNED_LOGICAL $part"
    fi
done

if [ -n "$PLANNED_LOGICAL" ] && [ ! -f "/sdcard/superhybrid_force" ]; then
    for core in system vendor product odm; do
        if ! is_in_list "$core" "$PLANNED_LOGICAL"; then
            ui_print "! Incomplete super set: missing ${core}.img in ${FILES_DIR}/"
            ui_print "! Create /sdcard/superhybrid_force if you intentionally want a partial super."
            abort "Super completeness guard triggered (no partitions modified)"
        fi
    done

    FREE_KB="$(df -k /sdcard 2>/dev/null | awk 'NR==2{print $4}')"
    if [ -n "$FREE_KB" ] && [ "$FREE_KB" -gt 0 ] 2>/dev/null; then
        if [ "$FREE_KB" -lt 12582912 ]; then
            FREE_GB=$((FREE_KB / 1048576))
            abort "Not enough free space on /sdcard (${FREE_GB} GB free; need >= 12 GB for super repack)"
        fi
    fi
fi

# Set active slot A after pre-flight guards pass
if [ "$IS_AB" = "1" ] && command -v bootctl >/dev/null 2>&1; then
    bootctl set-active-boot-slot 0 >/dev/null 2>&1 || true
    ui_print "- Active slot set to A"
fi

# --- GUARD 3: Per-partition block-size bounds check before writing any physical image ---
flash_block_img() {
    img="$1"
    blk="$2"
    magic="$(dd if="$img" bs=4 count=1 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')"
    if [ "$magic" = "3aff26ed" ]; then
        "$SIMG2IMG" "$img" "$blk" || return 1
    else
        img_sz="$(wc -c < "$img" | tr -d ' ')"
        blk_sz="$("$BLOCKDEV" --getsize64 "$blk" 2>/dev/null || echo 0)"
        if [ "$blk_sz" -gt 0 ] && [ "$img_sz" -gt "$blk_sz" ]; then
            ui_print "! Size overflow: $img ($img_sz B) > $blk ($blk_sz B)"
            return 1
        fi
        dd if="$img" of="$blk" bs=4M 2>/dev/null || dd if="$img" of="$blk" bs=1M || return 1
    fi
    return 0
}

FLASHED_PHYS=0
STAGED_LOGICAL=""

ui_print "- Scanning and flashing physical partitions..."
for entry in $IMG_LIST; do
    fn="${entry#${FILES_DIR}/}"
    part="${fn%.img}"

    if [ "$IS_AB" = "1" ] && [ -e "/dev/block/by-name/${part}_a" ]; then
        tmp_img="$WORKDIR/$fn"
        unzip -p "$ZIPFILE" "$entry" > "$tmp_img" || abort "Failed extracting $entry"
        ui_print "  * Flashing ${part}_a..."
        flash_block_img "$tmp_img" "/dev/block/by-name/${part}_a" || abort "Failed flashing ${part}_a"
        if [ -e "/dev/block/by-name/${part}_b" ]; then
            ui_print "  * Flashing ${part}_b..."
            flash_block_img "$tmp_img" "/dev/block/by-name/${part}_b" || abort "Failed flashing ${part}_b"
        fi
        rm -f "$tmp_img"
        FLASHED_PHYS=$((FLASHED_PHYS + 1))
    elif [ -e "/dev/block/by-name/${part}" ] && [ "$part" != "super" ]; then
        tmp_img="$WORKDIR/$fn"
        unzip -p "$ZIPFILE" "$entry" > "$tmp_img" || abort "Failed extracting $entry"
        ui_print "  * Flashing ${part}..."
        flash_block_img "$tmp_img" "/dev/block/by-name/${part}" || abort "Failed flashing ${part}"
        rm -f "$tmp_img"
        FLASHED_PHYS=$((FLASHED_PHYS + 1))
    elif is_logical_part "$part"; then
        ui_print "  + Staging logical partition: ${part}.img"
        unzip -p "$ZIPFILE" "$entry" > "$STAGE_DIR/$fn" || abort "Failed extracting $entry"
        STAGED_LOGICAL="$STAGED_LOGICAL $part"
    else
        ui_print "  - Skipping ${part}.img (not present on this device)"
    fi
done

ui_print "- Flashed $FLASHED_PHYS physical partition(s)."

# Dynamic super repacking with --virtual-ab
if [ -n "$STAGED_LOGICAL" ]; then
    [ -e "/dev/block/by-name/super" ] || abort "Logical images staged, but /dev/block/by-name/super not found"

    SUPER_SIZE="$("$BLOCKDEV" --getsize64 /dev/block/by-name/super 2>/dev/null)"
    [ -n "$SUPER_SIZE" ] && [ "$SUPER_SIZE" -gt 0 ] || abort "Could not read super partition size"

    GROUP_BASE=""
    if command -v lpdump >/dev/null 2>&1; then
        GROUP_BASE="$(lpdump /dev/block/by-name/super 2>/dev/null | awk '/Name:/{g=$2} /Maximum size:/{if (g != "default") {sub(/_a$|_b$/,"",g); print g; exit}}')"
    fi
    if [ -z "$GROUP_BASE" ] && [ -n "$META_GROUP_NAME" ]; then
        GROUP_BASE="$META_GROUP_NAME"
    fi
    if [ -z "$GROUP_BASE" ]; then
        HW="$(getprop ro.hardware 2>/dev/null)"
        if [ -e "/dev/block/by-name/lk_a" ] || echo "$HW" | grep -qi "^mt"; then
            GROUP_BASE="main"
        elif echo "$HW" | grep -qiE "^(gs|zuma|komodo|caiman|tokay|shiba|husky|panther|cheetah|oriole|raven|tensor)"; then
            GROUP_BASE="google_dynamic_partitions"
        else
            GROUP_BASE="qti_dynamic_partitions"
        fi
    fi

    GROUP_MAX=$((SUPER_SIZE - 4194304))
    ui_print "- Repacking super (${SUPER_SIZE} bytes, group: ${GROUP_BASE})..."

    LP_ARGS="--metadata-size 65536 --super-name super --metadata-slots 3 --device super:${SUPER_SIZE} --sparse"
    if [ "$IS_AB" = "1" ]; then
        LP_ARGS="$LP_ARGS --virtual-ab --group ${GROUP_BASE}_a:${GROUP_MAX} --group ${GROUP_BASE}_b:${GROUP_MAX}"
    else
        LP_ARGS="$LP_ARGS --group ${GROUP_BASE}:${GROUP_MAX}"
    fi

    for p in $STAGED_LOGICAL; do
        img="$STAGE_DIR/${p}.img"
        magic="$(dd if="$img" bs=4 count=1 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')"
        if [ "$magic" = "3aff26ed" ]; then
            "$SIMG2IMG" "$img" "${img}.raw" || abort "simg2img failed on ${p}.img"
            mv -f "${img}.raw" "$img"
        fi
        sz="$(wc -c < "$img" | tr -d ' ')"
        if [ "$IS_AB" = "1" ]; then
            LP_ARGS="$LP_ARGS --partition ${p}_a:readonly:${sz}:${GROUP_BASE}_a --image ${p}_a=${img}"
            LP_ARGS="$LP_ARGS --partition ${p}_b:readonly:0:${GROUP_BASE}_b"
        else
            LP_ARGS="$LP_ARGS --partition ${p}:readonly:${sz}:${GROUP_BASE} --image ${p}=${img}"
        fi
    done

    # shellcheck disable=SC2086
    "$LPMAKE" $LP_ARGS --output /sdcard/super_new.img || abort "lpmake failed (check free space on /sdcard)"

    ui_print "- Flashing super_new.img -> /dev/block/by-name/super..."
    "$SIMG2IMG" /sdcard/super_new.img /dev/block/by-name/super || abort "Failed flashing super"
    rm -f /sdcard/super_new.img
fi

rm -rf "$WORKDIR" "$STAGE_DIR" 2>/dev/null
ui_print "**************************************************"
ui_print "  __LABEL__ Flash Complete!"
ui_print "**************************************************"
exit 0
"""
    return tpl.replace("__FILES_DIR__", files_dir).replace("__LABEL__", label)


def build_universal_fastboot_sh(phys_early, phys_other, logical_parts, meta, files_dir="OS_FILES_HERE", label="MergedOTAFlasher") -> str:
    dev = meta.get("model") or meta.get("device") or "Universal ColorOS / OxygenOS"
    ver = meta.get("ota_version") or ""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'cd "$(dirname "$0")"',
        'FASTBOOT="$(command -v fastboot || echo Platform-Tools/fastboot)"',
        'echo "=================================================================="',
        f'echo "  {label} Fastboot Flasher - {dev} {ver}"',
        f'echo "  Metadata Source: {meta.get("source", "fallback")}"',
        'echo "=================================================================="',
        "",
    ]
    for p in phys_early:
        lines.append(f'"$FASTBOOT" flash {p}_a {files_dir}/{p}.img')
        lines.append(f'"$FASTBOOT" flash {p}_b {files_dir}/{p}.img')
    lines += [
        "",
        'echo ">>> Rebooting to fastbootd..."',
        '"$FASTBOOT" reboot fastboot',
        'read -rp "Once in fastbootd, press Enter to continue..." _',
        '"$FASTBOOT" snapshot-update cancel || true',
        "",
    ]
    for p in phys_other:
        lines.append(f'"$FASTBOOT" flash --slot=all {p} {files_dir}/{p}.img')
    lines.append("")
    for p in logical_parts:
        lines += [
            f'"$FASTBOOT" delete-logical-partition {p}_a || true',
            f'"$FASTBOOT" delete-logical-partition {p}_b || true',
            f'"$FASTBOOT" delete-logical-partition {p}_a-cow || true',
            f'"$FASTBOOT" delete-logical-partition {p}_b-cow || true',
            f'"$FASTBOOT" create-logical-partition {p}_a 1',
            f'"$FASTBOOT" create-logical-partition {p}_b 1',
            f'"$FASTBOOT" flash {p}_a {files_dir}/{p}.img',
        ]
    lines += [
        "",
        '"$FASTBOOT" --set-active=a',
        'echo "Done! Rebooting..."',
        '"$FASTBOOT" reboot',
        "",
    ]
    return "\n".join(lines)


def build_universal_fastboot_bat(phys_early, phys_other, logical_parts, meta, files_dir="OS_FILES_HERE", label="MergedOTAFlasher") -> str:
    dev = meta.get("model") or meta.get("device") or "Universal ColorOS / OxygenOS"
    lines = [
        "@echo off",
        f"title {label} Fastboot Flasher - {dev}",
        "cd /d %~dp0",
        "set fastboot=fastboot",
        "if exist Platform-Tools\\fastboot.exe set fastboot=Platform-Tools\\fastboot.exe",
        "",
    ]
    for p in phys_early:
        lines.append(f"%fastboot% flash {p}_a {files_dir}\\{p}.img")
        lines.append(f"%fastboot% flash {p}_b {files_dir}\\{p}.img")
    lines += [
        "",
        "echo Rebooting to fastbootd...",
        "%fastboot% reboot fastboot",
        "pause",
        "%fastboot% snapshot-update cancel",
        "",
    ]
    for p in phys_other:
        lines.append(f"%fastboot% flash --slot=all {p} {files_dir}\\{p}.img")
    lines.append("")
    for p in logical_parts:
        lines += [
            f"%fastboot% delete-logical-partition {p}_a",
            f"%fastboot% delete-logical-partition {p}_b",
            f"%fastboot% delete-logical-partition {p}_a-cow",
            f"%fastboot% delete-logical-partition {p}_b-cow",
            f"%fastboot% create-logical-partition {p}_a 1",
            f"%fastboot% create-logical-partition {p}_b 1",
            f"%fastboot% flash {p}_a {files_dir}\\{p}.img",
        ]
    lines += [
        "",
        "%fastboot% --set-active=a",
        "%fastboot% reboot",
        "pause",
        "",
    ]
    return "\r\n".join(lines)


class RootDumpDialog(QDialog):
    """Configure live root partition dump + stock overrides for root-modified images."""
    CORE_STOCK_IMGS = ("boot.img", "init_boot.img", "recovery.img")

    def __init__(self, parent, qss: str, existing: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Dump Entire Device System Image (Root)")
        self.setStyleSheet(qss)
        self.qss = qss
        self.stock_overrides = dict(existing or {})

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        t = QLabel("Dump Entire Device System Image (Root)")
        t.setObjectName("AppTitle")
        lay.addWidget(t)

        sub = QLabel(
            "Dumps your device's entire active system & firmware partitions (all raw logical super slices + physical partitions) via root "
            "and reads live device metadata for recovery META-INF. Provide stock images below for any partition modified by root or custom recovery."
        )
        sub.setObjectName("AppSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.row_labels = {}
        for fn in self.CORE_STOCK_IMGS:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(self._fmt_row(fn))
            lbl.setObjectName("TileSub")
            lbl.setWordWrap(True)
            self.row_labels[fn] = lbl
            btn = QPushButton(f"Pick {fn}")
            btn.clicked.connect(lambda _=False, k=fn: self.pick_single(k))
            row.addWidget(lbl, 1)
            row.addWidget(btn)
            lay.addLayout(row)

        self.extra_lbl = QLabel(self._fmt_extras())
        self.extra_lbl.setObjectName("TileSub")
        self.extra_lbl.setWordWrap(True)
        lay.addWidget(self.extra_lbl)

        extra_row = QHBoxLayout()
        extra_row.setSpacing(8)
        btn_more = QPushButton("+ Add More Stock .img(s)")
        btn_more.clicked.connect(self.pick_more)
        btn_clr = QPushButton("Clear Overrides")
        btn_clr.clicked.connect(self.clear_all)
        extra_row.addWidget(btn_more, 1)
        extra_row.addWidget(btn_clr)
        lay.addLayout(extra_row)

        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Use Device Dump as Base")
        btn_ok.setObjectName("PrimaryBtn")
        btn_ok.clicked.connect(self.accept)
        foot.addWidget(btn_cancel)
        foot.addWidget(btn_ok, 1)
        lay.addLayout(foot)

    def _fmt_row(self, fn: str) -> str:
        p = self.stock_overrides.get(fn, "")
        return f"{fn}: {os.path.basename(p)} (stock override)" if p else f"{fn}: dump from device (not overridden)"

    def _fmt_extras(self) -> str:
        extras = [k for k in sorted(self.stock_overrides) if k not in self.CORE_STOCK_IMGS]
        if not extras:
            return "Additional stock overrides (e.g. vendor_boot.img, vbmeta.img, dtbo.img): none"
        return "Additional stock overrides: " + ", ".join(extras)

    def pick_single(self, key: str):
        dlg = MobilePathPicker(self, f"Select Stock {key}", self.qss, "/storage/emulated/0",
                               dirs_only=False, ext_filter="", multi=False)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_paths:
            self.stock_overrides[key] = dlg.selected_paths[0]
            self.row_labels[key].setText(self._fmt_row(key))

    def pick_more(self):
        dlg = MobilePathPicker(self, "Select Additional Stock .img(s)", self.qss, "/storage/emulated/0",
                               dirs_only=False, ext_filter="", multi=True)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for p in dlg.selected_paths:
                bn = os.path.basename(p)
                if bn.lower().endswith(".img"):
                    self.stock_overrides[bn] = p
                    if bn in self.row_labels:
                        self.row_labels[bn].setText(self._fmt_row(bn))
            self.extra_lbl.setText(self._fmt_extras())

    def clear_all(self):
        self.stock_overrides.clear()
        for fn in self.CORE_STOCK_IMGS:
            self.row_labels[fn].setText(self._fmt_row(fn))
        self.extra_lbl.setText(self._fmt_extras())
'''

pat_cur_hyb = re.compile(r"\nDEFAULT_LOGICAL_PARTITIONS = .*?(?=\n\nclass DumpWorker\(QThread\):)", re.S)
pat_old_hyb = re.compile(r"\ndef is_regional_hybrid_zip\(path: str\):.*?(?=\n\nclass DumpWorker\(QThread\):)", re.S)
if pat_cur_hyb.search(txt):
    txt = pat_cur_hyb.sub(lambda _: "\n" + superhybrid_helpers, txt, count=1)
elif pat_old_hyb.search(txt):
    txt = pat_old_hyb.sub(lambda _: "\n" + superhybrid_helpers, txt, count=1)
else:
    txt = txt.replace("class DumpWorker(QThread):", superhybrid_helpers + "\n\nclass DumpWorker(QThread):", 1)

# ---------------------------------------------------------------------------
# 1b. Update DumpWorker.__init__ to accept recovery_mode & stock_overrides
# ---------------------------------------------------------------------------
old_init = "    def __init__(self, inputs, fake_ota=False, recovery_zip=False, extra_imgs=None, work_dir=None):"
new_init = '    def __init__(self, inputs, fake_ota=False, recovery_zip=False, recovery_mode="regional", extra_imgs=None, stock_overrides=None, work_dir=None):'
if 'recovery_mode="regional"' not in txt:
    assert old_init in txt, "Could not locate DumpWorker.__init__"
    txt = txt.replace(old_init, new_init, 1)
    txt = txt.replace(
        "        self.recovery_zip = recovery_zip",
        "        self.recovery_zip = recovery_zip\n"
        "        self.recovery_mode = recovery_mode or 'regional'\n"
        "        self.stock_overrides = dict(stock_overrides or {})\n"
        "        self.last_expected_hashes = {}\n"
        "        self.ota_meta = {'source': 'fallback', 'device': '', 'model': '', 'fingerprint': '', 'ota_version': '', 'ota_type': 'AB', 'super_group': '', 'logical_partitions': []}",
        1,
    )

# ---------------------------------------------------------------------------
# 1c. Replace _build_recovery_zip with universal dynamic builder + add root probe/dump/hash verify
# ---------------------------------------------------------------------------
worker_methods = '''
    def _su_read(self, cmd: str) -> str:
        proc = subprocess.run(["su", "-c", cmd], capture_output=True, text=True)
        return (proc.stdout or "").strip()

    def _probe_device_meta_root(self):
        """Parse live ColorOS / OxygenOS device info via root on the fly for universal META-INF generation."""
        if not shutil.which("su"):
            return
        try:
            model = self._su_read("getprop ro.product.model")
            dev = self._su_read("getprop ro.product.device") or self._su_read("getprop ro.build.product")
            market = self._su_read("getprop ro.vendor.oplus.market.name") or self._su_read("getprop ro.product.marketname") or self._su_read("getprop ro.oplus.market.name")
            plat = self._su_read("getprop ro.board.platform")
            fp = self._su_read("getprop ro.build.fingerprint")
            ver = self._su_read("getprop ro.build.display.id") or self._su_read("getprop ro.build.version.incremental")
            hw = self._su_read("getprop ro.hardware")
            slot = self._su_read("getprop ro.boot.slot_suffix")

            if dev and not self.ota_meta.get("device"):
                self.ota_meta["device"] = dev
            if model and not self.ota_meta.get("model"):
                self.ota_meta["model"] = model
            if market and not self.ota_meta.get("market_name"):
                self.ota_meta["market_name"] = market
            if plat and not self.ota_meta.get("platform"):
                self.ota_meta["platform"] = plat
            if fp and not self.ota_meta.get("fingerprint"):
                self.ota_meta["fingerprint"] = fp
            if ver and not self.ota_meta.get("ota_version"):
                self.ota_meta["ota_version"] = ver

            # Detect live super dynamic partition group name via lpdump or SoC check
            if not self.ota_meta.get("super_group"):
                grp = ""
                lp_out = self._su_read("command -v lpdump >/dev/null 2>&1 && lpdump /dev/block/by-name/super 2>/dev/null")
                cur_g = ""
                for ln in lp_out.splitlines():
                    st = ln.strip()
                    if st.startswith("Name:"):
                        cur_g = st.split(":", 1)[1].strip()
                    elif st.startswith("Maximum size:") and cur_g and cur_g != "default":
                        grp = re.sub(r"(_a|_b)$", "", cur_g)
                        break
                if not grp:
                    has_lk = self._su_read("[ -e /dev/block/by-name/lk_a ] && echo 1 || echo 0")
                    grp = "main" if (has_lk == "1" or hw.lower().startswith("mt")) else "qti_dynamic_partitions"
                self.ota_meta["super_group"] = grp

            # Detect live logical partitions from /dev/block/mapper (raw linear slices only)
            if not self.ota_meta.get("logical_partitions"):
                map_raw = self._su_read("ls -1 /dev/block/mapper 2>/dev/null")
                found = []
                for name in map_raw.splitlines():
                    name = name.strip()
                    if not name or name == "control" or name.endswith("-cow") or name.endswith("-verity") or name.endswith("_verity"):
                        continue
                    if slot:
                        if name.endswith(slot):
                            base = name[:-len(slot)]
                        elif name.endswith("_a") or name.endswith("_b"):
                            continue
                        else:
                            base = name
                    else:
                        base = name
                    if base.lower() not in DUMP_EXCLUDE_PARTITIONS and base not in found:
                        found.append(base)
                if found:
                    self.ota_meta["logical_partitions"] = sorted(found)

            if self.ota_meta.get("source") == "fallback" and (dev or model):
                self.ota_meta["source"] = "root_live_device"

            self.log.emit(
                f"Parsed live device metadata via root: model={self.ota_meta.get('model') or '?'}, "
                f"device={self.ota_meta.get('device') or '?'}, group={self.ota_meta.get('super_group') or 'auto'}\\n"
            )
        except Exception as e:
            self.log.emit(f"Note: Could not probe live device metadata via root ({e}); using fallback.\\n")

    def _dump_device_partitions(self, ota_dir: str, hybrid_preserved: str):
        if not shutil.which("su"):
            raise RuntimeError("Root (su) is required to dump base images from the device.")
        shutil.rmtree(ota_dir, ignore_errors=True)
        os.makedirs(ota_dir, exist_ok=True)
        os.makedirs(hybrid_preserved, exist_ok=True)

        self._probe_device_meta_root()
        slot = self._su_read("getprop ro.boot.slot_suffix")
        model = self.ota_meta.get("model") or self.ota_meta.get("device") or "device"
        self.log.emit(f"Root Full System Dump: model={model}, active_slot={slot or '(non-A/B)'}\\n")

        override_map = {k.lower(): (k, v) for k, v in self.stock_overrides.items() if v and os.path.isfile(v)}

        targets = {}
        phys_raw = self._su_read("ls -1 /dev/block/by-name 2>/dev/null")
        for name in phys_raw.splitlines():
            name = name.strip()
            if not name:
                continue
            if slot:
                if name.endswith(slot):
                    base = name[:-len(slot)]
                elif name.endswith("_a") or name.endswith("_b"):
                    continue
                else:
                    base = name
            else:
                base = name
            if base.lower() in DUMP_EXCLUDE_PARTITIONS:
                continue
            targets[base] = f"/dev/block/by-name/{name}"

        map_raw = self._su_read("ls -1 /dev/block/mapper 2>/dev/null")
        logical_found = []
        for name in map_raw.splitlines():
            name = name.strip()
            if not name or name == "control" or name.endswith("-cow") or name.endswith("-verity") or name.endswith("_verity"):
                continue
            if slot:
                if name.endswith(slot):
                    base = name[:-len(slot)]
                elif name.endswith("_a") or name.endswith("_b"):
                    continue
                else:
                    base = name
            else:
                base = name
            if base.lower() in DUMP_EXCLUDE_PARTITIONS:
                continue
            targets[base] = f"/dev/block/mapper/{name}"
            if base not in logical_found:
                logical_found.append(base)

        if logical_found:
            self.ota_meta["logical_partitions"] = sorted(logical_found)

        dumped = 0
        for part in sorted(targets.keys()):
            fn = f"{part}.img"
            dst = os.path.join(ota_dir, fn)
            if fn.lower() in override_map:
                _, src_override = override_map[fn.lower()]
                self.log.emit(f"  * Using stock override for {fn} ({os.path.basename(src_override)})\\n")
                shutil.copy2(src_override, dst)
                dumped += 1
            else:
                blk = targets[part]
                self.log.emit(f"  + Dumping {part} <- {blk}\\n")
                rc = subprocess.run(
                    ["su", "-c", f'dd if="{blk}" of="{dst}" bs=4M 2>/dev/null || dd if="{blk}" of="{dst}" bs=1M'],
                    capture_output=True, text=True,
                ).returncode
                if rc == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    dumped += 1
                else:
                    self.log.emit(f"  ! Skipped {part} (unreadable or empty)\\n")
                    try:
                        if os.path.exists(dst):
                            os.remove(dst)
                    except OSError:
                        pass
                    continue

            # Auto-preserve RegionalHybrid extra images from live dump so RegionalHybrid builds work seamlessly
            for req in REQUIRED_HYBRID_IMGS:
                if fn.lower() == req.lower():
                    pres = os.path.join(hybrid_preserved, req)
                    shutil.copy2(dst, pres)
                    if not os.path.isfile(self.extra_imgs.get(req, "")):
                        self.extra_imgs[req] = pres

        for low_fn, (orig_fn, src_override) in override_map.items():
            dst = os.path.join(ota_dir, orig_fn)
            if not os.path.isfile(dst):
                self.log.emit(f"  * Adding extra stock override {orig_fn}\\n")
                shutil.copy2(src_override, dst)
                dumped += 1

        self.log.emit(f"Root full system dump complete: {dumped} base partition images ready.\\n")
        return f"device-{model}"

    def _verify_partition_hashes(self, img_dir: str, part_hashes: dict, phase: str = "new"):
        """Verify SHA-256 of partition images against payload.bin old_partition_info or new_partition_info."""
        if not part_hashes:
            return
        key_h = "old_sha256" if phase == "old" else "new_sha256"
        key_s = "old_size" if phase == "old" else "new_size"
        label = "Pre-Merge Base" if phase == "old" else "Post-Merge OTA"
        self.log.emit(f"\\n=== Internal SHA-256 Hash Check ({label}) ===\\n")
        checked = 0
        mismatches = []
        for pname, info in sorted(part_hashes.items()):
            exp_h = info.get(key_h)
            exp_s = info.get(key_s)
            if not exp_h:
                continue
            img_p = os.path.join(img_dir, f"{pname}.img")
            if not os.path.isfile(img_p):
                continue
            actual_sz = os.path.getsize(img_p)
            hash_len = exp_s if (exp_s and actual_sz >= exp_s) else None
            got_h = sha256_file(img_p, max_bytes=hash_len)
            checked += 1
            if got_h.lower() == exp_h.lower():
                if phase == "old" and exp_s and actual_sz > exp_s:
                    with open(img_p, "r+b") as tf:
                        tf.truncate(exp_s)
                    self.log.emit(f"  [HASH OK] {pname}.img ({got_h[:12]}..., trimmed raw block {actual_sz} -> {exp_s} B)\\n")
                else:
                    self.log.emit(f"  [HASH OK] {pname}.img ({got_h[:12]}...)\\n")
            else:
                self.log.emit(f"  [HASH MISMATCH] {pname}.img: got {got_h[:12]}..., expected {exp_h[:12]}...\\n")
                mismatches.append(pname)
        self.log.emit(f"Hash check summary ({label}): {checked - len(mismatches)}/{checked} matched.\\n")
        if mismatches:
            hint = (
                " Supply stock .img override(s) in Dump Entire System Image (Root) for: " + ", ".join(mismatches)
                if phase == "old"
                else " Merged output did not match incremental OTA target hashes for: " + ", ".join(mismatches)
            )
            raise RuntimeError(f"SHA-256 verification failed ({label}).{hint}")

    def _build_universal_hybrid_zip(self, ota_dir: str, out_dir: str, safe_name: str, mode: str = "super"):
        # Enrich any missing metadata from the live rooted device on the fly
        self._probe_device_meta_root()

        is_regional = (mode == "regional")
        files_dir = "OOS_FILES_HERE" if is_regional else "OS_FILES_HERE"
        label = "RegionalHybrid" if is_regional else "MergedOTAFlasher"
        sh_name = "Regional_Flasher.sh" if is_regional else "MergedOTAFlasher.sh"
        bat_name = "Regional_Flasher.bat" if is_regional else "MergedOTAFlasher.bat"

        # If RegionalHybrid mode has explicit overrides (e.g. my_company/my_preload/system_dlkm_oki), stage them
        override_map = {}
        if is_regional:
            for req in REQUIRED_HYBRID_IMGS:
                p = self.extra_imgs.get(req, "")
                if p and os.path.isfile(p):
                    override_map[req.lower()] = (req, p)

        # Auto-pull EDL-only system_dlkm_oki.img / system_dlkm_gki.img via root if missing from OTA ZIP (OnePlus 15/15R/Ace 6/Ace 6T)
        if shutil.which("su"):
            slot = self._su_read("getprop ro.boot.slot_suffix")
            cur_lower = {f.lower() for f in os.listdir(ota_dir) if f.endswith(".img")} | set(override_map.keys())
            for dlkm_fn in ("system_dlkm_oki.img", "system_dlkm_gki.img", "my_company.img", "my_preload.img"):
                if dlkm_fn in cur_lower:
                    continue
                part = dlkm_fn[:-4]
                cands = ([f"/dev/block/mapper/{part}{slot}", f"/dev/block/by-name/{part}{slot}"] if slot else []) + [
                    f"/dev/block/mapper/{part}", f"/dev/block/by-name/{part}"
                ]
                for blk in cands:
                    if self._su_read(f'[ -e "{blk}" ] && echo 1 || echo 0') == "1":
                        dst = os.path.join(ota_dir, dlkm_fn)
                        rc = subprocess.run(
                            ["su", "-c", f'dd if="{blk}" of="{dst}" bs=4M 2>/dev/null || dd if="{blk}" of="{dst}" bs=1M'],
                            capture_output=True, text=True,
                        ).returncode
                        if rc == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                            self.log.emit(f"  * Auto-pulled EDL-only {dlkm_fn} from live device ({blk})\\n")
                        break

        merged_imgs = sorted(
            f for f in os.listdir(ota_dir)
            if f.endswith(".img") and os.path.isfile(os.path.join(ota_dir, f))
        )
        all_names = list(merged_imgs)
        existing_lower = {f.lower() for f in all_names}
        for low_req, (req_fn, _) in override_map.items():
            if low_req not in existing_lower:
                all_names.append(req_fn)
        all_names.sort()

        if not all_names:
            raise RuntimeError(f"No merged .img files found to package into {label} ZIP.")

        meta = dict(self.ota_meta or {})
        meta_logical = set(meta.get("logical_partitions") or [])
        phys_early, phys_other, logical_parts = [], [], []
        for fn in all_names:
            part = fn[:-4]
            if part == "super":
                continue
            is_log = (part in meta_logical) if meta_logical else is_default_logical_name(part)
            if is_log:
                logical_parts.append(part)
            elif part in EARLY_BOOT_PARTITIONS:
                phys_early.append(part)
            else:
                phys_other.append(part)

        meta["logical_partitions"] = logical_parts
        meta["files_dir"] = files_dir
        meta["mode"] = mode

        zip_path = os.path.join(out_dir, f"{label}_{safe_name}.zip")
        self.log.emit(f"Building Universal {label} ZIP ({files_dir}, metadata={meta.get('source', 'fallback')}):\\n  {zip_path}\\n")
        if meta.get("model") or meta.get("device"):
            self.log.emit(f"  * Target: {meta.get('model') or ''} ({meta.get('device') or ''}) | super group: {meta.get('super_group') or 'auto'}\\n")
        self.log.emit(f"  * Physical partitions: {len(phys_early) + len(phys_other)} | Logical (super): {len(logical_parts)}\\n")

        env_lines = [
            f'META_SOURCE="{meta.get("source", "fallback")}"',
            f'TARGET_MODEL="{meta.get("model", "")}"',
            f'TARGET_DEVICE="{meta.get("device", "")}"',
            f'TARGET_MARKET="{meta.get("market_name", "")}"',
            f'TARGET_PLATFORM="{meta.get("platform", "")}"',
            f'OTA_VERSION="{meta.get("ota_version", "")}"',
            f'META_GROUP_NAME="{meta.get("super_group", "")}"',
            f'META_LOGICAL_PARTS="{" ".join(logical_parts)}"',
        ]
        meta_env = "\\n".join(env_lines) + "\\n"
        meta_json = json.dumps(meta, indent=2) + "\\n"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zout:
            zi_bin = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
            zi_bin.external_attr = 0o100755 << 16
            zout.writestr(zi_bin, build_universal_update_binary(files_dir=files_dir, label=label).encode("utf-8"))
            zout.writestr("META-INF/com/google/android/updater-script", f"# {label} Universal ColorOS / OxygenOS Recovery Flasher\\n")
            zout.writestr("META-INF/hybrid_meta.env", meta_env.encode("utf-8"))
            zout.writestr("META-INF/hybrid_meta.json", meta_json.encode("utf-8"))

            zi_sh = zipfile.ZipInfo(sh_name)
            zi_sh.external_attr = 0o100755 << 16
            zout.writestr(zi_sh, build_universal_fastboot_sh(phys_early, phys_other, logical_parts, meta, files_dir=files_dir, label=label).encode("utf-8"))
            zout.writestr(bat_name, build_universal_fastboot_bat(phys_early, phys_other, logical_parts, meta, files_dir=files_dir, label=label).encode("utf-8"))

            for fn in all_names:
                if fn.lower() in override_map:
                    req_fn, src_p = override_map[fn.lower()]
                    self.log.emit(f"  + {files_dir}/{req_fn} (preserved/override)\\n")
                    zout.write(src_p, f"{files_dir}/{req_fn}")
                else:
                    self.log.emit(f"  + {files_dir}/{fn}\\n")
                    zout.write(os.path.join(ota_dir, fn), f"{files_dir}/{fn}")

        self.log.emit(f"{label} Flashable ZIP built ({len(all_names)} images in {files_dir}):\\n  {zip_path}\\n")
        return zip_path
'''

pat_cur_wm = re.compile(r"\n    def _su_read\(self, cmd: str\) -> str:.*?(?=\n    def run\(self\):)", re.S)
if pat_cur_wm.search(txt):
    txt = pat_cur_wm.sub(lambda _: "\n" + worker_methods + "\n", txt, count=1)
else:
    anchor_rec_ret = '        self.log.emit(f"Recovery Flashable ZIP built ({img_count} images in OOS_FILES_HERE):\\n  {zip_path}\\n")\n        return zip_path'
    assert anchor_rec_ret in txt, "Could not locate end of _build_recovery_zip()"
    txt = txt.replace(anchor_rec_ret, anchor_rec_ret + "\n" + worker_methods, 1)

# ---------------------------------------------------------------------------
# 1d. Update DumpWorker.run() for device://dump + RegionalHybrid/SuperHybrid + SHA-256 checks
# ---------------------------------------------------------------------------
old_run_hybrid = '''            is_hybrid_base, _ = is_regional_hybrid_zip(full_input)

            if os.path.isdir(full_input):
                self.log.emit(f"Using pre-extracted FULL OTA directory: {full_input}\\n")
                shutil.rmtree(ota_dir, ignore_errors=True)
                shutil.copytree(full_input, ota_dir)
                tag = f"folder-{os.path.basename(full_input.rstrip('/'))}"
                body = f"[{tag}]({full_input}) (pre-extracted)"
            elif is_hybrid_base:
                self.log.emit(f"Detected RegionalHybrid base ZIP: {os.path.basename(full_input)}\\n")
                self.log.emit("Extracting OOS_FILES_HERE/*.img directly (no duplicate copy)...\\n")
                shutil.rmtree(ota_dir, ignore_errors=True)
                os.makedirs(ota_dir, exist_ok=True)
                os.makedirs(hybrid_preserved, exist_ok=True)
                self.recovery_zip = True
                self.fake_ota = False
                extracted = 0
                with zipfile.ZipFile(full_input, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        norm = info.filename.replace("\\\\", "/")
                        parts = norm.split("/")
                        if len(parts) >= 2 and parts[-2].upper() == "OOS_FILES_HERE" and parts[-1].lower().endswith(".img"):
                            fn = parts[-1]
                            dst = os.path.join(ota_dir, fn)
                            with zf.open(info, "r") as src_f, open(dst, "wb") as dst_f:
                                shutil.copyfileobj(src_f, dst_f, length=4 * 1024 * 1024)
                            extracted += 1
                            for req in REQUIRED_HYBRID_IMGS:
                                if fn.lower() == req.lower():
                                    pres = os.path.join(hybrid_preserved, req)
                                    shutil.copy2(dst, pres)
                                    if not os.path.isfile(self.extra_imgs.get(req, "")):
                                        self.extra_imgs[req] = pres
                                    self.log.emit(f"  * Auto-preserved {req} from OOS_FILES_HERE\\n")
                self.log.emit(f"Extracted {extracted} base partition images from RegionalHybrid archive.\\n")
                tag = os.path.splitext(os.path.basename(full_input))[0]
                body = f"[{tag}]({full_input}) (RegionalHybrid base)"
            else:
                self._download_or_copy(full_input, ota_zip)
                with zipfile.ZipFile(ota_zip, "r") as zf:
                    tag, ota_ver = self._read_zip_meta(zf)
                    zf.extract("payload.bin", wd)'''

new_run_hybrid = '''            hyb_mode, _, hyb_meta = detect_hybrid_zip(full_input)
            used_device_dump = (full_input.strip().lower() == "device://dump")

            if used_device_dump:
                tag = self._dump_device_partitions(ota_dir, hybrid_preserved)
                body = f"[{tag}](device://dump) (root live dump)"
            elif os.path.isdir(full_input):
                self.log.emit(f"Using pre-extracted FULL OTA directory: {full_input}\\n")
                shutil.rmtree(ota_dir, ignore_errors=True)
                shutil.copytree(full_input, ota_dir)
                tag = f"folder-{os.path.basename(full_input.rstrip('/'))}"
                body = f"[{tag}]({full_input}) (pre-extracted)"
            elif hyb_mode in ("regional", "super"):
                folder_keys = ("OS_FILES_HERE", "COS_FILES_HERE") if hyb_mode == "super" else ("OOS_FILES_HERE",)
                folder_key = folder_keys[0]
                label_name = "MergedOTAFlasher" if hyb_mode == "super" else "RegionalHybrid"
                self.log.emit(f"Detected {label_name} base ZIP: {os.path.basename(full_input)}\\n")
                self.log.emit(f"Extracting {folder_key}/*.img directly (no duplicate copy)...\\n")
                shutil.rmtree(ota_dir, ignore_errors=True)
                os.makedirs(ota_dir, exist_ok=True)
                os.makedirs(hybrid_preserved, exist_ok=True)
                self.recovery_zip = True
                self.recovery_mode = hyb_mode
                self.fake_ota = False
                if hyb_meta:
                    self.ota_meta.update({k: v for k, v in hyb_meta.items() if v})
                extracted = 0
                with zipfile.ZipFile(full_input, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        norm = info.filename.replace("\\\\", "/")
                        parts = norm.split("/")
                        if len(parts) >= 2 and parts[-2].upper() in folder_keys and parts[-1].lower().endswith(".img"):
                            fn = parts[-1]
                            dst = os.path.join(ota_dir, fn)
                            with zf.open(info, "r") as src_f, open(dst, "wb") as dst_f:
                                shutil.copyfileobj(src_f, dst_f, length=4 * 1024 * 1024)
                            extracted += 1
                            if hyb_mode == "regional":
                                for req in REQUIRED_HYBRID_IMGS:
                                    if fn.lower() == req.lower():
                                        pres = os.path.join(hybrid_preserved, req)
                                        shutil.copy2(dst, pres)
                                        if not os.path.isfile(self.extra_imgs.get(req, "")):
                                            self.extra_imgs[req] = pres
                                        self.log.emit(f"  * Auto-preserved {req} from {folder_key}\\n")
                self.log.emit(f"Extracted {extracted} base partition images from {label_name} archive.\\n")
                tag = os.path.splitext(os.path.basename(full_input))[0]
                body = f"[{tag}]({full_input}) ({label_name} base)"
            else:
                self._download_or_copy(full_input, ota_zip)
                with zipfile.ZipFile(ota_zip, "r") as zf:
                    tag, ota_ver = self._read_zip_meta(zf)
                    self.ota_meta = extract_ota_zip_metadata(zf)
                    if ota_ver and not self.ota_meta.get("ota_version"):
                        self.ota_meta["ota_version"] = ota_ver
                    if self.ota_meta.get("device"):
                        self.log.emit(f"Parsed initial ZIP metadata: device={self.ota_meta['device']}, group={self.ota_meta.get('super_group') or 'auto'}\\n")
                    zf.extract("payload.bin", wd)'''

if 'used_device_dump = (full_input.strip().lower() == "device://dump")' not in txt:
    assert old_run_hybrid in txt, "Could not locate full_input hybrid block in DumpWorker.run()"
    txt = txt.replace(old_run_hybrid, new_run_hybrid, 1)

# Hook pre-merge & post-merge SHA-256 verification around incremental ota_extractor --source-dir
old_diff_cmd = '''                self._run_cmd([ota_extractor, payload_work, "--source-dir", ota_dir, "-o", ota_new],
                              allow_root_fallback=True)'''
new_diff_cmd = '''                inc_hashes = parse_payload_partition_hashes(payload_work)
                if inc_hashes and used_device_dump:
                    self._verify_partition_hashes(ota_dir, inc_hashes, phase="old")
                self._run_cmd([ota_extractor, payload_work, "--source-dir", ota_dir, "-o", ota_new],
                              allow_root_fallback=True)
                if inc_hashes:
                    self._verify_partition_hashes(ota_new, inc_hashes, phase="new")
                    self.last_expected_hashes = inc_hashes'''
if "inc_hashes = parse_payload_partition_hashes(payload_work)" not in txt:
    assert old_diff_cmd in txt, "Could not locate incremental ota_extractor call"
    txt = txt.replace(old_diff_cmd, new_diff_cmd, 1)

# Also capture metadata from incremental OTA ZIP when base was device://dump or folder
old_inc_meta = '                    tag, ota_ver = self._read_zip_meta(zf)'
if "self._merge_inc_meta" not in txt and txt.count(old_inc_meta) >= 2:
    # Replace second occurrence (inside incremental loop)
    first_idx = txt.find(old_inc_meta)
    sec_idx = txt.find(old_inc_meta, first_idx + len(old_inc_meta))
    inc_meta_add = (
        '                    tag, ota_ver = self._read_zip_meta(zf)\n'
        '                    inc_m = extract_ota_zip_metadata(zf)\n'
        '                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):\n'
        '                        if inc_m.get(mk) and not self.ota_meta.get(mk):\n'
        '                            self.ota_meta[mk] = inc_m[mk]\n'
        '                    if ota_ver:\n'
        '                        self.ota_meta["ota_version"] = ota_ver'
    )
    txt = txt[:sec_idx] + inc_meta_add + txt[sec_idx + len(old_inc_meta):]

# Verify Fake OTA payload.bin new_partition_info hashes match merged images
old_fake_done = 'self._run_cmd([delta_gen, f"--in_file={final_payload}", f"--properties_file={props_file}"])'
new_fake_done = (
    'self._run_cmd([delta_gen, f"--in_file={final_payload}", f"--properties_file={props_file}"])\n'
    '        if self.last_expected_hashes:\n'
    '            fake_hashes = parse_payload_partition_hashes(final_payload)\n'
    '            self.log.emit("\\n=== Verifying Fake OTA payload.bin Hashes Against Merged OTA ===\\n")\n'
    '            bad = []\n'
    '            ok_cnt = 0\n'
    '            for pname, exp in sorted(self.last_expected_hashes.items()):\n'
    '                exp_h = exp.get("new_sha256")\n'
    '                got_h = (fake_hashes.get(pname) or {}).get("new_sha256")\n'
    '                if exp_h and got_h:\n'
    '                    if exp_h.lower() == got_h.lower():\n'
    '                        ok_cnt += 1\n'
    '                        self.log.emit(f"  [FAKE OTA OK] {pname} ({got_h[:12]}...)\\n")\n'
    '                    else:\n'
    '                        bad.append(pname)\n'
    '                        self.log.emit(f"  [FAKE OTA MISMATCH] {pname}: {got_h[:12]}... != {exp_h[:12]}...\\n")\n'
    '            self.log.emit(f"Fake OTA payload hash verification: {ok_cnt}/{ok_cnt + len(bad)} matched.\\n")\n'
    '            if bad:\n'
    '                raise RuntimeError("Fake OTA payload hash mismatch for: " + ", ".join(bad))'
)
if "Verifying Fake OTA payload.bin Hashes Against Merged OTA" not in txt and old_fake_done in txt:
    txt = txt.replace(old_fake_done, new_fake_done, 1)

# Route BOTH RegionalHybrid (OOS_FILES_HERE) and SuperHybrid (COS_FILES_HERE) through the universal dynamic builder!
old_rec_call = "                self._build_recovery_zip(ota_dir, out_dir, safe_name)"
new_rec_call = "                self._build_universal_hybrid_zip(ota_dir, out_dir, safe_name, mode=self.recovery_mode)"
if "self._build_universal_hybrid_zip(" not in txt:
    assert old_rec_call in txt, "Could not locate _build_recovery_zip call in DumpWorker.run()"
    txt = txt.replace(old_rec_call, new_rec_call, 1)

# ---------------------------------------------------------------------------
# 1e. UI: Dump Entire System Image (Root) + RegionalHybrid / SuperHybrid differentiator
# ---------------------------------------------------------------------------
old_folder_btn = '''        self.add_folder_btn = QPushButton("Add FULL Folder")
        self.add_folder_btn.clicked.connect(self.add_full_folder)
        pick_row.addWidget(self.add_folder_btn)
        qc_layout.addLayout(pick_row)'''
new_folder_btn = '''        self.add_folder_btn = QPushButton("Add FULL Folder")
        self.add_folder_btn.clicked.connect(self.add_full_folder)
        pick_row.addWidget(self.add_folder_btn)
        qc_layout.addLayout(pick_row)
        self.stock_overrides = {}
        self.dump_dev_btn = QPushButton("Dump Entire System Image (Root)")
        self.dump_dev_btn.clicked.connect(self.configure_root_dump)
        qc_layout.addWidget(self.dump_dev_btn)'''
if "self.configure_root_dump" not in txt:
    assert old_folder_btn in txt, "Could not locate Add FULL Folder button"
    txt = txt.replace(old_folder_btn, new_folder_btn, 1)

old_rec_ui = '''        self.recovery_switch = M3Switch(self.tokens)
        self.recovery_switch.toggled.connect(self.on_recovery_toggled)
        row_rec.addWidget(self.recovery_switch)
        opt_col.addLayout(row_rec)'''

new_rec_ui = '''        self.recovery_switch = M3Switch(self.tokens)
        self.recovery_switch.toggled.connect(self.on_recovery_toggled)
        row_rec.addWidget(self.recovery_switch)
        opt_col.addLayout(row_rec)

        self.recovery_mode = "super"'''

if "self.recovery_mode =" not in txt:
    assert old_rec_ui in txt, "Could not locate recovery_switch UI row"
    txt = txt.replace(old_rec_ui, new_rec_ui, 1)

old_on_rec = '''    def on_recovery_toggled(self, checked: bool):
        if not checked:
            self.rec_sub.setText("Packs OOS_FILES_HERE + my_company, my_preload, system_dlkm_oki")
            return
        if self.fake_ota_switch.isChecked():
            self.fake_ota_switch.setChecked(False)
        dlg = RequiredImagesDialog(self, self.current_qss, self.hybrid_imgs)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.hybrid_imgs = dict(dlg.paths)
            self.rec_sub.setText("Selected: my_company, my_preload, system_dlkm_oki (ready)")
        else:
            self.recovery_switch.blockSignals(True)
            self.recovery_switch.setChecked(False)
            self.recovery_switch.blockSignals(False)'''

new_on_rec = '''    def _has_device_dump_queued(self) -> bool:
        lines = [l.strip().lower() for l in self.url_box.toPlainText().splitlines() if l.strip()]
        return bool(lines and lines[0] == "device://dump")

    def configure_root_dump(self):
        dlg = RootDumpDialog(self, self.current_qss, self.stock_overrides)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.stock_overrides = dict(dlg.stock_overrides)
            existing = [l.strip() for l in self.url_box.toPlainText().splitlines() if l.strip() and l.strip().lower() != "device://dump"]
            self.url_box.setPlainText("\\n".join(["device://dump"] + existing))
            ov_list = ", ".join(sorted(self.stock_overrides.keys())) if self.stock_overrides else "none"
            self.log(f"Base source set to live Root Full System Dump (stock overrides: {ov_list}).\\n")
            self.log("Add your incremental OTA ZIP(s) below device://dump, pick RegionalHybrid or SuperHybrid (or Fake OTA), and tap Merge.\\n")

    def set_recovery_mode(self, mode: str, silent: bool = False):
        self.recovery_mode = "super" if mode == "super" else "regional"
        is_super = (self.recovery_mode == "super")
        self.btn_mode_regional.setChecked(not is_super)
        self.btn_mode_super.setChecked(is_super)
        self.btn_mode_regional.setObjectName("" if is_super else "PrimaryBtn")
        self.btn_mode_super.setObjectName("PrimaryBtn" if is_super else "")
        for b in (self.btn_mode_regional, self.btn_mode_super):
            b.style().unpolish(b)
            b.style().polish(b)
        if is_super:
            self.rec_sub.setText("Universal ColorOS (COS_FILES_HERE) — live root META-INF + 4 safety guards")
        else:
            self.rec_sub.setText("Universal OOS RegionalHybrid (OOS_FILES_HERE) — live root META-INF + auto-preserve")
            if not silent and self.recovery_switch.isChecked() and not self._has_device_dump_queued():
                self.on_recovery_toggled(True)

    def on_recovery_toggled(self, checked: bool):
        if not checked:
            if self.recovery_mode == "super":
                self.rec_sub.setText("Universal ColorOS (COS_FILES_HERE) — live root META-INF + 4 safety guards")
            else:
                self.rec_sub.setText("Universal OOS RegionalHybrid (OOS_FILES_HERE) — live root META-INF + auto-preserve")
            return
        if self.fake_ota_switch.isChecked():
            self.fake_ota_switch.setChecked(False)
        if self.recovery_mode == "super":
            self.rec_sub.setText("SuperHybrid ready (COS_FILES_HERE + dynamic recovery & fastboot scripts)")
            return
        if self._has_device_dump_queued():
            self.rec_sub.setText("RegionalHybrid ready (OOS_FILES_HERE auto-populated from Root Device Dump)")
            return
        dlg = RequiredImagesDialog(self, self.current_qss, self.hybrid_imgs)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.hybrid_imgs = dict(dlg.paths)
            self.rec_sub.setText("Selected: my_company, my_preload, system_dlkm_oki (ready)")
        else:
            self.recovery_switch.blockSignals(True)
            self.recovery_switch.setChecked(False)
            self.recovery_switch.blockSignals(False)'''

if "def set_recovery_mode(" not in txt:
    assert old_on_rec in txt, "Could not locate on_recovery_toggled()"
    txt = txt.replace(old_on_rec, new_on_rec, 1)

old_add_hyb = '''            hybrid_picks, other_picks = [], []
            found_reqs = []
            for f in dlg.selected_paths:
                is_hyb, reqs = is_regional_hybrid_zip(f)
                if is_hyb:
                    hybrid_picks.append(f)
                    found_reqs = reqs
                else:
                    other_picks.append(f)

            if hybrid_picks:
                existing = [l.strip() for l in self.url_box.toPlainText().splitlines() if l.strip()]
                new_lines = hybrid_picks + [x for x in existing if x not in hybrid_picks] + [x for x in other_picks if x not in existing]
                self.url_box.setPlainText("\\n".join(new_lines))
                if self.fake_ota_switch.isChecked():
                    self.fake_ota_switch.setChecked(False)
                self.recovery_switch.blockSignals(True)
                self.recovery_switch.setChecked(True)
                self.recovery_switch.blockSignals(False)
                req_str = ", ".join(found_reqs) if found_reqs else "OOS_FILES_HERE"
                self.rec_sub.setText(f"Auto-linked from RegionalHybrid ZIP ({req_str})")
                self.log(f"Detected RegionalHybrid base ZIP: {os.path.basename(hybrid_picks[0])}\\n")
                self.log(f"Auto-enabled Custom Recovery Flashable ZIP (auto-grabbing {req_str}).\\n")'''

new_add_hyb = '''            hybrid_picks, other_picks = [], []
            detected_mode = None
            found_reqs = []
            for f in dlg.selected_paths:
                hmode, reqs, _ = detect_hybrid_zip(f)
                if hmode in ("regional", "super"):
                    hybrid_picks.append(f)
                    detected_mode = hmode
                    found_reqs = reqs
                else:
                    other_picks.append(f)

            if hybrid_picks:
                existing = [l.strip() for l in self.url_box.toPlainText().splitlines() if l.strip()]
                new_lines = hybrid_picks + [x for x in existing if x not in hybrid_picks] + [x for x in other_picks if x not in existing]
                self.url_box.setPlainText("\\n".join(new_lines))
                if self.fake_ota_switch.isChecked():
                    self.fake_ota_switch.setChecked(False)
                self.set_recovery_mode(detected_mode, silent=True)
                self.recovery_switch.blockSignals(True)
                self.recovery_switch.setChecked(True)
                self.recovery_switch.blockSignals(False)
                if detected_mode == "super":
                    self.rec_sub.setText("Auto-linked from MergedOTAFlasher ZIP (OS_FILES_HERE)")
                    self.log(f"Detected MergedOTAFlasher base ZIP: {os.path.basename(hybrid_picks[0])}\\n")
                    self.log("Auto-enabled MergedOTAFlasher (OS_FILES_HERE) recovery ZIP mode.\\n")
                else:
                    req_str = ", ".join(found_reqs) if found_reqs else "OOS_FILES_HERE"
                    self.rec_sub.setText(f"Auto-linked from RegionalHybrid ZIP ({req_str})")
                    self.log(f"Detected RegionalHybrid base ZIP: {os.path.basename(hybrid_picks[0])}\\n")
                    self.log(f"Auto-enabled RegionalHybrid recovery ZIP (auto-grabbing {req_str}).\\n")'''

if "detected_mode = None" not in txt:
    assert old_add_hyb in txt, "Could not locate add_local_files() hybrid block"
    txt = txt.replace(old_add_hyb, new_add_hyb, 1)

old_start = '''        use_rec = self.recovery_switch.isChecked()
        is_hyb_base, hyb_reqs = is_regional_hybrid_zip(lines[0])
        if is_hyb_base:
            use_rec = True
            if self.fake_ota_switch.isChecked():
                self.fake_ota_switch.setChecked(False)
            if not self.recovery_switch.isChecked():
                self.recovery_switch.blockSignals(True)
                self.recovery_switch.setChecked(True)
                self.recovery_switch.blockSignals(False)
        if use_rec:
            missing = [
                r for r in REQUIRED_HYBRID_IMGS
                if r not in hyb_reqs and not os.path.isfile(self.hybrid_imgs.get(r, ""))
            ]
            if missing:
                self.on_recovery_toggled(True)
                if not self.recovery_switch.isChecked():
                    return'''

new_start = '''        use_rec = self.recovery_switch.isChecked()
        rec_mode = self.recovery_mode
        is_dev_dump = (lines[0].strip().lower() == "device://dump")
        hyb_mode, hyb_reqs, _ = detect_hybrid_zip(lines[0])
        if hyb_mode in ("regional", "super"):
            use_rec = True
            rec_mode = hyb_mode
            self.set_recovery_mode(hyb_mode, silent=True)
            if self.fake_ota_switch.isChecked():
                self.fake_ota_switch.setChecked(False)
            if not self.recovery_switch.isChecked():
                self.recovery_switch.blockSignals(True)
                self.recovery_switch.setChecked(True)
                self.recovery_switch.blockSignals(False)
        if use_rec and rec_mode == "regional" and not is_dev_dump:
            missing = [
                r for r in REQUIRED_HYBRID_IMGS
                if r not in hyb_reqs and not os.path.isfile(self.hybrid_imgs.get(r, ""))
            ]
            if missing:
                self.on_recovery_toggled(True)
                if not self.recovery_switch.isChecked():
                    return'''

if "is_dev_dump = (lines[0].strip().lower() == \"device://dump\")" not in txt:
    assert old_start in txt, "Could not locate start_dump() hybrid check"
    txt = txt.replace(old_start, new_start, 1)

old_worker_call = '''        self.worker = DumpWorker(
            lines,
            fake_ota=self.fake_ota_switch.isChecked(),
            recovery_zip=use_rec,
            extra_imgs=self.hybrid_imgs,
            work_dir=self.work_dir,
        )'''
new_worker_call = '''        self.worker = DumpWorker(
            lines,
            fake_ota=self.fake_ota_switch.isChecked(),
            recovery_zip=use_rec,
            recovery_mode=rec_mode,
            extra_imgs=self.hybrid_imgs,
            stock_overrides=self.stock_overrides,
            work_dir=self.work_dir,
        )'''
if "stock_overrides=self.stock_overrides," not in txt:
    assert old_worker_call in txt, "Could not locate DumpWorker(...) instantiation"
    txt = txt.replace(old_worker_call, new_worker_call, 1)


# ---------------------------------------------------------------------------
# 1f. Add "Auto-Pull All 3 From Device (Root)" inside RequiredImagesDialog
# ---------------------------------------------------------------------------
old_auto_btn = """        auto_btn = QPushButton("Auto-Find All 3 From a Folder")
        auto_btn.clicked.connect(self.auto_find_from_folder)
        layout.addWidget(auto_btn)"""

new_auto_btn = """        auto_btn = QPushButton("Auto-Find All 3 From a Folder")
        auto_btn.clicked.connect(self.auto_find_from_folder)
        layout.addWidget(auto_btn)

        self.pull_root_btn = QPushButton("Auto-Pull All 3 From Device (Root)")
        self.pull_root_btn.setObjectName("PrimaryBtn")
        self.pull_root_btn.clicked.connect(self.auto_pull_from_device_root)
        layout.addWidget(self.pull_root_btn)"""

if "self.pull_root_btn" not in txt:
    assert old_auto_btn in txt, "Could not locate auto_btn in RequiredImagesDialog"
    txt = txt.replace(old_auto_btn, new_auto_btn, 1)

pull_method = """    def auto_pull_from_device_root(self):
        if not shutil.which("su"):
            QMessageBox.warning(self, "Root Required", "su binary not found. Root access is required to pull images from the device.")
            return
        self.pull_root_btn.setEnabled(False)
        self.pull_root_btn.setText("Pulling images via root...")
        QApplication.processEvents()
        try:
            slot = (subprocess.run(["su", "-c", "getprop ro.boot.slot_suffix"], capture_output=True, text=True).stdout or "").strip()
            out_dir = os.path.join(get_work_dir(), "pulled_regional_imgs")
            os.makedirs(out_dir, exist_ok=True)
            pulled, missing = [], []
            for req in REQUIRED_HYBRID_IMGS:
                part = req[:-4]
                cands = []
                if slot:
                    cands.append(f"/dev/block/mapper/{part}{slot}")
                    cands.append(f"/dev/block/by-name/{part}{slot}")
                cands.append(f"/dev/block/mapper/{part}")
                cands.append(f"/dev/block/by-name/{part}")
                blk = ""
                for c in cands:
                    chk = subprocess.run(["su", "-c", f'[ -e "{c}" ] && echo 1 || echo 0'], capture_output=True, text=True)
                    if (chk.stdout or "").strip() == "1":
                        blk = c
                        break
                if not blk:
                    missing.append(req)
                    continue
                dst = os.path.join(out_dir, req)
                self.pull_root_btn.setText(f"Pulling {req}...")
                QApplication.processEvents()
                rc = subprocess.run(
                    ["su", "-c", f'dd if="{blk}" of="{dst}" bs=4M 2>/dev/null || dd if="{blk}" of="{dst}" bs=1M'],
                    capture_output=True, text=True,
                ).returncode
                if rc == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    self.paths[req] = dst
                    self.labels[req].setText(self._fmt_path(dst))
                    pulled.append(req)
                else:
                    missing.append(req)
            if pulled and not missing:
                QMessageBox.information(self, "Pulled From Device", f"Successfully pulled all {len(pulled)} images from active slot {slot or '(non-A/B)'}.")
            elif pulled:
                QMessageBox.warning(self, "Partial Pull", f"Pulled: {', '.join(pulled)}\\nNot found on device: {', '.join(missing)}")
            else:
                QMessageBox.warning(self, "Pull Failed", "Could not find my_company, my_preload, or system_dlkm_oki on this device (check root permission).")
        finally:
            self.pull_root_btn.setEnabled(True)
            self.pull_root_btn.setText("Auto-Pull All 3 From Device (Root)")

    def validate_and_accept(self):"""

if "def auto_pull_from_device_root(" not in txt:
    assert "    def validate_and_accept(self):" in txt, "Could not locate validate_and_accept in RequiredImagesDialog"
    txt = txt.replace("    def validate_and_accept(self):", pull_method, 1)


# ---------------------------------------------------------------------------
# 1g. v1.7.1 UI Polish:
#   - Remove "(Magisk / KSU Next)" from Root System Update Capture label
#   - True Material 3 pill buttons (fix Qt6 border-radius > half-height clamp)
#   - Smooth back-and-forth marquee in PickerRowDelegate for long filenames/dirs
#   - Unify RegionalHybrid + SuperHybrid into ONE toggle (remove redundant button row)
# ---------------------------------------------------------------------------

txt = txt.replace(" (Magisk / KSU Next)", "")

txt = re.sub(
    r'QLabel#StatusChip \{\{.*?\}\}',
    """QLabel#StatusChip {{
    background-color: {t["primary_container"]};
    color: {t["on_primary_container"]};
    border-radius: 13px;
    padding: 3px 14px;
    min-height: 24px;
    font-size: 12px;
    font-weight: 600;
}}""",
    txt,
    flags=re.S,
)
txt = re.sub(
    r'QPushButton \{\{.*?\}\}',
    """QPushButton {{
    background-color: {t["surface_container_high"]};
    color: {t["on_surface"]};
    border: none;
    border-radius: 19px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 32px;
}}""",
    txt,
    count=1,
    flags=re.S,
)
txt = re.sub(
    r'QPushButton#PrimaryBtn \{\{.*?\}\}',
    """QPushButton#PrimaryBtn {{
    background-color: {t["primary"]};
    color: {t["on_primary"]};
    border: none;
    border-radius: 22px;
    padding: 8px 20px;
    font-size: 15px;
    font-weight: 700;
    min-height: 36px;
}}""",
    txt,
    count=1,
    flags=re.S,
)

new_delegate = """class PickerRowDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, accent_hex="#D32F2F", outline_hex="#6E6668", text_hex="#F4EFF0"):
        super().__init__(parent)
        self._view = parent
        self.accent = QColor(accent_hex)
        self.outline = QColor(outline_hex)
        self.text_col = QColor(text_hex)
        self._phase = 0
        self._has_overflow = False
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(33)
        self._marquee_timer.timeout.connect(self._tick_marquee)
        self._marquee_timer.start()

    def _tick_marquee(self):
        if self._view is not None and self._view.isVisible() and self._has_overflow:
            self._phase += 1
            self._view.viewport().update()

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if selected:
            bg = QColor(self.accent)
            bg.setAlpha(45)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(r.adjusted(4, 2, -4, -2), 14, 14)

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.setPen(self.text_col)
        text_rect = r.adjusted(14, 0, -68, 0)
        tw = painter.fontMetrics().horizontalAdvance(text)
        overflow = tw - text_rect.width()
        if overflow > 2:
            self._has_overflow = True
            pause = 28
            speed = 1.4
            travel = max(1, int(overflow / speed))
            cycle = pause + travel + pause + travel
            t = self._phase % cycle
            if t < pause:
                dx = 0
            elif t < pause + travel:
                dx = min(overflow, int((t - pause) * speed))
            elif t < pause + travel + pause:
                dx = overflow
            else:
                dx = max(0, int(overflow - (t - pause - travel - pause) * speed))
            painter.save()
            painter.setClipRect(text_rect)
            draw_rect = text_rect.adjusted(-dx, 0, overflow + 12, 0)
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            painter.restore()
        else:
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        udata = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(udata, tuple) and len(udata) >= 2:
            box_sz = 24
            bx = r.right() - box_sz - 18
            by = r.center().y() - (box_sz // 2)
            box_rect = QRectF(bx, by, box_sz, box_sz)
            if selected:
                painter.setBrush(self.accent)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(box_rect, 6, 6)
                pen = QPen(QColor("#FFFFFF"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(int(bx + 5), int(by + 12), int(bx + 10), int(by + 17))
                painter.drawLine(int(bx + 10), int(by + 17), int(bx + 19), int(by + 7))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(self.outline, 2.0))
                painter.drawRoundedRect(box_rect, 6, 6)

        painter.restore()"""

pat_del = re.compile(r"class PickerRowDelegate\(QStyledItemDelegate\):.*?(?=\n\nclass TouchScrollFilter\(QObject\):)", re.S)
assert pat_del.search(txt), "Could not locate PickerRowDelegate class"
txt = pat_del.sub(lambda _: new_delegate, txt, count=1)

UNIFIED_SUB = "Universal OOS/COS flasher, Non ColorOS device support is experimental"

txt = re.sub(
    r'self\.rec_sub = QLabel\("[^"]*"\)',
    f'self.rec_sub = QLabel("{UNIFIED_SUB}")',
    txt,
    count=1,
)

pat_rmode_ui = re.compile(
    r'\n        self\.recovery_mode = "regional"\n        row_rmode = QHBoxLayout\(\).*?opt_col\.addLayout\(row_rmode\)',
    re.S,
)
if pat_rmode_ui.search(txt):
    txt = pat_rmode_ui.sub('\n        self.recovery_mode = "super"', txt, count=1)

pat_rec_methods = re.compile(
    r'    def set_recovery_mode\(self, mode: str, silent: bool = False\):.*?(?=\n    def log\(self, text\):)',
    re.S,
)
unified_rec_methods = f"""    def set_recovery_mode(self, mode: str, silent: bool = False):
        self.recovery_mode = "regional" if mode == "regional" else "super"
        self.rec_sub.setText("{UNIFIED_SUB}")

    def on_recovery_toggled(self, checked: bool):
        if not checked:
            self.rec_sub.setText("{UNIFIED_SUB}")
            return
        if self.fake_ota_switch.isChecked():
            self.fake_ota_switch.setChecked(False)
        self.rec_sub.setText("{UNIFIED_SUB}")"""

assert pat_rec_methods.search(txt), "Could not locate set_recovery_mode / on_recovery_toggled"
txt = pat_rec_methods.sub(lambda _: unified_rec_methods, txt, count=1)

txt = txt.replace(
    'if use_rec and rec_mode == "regional" and not is_dev_dump:',
    'if False and use_rec and rec_mode == "regional" and not is_dev_dump:',
)

mp.write_text(txt)
print("Patched main.py: Universal ColorOS/OOS RegionalHybrid & SuperHybrid + Live Root META-INF + Full System Dump + SHA-256 checks.")
PYEOF

echo "=== 2. BUMP VERSION TO 1.8 (versionCode 1080000), REPACK DIST BUNDLE & BUMP private_version ==="
python3 - "$DIST_ROOT" << 'PYEOF'
import py_compile, re, shutil, sys, tarfile, tempfile, time
from pathlib import Path

dist = Path(sys.argv[1])

bg = dist / "build.gradle"
if bg.exists():
    bg_txt = bg.read_text()
    bg_txt = re.sub(r"versionName\s+['\"][^'\"]+['\"]", "versionName '1.8'", bg_txt)
    bg_txt = re.sub(r"versionCode\s+\d+", "versionCode 1080000", bg_txt, count=1)
    bg.write_text(bg_txt)
    print("Updated build.gradle -> versionName 1.8 / versionCode 1080000")

spec = Path("buildozer.spec")
if spec.exists():
    spec.write_text(re.sub(r"^version\s*=.*$", "version = 1.8", spec.read_text(), flags=re.M))
    print("Updated buildozer.spec -> version = 1.8")
assets = dist / "src" / "main" / "assets"
main_py = Path("main.py").resolve()
for cand in ("private.mp3", "private.tar", "private.tar.gz"):
    arc = assets / cand
    if not arc.exists():
        continue
    with open(arc, "rb") as fh:
        is_gz = (fh.read(2) == b"\x1f\x8b")
    r_mode, w_mode = ("r:gz", "w:gz") if is_gz else ("r:", "w:")
    tmp_dir = Path(tempfile.mkdtemp(prefix="ota_patch_"))
    tmp_arc = tmp_dir / cand
    pyc_tmp = tmp_dir / "main.pyc"
    py_compile.compile(str(main_py), cfile=str(pyc_tmp), doraise=True)
    with tarfile.open(arc, r_mode) as tin, tarfile.open(tmp_arc, w_mode) as tout:
        replaced = []
        for m in tin.getmembers():
            norm = m.name.lstrip("./")
            if norm == "main.py":
                tout.add(str(main_py), arcname=m.name); replaced.append(m.name)
            elif norm == "main.pyc":
                tout.add(str(pyc_tmp), arcname=m.name); replaced.append(m.name)
            else:
                tout.addfile(m, tin.extractfile(m)) if m.isfile() else tout.addfile(m)
        if not replaced:
            tout.add(str(main_py), arcname="main.py")
    shutil.move(str(tmp_arc), str(arc))
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("Updated bundle:", arc.name, replaced)
    break

strings_xml = dist / "src" / "main" / "res" / "values" / "strings.xml"
if strings_xml.exists():
    stamp = str(int(time.time()))
    s_txt = strings_xml.read_text()
    s_txt = re.sub(r'(<string\s+name="private_version">)[^<]*(</string>)', rf'\g<1>{stamp}\g<2>', s_txt)
    strings_xml.write_text(s_txt)
    print("Bumped private_version ->", stamp)
PYEOF

echo "=== 3. GRADLE ASSEMBLE (v1.8 MergedOTAFlasher + OS_FILES_HERE + Hardened Fastboot) ==="
(cd "$DIST_ROOT" && ./gradlew assembleDebug --no-daemon --max-workers=1)
sync

APK=$(find "$DIST_ROOT/build/outputs/apk/debug" -name "*.apk" | head -n 1)
OUT_APK="/sdcard/Download/OTAFWMerger-v1.8-JKurtz-arm64-v8a.apk"
cp -fv "$APK" "$OUT_APK"
ls -lh "$OUT_APK"
echo "SUCCESS! Ready to install: $OUT_APK"