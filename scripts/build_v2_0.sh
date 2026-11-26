#!/usr/bin/env bash
set -eo pipefail
source ~/.bashrc 2>/dev/null || true
source ~/pyside-build-venv/bin/activate 2>/dev/null || true
cd ~/build/OTAFirmwareMerger

BUILD_LOG="/sdcard/Download/build_v2_0.log"
: > "$BUILD_LOG"
exec > >(tee -a "$BUILD_LOG") 2>&1

export GRADLE_OPTS="-Xmx1536m -XX:MaxMetaspaceSize=512m"
DIST_ROOT=".buildozer/android/platform/build-arm64-v8a/dists/otafwmerger"

echo "=== 1. PATCH main.py (v2.0 SECURITY & RELIABILITY HARDENING RELEASE) ==="
python3 - << 'PYEOF'
import re
from pathlib import Path

mp = Path("main.py")
txt = mp.read_text()

# 1a. Bump APP_VERSION -> 2.0
txt = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "2.0"', txt, count=1)

# 1b. CRITICAL #1 & #4: Ensure `import time`, `import shlex`, and `QInputDialog` are imported!
for mod in ("shlex", "time"):
    if f"import {mod}" not in txt:
        txt = txt.replace("import shutil", f"import {mod}\nimport shutil", 1)

if "QInputDialog" not in txt:
    txt = txt.replace("QFrame, QHBoxLayout,", "QFrame, QHBoxLayout, QInputDialog,", 1)

# Add strict partition name validator helper
if "SAFE_PART_RE" not in txt:
    txt = txt.replace(
        "EARLY_BOOT_PARTITIONS = [",
        'SAFE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")\n\nEARLY_BOOT_PARTITIONS = [',
        1,
    )

# 1c. MEDIUM #3: Expand DUMP_EXCLUDE_PARTITIONS to block device-unique IMEI/calibration/serial blocks
old_excl = '''    "proinfo", "otp", "flashinfo", "pgpt", "sgpt", "boot_para",
}'''
new_excl = '''    "proinfo", "otp", "flashinfo", "pgpt", "sgpt", "boot_para",
    "oplusstanvbk", "devinfo", "secdata", "uefivarstore", "spunvm",
    "logfs", "logdump", "limits", "limits-cdsp", "apdp", "msadp",
    "dip", "mdtp", "mdtpsecapp", "catefv", "catecontentfv", "cateloader",
    "storsec", "storsec_bak", "conninfra_cfg", "efisp", "efuse",
}'''
if '"oplusstanvbk"' not in txt and old_excl in txt:
    txt = txt.replace(old_excl, new_excl, 1)

# 1d. MEDIUM #2: Fix extract_model_from_tag() so MergedOTAFlasher_CPH2749 / folder- / device- parse cleanly
old_ext_model = '''def extract_model_from_tag(tag: str) -> str:
    m = re.match(r"^([A-Za-z0-9]+)_", tag.strip())
    if m:
        return m.group(1)
    return getprop("ro.product.model", "UNKNOWN")'''

new_ext_model = '''def extract_model_from_tag(tag: str) -> str:
    cleaned = tag.strip()
    for pfx in ("MergedOTAFlasher_", "SuperHybrid_", "RegionalHybrid_", "folder-", "device-"):
        if cleaned.startswith(pfx):
            cleaned = cleaned[len(pfx):]
    m = re.match(r"^([A-Za-z0-9]+)_", cleaned)
    if m:
        cand = m.group(1)
        if cand.lower() not in ("merged", "ota", "full", "incremental", "folder", "device", "unknown"):
            return cand
    return getprop("ro.product.model", "UNKNOWN")'''

if 'for pfx in ("MergedOTAFlasher_"' not in txt and old_ext_model in txt:
    txt = txt.replace(old_ext_model, new_ext_model, 1)

# 1e. CRITICAL #5: Restore TLS certificate verification in aria2c using bundled cacert.pem
old_aria_tls = '"--check-certificate=false",'
new_aria_tls = '*(["--ca-certificate=" + os.path.join(APP_DIR, "cacert.pem")] if os.path.isfile(os.path.join(APP_DIR, "cacert.pem")) else []),'
if old_aria_tls in txt:
    txt = txt.replace(old_aria_tls, new_aria_tls)

