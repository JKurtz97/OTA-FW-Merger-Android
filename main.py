import base64
import hashlib
import json
import struct
import os
import re
import shutil
import subprocess
import sys
import zipfile
from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette, QPen, QTextCursor
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QDialog,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QStyle, QStyledItemDelegate, QStackedWidget, QScroller, QScrollerProperties, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "1.8"
APP_PUBLISHER = "JKurtz"
APP_PACKAGE = "com.jkurtz.otafwmerger"
REQUIRED_HYBRID_IMGS = ("my_company.img", "my_preload.img", "system_dlkm_oki.img")

CREDITS_LIST = [
    ("koaaN (Jonas Salo)", "Original OTAFirmwareMerger & Regional Hybrid Flasher", "https://github.com/koaaN/OTAFirmwareMerger"),
    ("luk1337", "oplus_archive OTA extraction & incremental merge pipeline", "https://github.com/luk1337/oplus_archive"),
    ("snowwolf725", "Payload_Repack_Tool (delta_generator & payload repacking)", "https://github.com/snowwolf725/Payload_Repack_Tool"),
    ("rhythmcache", "payload-dumper-rust static arm64 extraction engine", "https://github.com/rhythmcache/payload-dumper-rust"),
    ("aria2", "Multi-connection Android aarch64 download engine", "https://github.com/aria2/aria2"),
    ("Houvven", "OplusUpdater (direct device-specific OPLUS OTA queries)", "https://github.com/Houvven/OplusUpdater"),
    ("R0rt1z2", "realme-ota (OPLUS OTA protocol research)", "https://github.com/R0rt1z2/realme-ota"),
    ("docnok63, Jonas Salo & Daniel", "Regional Hybrid Flasher (inspired by FTH PHONE 1902 & Venkay)", "https://roms.danielspringer.at/"),
    ("lzhiyong", "termux-ndk & android-sdk-tools (on-device arm64 build toolchain)", "https://github.com/lzhiyong/termux-ndk"),
    ("EchterAlsFake", "PySide6-to-Android Qt 6.12 deployment guide", "https://github.com/EchterAlsFake/PySide6-to-Android"),
]


def _load_android_monet() -> dict:
    candidates = [
        os.path.join(os.path.dirname(APP_DIR), "monet_palette.json"),
        f"/data/user/0/{APP_PACKAGE}/files/monet_palette.json",
        f"/data/data/{APP_PACKAGE}/files/monet_palette.json",
    ]
    for p in candidates:
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict) and "a1_200" in data:
                        return data
        except Exception:
            pass
    return {}


def _contrast_fg(hex_bg: str, dark_fg: str, light_fg: str) -> str:
    c = QColor(hex_bg)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return dark_fg if lum > 145 else light_fg


