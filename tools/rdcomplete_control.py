#!/usr/bin/python3
"""Rivendell Complete — native Qt station control center.

This operator GUI does not implement playback timing; the installed Rivendell
RDAirPlay/CAE engine remains authoritative. Privileged NAS operations run only
through the root-owned and narrowly scoped local helper.
"""
from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from urllib import error, request
from urllib.parse import urlsplit

from PyQt5.QtCore import Qt, QProcess, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

ROOT_HELPER = "/usr/local/libexec/rivendell-complete/rdcomplete_root.py"
STATE = Path.home() / ".local/state/rivendell-complete"
CONFIG = Path.home() / ".config/rivendell-complete"
MUSIC_ROOT = Path("/mnt/radio-music")
GROUP = "MUSIC"
SERVICE = "Production"

COLORS = {
    "paper": "#F7F4EC", "white": "#FFFEFB", "ink": "#21342D",
    "muted": "#526158", "pine": "#225A40", "tangerine": "#B74D2E",
    "line": "#D8DCCF", "active": "#E7EAD9", "cream": "#F1E6CE",
}
STYLE = """
QMainWindow, QWidget { background: #F7F4EC; color: #21342D;
 font-family: 'DejaVu Sans'; font-size: 13px; }
QListWidget { background: #21342D; color: #F7F4EC; border: 0;
 font-size: 14px; padding: 18px 9px; outline: none; }
QListWidget::item { border: 0; padding: 14px 12px; min-height: 26px; }
QListWidget::item:selected { background: #397350; color: white; }
QListWidget::item:hover:!selected { background: #325143; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #87978B;
 border-radius: 3px; min-height: 30px; padding: 4px 8px; color: #21342D; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #225A40; }
QPushButton { background: #225A40; color: white; border: 1px solid #225A40;
 border-radius: 3px; padding: 9px 16px; min-height: 25px; font-weight: 600; }
QPushButton:hover { background: #174932; }
QPushButton:disabled { background: #D0D4C8; color: #5F665D; border-color: #D0D4C8; }
QPushButton:focus { border: 2px solid #B74D2E; }
QPushButton[secondary="true"] { background: #F7F4EC; border-color: #5B7366; color: #21342D; }
QPushButton[secondary="true"]:hover { background: #E7EAD9; }
QGroupBox { border: 1px solid #D8DCCF; margin-top: 15px; border-radius: 4px;
 background: #FFFEFB; padding: 13px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QPlainTextEdit, QTextEdit, QTableWidget { background: #FFFEFB; border: 1px solid #D8DCCF;
 selection-background-color: #225A40; selection-color: white; }
QHeaderView::section { background: #E7EAD9; padding: 7px; border: 0; }
QProgressBar { background: #E7EAD9; border: 0; height: 5px; }
QProgressBar::chunk { background: #B74D2E; }
"""

def note(text: str, parent: QWidget | None = None) -> QLabel:
    result = QLabel(text, parent)
    result.setWordWrap(True)
    result.setStyleSheet(f"color: {COLORS['muted']}; line-height: 1.35;")
    return result