# 1f. CRITICAL #4: Escape all su -c commands with shlex.quote()
# _root_bin_exists
txt = txt.replace(
    '["su", "-c", f\'[ -x "{cand}" ] && echo 1 || echo 0\']',
    '["su", "-c", f"[ -x {shlex.quote(cand)} ] && echo 1 || echo 0"]',
)
# _run_cmd su fallback
txt = txt.replace(
    'su_cmd = ["su", "-c", " ".join(f\'"{c}"\' for c in cmd)]',
    'su_cmd = ["su", "-c", " ".join(shlex.quote(str(c)) for c in cmd)]',
)
# _dump_device_partitions dd
txt = txt.replace(
    '["su", "-c", f\'dd if="{blk}" of="{dst}" bs=4M 2>/dev/null || dd if="{blk}" of="{dst}" bs=1M\']',
    '["su", "-c", f"dd if={shlex.quote(blk)} of={shlex.quote(dst)} bs=4M 2>/dev/null || dd if={shlex.quote(blk)} of={shlex.quote(dst)} bs=1M"]',
)
# auto-pull check & dd
txt = txt.replace(
    'self._su_read(f\'[ -e "{blk}" ] && echo 1 || echo 0\')',
    'self._su_read(f"[ -e {shlex.quote(blk)} ] && echo 1 || echo 0")',
)
txt = txt.replace(
    '["su", "-c", f\'[ -e "{c}" ] && echo 1 || echo 0\']',
    '["su", "-c", f"[ -e {shlex.quote(c)} ] && echo 1 || echo 0"]',
)
# BinaryUpdateWorker._install_root_bin & reset_bins
txt = txt.replace(
    '["su", "-c", f\'mkdir -p "{ROOT_BIN_DIR}" && cp -f "{src_path}" "{ROOT_BIN_DIR}/{bin_name}" && chmod 755 "{ROOT_BIN_DIR}/{bin_name}"\']',
    '["su", "-c", f"mkdir -p {shlex.quote(ROOT_BIN_DIR)} && cp -f {shlex.quote(src_path)} {shlex.quote(ROOT_BIN_DIR + \'/\' + bin_name)} && chmod 755 {shlex.quote(ROOT_BIN_DIR + \'/\' + bin_name)}"]',
)
txt = txt.replace(
    '["su", "-c", f\'rm -rf "{ROOT_BIN_DIR}"\']',
    '["su", "-c", f"rm -rf {shlex.quote(ROOT_BIN_DIR)}"]',
)
# FastbootFlashWorker._fb & DumperGUI quick/refresh fastboot commands
txt = txt.replace(
    'cmd_str = " ".join([f\'"{fb_bin}"\'] + [f\'"{a}"\' for a in args])',
    'cmd_str = " ".join([shlex.quote(fb_bin)] + [shlex.quote(str(a)) for a in args])',
)
txt = txt.replace(
    'cmd_str = " ".join([f\'"{fb}"\'] + [f\'"{a}"\' for a in args])',
    'cmd_str = " ".join([shlex.quote(fb)] + [shlex.quote(str(a)) for a in args])',
)
txt = txt.replace(
    '["su", "-c", f\'"{fb}" devices\']',
    '["su", "-c", f"{shlex.quote(fb)} devices"]',
)
txt = txt.replace(
    '["su", "-c", f\'"{fb}" getvar product 2>&1\']',
    '["su", "-c", f"{shlex.quote(fb)} getvar product 2>&1"]',
)
txt = txt.replace(
    '["su", "-c", f\'"{fb}" getvar current-slot 2>&1\']',
    '["su", "-c", f"{shlex.quote(fb)} getvar current-slot 2>&1"]',
)

# Validate ZIP-extracted image names in FastbootFlashWorker (block shell metacharacters / path traversal)
old_fb_bn = '''                        bn = os.path.basename(info.filename.replace("\\\\", "/"))
                        dst = os.path.join(tmp_stage, bn)'''
new_fb_bn = '''                        bn = os.path.basename(info.filename.replace("\\\\", "/"))
                        if not SAFE_PART_RE.match(bn):
                            self.log.emit(f"  ! Skipping unsafe filename in ZIP: {bn}\\n")
                            continue
                        dst = os.path.join(tmp_stage, bn)'''
if "Skipping unsafe filename in ZIP:" not in txt and old_fb_bn in txt:
    txt = txt.replace(old_fb_bn, new_fb_bn, 1)