def build_m3_tokens(app: QApplication) -> dict:
    monet = _load_android_monet()
    if monet:
        is_dark = bool(monet.get("is_dark", True))
        if is_dark:
            primary = monet.get("a1_500", monet.get("a1_200", "#D32F2F"))
            primary_pressed = monet.get("a1_600", primary)
            on_primary = _contrast_fg(primary, monet.get("a1_900", "#1A0000"), "#FFFFFF")
            p_cont = monet.get("a1_700", monet.get("a1_800", "#5C1111"))
            on_p_cont = _contrast_fg(p_cont, "#000000", monet.get("a1_50", "#FFFFFF"))
            return {
                "is_dark": True,
                "surface": monet.get("n1_1000", "#000000"),
                "surface_container": "#121212" if monet.get("n1_900", "").upper() == "#000000" else monet.get("n1_900", "#141213"),
                "surface_container_high": monet.get("n2_800", "#221E1F"),
                "surface_pressed": monet.get("n2_700", "#332D2E"),
                "surface_lowest": "#000000",
                "primary": primary,
                "primary_pressed": primary_pressed,
                "on_primary": on_primary,
                "primary_container": p_cont,
                "on_primary_container": on_p_cont,
                "outline": monet.get("n2_500", "#5A5253"),
                "on_surface": monet.get("n1_50", "#F4EFF0"),
                "on_surface_variant": monet.get("n2_200", "#C8BFC0"),
                "disabled_bg": monet.get("n1_800", "#2A2627"),
                "disabled_fg": monet.get("n2_400", "#8A8082"),
            }
        primary = monet.get("a1_600", "#C62828")
        primary_pressed = monet.get("a1_700", primary)
        p_cont = monet.get("a1_100", "#FFDAD6")
        return {
            "is_dark": False,
            "surface": monet.get("n1_10", "#FFFBFF"),
            "surface_container": monet.get("n1_50", "#F7F2F2"),
            "surface_container_high": monet.get("n1_100", "#EDE7E7"),
            "surface_pressed": monet.get("n1_200", "#DFD8D8"),
            "surface_lowest": monet.get("n1_0", "#FFFFFF"),
            "primary": primary,
            "primary_pressed": primary_pressed,
            "on_primary": "#FFFFFF",
            "primary_container": p_cont,
            "on_primary_container": _contrast_fg(p_cont, monet.get("a1_900", "#3B0907"), "#FFFFFF"),
            "outline": monet.get("n2_400", "#857372"),
            "on_surface": monet.get("n1_900", "#201A1A"),
            "on_surface_variant": monet.get("n2_700", "#534342"),
            "disabled_bg": monet.get("n1_200", "#E0D8D8"),
            "disabled_fg": monet.get("n2_400", "#8A7E7E"),
        }

    pal = app.palette()
    try:
        scheme = app.styleHints().colorScheme()
        is_dark = (scheme == Qt.ColorScheme.Dark) if scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light) else (pal.color(QPalette.ColorRole.Window).lightness() < 128)
    except Exception:
        is_dark = pal.color(QPalette.ColorRole.Window).lightness() < 128
    accent = pal.color(QPalette.ColorRole.Accent)
    if not accent.isValid() or accent.hslSaturation() < 20:
        accent = pal.color(QPalette.ColorRole.Highlight)
    h = accent.hslHue() if accent.hslHue() >= 0 else 212
    s = max(min(accent.hslSaturation(), 210), 110)

    def hsl(hue, sat, light):
        return QColor.fromHsl(hue % 360, max(0, min(255, sat)), max(0, min(255, light))).name()

    if is_dark:
        return {
            "is_dark": True,
            "surface": "#000000",
            "surface_container": hsl(h, min(s // 4, 24), 20),
            "surface_container_high": hsl(h, min(s // 3, 36), 34),
            "surface_pressed": hsl(h, min(s // 3, 44), 46),
            "surface_lowest": "#000000",
            "primary": hsl(h, min(s, 200), 170),
            "primary_pressed": hsl(h, min(s, 200), 145),
            "on_primary": "#FFFFFF",
            "primary_container": hsl(h, min(s // 2, 120), 62),
            "on_primary_container": hsl(h, min(s, 210), 232),
            "outline": hsl(h, min(s // 4, 34), 70),
            "on_surface": hsl(h, 16, 236),
            "on_surface_variant": hsl(h, 18, 174),
            "disabled_bg": hsl(h, 14, 42),
            "disabled_fg": hsl(h, 12, 110),
        }
    return {
        "is_dark": False,
        "surface": hsl(h, min(s // 4, 34), 248),
        "surface_container": hsl(h, min(s // 3, 44), 238),
        "surface_container_high": hsl(h, min(s // 2, 72), 224),
        "surface_pressed": hsl(h, min(s // 2, 80), 210),
        "surface_lowest": "#FFFFFF",
        "primary": hsl(h, min(s, 190), 96),
        "primary_pressed": hsl(h, min(s, 190), 82),
        "on_primary": "#FFFFFF",
        "primary_container": hsl(h, min(s, 160), 224),
        "on_primary_container": hsl(h, min(s, 190), 46),
        "outline": hsl(h, min(s // 4, 38), 190),
        "on_surface": hsl(h, 18, 28),
        "on_surface_variant": hsl(h, 18, 86),
        "disabled_bg": hsl(h, 12, 218),
        "disabled_fg": hsl(h, 12, 145),
    }


def render_m3_stylesheet(t: dict) -> str:
    return f"""
QWidget {{
    background-color: {t["surface"]};
    color: {t["on_surface"]};
    font-family: "Roboto", "Sans-Serif";
    font-size: 14px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QFrame#Card {{
    background-color: {t["surface_container"]};
    border: 1px solid {t["outline"]};
    border-radius: 20px;
}}
QLabel#AppTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {t["on_surface"]};
    background: transparent;
}}
QLabel#AppSubtitle {{
    font-size: 12px;
    color: {t["on_surface_variant"]};
    background: transparent;
}}
QLabel#SectionLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {t["primary"]};
    background: transparent;
}}
QLabel#TileTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {t["on_surface"]};
    background: transparent;
}}
QLabel#TileSub {{
    font-size: 12px;
    color: {t["on_surface_variant"]};
    background: transparent;
}}
QLabel#StatusChip {{
    background-color: {t["primary_container"]};
    color: {t["on_primary_container"]};
    border-radius: 13px;
    padding: 3px 14px;
    min-height: 24px;
    font-size: 12px;
    font-weight: 600;
}}
QComboBox {{
    background-color: {t["surface_container_high"]};
    color: {t["on_surface"]};
    border: 1px solid {t["outline"]};
    border-radius: 12px;
    padding: 6px 12px;
    font-size: 13px;
}}
QTextEdit {{
    background-color: {t["surface_lowest"]};
    color: {t["on_surface"]};
    border: 1px solid {t["outline"]};
    border-radius: 14px;
    padding: 10px;
    font-size: 13px;
}}
QTextEdit#LogBox {{
    font-family: "monospace";
    font-size: 12px;
    color: {t["on_surface"]};
}}
QPushButton {{
    background-color: {t["surface_container_high"]};
    color: {t["on_surface"]};
    border: none;
    border-radius: 19px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 32px;
}}
QPushButton:pressed {{
    background-color: {t["surface_pressed"]};
}}
QPushButton#PrimaryBtn {{
    background-color: {t["primary"]};
    color: {t["on_primary"]};
    border: none;
    border-radius: 22px;
    padding: 8px 20px;
    font-size: 15px;
    font-weight: 700;
    min-height: 36px;
}}
QPushButton#PrimaryBtn:pressed {{
    background-color: {t["primary_pressed"]};
}}
QPushButton#PrimaryBtn:disabled {{
    background-color: {t["disabled_bg"]};
    color: {t["disabled_fg"]};
}}
QPushButton#TextBtn {{
    background-color: transparent;
    color: {t["primary"]};
    padding: 6px 10px;
    font-size: 13px;
    font-weight: 600;
    border-radius: 12px;
}}
QPushButton#TextBtn:pressed {{
    background-color: {t["surface_container_high"]};
}}
QListWidget {{
    background-color: {t["surface_lowest"]};
    border: 1px solid {t["outline"]};
    border-radius: 16px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 14px 12px;
    border-radius: 12px;
    margin: 2px 0px;
}}
QListWidget::item:selected {{
    background-color: {t["primary_container"]};
    color: {t["on_primary_container"]};
}}
QProgressBar {{
    background-color: {t["surface_container_high"]};
    border: none;
    border-radius: 4px;
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {t["primary"]};
    border-radius: 4px;
}}

QFrame#BottomNav {{
    background-color: {t['surface']};
    border-top: 1px solid {t['surface_container_high']};
}}
QPushButton#NavTab {{
    background-color: transparent;
    color: {t['on_surface_variant']};
    border: none;
    border-radius: 18px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    min-height: 36px;
}}
QPushButton#NavTab[active="true"] {{
    background-color: {t['primary_container']};
    color: {t['on_primary_container']};
    font-weight: 700;
}}
"""


class M3Switch(QAbstractButton):
    def __init__(self, tokens: dict, parent=None):
        super().__init__(parent)
        self.tokens = tokens
        self.setCheckable(True)
        self.setFixedSize(QSize(56, 32))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_tokens(self, tokens: dict):
        self.tokens = tokens
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        checked = self.isChecked()
        t = self.tokens
        track = QColor(t["primary"]) if checked else QColor(t["surface_container_high"])
        border = QColor(t["primary"]) if checked else QColor(t["outline"])
        p.setBrush(track)
        p.setPen(border)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), (h - 2) / 2, (h - 2) / 2)
        thumb_d = 24 if checked else 18
        thumb_y = (h - thumb_d) / 2
        thumb_x = (w - thumb_d - 4) if checked else 7
        thumb = QColor(t["on_primary"]) if checked else QColor(t["on_surface_variant"])
        p.setBrush(thumb)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(thumb_x, thumb_y, thumb_d, thumb_d))
        p.end()


def get_work_dir() -> str:
    for candidate in (
        "/storage/emulated/0/Download/OTAFirmwareMerger",
        os.path.join(os.path.expanduser("~"), "OTAFirmwareMerger_work"),
    ):
        try:
            os.makedirs(candidate, exist_ok=True)
            test_f = os.path.join(candidate, ".write_test")
            with open(test_f, "w") as fp:
                fp.write("ok")
            os.remove(test_f)
            return candidate
        except OSError:
            continue
    return APP_DIR


def get_native_lib_dir() -> str:
    try:
        with open("/proc/self/maps", "r") as fp:
            for line in fp:
                if "/lib/arm64/" in line and ".so" in line:
                    d = os.path.dirname(line.strip().split()[-1])
                    if os.path.isdir(d):
                        return d
    except OSError:
        pass
    local = os.path.join(APP_DIR, "libs", "arm64-v8a")
    return local if os.path.isdir(local) else ""


def find_bin(name: str) -> str:
    lib_dir = get_native_lib_dir()
    if lib_dir:
        cand = os.path.join(lib_dir, f"lib{name}.so")
        if os.path.isfile(cand):
            return cand
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Bundled binary lib{name}.so not found in {lib_dir or 'PATH'}")


def getprop(key: str, default: str = "") -> str:
    try:
        val = subprocess.check_output(["getprop", key], text=True, timeout=2).strip()
        return val or default
    except Exception:
        return default


def extract_model_from_tag(tag: str) -> str:
    m = re.match(r"^([A-Za-z0-9]+)_", tag.strip())
    if m:
        return m.group(1)
    return getprop("ro.product.model", "UNKNOWN")


def load_tracker_state(work_dir: str) -> dict:
    path = os.path.join(work_dir, "ota_tracker.json")
    state = {
        "model": getprop("ro.product.model", ""),
        "ota_version": getprop("ro.build.version.ota", ""),
        "display_version": getprop("ro.build.display.id", ""),
        "carrier": getprop("ro.build.oplus_nv_id", "01000100"),
        "region": "EU",
        "daily_check": False,
        "auto_download": False,
        "wifi_only": True,
        "last_found_version": "",
        "last_found_url": "",
    }
    if os.path.isfile(path):
        try:
            saved = json.load(open(path, "r"))
            state.update(saved)
        except Exception:
            pass
    rel = os.path.join(work_dir, "release_info.txt")
    if os.path.isfile(rel) and not state.get("display_version"):
        try:
            for line in open(rel):
                if line.startswith("tag="):
                    tag = line[4:].strip()
                    state["display_version"] = tag
                    state["model"] = extract_model_from_tag(tag)
        except Exception:
            pass
    return state


def save_tracker_state(work_dir: str, state: dict):
    path = os.path.join(work_dir, "ota_tracker.json")
    with open(path, "w") as fp:
        json.dump(state, fp, indent=2)


def _read_asn1_tlv(data: bytes, idx: int):
    tag = data[idx]
    idx += 1
    length = data[idx]
    idx += 1
    if length & 0x80:
        nbytes = length & 0x7F
        length = int.from_bytes(data[idx:idx + nbytes], "big")
        idx += nbytes
    return tag, data[idx:idx + length], idx + length


def _parse_rsa_pem(pem_path: str):
    with open(pem_path, "r") as fp:
        lines = [l.strip() for l in fp if l.strip() and not l.startswith("-----")]
    der = base64.b64decode("".join(lines))
    _, seq, _ = _read_asn1_tlv(der, 0)
    pos = 0
    ints = []
    while pos < len(seq):
        tag, val, pos = _read_asn1_tlv(seq, pos)
        if tag == 0x02:
            ints.append(int.from_bytes(val, "big"))
        elif tag == 0x04 and len(ints) == 1:
            _, inner, _ = _read_asn1_tlv(val, 0)
            ipos = 0
            ints = []
            while ipos < len(inner):
                itag, ival, ipos = _read_asn1_tlv(inner, ipos)
                if itag == 0x02:
                    ints.append(int.from_bytes(ival, "big"))
            break
    return ints[1], ints[3]


def rsa_sign_sha256_digest(pem_path: str, digest_bytes: bytes) -> bytes:
    n, d = _parse_rsa_pem(pem_path)
    k = (n.bit_length() + 7) // 8
    prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    t = prefix + digest_bytes
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")














class PickerRowDelegate(QStyledItemDelegate):
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

        painter.restore()

class TouchScrollFilter(QObject):
    def __init__(self, scroll_widget, tap_callback=None):
        super().__init__(scroll_widget)
        self.sw = scroll_widget
        self.vp = scroll_widget.viewport()
        self.tap_callback = tap_callback
        self.is_list = isinstance(scroll_widget, QListWidget)
        self.pressed = False
        self.dragging = False
        self.start_y = 0.0
        self.last_y = 0.0
        self.vel = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._coast)
        self._install_targets()

    def _install_targets(self):
        self.vp.installEventFilter(self)
        if not self.is_list and hasattr(self.sw, "widget") and self.sw.widget() is not None:
            root_w = self.sw.widget()
            root_w.installEventFilter(self)
            for child in root_w.findChildren(QWidget):
                if isinstance(child, (QLabel, QFrame)) and not isinstance(child, (QTextEdit, QListWidget, QPushButton, QAbstractButton)):
                    child.installEventFilter(self)

    def _coast(self):
        if abs(self.vel) < 0.5:
            self.timer.stop()
            self.vel = 0.0
            return
        vb = self.sw.verticalScrollBar()
        old = vb.value()
        vb.setValue(int(round(old - self.vel)))
        if vb.value() == old:
            self.timer.stop()
            self.vel = 0.0
            return
        self.vel *= 0.92

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self.timer.stop()
            self.vel = 0.0
            self.pressed = True
            self.dragging = False
            self.start_y = ev.globalPosition().y()
            self.last_y = self.start_y
            return True if self.is_list else False

        if t == QEvent.Type.MouseMove and self.pressed:
            y = ev.globalPosition().y()
            if not self.dragging and abs(y - self.start_y) > 10.0:
                self.dragging = True
            if self.dragging:
                dy = y - self.last_y
                self.last_y = y
                self.vel = 0.65 * dy + 0.35 * self.vel
                vb = self.sw.verticalScrollBar()
                vb.setValue(int(round(vb.value() - dy)))
                return True
            return True if self.is_list else False

        if t == QEvent.Type.MouseButtonRelease and self.pressed:
            self.pressed = False
            if self.dragging:
                self.dragging = False
                if abs(self.vel) > 1.2:
                    self.timer.start()
                return True
            if self.is_list:
                local_pt = self.vp.mapFromGlobal(ev.globalPosition().toPoint())
                item = self.sw.itemAt(local_pt)
                if item is not None:
                    is_checkbox_hit = (local_pt.x() >= self.vp.width() - 72)
                    if self.tap_callback is not None:
                        self.tap_callback(item, is_checkbox_hit)
                    else:
                        item.setSelected(not item.isSelected())
                return True
            return False
        return False


def configure_smooth_scroll(scroll_widget, tap_callback=None):
    try:
        QScroller.ungrabGesture(scroll_widget.viewport())
    except Exception:
        pass
    try:
        scroll_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_widget.horizontalScrollBar().setEnabled(False)
    except Exception:
        pass
    try:
        if hasattr(scroll_widget, "setVerticalScrollMode"):
            scroll_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        if hasattr(scroll_widget, "setDragEnabled"):
            scroll_widget.setDragEnabled(False)
    except Exception:
        pass
    if not hasattr(scroll_widget, "_touch_scroll_filter"):
        scroll_widget._touch_scroll_filter = TouchScrollFilter(scroll_widget, tap_callback=tap_callback)


class CreditsDialog(QDialog):
    def __init__(self, parent, qss: str, primary_hex: str):
        super().__init__(parent)
        self.setWindowTitle("Credits & Open Source")
        self.setStyleSheet(qss)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 40, 16, 28)
        layout.setSpacing(12)

        t = QLabel("Credits & Source Code")
        t.setObjectName("AppTitle")
        layout.addWidget(t)

        note = QLabel(
            f"OTA FW Merger v{APP_VERSION} • Published by {APP_PUBLISHER}\n"
            "Built with AI assistance and tested on-device on a rooted North American OnePlus 15."
        )
        note.setObjectName("AppSubtitle")
        note.setWordWrap(True)
        layout.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        configure_smooth_scroll(scroll)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(8)

        for author, desc, url in CREDITS_LIST:
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(3)

            lbl = QLabel(f'<b>{author}</b> &nbsp; <a style="color:{primary_hex};" href="{url}">GitHub / Source</a>')
            lbl.setObjectName("TileTitle")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setOpenExternalLinks(False)
            lbl.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))

            sub = QLabel(desc)
            sub.setObjectName("TileSub")
            sub.setWordWrap(True)

            cl.addWidget(lbl)
            cl.addWidget(sub)
            il.addWidget(card)

        il.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("PrimaryBtn")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class MobilePathPicker(QDialog):
    def __init__(
        self, parent, title: str, qss: str, start_dir: str = "/storage/emulated/0",
        dirs_only: bool = False, ext_filter: str = ".zip", multi: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(qss)
        self.dirs_only = dirs_only
        self.ext_filter = ext_filter.lower()
        self.multi = multi
        self.current_dir = start_dir if os.path.isdir(start_dir) else "/storage/emulated/0"
        self.selected_paths = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 40, 16, 28)
        layout.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("AppTitle")
        layout.addWidget(title_lbl)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(10)
        self.up_btn = QPushButton("Up")
        self.up_btn.setFixedWidth(78)
        self.up_btn.clicked.connect(self.go_up)
        nav_row.addWidget(self.up_btn)

        self.path_label = QLabel()
        self.path_label.setObjectName("AppSubtitle")
        self.path_label.setWordWrap(True)
        nav_row.addWidget(self.path_label, 1)
        layout.addLayout(nav_row)

        self.list_widget = QListWidget()
        _tok = build_m3_tokens(QApplication.instance()) if QApplication.instance() else {}
        self.list_widget.setItemDelegate(PickerRowDelegate(
            self.list_widget,
            accent_hex=_tok.get("primary", "#D32F2F"),
            outline_hex=_tok.get("outline", "#6E6668"),
            text_hex=_tok.get("on_surface", "#F4EFF0"),
        ))
        _tok = build_m3_tokens(QApplication.instance()) if QApplication.instance() else {}
        self.list_widget.setItemDelegate(PickerRowDelegate(
            self.list_widget,
            accent_hex=_tok.get("primary", "#D32F2F"),
            outline_hex=_tok.get("outline", "#6E6668"),
            text_hex=_tok.get("on_surface", "#F4EFF0"),
        ))
        if not dirs_only:
            mode = QAbstractItemView.SelectionMode.MultiSelection if multi else QAbstractItemView.SelectionMode.SingleSelection
            self.list_widget.setSelectionMode(mode)
        configure_smooth_scroll(self.list_widget, tap_callback=self.on_item_tapped)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_label = "Select This Folder" if dirs_only else (f"Add Selected {ext_filter.upper()}" if multi else "Select File")
        self.ok_btn = QPushButton(ok_label)
        self.ok_btn.setObjectName("PrimaryBtn")
        self.ok_btn.clicked.connect(self.confirm_selection)
        btn_row.addWidget(self.ok_btn, 1)
        layout.addLayout(btn_row)
        self.refresh()

    def refresh(self):
        self.path_label.setText(self.current_dir)
        self.list_widget.clear()
        try:
            entries = sorted(os.listdir(self.current_dir), key=lambda s: s.lower())
        except OSError as e:
            self.list_widget.addItem(f"(Cannot read folder: {e})")
            return
        dirs, files = [], []
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(self.current_dir, name)
            if os.path.isdir(full):
                dirs.append((name, full))
            elif not self.dirs_only and (not self.ext_filter or name.lower().endswith(self.ext_filter)):
                files.append((name, full))
        for name, full in dirs:
            item = QListWidgetItem(f"[DIR]   {name}")
            item.setData(Qt.ItemDataRole.UserRole, ("dir", full))
            self.list_widget.addItem(item)
        for name, full in files:
            ext_tag = (os.path.splitext(name)[1].lstrip(".").upper() or "FILE")[:6]
            item = QListWidgetItem(f"[{ext_tag}]   {name}")
            item.setData(Qt.ItemDataRole.UserRole, ("file", full))
            self.list_widget.addItem(item)

    def go_up(self):
        parent = os.path.dirname(self.current_dir.rstrip("/"))
        if parent and os.path.isdir(parent):
            self.current_dir = parent
            self.refresh()

    def on_item_tapped(self, item: QListWidgetItem, is_checkbox_hit: bool = False):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) < 2:
            return
        kind, path = data[0], data[1]
        if kind == "dir" and not is_checkbox_hit:
            self.current_dir = path
            self.refresh()
            return
        if self.list_widget.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection or (self.dirs_only and kind == "dir"):
            was_sel = item.isSelected()
            self.list_widget.clearSelection()
            item.setSelected(not was_sel)
        else:
            item.setSelected(not item.isSelected())

    def on_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data[0] == "dir":
            self.current_dir = data[1]
            self.refresh()

    def confirm_selection(self):
        checked_dirs = [
            item.data(Qt.ItemDataRole.UserRole)[1]
            for item in self.list_widget.selectedItems()
            if isinstance(item.data(Qt.ItemDataRole.UserRole), tuple) and item.data(Qt.ItemDataRole.UserRole)[0] == "dir"
        ]
        checked_files = [
            item.data(Qt.ItemDataRole.UserRole)[1]
            for item in self.list_widget.selectedItems()
            if isinstance(item.data(Qt.ItemDataRole.UserRole), tuple) and item.data(Qt.ItemDataRole.UserRole)[0] == "file"
        ]
        if self.dirs_only:
            self.selected_paths = [checked_dirs[0]] if checked_dirs else [self.current_dir]
        else:
            picked = checked_files + checked_dirs
            if not picked:
                QMessageBox.information(self, "Select File", f"Check a {self.ext_filter} file or folder first.")
                return
            self.selected_paths = picked
        self.accept()


class RequiredImagesDialog(QDialog):
    def __init__(self, parent, qss: str, existing: dict):
        super().__init__(parent)
        self.setWindowTitle("Required Recovery Images")
        self.setStyleSheet(qss)
        self.qss = qss
        self.paths = dict(existing)
        self.labels = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 40, 16, 28)
        layout.setSpacing(12)

        t = QLabel("Required Regional Images")
        t.setObjectName("AppTitle")
        layout.addWidget(t)

        sub = QLabel("Select my_company.img, my_preload.img, and system_dlkm_oki.img for OOS_FILES_HERE.")
        sub.setObjectName("AppSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        auto_btn = QPushButton("Auto-Find All 3 From a Folder")
        auto_btn.clicked.connect(self.auto_find_from_folder)
        layout.addWidget(auto_btn)

        self.pull_root_btn = QPushButton("Auto-Pull All 3 From Device (Root)")
        self.pull_root_btn.setObjectName("PrimaryBtn")
        self.pull_root_btn.clicked.connect(self.auto_pull_from_device_root)
        layout.addWidget(self.pull_root_btn)

        for req in REQUIRED_HYBRID_IMGS:
            card = QFrame()
            card.setObjectName("Card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(10)
            info = QVBoxLayout()
            info.setSpacing(2)
            nl = QLabel(req)
            nl.setObjectName("TileTitle")
            pl = QLabel(self._fmt_path(self.paths.get(req, "")))
            pl.setObjectName("TileSub")
            pl.setWordWrap(True)
            info.addWidget(nl)
            info.addWidget(pl)
            cl.addLayout(info, 1)
            self.labels[req] = pl
            pb = QPushButton("Pick")
            pb.setFixedWidth(78)
            pb.clicked.connect(lambda _=False, r=req: self.pick_one(r))
            cl.addWidget(pb)
            layout.addWidget(card)

        layout.addStretch(1)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cb = QPushButton("Cancel")
        cb.clicked.connect(self.reject)
        btn_row.addWidget(cb)
        ok = QPushButton("Confirm Images")
        ok.setObjectName("PrimaryBtn")
        ok.clicked.connect(self.validate_and_accept)
        btn_row.addWidget(ok, 1)
        layout.addLayout(btn_row)

    def _fmt_path(self, p: str) -> str:
        return p if p and os.path.isfile(p) else "Not selected"

    def pick_one(self, req_name: str):
        dlg = MobilePathPicker(self, f"Select {req_name}", self.qss, "/storage/emulated/0",
                               dirs_only=False, ext_filter=".img", multi=False)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_paths:
            self.paths[req_name] = dlg.selected_paths[0]
            self.labels[req_name].setText(self._fmt_path(self.paths[req_name]))

    def auto_find_from_folder(self):
        dlg = MobilePathPicker(self, "Select Folder Containing .img Files", self.qss, "/storage/emulated/0", dirs_only=True)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_paths:
            folder = dlg.selected_paths[0]
            found = 0
            for req in REQUIRED_HYBRID_IMGS:
                cand = os.path.join(folder, req)
                if os.path.isfile(cand):
                    self.paths[req] = cand
                    self.labels[req].setText(cand)
                    found += 1
            if found < len(REQUIRED_HYBRID_IMGS):
                missing = [r for r in REQUIRED_HYBRID_IMGS if not os.path.isfile(self.paths.get(r, ""))]
                QMessageBox.information(self, "Partial Match", f"Found {found}/3. Still need: {', '.join(missing)}")

    def auto_pull_from_device_root(self):
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
                QMessageBox.warning(self, "Partial Pull", f"Pulled: {', '.join(pulled)}\nNot found on device: {', '.join(missing)}")
            else:
                QMessageBox.warning(self, "Pull Failed", "Could not find my_company, my_preload, or system_dlkm_oki on this device (check root permission).")
        finally:
            self.pull_root_btn.setEnabled(True)
            self.pull_root_btn.setText("Auto-Pull All 3 From Device (Root)")

    def validate_and_accept(self):
        missing = [r for r in REQUIRED_HYBRID_IMGS if not os.path.isfile(self.paths.get(r, ""))]
        if missing:
            QMessageBox.warning(self, "Missing Files", f"Please select: {', '.join(missing)}")
            return
        self.accept()



def find_su_bin() -> str:
    for cand in (
        "/data/adb/ksu/bin/su",
        "/data/adb/ap/bin/su",
        "/system/bin/su",
        "/system/xbin/su",
        "/sbin/su",
        "/debug_ramdisk/su",
    ):
        if os.path.exists(cand):
            return cand
    return shutil.which("su") or ""


def capture_system_update_urls_root():
    su = find_su_bin()
    if not su:
        return [], "No su binary found (Magisk / KernelSU Next root required)."
    probe = (
        "grep -rhoE 'https?://(android\.googleapis\.com/packages/ota-api/package/[^<>[:space:]&]+|[^<>[:space:]&]*allawn[^<>[:space:]&]*\.zip[^<>[:space:]&]*)' "
        "/data/data/com.google.android.gms/shared_prefs/ "
        "/data/data/com.oplus.ota/shared_prefs/ "
        "/data/data/com.oneplus.opbackup/shared_prefs/ 2>/dev/null; "
        "logcat -d 2>/dev/null | grep -oE 'https?://(android\.googleapis\.com/packages/ota-api/package/[^<>[:space:]&]+|[^<>[:space:]&]*allawn[^<>[:space:]&]*\.zip[^<>[:space:]&]*)' | tail -n 30; "
        "ls -1 /data/ota_package/*.zip 2>/dev/null || true"
    )
    try:
        proc = subprocess.run([su, "-c", probe], capture_output=True, text=True, timeout=20)
        raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
        seen, urls = set(), []
        for line in raw.splitlines():
            s = line.strip().rstrip(".,;)]}")
            if not s or s in seen:
                continue
            if s.startswith("http://") or s.startswith("https://") or s.startswith("/data/ota_package/"):
                seen.add(s)
                urls.append(s)
        return urls, raw.strip()
    except Exception as e:
        return [], f"Root capture error: {e}"


class OtaCheckWorker(QThread):
    log = Signal(str)
    found = Signal(str, str)
    done = Signal(str)

    def __init__(self, state: dict, work_dir: str, root_only: bool = False):
        super().__init__()
        self.state = dict(state)
        self.work_dir = work_dir
        self.root_only = root_only

    def _run_oplus(self, updater: str, model: str, query_ver: str, zones: list, carrier: str):
        out = ""
        for z in zones:
            cmd = [updater, query_ver, f"--model={model}", f"--region={z}"]
            if carrier:
                cmd.append(f"--carrier={carrier}")
            self.log.emit(f"Querying OPLUS server ({z}) with base {query_ver}...\n")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            self.log.emit(out + "\n")
            if re.search(r"https?://[^\s\x22\x27<>]+\.zip", out):
                break
        return out

    def run(self):
        try:
            model = self.state.get("model", "").strip()
            ota_ver = self.state.get("ota_version", "").strip() or self.state.get("display_version", "").strip()
            disp_ver = self.state.get("display_version", "").strip()
            carrier = self.state.get("carrier", "").strip()
            root_cap = bool(self.state.get("root_capture", False)) or self.root_only
            force_latest = bool(self.state.get("force_latest", False))

            if root_cap:
                self.log.emit("\n=== Capturing System Update URLs via Root ===\n")
                urls, raw = capture_system_update_urls_root()
                if urls:
                    for u in urls:
                        self.log.emit(f"Captured: {u}\n")
                    picked = urls[-1]
                    tag = f"{model}_GOTA_captured" if model else "GOTA_captured"
                    if force_latest or picked != self.state.get("last_found_url", ""):
                        self.found.emit(tag, picked)
                        self.done.emit(f"Captured System Update URL ({len(urls)} found).")
                        return
                    self.done.emit("System Update URL already captured (enable Force Latest to re-download).")
                    return
                self.log.emit(f"No System Update URL found in GMS/OPLUS prefs or logcat.\n{raw}\n")
                if self.root_only:
                    self.done.emit("No pending System Update URL found. Open Settings -> Software Update first, then retry.")
                    return

            if not model or not ota_ver:
                self.done.emit("No device model/version tracked yet. Run a merge first.")
                return

            updater = find_bin("oplus_updater")
            m_up = model.upper()
            v_up = ota_ver.upper()
            if m_up.startswith(("PLK", "PJD", "PJZ", "PHB", "PJA", "PGP", "PKG", "PKR", "PKX")) or "(CN" in v_up:
                zones = ["CN"]
            elif m_up.endswith("IN") or "(IN" in v_up:
                zones = ["IN", "EU"]
            else:
                zones = ["EU", "IN"]

            self.log.emit(f"\n=== Checking official OPLUS OTA for {model} ===\n")
            out = self._run_oplus(updater, model, ota_ver, zones, carrier)
            urls = re.findall(r"https?://[^\s\x22\x27<>]+\.zip[^\s\x22\x27<>]*", out)

            if not urls and force_latest:
                fallback_ver = f"{model}_11.A.01_0001_202001010000"
                self.log.emit(f"Force Latest enabled — querying baseline {fallback_ver}...\n")
                out = self._run_oplus(updater, model, fallback_ver, zones, carrier)
                urls = re.findall(r"https?://[^\s\x22\x27<>]+\.zip[^\s\x22\x27<>]*", out)

            ver_m = re.search(r'"(?:otaVersion|versionName)"\s*:\s*"([^"]+)"', out)
            if not ver_m:
                ver_m = re.search(rf"({re.escape(model)}_[A-Za-z0-9._()]+)", out)
            new_ver = ver_m.group(1) if ver_m else ""

            if urls and new_ver and new_ver.upper().startswith(model.upper()):
                if force_latest or (new_ver != ota_ver and new_ver != disp_ver):
                    url = urls[0]
                    self.found.emit(new_ver, url)
                    self.done.emit(f"Update available for {model}: {new_ver}")
                    return
            self.done.emit(f"Up to date for {model} ({ota_ver}).")
        except Exception as e:
            self.log.emit(f"OTA check error: {e}\n")
            self.done.emit(f"Check failed: {e}")







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


class DumpWorker(QThread):
    log = Signal(str)
    finished = Signal(int, str, str)

    def __init__(self, inputs, fake_ota=False, recovery_zip=False, recovery_mode="regional", extra_imgs=None, stock_overrides=None, work_dir=None):
        super().__init__()
        self.inputs = inputs
        self.fake_ota = fake_ota
        self.recovery_zip = recovery_zip
        self.recovery_mode = recovery_mode or 'regional'
        self.stock_overrides = dict(stock_overrides or {})
        self.last_expected_hashes = {}
        self.ota_meta = {'source': 'fallback', 'device': '', 'model': '', 'fingerprint': '', 'ota_version': '', 'ota_type': 'AB', 'super_group': '', 'logical_partitions': []}
        self.extra_imgs = extra_imgs or {}
        self.work_dir = work_dir or get_work_dir()

    def _run_cmd(self, cmd, cwd=None, allow_root_fallback=False):
        self.log.emit(f"$ {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=cwd or self.work_dir, text=True,
        )
        out_lines = []
        for line in proc.stdout:
            out_lines.append(line)
            self.log.emit(line)
        rc = proc.wait()
        if rc != 0 and allow_root_fallback and shutil.which("su"):
            joined = "".join(out_lines)
            if "CANNOT LINK EXECUTABLE" in joined or "not found" in joined or rc in (126, 127):
                self.log.emit("Retrying via su...\n")
                su_cmd = ["su", "-c", " ".join(f'"{c}"' for c in cmd)]
                proc2 = subprocess.Popen(
                    su_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=cwd or self.work_dir, text=True,
                )
                for line in proc2.stdout:
                    self.log.emit(line)
                rc = proc2.wait()
        if rc != 0:
            raise RuntimeError(f"Command failed (exit {rc}): {cmd[0]}")

    def _download_or_copy(self, src: str, out_path: str):
        if src.startswith("http://") or src.startswith("https://"):
            self.log.emit(f"Downloading OTA: {src}\n")
            aria2c = find_bin("aria2c")
            self._run_cmd([
                aria2c, "-x", "16", "-s", "16",
                "--max-connection-per-server=16", "--file-allocation=trunc",
                "--continue=true", "--auto-file-renaming=false",
                "--summary-interval=5", "--retry-wait=10",
                "--timeout=60", "--connect-timeout=60",
                "--max-tries=0", "--lowest-speed-limit=1K",
                "--check-certificate=false",
                src, "-d", os.path.dirname(out_path), "-o", os.path.basename(out_path),
            ])
        else:
            self.log.emit(f"Using local OTA file: {src}\n")
            if not os.path.isfile(src):
                raise FileNotFoundError(f"File not found: {src}")
            shutil.copy2(src, out_path)

    def _read_zip_meta(self, zf: zipfile.ZipFile):
        ver_name, ota_ver = "unknown", ""
        try:
            meta = zf.read("META-INF/com/android/metadata").decode("utf-8", errors="ignore")
            for line in meta.splitlines():
                if line.startswith("version_name="):
                    ver_name = line[len("version_name="):].strip()
                elif line.startswith("ota_version=") or line.startswith("post-build-incremental="):
                    if not ota_ver:
                        ota_ver = line.split("=", 1)[1].strip()
        except KeyError:
            pass
        return ver_name, ota_ver

    def _repack_payload(self, images_dir: str, out_dir: str):
        delta_gen = find_bin("delta_generator")
        key_path = os.path.join(APP_DIR, "key", "testkey.key")
        imgs = sorted(
            os.path.join(images_dir, f) for f in os.listdir(images_dir)
            if f.endswith(".img") and os.path.isfile(os.path.join(images_dir, f))
        )
        if not imgs:
            raise RuntimeError("No .img files found to repack!")
        names = ":".join(os.path.splitext(os.path.basename(p))[0] for p in imgs)
        files = ":".join(imgs)
        os.makedirs(out_dir, exist_ok=True)
        unsigned = os.path.join(out_dir, "unsigned-payload.bin")
        sig_meta = os.path.join(out_dir, "sig_metadata.bin")
        sig_hash = os.path.join(out_dir, "sig_hash.bin")
        signed_meta = os.path.join(out_dir, "signed_metadata.bin")
        signed_hash = os.path.join(out_dir, "signed_hash.bin")
        final_payload = os.path.join(out_dir, "payload.bin")
        props_file = os.path.join(out_dir, "payload_properties.txt")

        self._run_cmd([delta_gen, f"-out_file={unsigned}", f"-partition_names={names}", f"-new_partitions={files}"])
        self._run_cmd([delta_gen, f"--in_file={unsigned}", "-signature_size=256",
                       f"-out_metadata_hash_file={sig_meta}", f"-out_hash_file={sig_hash}"])
        for src_digest, dst_sig in ((sig_hash, signed_hash), (sig_meta, signed_meta)):
            with open(src_digest, "rb") as fp:
                dig = fp.read()
            with open(dst_sig, "wb") as fp:
                fp.write(rsa_sign_sha256_digest(key_path, dig))
        self._run_cmd([delta_gen, f"--in_file={unsigned}", f"--out_file={final_payload}",
                       "--signature_size=256", f"--metadata_signature_file={signed_meta}",
                       f"--payload_signature_file={signed_hash}"])
        self._run_cmd([delta_gen, f"--in_file={final_payload}", f"--properties_file={props_file}"])
        if self.last_expected_hashes:
            fake_hashes = parse_payload_partition_hashes(final_payload)
            self.log.emit("\n=== Verifying Fake OTA payload.bin Hashes Against Merged OTA ===\n")
            bad = []
            ok_cnt = 0
            for pname, exp in sorted(self.last_expected_hashes.items()):
                exp_h = exp.get("new_sha256")
                got_h = (fake_hashes.get(pname) or {}).get("new_sha256")
                if exp_h and got_h:
                    if exp_h.lower() == got_h.lower():
                        ok_cnt += 1
                        self.log.emit(f"  [FAKE OTA OK] {pname} ({got_h[:12]}...)\n")
                    else:
                        bad.append(pname)
                        self.log.emit(f"  [FAKE OTA MISMATCH] {pname}: {got_h[:12]}... != {exp_h[:12]}...\n")
            self.log.emit(f"Fake OTA payload hash verification: {ok_cnt}/{ok_cnt + len(bad)} matched.\n")
            if bad:
                raise RuntimeError("Fake OTA payload hash mismatch for: " + ", ".join(bad))
        return final_payload

    def _build_recovery_zip(self, ota_dir: str, out_dir: str, safe_name: str):
        tpl_zip = os.path.join(APP_DIR, "template", "regional_hybrid_template.zip")
        if not os.path.isfile(tpl_zip):
            raise FileNotFoundError(f"Bundled Regional Hybrid template not found at {tpl_zip}")
        for req in REQUIRED_HYBRID_IMGS:
            p = self.extra_imgs.get(req, "")
            if not p or not os.path.isfile(p):
                raise FileNotFoundError(f"Missing required image: {req}")

        zip_path = os.path.join(out_dir, f"RegionalHybrid_{safe_name}.zip")
        self.log.emit(f"Building custom recovery flashable ZIP:\n  {zip_path}\n")
        override_names = set(REQUIRED_HYBRID_IMGS)
        img_count = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zout:
            with zipfile.ZipFile(tpl_zip, "r") as ztpl:
                for info in ztpl.infolist():
                    if info.is_dir():
                        continue
                    zout.writestr(info, ztpl.read(info.filename))
            for fn in sorted(f for f in os.listdir(ota_dir) if f.endswith(".img") and os.path.isfile(os.path.join(ota_dir, f))):
                if fn in override_names:
                    continue
                self.log.emit(f"  + OOS_FILES_HERE/{fn}\n")
                zout.write(os.path.join(ota_dir, fn), f"OOS_FILES_HERE/{fn}")
                img_count += 1
            for req in REQUIRED_HYBRID_IMGS:
                src_p = self.extra_imgs[req]
                self.log.emit(f"  + OOS_FILES_HERE/{req}\n")
                zout.write(src_p, f"OOS_FILES_HERE/{req}")
                img_count += 1
        self.log.emit(f"Recovery Flashable ZIP built ({img_count} images in OOS_FILES_HERE):\n  {zip_path}\n")
        return zip_path





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
                f"device={self.ota_meta.get('device') or '?'}, group={self.ota_meta.get('super_group') or 'auto'}\n"
            )
        except Exception as e:
            self.log.emit(f"Note: Could not probe live device metadata via root ({e}); using fallback.\n")

    def _dump_device_partitions(self, ota_dir: str, hybrid_preserved: str):
        if not shutil.which("su"):
            raise RuntimeError("Root (su) is required to dump base images from the device.")
        shutil.rmtree(ota_dir, ignore_errors=True)
        os.makedirs(ota_dir, exist_ok=True)
        os.makedirs(hybrid_preserved, exist_ok=True)

        self._probe_device_meta_root()
        slot = self._su_read("getprop ro.boot.slot_suffix")
        model = self.ota_meta.get("model") or self.ota_meta.get("device") or "device"
        self.log.emit(f"Root Full System Dump: model={model}, active_slot={slot or '(non-A/B)'}\n")

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
                self.log.emit(f"  * Using stock override for {fn} ({os.path.basename(src_override)})\n")
                shutil.copy2(src_override, dst)
                dumped += 1
            else:
                blk = targets[part]
                self.log.emit(f"  + Dumping {part} <- {blk}\n")
                rc = subprocess.run(
                    ["su", "-c", f'dd if="{blk}" of="{dst}" bs=4M 2>/dev/null || dd if="{blk}" of="{dst}" bs=1M'],
                    capture_output=True, text=True,
                ).returncode
                if rc == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    dumped += 1
                else:
                    self.log.emit(f"  ! Skipped {part} (unreadable or empty)\n")
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
                self.log.emit(f"  * Adding extra stock override {orig_fn}\n")
                shutil.copy2(src_override, dst)
                dumped += 1

        self.log.emit(f"Root full system dump complete: {dumped} base partition images ready.\n")
        return f"device-{model}"

    def _verify_partition_hashes(self, img_dir: str, part_hashes: dict, phase: str = "new"):
        """Verify SHA-256 of partition images against payload.bin old_partition_info or new_partition_info."""
        if not part_hashes:
            return
        key_h = "old_sha256" if phase == "old" else "new_sha256"
        key_s = "old_size" if phase == "old" else "new_size"
        label = "Pre-Merge Base" if phase == "old" else "Post-Merge OTA"
        self.log.emit(f"\n=== Internal SHA-256 Hash Check ({label}) ===\n")
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
                    self.log.emit(f"  [HASH OK] {pname}.img ({got_h[:12]}..., trimmed raw block {actual_sz} -> {exp_s} B)\n")
                else:
                    self.log.emit(f"  [HASH OK] {pname}.img ({got_h[:12]}...)\n")
            else:
                self.log.emit(f"  [HASH MISMATCH] {pname}.img: got {got_h[:12]}..., expected {exp_h[:12]}...\n")
                mismatches.append(pname)
        self.log.emit(f"Hash check summary ({label}): {checked - len(mismatches)}/{checked} matched.\n")
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
                            self.log.emit(f"  * Auto-pulled EDL-only {dlkm_fn} from live device ({blk})\n")
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
        self.log.emit(f"Building Universal {label} ZIP ({files_dir}, metadata={meta.get('source', 'fallback')}):\n  {zip_path}\n")
        if meta.get("model") or meta.get("device"):
            self.log.emit(f"  * Target: {meta.get('model') or ''} ({meta.get('device') or ''}) | super group: {meta.get('super_group') or 'auto'}\n")
        self.log.emit(f"  * Physical partitions: {len(phys_early) + len(phys_other)} | Logical (super): {len(logical_parts)}\n")

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
        meta_env = "\n".join(env_lines) + "\n"
        meta_json = json.dumps(meta, indent=2) + "\n"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zout:
            zi_bin = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
            zi_bin.external_attr = 0o100755 << 16
            zout.writestr(zi_bin, build_universal_update_binary(files_dir=files_dir, label=label).encode("utf-8"))
            zout.writestr("META-INF/com/google/android/updater-script", f"# {label} Universal ColorOS / OxygenOS Recovery Flasher\n")
            zout.writestr("META-INF/hybrid_meta.env", meta_env.encode("utf-8"))
            zout.writestr("META-INF/hybrid_meta.json", meta_json.encode("utf-8"))

            zi_sh = zipfile.ZipInfo(sh_name)
            zi_sh.external_attr = 0o100755 << 16
            zout.writestr(zi_sh, build_universal_fastboot_sh(phys_early, phys_other, logical_parts, meta, files_dir=files_dir, label=label).encode("utf-8"))
            zout.writestr(bat_name, build_universal_fastboot_bat(phys_early, phys_other, logical_parts, meta, files_dir=files_dir, label=label).encode("utf-8"))

            for fn in all_names:
                if fn.lower() in override_map:
                    req_fn, src_p = override_map[fn.lower()]
                    self.log.emit(f"  + {files_dir}/{req_fn} (preserved/override)\n")
                    zout.write(src_p, f"{files_dir}/{req_fn}")
                else:
                    self.log.emit(f"  + {files_dir}/{fn}\n")
                    zout.write(os.path.join(ota_dir, fn), f"{files_dir}/{fn}")

        self.log.emit(f"{label} Flashable ZIP built ({len(all_names)} images in {files_dir}):\n  {zip_path}\n")
        return zip_path


    def run(self):
        tag, ota_ver = "", ""
        try:
            wd = self.work_dir
            ota_dir = os.path.join(wd, "ota")
            out_dir = os.path.join(wd, "output")
            meta_dir = os.path.join(wd, "META-INF")
            ota_zip = os.path.join(wd, "ota.zip")
            payload_work = os.path.join(wd, "payload_working.bin")
            ota_extractor = find_bin("ota_extractor")

            self.log.emit(f"\n=== Starting merge (workspace: {wd}) ===\n")
            full_input = self.inputs[0]
            hybrid_preserved = os.path.join(wd, "hybrid_preserved")
            shutil.rmtree(hybrid_preserved, ignore_errors=True)
            hyb_mode, _, hyb_meta = detect_hybrid_zip(full_input)
            used_device_dump = (full_input.strip().lower() == "device://dump")

            if used_device_dump:
                tag = self._dump_device_partitions(ota_dir, hybrid_preserved)
                body = f"[{tag}](device://dump) (root live dump)"
            elif os.path.isdir(full_input):
                self.log.emit(f"Using pre-extracted FULL OTA directory: {full_input}\n")
                shutil.rmtree(ota_dir, ignore_errors=True)
                shutil.copytree(full_input, ota_dir)
                tag = f"folder-{os.path.basename(full_input.rstrip('/'))}"
                body = f"[{tag}]({full_input}) (pre-extracted)"
            elif hyb_mode in ("regional", "super"):
                folder_key = "COS_FILES_HERE" if hyb_mode == "super" else "OOS_FILES_HERE"
                label_name = "SuperHybrid" if hyb_mode == "super" else "RegionalHybrid"
                self.log.emit(f"Detected {label_name} base ZIP: {os.path.basename(full_input)}\n")
                self.log.emit(f"Extracting {folder_key}/*.img directly (no duplicate copy)...\n")
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
                        norm = info.filename.replace("\\", "/")
                        parts = norm.split("/")
                        if len(parts) >= 2 and parts[-2].upper() == folder_key and parts[-1].lower().endswith(".img"):
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
                                        self.log.emit(f"  * Auto-preserved {req} from {folder_key}\n")
                self.log.emit(f"Extracted {extracted} base partition images from {label_name} archive.\n")
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
                        self.log.emit(f"Parsed initial ZIP metadata: device={self.ota_meta['device']}, group={self.ota_meta.get('super_group') or 'auto'}\n")
                    zf.extract("payload.bin", wd)
                shutil.move(os.path.join(wd, "payload.bin"), payload_work)
                os.remove(ota_zip)
                body = f"[{tag}]({full_input}) (full)"
                shutil.rmtree(ota_dir, ignore_errors=True)
                os.makedirs(ota_dir, exist_ok=True)
                self._run_cmd([ota_extractor, payload_work, "-o", ota_dir], allow_root_fallback=True)
                os.remove(payload_work)

            for inc in self.inputs[1:]:
                self._download_or_copy(inc, ota_zip)
                shutil.rmtree(meta_dir, ignore_errors=True)
                with zipfile.ZipFile(ota_zip, "r") as zf:
                    tag, ota_ver = self._read_zip_meta(zf)
                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver
                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver
                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver
                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver
                    inc_m = extract_ota_zip_metadata(zf)
                    for mk in ("device", "fingerprint", "ota_version", "super_group", "logical_partitions"):
                        if inc_m.get(mk) and not self.ota_meta.get(mk):
                            self.ota_meta[mk] = inc_m[mk]
                    if ota_ver:
                        self.ota_meta["ota_version"] = ota_ver
                    for member in zf.namelist():
                        if member in ("payload.bin", "payload_properties.txt") or member.startswith("META-INF/"):
                            zf.extract(member, wd)
                shutil.move(os.path.join(wd, "payload.bin"), payload_work)
                os.remove(ota_zip)
                body = f"{body} -> [{tag}]({inc})"
                ota_new = os.path.join(wd, "ota_new")
                shutil.rmtree(ota_new, ignore_errors=True)
                os.makedirs(ota_new, exist_ok=True)
                inc_hashes = parse_payload_partition_hashes(payload_work)
                if inc_hashes and used_device_dump:
                    self._verify_partition_hashes(ota_dir, inc_hashes, phase="old")
                self._run_cmd([ota_extractor, payload_work, "--source-dir", ota_dir, "-o", ota_new],
                              allow_root_fallback=True)
                if inc_hashes:
                    self._verify_partition_hashes(ota_new, inc_hashes, phase="new")
                    self.last_expected_hashes = inc_hashes
                shutil.rmtree(ota_dir, ignore_errors=True)
                shutil.move(ota_new, ota_dir)
                os.remove(payload_work)

            with open(os.path.join(wd, "release_info.txt"), "w") as fp:
                fp.write(f"tag={tag}\nbody={body}\n")

            os.makedirs(out_dir, exist_ok=True)
            safe_name = tag.split("(")[0].strip().replace(" ", "_") or "merged_ota"

            if self.recovery_zip:
                # Remove any stale loose .img files in output/ so only the flashable recovery ZIP remains
                for fn in list(os.listdir(out_dir)):
                    if fn.endswith(".img"):
                        try:
                            os.remove(os.path.join(out_dir, fn))
                        except OSError:
                            pass
                self._build_universal_hybrid_zip(ota_dir, out_dir, safe_name, mode=self.recovery_mode)
                for cleanup in (ota_dir, os.path.join(wd, "ota_new"), meta_dir, os.path.join(wd, "hybrid_preserved")):
                    shutil.rmtree(cleanup, ignore_errors=True)
                for tmpf in (ota_zip, payload_work, os.path.join(wd, "payload_properties.txt")):
                    if os.path.isfile(tmpf):
                        try:
                            os.remove(tmpf)
                        except OSError:
                            pass
                self.log.emit("Cleaned up temporary images — output folder contains only the flashable ZIP.\n")
            elif self.fake_ota:
                repack_out = os.path.join(wd, "repack_out")
                shutil.rmtree(repack_out, ignore_errors=True)
                payload_out = self._repack_payload(ota_dir, repack_out)
                shutil.move(payload_out, os.path.join(out_dir, "payload.bin"))
                shutil.rmtree(os.path.join(out_dir, "META-INF"), ignore_errors=True)
                if os.path.isdir(meta_dir):
                    shutil.move(meta_dir, os.path.join(out_dir, "META-INF"))
                props_src = os.path.join(wd, "payload_properties.txt")
                if os.path.isfile(props_src):
                    shutil.move(props_src, os.path.join(out_dir, "payload_properties.txt"))
                zip_path = os.path.join(out_dir, f"{safe_name}.zip")
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
                    for item in ("payload.bin", "payload_properties.txt"):
                        p = os.path.join(out_dir, item)
                        if os.path.isfile(p):
                            zf.write(p, item)
                    meta_out = os.path.join(out_dir, "META-INF")
                    if os.path.isdir(meta_out):
                        for r, _, files in os.walk(meta_out):
                            for fn in files:
                                fp_abs = os.path.join(r, fn)
                                zf.write(fp_abs, os.path.relpath(fp_abs, out_dir))
                for cleanup in (repack_out, ota_dir, os.path.join(out_dir, "META-INF")):
                    shutil.rmtree(cleanup, ignore_errors=True)
                for fn in ("payload.bin", "payload_properties.txt"):
                    p = os.path.join(out_dir, fn)
                    if os.path.isfile(p):
                        os.remove(p)
                self.log.emit(f"Fake OTA built: {zip_path}\n")
            else:
                for fn in os.listdir(ota_dir):
                    shutil.move(os.path.join(ota_dir, fn), os.path.join(out_dir, fn))
                shutil.rmtree(ota_dir, ignore_errors=True)
                self.log.emit(f"Merged firmware ready in: {out_dir}\n")

            self.finished.emit(0, tag, ota_ver)
        except Exception as e:
            self.log.emit(f"\nError: {e}\n")
            self.finished.emit(1, tag, ota_ver)



class DumperGUI(QWidget):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.setWindowTitle("OTA FW Merger")
        self.work_dir = get_work_dir()
        self.tokens = build_m3_tokens(app)
        self.current_qss = render_m3_stylesheet(self.tokens)
        self.hybrid_imgs = {}
        self.tracker = load_tracker_state(self.work_dir)
        self.pending_ota_url = self.tracker.get("last_found_url", "")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Persistent Top Header
        hdr_wrap = QWidget()
        hdr_row = QHBoxLayout(hdr_wrap)
        hdr_row.setContentsMargins(16, 40, 16, 8)
        hdr_text = QVBoxLayout()
        hdr_text.setSpacing(2)
        title = QLabel("OTA FW Merger")
        title.setObjectName("AppTitle")
        self.sub_lbl = QLabel()
        self.sub_lbl.setObjectName("AppSubtitle")
        self.sub_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.sub_lbl.linkActivated.connect(lambda _: self.open_credits())
        hdr_text.addWidget(title)
        hdr_text.addWidget(self.sub_lbl)
        hdr_row.addLayout(hdr_text, 1)

        self.status_chip = QLabel("Ready")
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hdr_row.addWidget(self.status_chip)
        outer.addWidget(hdr_wrap)

        self.pages = QStackedWidget()

        # ================= TAB 1: MERGER =================
        scroll_merge = QScrollArea()
        scroll_merge.setWidgetResizable(True)
        scroll_merge.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        merge_content = QWidget()
        merge_content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(merge_content)
        root.setContentsMargins(16, 6, 16, 20)
        root.setSpacing(10)

        queue_card = QFrame()
        queue_card.setObjectName("Card")
        qc_layout = QVBoxLayout(queue_card)
        qc_layout.setContentsMargins(14, 10, 14, 12)
        qc_layout.setSpacing(8)

        q_top = QHBoxLayout()
        q_lbl = QLabel("OTA Queue (1st = FULL, rest = INCREMENTAL)")
        q_lbl.setObjectName("SectionLabel")
        q_top.addWidget(q_lbl, 1)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("TextBtn")
        clear_btn.clicked.connect(lambda: self.url_box.clear())
        q_top.addWidget(clear_btn)
        qc_layout.addLayout(q_top)

        self.url_box = QTextEdit()
        self.url_box.setPlaceholderText("Paste URLs or use buttons below to add Full + Incremental OTAs...")
        self.url_box.setFixedHeight(84)
        qc_layout.addWidget(self.url_box)

        pick_row = QHBoxLayout()
        pick_row.setSpacing(10)
        self.add_files_btn = QPushButton("Add OTA ZIP(s)")
        self.add_files_btn.clicked.connect(self.add_local_files)
        pick_row.addWidget(self.add_files_btn)
        self.add_folder_btn = QPushButton("Add FULL Folder")
        self.add_folder_btn.clicked.connect(self.add_full_folder)
        pick_row.addWidget(self.add_folder_btn)
        qc_layout.addLayout(pick_row)
        self.stock_overrides = {}
        self.dump_dev_btn = QPushButton("Dump Entire System Image (Root)")
        self.dump_dev_btn.clicked.connect(self.configure_root_dump)
        qc_layout.addWidget(self.dump_dev_btn)
        root.addWidget(queue_card)

        opt_card = QFrame()
        opt_card.setObjectName("Card")
        opt_col = QVBoxLayout(opt_card)
        opt_col.setContentsMargins(16, 10, 16, 10)
        opt_col.setSpacing(10)

        row_fake = QHBoxLayout()
        ft_txt = QVBoxLayout()
        f_title = QLabel('Build "fake" OTA')
        f_title.setObjectName("TileTitle")
        f_sub = QLabel("Repack merged images into testkey-signed payload ZIP")
        f_sub.setObjectName("TileSub")
        f_sub.setWordWrap(True)
        ft_txt.addWidget(f_title)
        ft_txt.addWidget(f_sub)
        row_fake.addLayout(ft_txt, 1)
        self.fake_ota_switch = M3Switch(self.tokens)
        self.fake_ota_switch.toggled.connect(self.on_fake_toggled)
        row_fake.addWidget(self.fake_ota_switch)
        opt_col.addLayout(row_fake)

        row_rec = QHBoxLayout()
        rt_txt = QVBoxLayout()
        r_title = QLabel("Custom Recovery Flashable ZIP")
        r_title.setObjectName("TileTitle")
        self.rec_sub = QLabel("Universal OOS/COS flasher, Non ColorOS device support is experimental")
        self.rec_sub.setObjectName("TileSub")
        self.rec_sub.setWordWrap(True)
        rt_txt.addWidget(r_title)
        rt_txt.addWidget(self.rec_sub)
        row_rec.addLayout(rt_txt, 1)
        self.recovery_switch = M3Switch(self.tokens)
        self.recovery_switch.toggled.connect(self.on_recovery_toggled)
        row_rec.addWidget(self.recovery_switch)
        opt_col.addLayout(row_rec)

        self.recovery_mode = "super"
        root.addWidget(opt_card)

        self.run_btn = QPushButton("Merge OTA Firmwares")
        self.run_btn.setObjectName("PrimaryBtn")
        self.run_btn.clicked.connect(self.start_dump)
        root.addWidget(self.run_btn)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        root.addWidget(self.progress)

        log_card = QFrame()
        log_card.setObjectName("Card")
        lc_layout = QVBoxLayout(log_card)
        lc_layout.setContentsMargins(14, 10, 14, 12)
        lc_layout.setSpacing(6)
        log_lbl = QLabel(f"Console  •  Output: {self.work_dir}/output")
        log_lbl.setObjectName("AppSubtitle")
        log_lbl.setWordWrap(True)
        lc_layout.addWidget(log_lbl)
        self.log_box = QTextEdit()
        self.log_box.setObjectName("LogBox")
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(280)
        configure_smooth_scroll(self.log_box)
        lc_layout.addWidget(self.log_box, 1)
        root.addWidget(log_card, 1)

        scroll_merge.setWidget(merge_content)
        configure_smooth_scroll(scroll_merge)
        self.pages.addWidget(scroll_merge)

        # ================= TAB 2: DEVICE-SPECIFIC OTA WATCHER =================
        scroll_watch = QScrollArea()
        scroll_watch.setWidgetResizable(True)
        scroll_watch.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        watch_content = QWidget()
        watch_content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        w_root = QVBoxLayout(watch_content)
        w_root.setContentsMargins(16, 6, 16, 20)
        w_root.setSpacing(10)

        watch_card = QFrame()
        watch_card.setObjectName("Card")
        wl = QVBoxLayout(watch_card)
        wl.setContentsMargins(16, 12, 16, 14)
        wl.setSpacing(10)

        w_hdr = QHBoxLayout()
        w_lbl = QLabel("Device-Specific OTA Watcher")
        w_lbl.setObjectName("SectionLabel")
        w_hdr.addWidget(w_lbl, 1)
        self.check_now_btn = QPushButton("Check Now")
        self.check_now_btn.clicked.connect(self.check_ota_now)
        w_hdr.addWidget(self.check_now_btn)
        wl.addLayout(w_hdr)

        self.tracked_lbl = QLabel()
        self.tracked_lbl.setObjectName("TileSub")
        self.tracked_lbl.setWordWrap(True)
        wl.addWidget(self.tracked_lbl)

        row_daily = QHBoxLayout()
        dl_txt = QVBoxLayout()
        dt = QLabel("Daily Push Check (24h)")
        dt.setObjectName("TileTitle")
        ds = QLabel("Notify only when a newer incremental drops for this exact model")
        ds.setObjectName("TileSub")
        ds.setWordWrap(True)
        dl_txt.addWidget(dt)
        dl_txt.addWidget(ds)
        row_daily.addLayout(dl_txt, 1)
        self.daily_switch = M3Switch(self.tokens)
        self.daily_switch.setChecked(bool(self.tracker.get("daily_check", False)))
        self.daily_switch.toggled.connect(self.on_tracker_changed)
        row_daily.addWidget(self.daily_switch)
        wl.addLayout(row_daily)

        row_auto = QHBoxLayout()
        al_txt = QVBoxLayout()
        at = QLabel("Auto-Download Incrementals (Wi-Fi)")
        at.setObjectName("TileTitle")
        asub = QLabel("Save new device incrementals to Download/OTAFirmwareMerger/incoming/")
        asub.setObjectName("TileSub")
        asub.setWordWrap(True)
        al_txt.addWidget(at)
        al_txt.addWidget(asub)
        row_auto.addLayout(al_txt, 1)
        self.autodl_switch = M3Switch(self.tokens)
        self.autodl_switch.setChecked(bool(self.tracker.get("auto_download", False)))
        self.autodl_switch.toggled.connect(self.on_tracker_changed)
        row_auto.addWidget(self.autodl_switch)
        wl.addLayout(row_auto)

        row_root = QHBoxLayout()
        rc_txt = QVBoxLayout()
        rct = QLabel("Root System Update Capture")
        rct.setObjectName("TileTitle")
        rcs = QLabel("Capture NA/GOTA googleapis.com links from System Update prefs & logcat")
        rcs.setObjectName("TileSub")
        rcs.setWordWrap(True)
        rc_txt.addWidget(rct)
        rc_txt.addWidget(rcs)
        row_root.addLayout(rc_txt, 1)
        self.root_cap_switch = M3Switch(self.tokens)
        self.root_cap_switch.setChecked(bool(self.tracker.get("root_capture", False)))
        self.root_cap_switch.toggled.connect(self.on_tracker_changed)
        row_root.addWidget(self.root_cap_switch)
        wl.addLayout(row_root)

        row_force = QHBoxLayout()
        fl_txt = QVBoxLayout()
        flt = QLabel("Force Latest Incremental (Advanced)")
        flt.setObjectName("TileTitle")
        fls = QLabel("Fetch/download latest available OTA even if already on the latest firmware")
        fls.setObjectName("TileSub")
        fls.setWordWrap(True)
        fl_txt.addWidget(flt)
        fl_txt.addWidget(fls)
        row_force.addLayout(fl_txt, 1)
        self.force_latest_switch = M3Switch(self.tokens)
        self.force_latest_switch.setChecked(bool(self.tracker.get("force_latest", False)))
        self.force_latest_switch.toggled.connect(self.on_tracker_changed)
        row_force.addWidget(self.force_latest_switch)
        wl.addLayout(row_force)

        self.capture_root_btn = QPushButton("Capture from System Update (Root)")
        self.capture_root_btn.clicked.connect(self.capture_ota_root)
        wl.addWidget(self.capture_root_btn)

        self.add_found_btn = QPushButton("Queue Found Incremental URL")
        self.add_found_btn.setObjectName("PrimaryBtn")
        self.add_found_btn.clicked.connect(self.queue_found_url)
        self.add_found_btn.setVisible(bool(self.pending_ota_url))
        wl.addWidget(self.add_found_btn)
        w_root.addWidget(watch_card)

        w_log_card = QFrame()
        w_log_card.setObjectName("Card")
        wlc = QVBoxLayout(w_log_card)
        wlc.setContentsMargins(14, 10, 14, 12)
        wlc.setSpacing(6)
        wlc_lbl = QLabel("OTA Check Output")
        wlc_lbl.setObjectName("AppSubtitle")
        wlc.addWidget(wlc_lbl)
        self.watch_log_box = QTextEdit()
        self.watch_log_box.setObjectName("LogBox")
        self.watch_log_box.setReadOnly(True)
        self.watch_log_box.setMinimumHeight(280)
        configure_smooth_scroll(self.watch_log_box)
        wlc.addWidget(self.watch_log_box, 1)
        w_root.addWidget(w_log_card, 1)

        scroll_watch.setWidget(watch_content)
        configure_smooth_scroll(scroll_watch)
        self.pages.addWidget(scroll_watch)

        outer.addWidget(self.pages, 1)

        # ================= MATERIAL 3 BOTTOM NAVIGATION BAR =================
        nav_bar = QFrame()
        nav_bar.setObjectName("BottomNav")
        nav_row = QHBoxLayout(nav_bar)
        nav_row.setContentsMargins(16, 8, 16, 18)
        nav_row.setSpacing(12)

        self.nav_merge_btn = QPushButton("Merger")
        self.nav_merge_btn.setObjectName("NavTab")
        self.nav_merge_btn.clicked.connect(lambda: self.switch_tab(0))
        nav_row.addWidget(self.nav_merge_btn, 1)

        self.nav_watch_btn = QPushButton("OTA Watcher")
        self.nav_watch_btn.setObjectName("NavTab")
        self.nav_watch_btn.clicked.connect(lambda: self.switch_tab(1))
        nav_row.addWidget(self.nav_watch_btn, 1)
        outer.addWidget(nav_bar)

        self.switch_tab(0)
        self.refresh_tracked_label()
        self.apply_dynamic_theme()
        try:
            self.app.styleHints().colorSchemeChanged.connect(lambda _: self.apply_dynamic_theme())
            self.app.applicationStateChanged.connect(lambda st: self.apply_dynamic_theme() if st == Qt.ApplicationState.ApplicationActive else None)
        except Exception:
            pass

    def switch_tab(self, idx: int):
        self.pages.setCurrentIndex(idx)
        self.nav_merge_btn.setProperty("active", "true" if idx == 0 else "false")
        self.nav_watch_btn.setProperty("active", "true" if idx == 1 else "false")
        for b in (self.nav_merge_btn, self.nav_watch_btn):
            b.style().unpolish(b)
            b.style().polish(b)

    def append_watch_log(self, text: str):
        self.watch_log_box.moveCursor(QTextCursor.MoveOperation.End)
        self.watch_log_box.insertPlainText(text)
        self.watch_log_box.moveCursor(QTextCursor.MoveOperation.End)
        self.append_log(text)

    def refresh_tracked_label(self):
        m = self.tracker.get("model") or "Unknown"
        v = self.tracker.get("display_version") or self.tracker.get("ota_version") or "Not yet merged"
        self.tracked_lbl.setText(f"Tracking device: {m}  •  Last version: {v}")

    def apply_dynamic_theme(self):
        self.tokens = build_m3_tokens(self.app)
        self.current_qss = render_m3_stylesheet(self.tokens)
        self.setStyleSheet(self.current_qss)
        for sw in (self.fake_ota_switch, self.recovery_switch, self.daily_switch, self.autodl_switch, self.root_cap_switch, self.force_latest_switch):
            sw.set_tokens(self.tokens)
        p_hex = self.tokens["primary"]
        self.sub_lbl.setText(
            f'v{APP_VERSION}  •  Published by {APP_PUBLISHER}  •  '
            f'<a style="color:{p_hex};text-decoration:underline;" href="credits">Credits</a>'
        )

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.apply_dynamic_theme()
        super().changeEvent(event)

    def open_credits(self):
        dlg = CreditsDialog(self, self.current_qss, self.tokens["primary"])
        dlg.showMaximized()
        dlg.exec()

    def on_tracker_changed(self, *_):
        self.tracker["daily_check"] = self.daily_switch.isChecked()
        self.tracker["auto_download"] = self.autodl_switch.isChecked()
        self.tracker["root_capture"] = self.root_cap_switch.isChecked()
        self.tracker["force_latest"] = self.force_latest_switch.isChecked()
        save_tracker_state(self.work_dir, self.tracker)
        try:
            subprocess.Popen([
                "am", "broadcast", "-n",
                f"{APP_PACKAGE}/{APP_PACKAGE}.OtaBootReceiver",
                "-a", f"{APP_PACKAGE}.ACTION_RESCHEDULE",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def capture_ota_root(self):
        self.on_tracker_changed()
        self.capture_root_btn.setEnabled(False)
        self.check_now_btn.setEnabled(False)
        self.status_chip.setText("Capturing...")
        self.ota_worker = OtaCheckWorker(self.tracker, self.work_dir, root_only=True)
        self.ota_worker.log.connect(self.append_watch_log)
        self.ota_worker.found.connect(self.on_ota_found)
        self.ota_worker.done.connect(self.on_ota_check_done)
        self.ota_worker.start()

    def check_ota_now(self):
        self.check_now_btn.setEnabled(False)
        self.status_chip.setText("Checking...")
        self.ota_worker = OtaCheckWorker(self.tracker, self.work_dir)
        self.ota_worker.log.connect(self.log)
        self.ota_worker.found.connect(self.on_ota_found)
        self.ota_worker.done.connect(self.on_ota_check_done)
        self.ota_worker.start()

    def on_ota_found(self, new_ver: str, url: str):
        self.pending_ota_url = url
        self.tracker["last_found_version"] = new_ver
        self.tracker["last_found_url"] = url
        save_tracker_state(self.work_dir, self.tracker)
        self.add_found_btn.setText(f"Queue Found: {new_ver}")
        self.add_found_btn.setVisible(True)

    def on_ota_check_done(self, msg: str):
        self.check_now_btn.setEnabled(True)
        self.capture_root_btn.setEnabled(True)
        self.status_chip.setText("Ready")
        self.log(f"{msg}\n")

    def queue_found_url(self):
        if self.pending_ota_url:
            self.url_box.append(self.pending_ota_url)

    def on_fake_toggled(self, checked: bool):
        if checked and self.recovery_switch.isChecked():
            self.recovery_switch.setChecked(False)

    def _has_device_dump_queued(self) -> bool:
        lines = [l.strip().lower() for l in self.url_box.toPlainText().splitlines() if l.strip()]
        return bool(lines and lines[0] == "device://dump")

    def configure_root_dump(self):
        dlg = RootDumpDialog(self, self.current_qss, self.stock_overrides)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.stock_overrides = dict(dlg.stock_overrides)
            existing = [l.strip() for l in self.url_box.toPlainText().splitlines() if l.strip() and l.strip().lower() != "device://dump"]
            self.url_box.setPlainText("\n".join(["device://dump"] + existing))
            ov_list = ", ".join(sorted(self.stock_overrides.keys())) if self.stock_overrides else "none"
            self.log(f"Base source set to live Root Full System Dump (stock overrides: {ov_list}).\n")
            self.log("Add your incremental OTA ZIP(s) below device://dump, pick RegionalHybrid or SuperHybrid (or Fake OTA), and tap Merge.\n")

    def set_recovery_mode(self, mode: str, silent: bool = False):
        self.recovery_mode = "regional" if mode == "regional" else "super"
        self.rec_sub.setText("Universal OOS/COS flasher, Non ColorOS device support is experimental")

    def on_recovery_toggled(self, checked: bool):
        if not checked:
            self.rec_sub.setText("Universal OOS/COS flasher, Non ColorOS device support is experimental")
            return
        if self.fake_ota_switch.isChecked():
            self.fake_ota_switch.setChecked(False)
        self.rec_sub.setText("Universal OOS/COS flasher, Non ColorOS device support is experimental")
    def log(self, text):
        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log_box.setTextCursor(cursor)
        self.log_box.ensureCursorVisible()

    def add_local_files(self):
        dlg = MobilePathPicker(self, "Select OTA ZIP(s)", self.current_qss, "/storage/emulated/0",
                               dirs_only=False, ext_filter="", multi=True)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            hybrid_picks, other_picks = [], []
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
                self.url_box.setPlainText("\n".join(new_lines))
                if self.fake_ota_switch.isChecked():
                    self.fake_ota_switch.setChecked(False)
                self.set_recovery_mode(detected_mode, silent=True)
                self.recovery_switch.blockSignals(True)
                self.recovery_switch.setChecked(True)
                self.recovery_switch.blockSignals(False)
                if detected_mode == "super":
                    self.rec_sub.setText("Auto-linked from SuperHybrid ZIP (COS_FILES_HERE)")
                    self.log(f"Detected SuperHybrid base ZIP: {os.path.basename(hybrid_picks[0])}\n")
                    self.log("Auto-enabled SuperHybrid (COS_FILES_HERE) recovery ZIP mode.\n")
                else:
                    req_str = ", ".join(found_reqs) if found_reqs else "OOS_FILES_HERE"
                    self.rec_sub.setText(f"Auto-linked from RegionalHybrid ZIP ({req_str})")
                    self.log(f"Detected RegionalHybrid base ZIP: {os.path.basename(hybrid_picks[0])}\n")
                    self.log(f"Auto-enabled RegionalHybrid recovery ZIP (auto-grabbing {req_str}).\n")
            else:
                for f in other_picks:
                    self.url_box.append(f)

    def add_full_folder(self):
        dlg = MobilePathPicker(self, "Select FULL OTA Folder", self.current_qss, "/storage/emulated/0", dirs_only=True)
        dlg.showMaximized()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for f in dlg.selected_paths:
                self.url_box.append(f)

    def start_dump(self):
        lines = [l.strip() for l in self.url_box.toPlainText().splitlines() if l.strip()]
        if not lines:
            QMessageBox.critical(self, "Missing Input", "Add at least one FULL OTA URL, ZIP, or folder.")
            return
        use_rec = self.recovery_switch.isChecked()
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
        if False and use_rec and rec_mode == "regional" and not is_dev_dump:
            missing = [
                r for r in REQUIRED_HYBRID_IMGS
                if r not in hyb_reqs and not os.path.isfile(self.hybrid_imgs.get(r, ""))
            ]
            if missing:
                self.on_recovery_toggled(True)
                if not self.recovery_switch.isChecked():
                    return
        self.run_btn.setEnabled(False)
        self.status_chip.setText("Merging...")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.log_box.clear()
        self.worker = DumpWorker(
            lines,
            fake_ota=self.fake_ota_switch.isChecked(),
            recovery_zip=use_rec,
            recovery_mode=rec_mode,
            extra_imgs=self.hybrid_imgs,
            stock_overrides=self.stock_overrides,
            work_dir=self.work_dir,
        )
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, code, tag, ota_ver):
        self.run_btn.setEnabled(True)
        self.progress.hide()
        self.progress.setRange(0, 1)
        self.status_chip.setText("Done" if code == 0 else "Failed")
        if code == 0 and tag:
            self.tracker["display_version"] = tag
            if ota_ver:
                self.tracker["ota_version"] = ota_ver
            self.tracker["model"] = extract_model_from_tag(tag)
            save_tracker_state(self.work_dir, self.tracker)
            self.refresh_tracked_label()
        self.log(f"\n=== Done (exit code {code}) ===\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = DumperGUI(app)
    w.showMaximized()
    sys.exit(app.exec())