def title(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont("DejaVu Sans", 22, QFont.Bold)
    label.setFont(font)
    return label


def push(text: str, action, secondary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("secondary", "true" if secondary else "false")
    button.clicked.connect(action)
    return button


class Panel(QWidget):
    def __init__(self, heading: str, description: str):
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(28, 22, 28, 22)
        self.layout_.setSpacing(13)
        self.layout_.addWidget(title(heading))
        self.layout_.addWidget(note(description))
    def add(self, obj):
        self.layout_.addWidget(obj)
        return obj
    def finish(self):
        self.layout_.addStretch(1)


class Console(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rivendell Complete — Station Operations")
        self.setMinimumSize(840, 650)
        self.resize(1220, 820)
        self.busy = False
        self.command = None
        self.mode = ""
        self.output = bytearray()
        self.smb_secret: bytes | None = None
        self.buttons: list[QPushButton] = []
        self.request_ids: list[int] = []

        shell = QWidget()
        self.setCentralWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setFixedWidth(221)
        sidebar.setStyleSheet("background:#21342D;")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 20, 0, 0)
        brand = QLabel("RIVENDELL\nCOMPLETE")
        brand.setFont(QFont("DejaVu Sans", 18, QFont.Bold))
        brand.setStyleSheet("color:#F7F4EC; padding:14px 22px; line-height:1.2;")
        side.addWidget(brand)
        side.addWidget(QLabel("  Production  /  MUSIC"))
        side.itemAt(1).widget().setStyleSheet("color:#C2CFC4; padding:4px 15px;")
        self.menu = QListWidget()
        for item in ["Overview", "Music & NAS", "Import library", "Listener requests",
                     "Stream encoder", "Audio routing", "Scheduling"]:
            self.menu.addItem(item)
        self.menu.setAccessibleName("Station operations navigation")
        side.addWidget(self.menu)
        footer = QLabel("Rivendell 4.5.0\nNative broadcast engine")
        footer.setStyleSheet("color:#C2CFC4;padding:16px 22px;")
        side.addWidget(footer)
        outer.addWidget(sidebar)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self._overview()
        self._nas()
        self._import()
        self._requests()
        self._stream()
        self._audio()
        self._scheduling()
        self.menu.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.menu.setCurrentRow(0)
        self.status = QLabel("Safe mode · No outgoing audio was enabled by this application.")
        self.statusBar().addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        QTimer.singleShot(200, self.readiness)

    def register(self, button: QPushButton) -> QPushButton:
        self.buttons.append(button)
        return button

    def _overview(self):
        page = Panel("Station overview",
            "Current configuration and service state. This screen reports facts from the workstation; it does not start a broadcast.")
        self.health = QPlainTextEdit()
        self.health.setReadOnly(True)
        self.health.setFont(QFont("DejaVu Sans Mono", 11))
        self.health.setMinimumHeight(320)
        page.add(self.health)
        buttons = QHBoxLayout()
        buttons.addWidget(self.register(push("Refresh readiness", self.readiness)))
        buttons.addWidget(self.register(push("Open RDAirPlay", lambda: self.launch("rdairplay"), True)))
        buttons.addWidget(self.register(push("Open RDAdmin", lambda: self.launch("rdadmin"), True)))
        page.layout_.addLayout(buttons)
        page.add(note("A working database, encoder installation and catalog do not by themselves prove audio reached the sound card or stream server."))
        page.finish()
        self.pages.addWidget(page)

    def _nas(self):
        page = Panel("Connect the music library",
            "Original audio stays on the NAS. Rivendell mounts the share read-only, stores only metadata and references on the local disk, and refuses to replace an existing share.")
        box = QGroupBox("Read-only NAS connection")
        form = QFormLayout(box)
        self.nas_protocol = QComboBox()
        self.nas_protocol.addItems(["NFS", "SMB"])
        form.addRow("Protocol", self.nas_protocol)
        self.nas_source = QLineEdit()
        self.nas_source.setPlaceholderText("HOST:/export/music  or  //HOST/music")
        form.addRow("Share / export", self.nas_source)
        self.nas_username = QLineEdit()
        self.nas_username.setPlaceholderText("Only for SMB")
        form.addRow("SMB username", self.nas_username)
        self.nas_password = QLineEdit()
        self.nas_password.setEchoMode(QLineEdit.Password)
        form.addRow("SMB password", self.nas_password)
        self.nas_protocol.currentTextChanged.connect(self._nas_fields)
        self._nas_fields()
        page.add(box)
        page.add(note("A system authentication dialog will ask permission to mount the NAS. SMB credentials are never included in command arguments or displayed in activity logs."))
        page.add(self.register(push("Connect and configure source", self.mount_nas)))
        page.add(note("If the share is already mounted read-only at /mnt/radio-music, existing settings are preserved. Different mounts must be reviewed manually."))
        page.finish()
        self.pages.addWidget(page)

    def _nas_fields(self):
        smb = self.nas_protocol.currentText() == "SMB"
        self.nas_username.setEnabled(smb)
        self.nas_password.setEnabled(smb)

    def _import(self):
        page = Panel("Import existing music",
            "Scan existing NAS files, preview the metadata and explicitly confirm the catalog import. The original files are neither copied nor rewritten.")
        self.import_count = QSpinBox()
        self.import_count.setRange(1, 500)
        self.import_count.setValue(25)
        box = QGroupBox("Source: /mnt/radio-music   →   Rivendell group: MUSIC")
        form = QFormLayout(box)
        form.addRow("Preview up to", self.import_count)
        page.add(box)
        actions = QHBoxLayout()
        actions.addWidget(self.register(push("Preview scan", self.scan_import)))
        actions.addWidget(self.register(push("Import all supported tracks", self.import_music, True)))
        page.layout_.addLayout(actions)
        page.add(note("Supported import formats: MP3, PCM WAV (16/24-bit), and Ogg Vorbis. FLAC is not yet supported by this external-audio playback path. Stop RDAirPlay before importing."))
        self.import_output = QPlainTextEdit()
        self.import_output.setReadOnly(True)
        self.import_output.setFont(QFont("DejaVu Sans Mono", 10))
        self.import_output.setMinimumHeight(210)
        page.add(self.import_output)
        page.finish()
        self.pages.addWidget(page)

    def _requests(self):
        page = Panel("Listener requests",
            "Manage the local authenticated request queue. The request service will not start until MUSIC contains playable carts and a catalog is exported.")
        actions = QHBoxLayout()
        actions.addWidget(self.register(push("Export MUSIC catalog", self.export_catalog)))
        actions.addWidget(self.register(push("Start request service", self.start_requests, True)))
        page.layout_.addLayout(actions)
        self.requests_status = note("No request queue loaded.")
        page.add(self.requests_status)
        self.request_table = QTableWidget(0, 5)
        self.request_table.setHorizontalHeaderLabels(["ID", "Cart", "Requester", "Status", "Submitted"])
        self.request_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.request_table.setSelectionMode(QTableWidget.SingleSelection)
        self.request_table.horizontalHeader().setStretchLastSection(True)
        page.add(self.request_table)
        row = QHBoxLayout()
        row.addWidget(self.register(push("Refresh queue", self.load_requests, True)))
        row.addWidget(self.register(push("Approve selected", lambda: self.moderate("approve"), True)))
        row.addWidget(self.register(push("Reject selected", lambda: self.moderate("reject"), True)))
        page.layout_.addLayout(row)
        page.add(note("The listener endpoint is bound to 127.0.0.1:8787. No public website or remote network port is enabled here. Public requests require a separately secured front end; insertion into on-air logs is not yet qualified."))
        page.finish()
        self.pages.addWidget(page)

    def _stream(self):
        page = Panel("Streaming output",
            "Configure one authenticated Icecast or SHOUTcast source. Credentials are stored privately; an encoder is never started just by saving settings.")
        box = QGroupBox("Encoder configuration")
        form = QFormLayout(box)
        self.stream_type = QComboBox()
        self.stream_type.addItems(["Shout2", "IceCast2", "Shout1"])
        form.addRow("Server", self.stream_type)
        self.stream_url = QLineEdit()
        self.stream_url.setPlaceholderText("http://your-stream-server:8000/mount")
        form.addRow("Server URL", self.stream_url)
        self.stream_username = QLineEdit("source")
        form.addRow("Source username", self.stream_username)
        self.stream_password = QLineEdit()
        self.stream_password.setEchoMode(QLineEdit.Password)
        form.addRow("Source password", self.stream_password)
        self.stream_device = QComboBox()
        self.stream_device.addItems(["JACK", "ALSA"])
        form.addRow("Capture audio from", self.stream_device)
        self.stream_bitrate = QComboBox()
        self.stream_bitrate.addItems(["128", "192", "256", "320", "64"])
        form.addRow("MP3 bitrate (kbps)", self.stream_bitrate)
        self.stream_name = QLineEdit("Production")
        form.addRow("Stream name", self.stream_name)
        page.add(box)
        actions = QHBoxLayout()
        actions.addWidget(self.register(push("Save private stream settings", self.save_stream)))
        actions.addWidget(self.register(push("Verify settings", lambda: self.execute(
            ["rdcomplete-stream", "verify"], "stream-check"), True)))
        page.layout_.addLayout(actions)
        page.add(self.register(push("Start test encoder", self.start_stream, True)))
        page.add(note("You must select and verify the real capture routing first. Starting the encoder makes an outgoing source connection to your specified stream server."))
        page.finish()
        self.pages.addWidget(page)

    def _audio(self):
        page = Panel("Audio routing",
            "Discover the actual JACK ports before connecting Rivendell outputs to the encoder inputs. Routing controls do not start or replace RDAirPlay.")
        page.add(self.register(push("Discover live JACK ports", lambda: self.execute(
            ["rdcomplete-jack-route", "--discover"], "audio-discover")))
        self.port_output = QPlainTextEdit()
        self.port_output.setReadOnly(True)
        self.port_output.setFont(QFont("DejaVu Sans Mono", 10))
        page.add(self.port_output)
        box = QGroupBox("Stereo connection mapping")
        form = QFormLayout(box)
        self.route_inputs = []
        for field in ["Rivendell left output", "Encoder left input", "Rivendell right output", "Encoder right input"]:
            edit = QLineEdit()
            edit.setPlaceholderText("Exact JACK port name from discovery")
            self.route_inputs.append(edit)
            form.addRow(field, edit)
        page.add(box)
        page.add(self.register(push("Save validated stereo route", self.save_route)))
        page.add(self.register(push("Enable route reconnection", self.start_route, True)))
        page.add(note("An empty JACK graph means the audio server or RDAirPlay is not running. Do not guess port names."))
        page.finish()
        self.pages.addWidget(page)

    def _scheduling(self):
        page = Panel("Production scheduling",
            "Protect the existing Production service and schedule. Inspect the generated commands before enabling the recurring timer.")
        page.add(self.register(push("Preview next seven days", lambda: self.execute(
            ["rdcomplete-loggen", "--service", SERVICE, "--days", "7", "--dry-run"], "schedule-preview")))
        page.add(self.register(push("Enable future log timer", self.enable_schedule, True)))
        page.add(note("Enabling scheduling requires configured grids, clocks, legal IDs and playable carts in RDLogManager. This tool is not continuous live backtiming."))
        page.add(self.register(push("Open RDLogManager", lambda: self.launch("rdlogmanager"), True)))
        page.finish()
        self.pages.addWidget(page)

    def _confirm(self, heading: str, detail: str) -> bool:
        return QMessageBox.question(self, heading, detail, QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No) == QMessageBox.Yes

    def _alert(self, message: str):
        QMessageBox.warning(self, "Rivendell Complete", message)

    def launch(self, executable: str):
        if executable not in ("rdadmin", "rdairplay", "rdlogmanager", "rdlibrary", "rdlogedit"):
            return
        result = QProcess.startDetached(executable, [])
        launched = result[0] if isinstance(result, tuple) else result
        if not launched:
            self._alert(f"Could not open {executable}; use the Ubuntu desktop session.")

    def _root(self, action: str, params: list[str] | None = None,
              data: bytes | None = None, mode: str = "root"):
        self.execute(["pkexec", "/usr/bin/python3", ROOT_HELPER, action, *(params or [])],
                     mode, data)

    def execute(self, cmd: list[str], mode: str, data: bytes | None = None):
        if self.busy:
            self._alert("A station operation is already running.")
            return
        self.busy = True
        self.mode = mode
        self.output = bytearray()
        self.smb_secret = data
        for button in self.buttons:
            button.setEnabled(False)
        self.progress.show()
        self.status.setText(f"Running: {mode}. Do not close the application.")
        self.command = QProcess(self)
        self.command.setProcessChannelMode(QProcess.MergedChannels)
        self.command.readyReadStandardOutput.connect(self._read_output)
        self.command.started.connect(self._send_stdin)
        self.command.finished.connect(self._finished)
        self.command.errorOccurred.connect(self._error)
        self.command.start(cmd[0], cmd[1:])

    def _send_stdin(self):
        if self.smb_secret is not None:
            self.command.write(self.smb_secret)
            self.command.closeWriteChannel()
            self.smb_secret = None

    def _read_output(self):
        if self.command is None:
            return
        chunk = bytes(self.command.readAllStandardOutput())
        # Request catalogs can be large; never show their JSON in the log.
        if self.mode == "catalog":
            if len(self.output) + len(chunk) > 50 * 1024 * 1024:
                self.command.kill()
                self._alert("Catalog export exceeded the 50 MiB safety limit.")
                return
            self.output.extend(chunk)
        else:
            if len(self.output) < 1024 * 1024:
                self.output.extend(chunk[:1024 * 1024 - len(self.output)])
            line = chunk.decode("utf-8", "replace")
            if self.mode in ("import", "scan"):
                self.import_output.insertPlainText(line)
                self.import_output.ensureCursorVisible()
            elif self.mode == "audio-discover":
                self.port_output.insertPlainText(line)
                self.port_output.ensureCursorVisible()
            elif self.mode == "readiness":
                self.health.insertPlainText(line)
            else:
                self.status.setText(line.strip()[-250:] or f"Running: {self.mode}")

    def _error(self, failure):
        if failure == QProcess.FailedToStart:
            self._alert("Could not start the required program. Check its installation and desktop authentication agent.")
            self.busy = False
            self.progress.hide()
            for button in self.buttons:
                button.setEnabled(True)
            self.status.setText("Unable to launch required command.")

    def _finished(self, code: int, status):
        self._read_output()
        mode = self.mode
        good = code == 0 and status == QProcess.NormalExit
        self.busy = False
        self.progress.hide()
        for button in self.buttons:
            button.setEnabled(True)
        self.status.setText(f"{mode}: {'completed' if good else 'failed (exit '+str(code)+')'}")
        if mode == "catalog" and good:
            try:
                self._write_catalog(bytes(self.output))
            except (OSError, ValueError, RuntimeError) as exc:
                good = False
                self._alert(f"Catalog export could not be saved: {exc}")
        elif mode == "readiness":
            try:
                report = json.loads(bytes(self.output))
                summary = "\n".join(
                    f"{r['status'].upper():5} {r['name']:<28} {r['detail']}"
                    for r in report.get("checks", []))
                self.health.setPlainText(summary)
            except (ValueError, KeyError, TypeError):
                pass
        if mode in ("mount", "import", "stream-check", "request-start", "schedule-enable") and not good:
            details = bytes(self.output).decode("utf-8", "replace")[-1700:]
            self._alert(f"Operation failed (exit {code}).\n\n{details}")
        if mode == "import" and good:
            self._confirm("Music import completed",
                          "Import finished. Export an updated request catalog on the Listener requests page.")
        self.command.deleteLater()
        self.command = None
        self.output = bytearray()

    def readiness(self):
        self.health.clear()
        self.execute(["rdcomplete-selftest", "--json"], "readiness")

    def mount_nas(self):
        src = self.nas_source.text().strip()
        smb = self.nas_protocol.currentText() == "SMB"
        pattern = (r"//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+"
                   if smb else r"[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+")
        if not re.fullmatch(pattern, src):
            self._alert("Enter a valid full NAS share/export path.")
            return
        creds = None
        if smb:
            user = self.nas_username.text()
            password = self.nas_password.text()
            if not user or not password or any(c in "\r\n=\\" for c in user) or "\n" in password or "\r" in password:
                self._alert("SMB username/password invalid or missing.")
                return
            creds = f"{user}\n{password}\n".encode()
        if not self._confirm("Connect NAS read-only",
                f"Mount {src} read-only and configure original-path audio references?\n\n"
                "No source audio files will be copied or modified."):
            return
        self.nas_password.clear()
        self._root("mount-smb" if smb else "mount-nfs", ["--source", src], creds, "mount")

    def scan_import(self):
        self.import_output.clear()
        self._root("scan", ["--group", GROUP, "--limit", str(self.import_count.value())], mode="scan")

    def import_music(self):
        if not self._confirm("Import music metadata",
                "Register every supported new file in MUSIC? This creates cart records and "
                "small local reference files, but does NOT modify music stored on the NAS.\n\n"
                "RDAirPlay must be stopped. Existing carts will not be overwritten."):
            return
        self.import_output.clear()
        self._root("import", ["--group", GROUP], mode="import")

    def _write_catalog(self, raw: bytes):
        result = json.loads(raw)
        if not isinstance(result, list) or not result or not all(
            isinstance(x, dict) and type(x.get("cart")) is int for x in result):
            raise ValueError("No playable music carts were returned")
        if CONFIG.is_symlink() or STATE.is_symlink():
            raise RuntimeError("Unsafe station configuration directory")
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        if STATE.stat().st_uid != os.getuid() or STATE.stat().st_mode & 0o077:
            raise RuntimeError("State directory ownership/permissions unsafe")
        dest = STATE / "request-catalog.json"
        if dest.is_symlink() or (dest.exists() and (
                not dest.is_file() or dest.stat().st_uid != os.getuid())):
            raise RuntimeError("Existing request catalog has unsafe ownership or type")
        import tempfile
        fd, temp = tempfile.mkstemp(prefix=".request-catalog-", dir=STATE)
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, dest)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.requests_status.setText(f"{len(result)} playable carts exported to the protected local request catalog")
        self.status.setText("Request catalog updated safely.")

    def export_catalog(self):
        self._root("export-catalog", mode="catalog")

    def start_requests(self):
        catalog = STATE / "request-catalog.json"
        if not catalog.is_file() or catalog.is_symlink() or catalog.stat().st_size < 10:
            self._alert("Export a populated MUSIC catalog before starting the request service.")
            return
        if not self._confirm("Start local listener intake",
                "Start the authenticated request API on 127.0.0.1:8787?\n\n"
                "This is a local-only API, not a publicly accessible website."):
            return
        self.execute(["systemctl", "--user", "enable", "--now",
                      "rdcomplete-requests.service"], "request-start")

    def load_requests(self):
        database = STATE / "requests.sqlite"
        if not database.is_file() or database.is_symlink():
            self.requests_status.setText("No request database yet. Start the local request service first.")
            return
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=3) as db:
                rows = db.execute(
                    "SELECT id,cart,requester,status,datetime(submitted_at,'unixepoch','localtime') "
                    "FROM requests ORDER BY id DESC LIMIT 200").fetchall()
        except (sqlite3.Error, OSError) as exc:
            self._alert(f"Cannot read the local request queue: {exc}")
            return
        self.request_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.request_table.setItem(r, c, item)
        self.requests_status.setText(f"{len(rows)} newest requests displayed (read-only until selected for moderation).")

    def moderate(self, action: str):
        row = self.request_table.currentRow()
        if row < 0:
            self._alert("Select a request in the table.")
            return
        try:
            request_id = int(self.request_table.item(row, 0).text())
            current = self.request_table.item(row, 3).text()
        except (AttributeError, ValueError):
            self._alert("Invalid request selection.")
            return
        if current != "pending":
            self._alert("Only pending requests can be approved or rejected.")
            return
        if not self._confirm(action.capitalize() + " request", f"{action.capitalize()} request #{request_id}?"):
            return
        token = CONFIG / "request-admin.token"
        try:
            info = token.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError("Admin token ownership/permissions invalid")
            secret = token.read_text(encoding="ascii").strip()
            req = request.Request(
                f"http://127.0.0.1:8787/api/v1/admin/requests/{request_id}/{action}",
                method="POST", headers={"Authorization": "Bearer " + secret,
                                        "Content-Length": "0"})
            with request.urlopen(req, timeout=3) as res:
                body = json.loads(res.read(2048))
            if not body.get("changed"):
                raise RuntimeError("Request was not pending at the server")
        except (OSError, ValueError, RuntimeError, error.URLError) as exc:
            self._alert(f"Moderation failed: {exc}")
            return
        self.load_requests()

    def save_stream(self):
        from urllib.parse import urlsplit
        url = self.stream_url.text().strip()
        try:
            parsed = urlsplit(url)
            valid_url = (parsed.scheme == "http" and parsed.hostname and parsed.port
                         and not parsed.username and not parsed.password
                         and not parsed.query and not parsed.fragment)
        except ValueError:
            valid_url = False
        if not valid_url:
            self._alert("Use an http://HOST:PORT/path URL without embedded credentials.")
            return
        username = self.stream_username.text()
        password = self.stream_password.text()
        if not username or any(ord(c) <= 32 or c == "=" for c in username):
            self._alert("Invalid stream source username.")
            return
        if not password or any(ord(c) < 32 or ord(c) == 127 for c in password):
            self._alert("Invalid stream source password.")
            return
        if not self._confirm("Save stream credentials",
                             "Save private credentials and encoder settings for this station?\n\n"
                             "The encoder will remain stopped."):
            return
        if CONFIG.is_symlink():
            self._alert("Refusing a symlinked configuration directory.")
            return
        CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
        if CONFIG.stat().st_uid != os.getuid() or CONFIG.stat().st_mode & 0o077:
            self._alert("Station configuration directory permissions are unsafe.")
            return
        stream = CONFIG / "stream.json"
        credentials = CONFIG / "credentials.ini"
        if stream.exists() or stream.is_symlink() or credentials.exists() or credentials.is_symlink():
            self._alert("A stream is already configured. Existing credentials are preserved; no overwrite.")
            return
        configuration = {
            "server_type": self.stream_type.currentText(),
            "server_url": url,
            "audio_device": self.stream_device.currentText(),
            "alsa_device": "default",
            "jack_client": "rivendell-complete",
            "bitrate": int(self.stream_bitrate.currentText()),
            "samplerate": 44100,
            "stream_name": self.stream_name.text().strip(),
            "genre": "",
            "metadata_enabled": True,
        }
        from os import O_CREAT, O_EXCL, O_WRONLY, O_NOFOLLOW
        created: list[Path] = []
        try:
            for path, payload in [
                (credentials, f"[Credentials]\nUsername={username}\nPassword={password}\n".encode()),
                (stream, (json.dumps(configuration, indent=2) + "\n").encode()),
            ]:
                fd = os.open(path, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW, 0o600)
                created.append(path)
                with os.fdopen(fd, "wb") as out:
                    out.write(payload)
                    out.flush()
                    os.fsync(out.fileno())
        except (OSError, ValueError) as exc:
            for path in created:
                path.unlink(missing_ok=True)
            self._alert(f"Could not save stream settings: {exc}")
            return
        finally:
            self.stream_password.clear()
        self.execute(["rdcomplete-stream", "verify"], "stream-check")

    def start_stream(self):
        if not (CONFIG / "stream.json").is_file():
            self._alert("Save and verify streaming credentials first.")
            return
        if not self._confirm("Start outgoing test stream",
                 "This will connect to the configured SHOUTcast/Icecast server.\n\n"
                 "Have you verified the audio capture device and route?"):
            return
        self.execute(["systemctl", "--user", "enable", "--now",
                      "rdcomplete-stream.service"], "stream-start")

    def save_route(self):
        values = [w.text().strip() for w in self.route_inputs]
        if any(not p or len(p) > 255 or any(ord(c) < 32 for c in p) for p in values):
            self._alert("Enter four valid actual JACK port names from discovery.")
            return
        self.execute(["rdcomplete-jack-route", "--set", *values], "route-save")

    def start_route(self):
        if not (CONFIG / "jack-route.json").is_file():
            self._alert("Save a validated stereo route first.")
            return
        self.execute(["systemctl", "--user", "enable", "--now",
                      "rdcomplete-jack-route.service"], "route-start")

    def enable_schedule(self):
        if not self._confirm("Enable automatic log generation",
                 "Enable daily Production log generation at 02:15 and 14:15?\n\n"
                 "Confirm that RDLogManager clocks/grids, legal IDs and playable carts are configured."):
            return
        self.execute(["systemctl", "--user", "enable", "--now",
                      "rdcomplete-loggen.timer"], "schedule-enable")


def main() -> int:
    if os.geteuid() == 0:
        print("Run the GUI as the desktop user, not root", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("Rivendell Complete")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Console()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