# MEDIUM #4: Do NOT silently ignore firmware flash failures on phys_other in FastbootFlashWorker
txt = txt.replace(
    'self._fb(fb, ["flash", "--slot=all", p, ip], ignore_err=True)',
    'self._fb(fb, ["flash", "--slot=all", p, ip])',
)
txt = txt.replace(
    'self._fb(fb, ["flash", p, ip], ignore_err=True)',
    'self._fb(fb, ["flash", p, ip])',
)

# 1g. CRITICAL #6: Safe tar extraction (filter="data") + aarch64 ELF verification in BinaryUpdateWorker
old_tf_ext = 'tf.extract(m, tmp_dir)'
new_tf_ext = 'tf.extract(m, tmp_dir, filter="data") if hasattr(tarfile, "data_filter") else (tf.extract(m, tmp_dir) if os.path.realpath(os.path.join(tmp_dir, m.name)).startswith(os.path.realpath(tmp_dir) + os.sep) else (_ for _ in ()).throw(RuntimeError("Unsafe tar path")))' 
if old_tf_ext in txt:
    txt = txt.replace(old_tf_ext, new_tf_ext)

old_inst_bin = '''    def _install_root_bin(self, src_path: str, bin_name: str):'''
new_inst_bin = '''    def _install_root_bin(self, src_path: str, bin_name: str):
        if not SAFE_PART_RE.match(bin_name):
            raise RuntimeError(f"Unsafe binary name: {bin_name}")
        with open(src_path, "rb") as fh:
            hdr = fh.read(20)
        if not (hdr[:4] == b"\\x7fELF" and hdr[4] == 2 and hdr[18:20] == b"\\xb7\\x00"):
            raise RuntimeError(f"Downloaded {bin_name} is not a valid aarch64 ELF binary — aborting install")'''
if "is not a valid aarch64 ELF binary" not in txt and old_inst_bin in txt:
    txt = txt.replace(old_inst_bin, new_inst_bin, 1)

# 1h. MEDIUM #1: Fix Fake OTA payload_properties.txt (pack newly generated repack_out/payload_properties.txt!)
old_props_src = '''                props_src = os.path.join(wd, "payload_properties.txt")
                if os.path.isfile(props_src):
                    shutil.move(props_src, os.path.join(out_dir, "payload_properties.txt"))'''
new_props_src = '''                props_src = os.path.join(repack_out, "payload_properties.txt")
                if not os.path.isfile(props_src):
                    props_src = os.path.join(wd, "payload_properties.txt")
                if os.path.isfile(props_src):
                    shutil.copy2(props_src, os.path.join(out_dir, "payload_properties.txt"))'''
if 'os.path.join(repack_out, "payload_properties.txt")' not in txt and old_props_src in txt:
    txt = txt.replace(old_props_src, new_props_src, 1)

