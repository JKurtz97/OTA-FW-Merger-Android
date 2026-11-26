#!/usr/bin/env bash
set -eo pipefail
source ~/.bashrc 2>/dev/null || true
source ~/pyside-build-venv/bin/activate 2>/dev/null || true
cd ~/build/OTAFirmwareMerger

BUILD_LOG="/sdcard/Download/build_v1_9_5.log"
: > "$BUILD_LOG"
exec > >(tee -a "$BUILD_LOG") 2>&1

export GRADLE_OPTS="-Xmx1536m -XX:MaxMetaspaceSize=512m"
DIST_ROOT=".buildozer/android/platform/build-arm64-v8a/dists/otafwmerger"

echo "=== 1. PATCH main.py (v1.9.5: FIX ANDROID CONSCRYPT SSL CA STORE FOR GITHUB BINARY UPDATER) ==="
python3 - << 'PYEOF'
import re
from pathlib import Path

mp = Path("main.py")
txt = mp.read_text()

# 1a. Bump APP_VERSION -> 1.9.5
txt = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "1.9.5"', txt, count=1)

# 1b. Ensure ssl is imported
if "import ssl" not in txt:
    txt = txt.replace("import urllib.request", "import ssl\nimport urllib.request", 1)

# 1c. Use Android's real system CA store (/apex/com.android.conscrypt/cacerts -> /system/etc/security/cacerts -> certifi)
new_http_methods = '''    def _ssl_ctx(self):
        # 1. Bundled Mozilla/Ubuntu CA bundle inside APK assets (APP_DIR/cacert.pem)
        bundled_ca = os.path.join(APP_DIR, "cacert.pem")
        if os.path.isfile(bundled_ca) and os.path.getsize(bundled_ca) > 10000:
            try:
                return ssl.create_default_context(cafile=bundled_ca)
            except Exception:
                pass
        # 2. Load Android Conscrypt / system PEM certs directly via cadata= (avoids OpenSSL 3 capath hash mismatch)
        pems = []
        for cadir in ("/apex/com.android.conscrypt/cacerts", "/system/etc/security/cacerts"):
            if os.path.isdir(cadir):
                try:
                    for fn in os.listdir(cadir):
                        fp = os.path.join(cadir, fn)
                        if not os.path.isfile(fp):
                            continue
                        raw = open(fp, "r", encoding="ascii", errors="ignore").read()
                        s_idx = raw.find("-----BEGIN CERTIFICATE-----")
                        e_idx = raw.find("-----END CERTIFICATE-----")
                        if s_idx != -1 and e_idx != -1:
                            pems.append(raw[s_idx:e_idx + len("-----END CERTIFICATE-----")])
                except Exception:
                    pass
                if pems:
                    break
        if pems:
            ctx = ssl.create_default_context()
            ctx.load_verify_locations(cadata=chr(10).join(pems))
            return ctx
        return ssl.create_default_context()

    def _http_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "OTA-FW-Merger/1.9.5"})
        with urllib.request.urlopen(req, timeout=20, context=self._ssl_ctx()) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _http_download(self, url: str, dst: str):
        req = urllib.request.Request(url, headers={"User-Agent": "OTA-FW-Merger/1.9.5"})
        with urllib.request.urlopen(req, timeout=60, context=self._ssl_ctx()) as resp, open(dst, "wb") as fp:
            shutil.copyfileobj(resp, fp, length=256 * 1024)'''

pat_http = re.compile(r"    (?:def _ssl_ctx\(self\):.*?)?def _http_json\(self, url: str\) -> dict:.*?(?=\n    def _install_root_bin\()", re.S)
assert pat_http.search(txt), "Could not locate BinaryUpdateWorker HTTP methods"
txt = pat_http.sub(lambda _: new_http_methods, txt, count=1)

mp.write_text(txt)
print("Patched main.py -> v1.9.5 (Android Conscrypt SSL CA verification in BinaryUpdateWorker).")
PYEOF

echo "=== 2. BUMP VERSION TO 1.9.5 (versionCode 1090500), REPACK DIST BUNDLE & BUMP private_version ==="
python3 - "$DIST_ROOT" << 'PYEOF'
import py_compile, re, shutil, sys, tarfile, tempfile, time
from pathlib import Path

dist = Path(sys.argv[1])

bg = dist / "build.gradle"
if bg.exists():
    bg_txt = bg.read_text()
    bg_txt = re.sub(r"versionName\s+['\"][^'\"]+['\"]", "versionName '1.9.5'", bg_txt)
    bg_txt = re.sub(r"versionCode\s+\d+", "versionCode 1090500", bg_txt, count=1)
    bg.write_text(bg_txt)
    print("Updated build.gradle -> versionName 1.9.5 / versionCode 1090500")

spec = Path("buildozer.spec")
if spec.exists():
    spec.write_text(re.sub(r"^version\s*=.*$", "version = 1.9.5", spec.read_text(), flags=re.M))
    print("Updated buildozer.spec -> version = 1.9.5")

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
        ca_src = Path("/etc/ssl/certs/ca-certificates.crt")
        if ca_src.is_file() and not any(m.name.lstrip("./") == "cacert.pem" for m in tin.getmembers()):
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

echo "=== 3. GRADLE ASSEMBLE (v1.9.5) ==="
(cd "$DIST_ROOT" && ./gradlew assembleDebug --no-daemon --max-workers=1)
sync

APK=$(find "$DIST_ROOT/build/outputs/apk/debug" -name "*.apk" | head -n 1)
OUT_APK="/sdcard/Download/OTAFWMerger-v1.9.5-JKurtz-arm64-v8a.apk"
cp -fv "$APK" "$OUT_APK"
ls -lh "$OUT_APK"
echo "SUCCESS! Ready to install: $OUT_APK"