# 1i. CRITICAL #2 & #3: Rebuild build_universal_update_binary() so:
#   - Strict device/platform check: aborts unless codename/model/market/SoC matches OR /sdcard/superhybrid_force exists
#   - Computes real required free space (2 * logical_total + 1 GB) from unzip -l
#   - Stages logical images & builds /sdcard/super_new.img with lpmake FIRST — BEFORE writing a single physical partition!
new_ub_fn = r'''def build_universal_update_binary(files_dir: str = "OS_FILES_HERE", label: str = "MergedOTAFlasher") -> str:
    tpl = r"""#!/sbin/sh
# __LABEL__ Universal Recovery Flasher (v2.0 Hardened: lpmake-first atomic staging)
# Supports AERA & OrangeFox recoveries with 4 pre-flight safety guards + --virtual-ab
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
ui_print "  __LABEL__ Universal Recovery Flasher (v2.0)"
ui_print "  Image Folder   : $FILES_DIR"
ui_print "  Metadata Source: ${META_SOURCE:-fallback}"
[ -n "$TARGET_MODEL" ]    && ui_print "  Target Model   : $TARGET_MODEL"
[ -n "$TARGET_DEVICE" ]   && ui_print "  Target Device  : $TARGET_DEVICE"
[ -n "$TARGET_PLATFORM" ] && ui_print "  Target SoC     : $TARGET_PLATFORM"
[ -n "$OTA_VERSION" ]     && ui_print "  Build Version  : $OTA_VERSION"
ui_print "**************************************************"

# --- GUARD 1: Pre-flight Recovery & Tool Check (AERA / OrangeFox) ---
LPMAKE="$(command -v lpmake || echo /system/bin/lpmake)"
[ ! -x "$LPMAKE" ] && [ -x "/vendor/bin/lpmake" ] && LPMAKE="/vendor/bin/lpmake"
SIMG2IMG="$(command -v simg2img || echo /system/bin/simg2img)"
BLOCKDEV="$(command -v blockdev || echo /system/bin/blockdev)"

command -v unzip >/dev/null 2>&1 || abort "Recovery is missing unzip"
[ -x "$BLOCKDEV" ] || abort "Recovery is missing blockdev (use AERA or OrangeFox)"
[ -x "$LPMAKE" ]   || abort "Recovery is missing lpmake (use AERA or OrangeFox)"
[ -x "$SIMG2IMG" ] || abort "Recovery is missing simg2img (use AERA or OrangeFox)"

# --- GUARD 2: Strict Device / SoC Platform Check (overrideable via /sdcard/superhybrid_force) ---
if [ ! -f "/sdcard/superhybrid_force" ]; then
    CUR_DEV="$(getprop ro.product.device 2>/dev/null)"
    CUR_MOD="$(getprop ro.product.model 2>/dev/null)"
    CUR_PRD="$(getprop ro.build.product 2>/dev/null)"
    CUR_VDEV="$(getprop ro.product.vendor.device 2>/dev/null)"
    CUR_PLAT="$(getprop ro.board.platform 2>/dev/null)"
    CUR_SOC="$(getprop ro.soc.model 2>/dev/null)"
    CUR_HWPLAT="$(getprop ro.boot.hardware.platform 2>/dev/null)"
    if [ -z "$TARGET_DEVICE" ] && [ -z "$TARGET_MODEL" ] && [ -z "$TARGET_PLATFORM" ] && [ -z "$TARGET_MARKET" ]; then
        ui_print "! Unstamped ZIP: no device or SoC metadata found in META-INF."
        ui_print "! Create /sdcard/superhybrid_force to flash an unstamped ZIP."
        abort "Unstamped ZIP (no partitions modified)"
    fi
    MATCHED=0
    T_DEV_LC="$(echo "$TARGET_DEVICE" | tr A-Z a-z)"
    T_MOD_LC="$(echo "$TARGET_MODEL" | tr A-Z a-z)"
    T_MKT_LC="$(echo "$TARGET_MARKET" | tr A-Z a-z)"
    T_PLT_LC="$(echo "$TARGET_PLATFORM" | tr A-Z a-z)"
    for c in "$CUR_DEV" "$CUR_MOD" "$CUR_PRD" "$CUR_VDEV" "$CUR_PLAT" "$CUR_SOC" "$CUR_HWPLAT"; do
        [ -z "$c" ] && continue
        c_lc="$(echo "$c" | tr A-Z a-z)"
        if { [ -n "$T_DEV_LC" ] && [ "$c_lc" = "$T_DEV_LC" ]; } || \
           { [ -n "$T_MOD_LC" ] && [ "$c_lc" = "$T_MOD_LC" ]; } || \
           { [ -n "$T_MKT_LC" ] && [ "$c_lc" = "$T_MKT_LC" ]; } || \
           { [ -n "$T_PLT_LC" ] && [ "$c_lc" = "$T_PLT_LC" ]; }; then
            ui_print "- Hardware verified: matched '$c'"
            MATCHED=1
            break
        fi
    done
    if [ "$MATCHED" = "0" ]; then
        ui_print "! Device/SoC mismatch: phone is $CUR_MOD ($CUR_DEV / $CUR_PLAT / $CUR_SOC)."
        ui_print "! ZIP targets: ${TARGET_MODEL:-$TARGET_DEVICE} (${TARGET_PLATFORM:-no SoC stamp})."
        ui_print "! Create /sdcard/superhybrid_force to override if you are sure this ZIP is for your phone."
        abort "Device/SoC mismatch (no partitions modified)"
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

# Classify planned physical vs logical partitions BEFORE touching any block device
PLANNED_PHYS=""
PLANNED_LOGICAL=""
for entry in $IMG_LIST; do
    fn="${entry#${FILES_DIR}/}"
    part="${fn%.img}"
    if [ "$IS_AB" = "1" ] && [ -e "/dev/block/by-name/${part}_a" ]; then
        PLANNED_PHYS="$PLANNED_PHYS $entry"
    elif [ -e "/dev/block/by-name/${part}" ] && [ "$part" != "super" ]; then
        PLANNED_PHYS="$PLANNED_PHYS $entry"
    elif is_logical_part "$part"; then
        PLANNED_LOGICAL="$PLANNED_LOGICAL $entry"
    else
        ui_print "  - Will skip ${part}.img (not present on this device)"
    fi
done

# --- GUARD 3 & 4: Core super completeness + dynamic 2x logical free-space check ---
if [ -n "$PLANNED_LOGICAL" ]; then
    [ -e "/dev/block/by-name/super" ] || abort "Logical images present, but /dev/block/by-name/super not found"

    if [ ! -f "/sdcard/superhybrid_force" ]; then
        LOG_NAMES=""
        for entry in $PLANNED_LOGICAL; do
            fn="${entry#${FILES_DIR}/}"
            LOG_NAMES="$LOG_NAMES ${fn%.img}"
        done
        for core in system vendor product odm; do
            if ! is_in_list "$core" "$LOG_NAMES"; then
                ui_print "! Incomplete super set: missing ${core}.img in ${FILES_DIR}/"
                ui_print "! Create /sdcard/superhybrid_force to override."
                abort "Super completeness guard triggered (no partitions modified)"
            fi
        done
    fi

    # Compute exact uncompressed logical size from unzip -l (need ~2x + 1 GB for staging + super_new.img)
    LOG_BYTES="$(unzip -l "$ZIPFILE" 2>/dev/null | awk -v dir="${FILES_DIR}/" '$NF ~ "^"dir"[^/]+\\.img$" {sum += $1} END {printf "%.0f", sum}')"
    FREE_KB="$(df -k /sdcard 2>/dev/null | awk 'NR==2{print $4}')"
    if [ -n "$FREE_KB" ] && [ "$FREE_KB" -gt 0 ] 2>/dev/null; then
        REQ_KB=12582912
        if [ -n "$LOG_BYTES" ] && [ "$LOG_BYTES" -gt 0 ] 2>/dev/null; then
            REQ_KB=$(( (LOG_BYTES / 1024) * 2 + 1048576 ))
        fi
        if [ "$FREE_KB" -lt "$REQ_KB" ]; then
            FREE_GB=$((FREE_KB / 1048576))
            REQ_GB=$(( (REQ_KB + 1048575) / 1048576 ))
            abort "Not enough free space on /sdcard (${FREE_GB} GB free; need ~${REQ_GB} GB for staging + super_new.img)"
        fi
    fi

    # --- PHASE 1 (NON-DESTRUCTIVE): Stage logical images & run lpmake BEFORE flashing any physical partition ---
    ui_print "- Phase 1/2: Staging logical images and building super_new.img..."
    SUPER_SIZE="$("$BLOCKDEV" --getsize64 /dev/block/by-name/super 2>/dev/null)"
    [ -n "$SUPER_SIZE" ] && [ "$SUPER_SIZE" -gt 0 ] || abort "Could not read super partition size"

    GROUP_BASE=""
    if command -v lpdump >/dev/null 2>&1; then
        GROUP_BASE="$(lpdump /dev/block/by-name/super 2>/dev/null | awk '/Name:/{g=$2} /Maximum size:/{if (g != "default") {sub(/_a$|_b$/,"",g); print g; exit}}')"
    fi
    [ -z "$GROUP_BASE" ] && [ -n "$META_GROUP_NAME" ] && GROUP_BASE="$META_GROUP_NAME"
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
    LP_ARGS="--metadata-size 65536 --super-name super --metadata-slots 3 --device super:${SUPER_SIZE} --sparse"
    if [ "$IS_AB" = "1" ]; then
        LP_ARGS="$LP_ARGS --virtual-ab --group ${GROUP_BASE}_a:${GROUP_MAX} --group ${GROUP_BASE}_b:${GROUP_MAX}"
    else
        LP_ARGS="$LP_ARGS --group ${GROUP_BASE}:${GROUP_MAX}"
    fi

    for entry in $PLANNED_LOGICAL; do
        fn="${entry#${FILES_DIR}/}"
        p="${fn%.img}"
        img="$STAGE_DIR/$fn"
        ui_print "  + Staging ${fn}..."
        unzip -p "$ZIPFILE" "$entry" > "$img" || abort "Failed extracting $entry (no partitions modified)"
        magic="$(dd if="$img" bs=4 count=1 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')"
        if [ "$magic" = "3aff26ed" ]; then
            "$SIMG2IMG" "$img" "${img}.raw" || abort "simg2img failed on ${fn} (no partitions modified)"
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

    ui_print "- Running lpmake (${SUPER_SIZE} B, group: ${GROUP_BASE})..."
    # shellcheck disable=SC2086
    "$LPMAKE" $LP_ARGS --output /sdcard/super_new.img || abort "lpmake failed (no partitions modified!)"
    rm -rf "$STAGE_DIR" 2>/dev/null
    ui_print "- super_new.img built cleanly! Starting block writes..."
fi

# --- PHASE 2 (BLOCK WRITES): Only runs after super_new.img succeeded ---
if [ "$IS_AB" = "1" ] && command -v bootctl >/dev/null 2>&1; then
    bootctl set-active-boot-slot 0 >/dev/null 2>&1 || true
    ui_print "- Active slot set to A"
fi

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
ui_print "- Phase 2/2: Flashing physical partitions..."
for entry in $PLANNED_PHYS; do
    fn="${entry#${FILES_DIR}/}"
    part="${fn%.img}"
    tmp_img="$WORKDIR/$fn"
    unzip -p "$ZIPFILE" "$entry" > "$tmp_img" || abort "Failed extracting $entry"
    if [ "$IS_AB" = "1" ] && [ -e "/dev/block/by-name/${part}_a" ]; then
        ui_print "  * Flashing ${part}_a..."
        flash_block_img "$tmp_img" "/dev/block/by-name/${part}_a" || abort "Failed flashing ${part}_a"
        if [ -e "/dev/block/by-name/${part}_b" ]; then
            ui_print "  * Flashing ${part}_b..."
            flash_block_img "$tmp_img" "/dev/block/by-name/${part}_b" || abort "Failed flashing ${part}_b"
        fi
    else
        ui_print "  * Flashing ${part}..."
        flash_block_img "$tmp_img" "/dev/block/by-name/${part}" || abort "Failed flashing ${part}"
    fi
    rm -f "$tmp_img"
    FLASHED_PHYS=$((FLASHED_PHYS + 1))
done
ui_print "- Flashed $FLASHED_PHYS physical partition(s)."

if [ -f "/sdcard/super_new.img" ]; then
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
    return tpl.replace("__FILES_DIR__", files_dir).replace("__LABEL__", label)'''

pat_ub = re.compile(r"def build_universal_update_binary\(.*?(?=\n\ndef build_universal_fastboot_sh\()", re.S)
assert pat_ub.search(txt), "Could not locate build_universal_update_binary()"
txt = pat_ub.sub(lambda _: new_ub_fn, txt, count=1)

# 1j. CRITICAL #2: Let "Another Device" popup ask for optional target SoC/codename (e.g. sm8850, sm8650, infiniti)
old_other_dev = '''            for_other_dev = (mb.clickedButton() == btn_other)'''
new_other_dev = '''            for_other_dev = (mb.clickedButton() == btn_other)
            target_plat_override = ""
            if for_other_dev:
                val, ok_in = QInputDialog.getText(
                    self,
                    "Target Device SoC / Codename (Recommended)",
                    "Enter target device SoC platform or recovery codename (e.g. sm8850, sm8650, infiniti, dodge)\\n"
                    "so recovery can verify hardware before flashing (leave blank to require /sdcard/superhybrid_force):",
                )
                if ok_in and val.strip():
                    target_plat_override = val.strip()'''
if "target_plat_override = " not in txt and old_other_dev in txt:
    txt = txt.replace(old_other_dev, new_other_dev, 1)
    txt = txt.replace(
        "        self.for_other_device = bool(for_other_device)",
        "        self.for_other_device = bool(for_other_device)\n        self.target_plat_override = ''",
        1,
    )
    txt = txt.replace(
        '            for_other_device=for_other_dev,',
        '            for_other_device=for_other_dev,\n            target_plat_override=target_plat_override,',
        1,
    )
    txt = txt.replace(
        'for_other_device=False, skip_hash_check=False, work_dir=None):',
        'for_other_device=False, skip_hash_check=False, target_plat_override="", work_dir=None):',
        1,
    )
    txt = txt.replace(
        "        self.target_plat_override = ''",
        "        self.target_plat_override = (target_plat_override or '').strip()",
        1,
    )
    txt = txt.replace(
        'self.log.emit("Target = Another Device: building META-INF strictly from OTA ZIP metadata (skipping host props).\\n")',
        'self.log.emit("Target = Another Device: building META-INF strictly from OTA ZIP metadata (skipping host props).\\n")\n'
        '            if self.target_plat_override:\n'
        '                self.ota_meta["platform"] = self.target_plat_override\n'
        '                self.log.emit(f"  * Stamped target SoC/codename: {self.target_plat_override}\\n")',
        1,
    )

# 1k. LOW: Deduplicate repeated inc_m = extract_ota_zip_metadata(zf) blocks & remove dead `if False and`
dup_inc = '''                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver'''
while txt.count(dup_inc) > 1:
    first = txt.find(dup_inc)
    second = txt.find(dup_inc, first + len(dup_inc))
    txt = txt[:second] + txt[second + len(dup_inc):]

# Remove dead `if False and ...` block in start_dump()
pat_dead = re.compile(r'\n        if False and use_rec and rec_mode == "regional" and not is_dev_dump:.*?return', re.S)
txt = pat_dead.sub("", txt)


# Fix non-raw grep/logcat probe strings that emit Python 3.12+ SyntaxWarning
txt = re.sub(r'^(\s+)"(grep -rhoE|logcat -d)', r'\1r"\2', txt, flags=re.M)

mp.write_text(txt)
print("Patched main.py -> v2.0 (All Critical, High, Medium & Low audit fixes applied).")
PYEOF

echo "=== 2. BUMP VERSION TO 2.0 (versionCode 2000000), REPACK DIST BUNDLE + cacert.pem & BUMP private_version ==="
python3 - "$DIST_ROOT" << 'PYEOF'
import py_compile, re, shutil, sys, tarfile, tempfile, time
from pathlib import Path

dist = Path(sys.argv[1])

bg = dist / "build.gradle"
if bg.exists():
    bg_txt = bg.read_text()
    bg_txt = re.sub(r"versionName\s+['\"][^'\"]+['\"]", "versionName '2.0'", bg_txt)
    bg_txt = re.sub(r"versionCode\s+\d+", "versionCode 2000000", bg_txt, count=1)
    bg.write_text(bg_txt)
    print("Updated build.gradle -> versionName 2.0 / versionCode 2000000")

spec = Path("buildozer.spec")
if spec.exists():
    spec.write_text(re.sub(r"^version\s*=.*$", "version = 2.0", spec.read_text(), flags=re.M))
    print("Updated buildozer.spec -> version = 2.0")

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
        has_ca = False
        for m in tin.getmembers():
            norm = m.name.lstrip("./")
            if norm == "cacert.pem":
                has_ca = True
            if norm == "main.py":
                tout.add(str(main_py), arcname=m.name); replaced.append(m.name)
            elif norm == "main.pyc":
                tout.add(str(pyc_tmp), arcname=m.name); replaced.append(m.name)
            else:
                tout.addfile(m, tin.extractfile(m)) if m.isfile() else tout.addfile(m)
        if not replaced:
            tout.add(str(main_py), arcname="main.py")
        ca_src = Path("/etc/ssl/certs/ca-certificates.crt")
        if ca_src.is_file() and not has_ca:
            tout.add(str(ca_src), arcname="cacert.pem")
            print("Bundled cacert.pem from", ca_src)
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

echo "=== 3. GRADLE ASSEMBLE (v2.0) ==="
(cd "$DIST_ROOT" && ./gradlew assembleDebug --no-daemon --max-workers=1)
sync

APK=$(find "$DIST_ROOT/build/outputs/apk/debug" -name "*.apk" | head -n 1)
OUT_APK="/sdcard/Download/OTAFWMerger-v2.0-JKurtz-arm64-v8a.apk"
cp -fv "$APK" "$OUT_APK"
ls -lh "$OUT_APK"
echo "SUCCESS! Ready to install: $OUT_APK"