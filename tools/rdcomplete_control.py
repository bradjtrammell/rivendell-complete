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
from rdcomplete_schedule_ui import SchedulePanel
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
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
        self.errors = bytearray()
        self.smb_secret: bytes | None = None
        self.buttons: list[QPushButton] = []
        self.request_ids: list[int] = []
        self.nas_discovery_rows: list[dict] = []
        self.nas_discovery_mode = ""
        self.import_folder = ""
        self.last_import_source = ""
        self.groups_loaded = False
        self.pending_nas_mapping = None

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
        self.menu.currentRowChanged.connect(self.page_changed)
        self.menu.setCurrentRow(0)
        self.status = QLabel("Safe mode · No outgoing audio was enabled by this application.")
        self.statusBar().addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        QTimer.singleShot(200, self.readiness)

    def add_page(self, page: QWidget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)

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
        self.add_page(page)

    def _nas(self):
        page = Panel("Connect the music library",
            "Original audio stays on the NAS. Rivendell mounts the share read-only, stores only metadata and references on the local disk, and refuses to replace an existing share.")
        self.mount_table = QTableWidget(0, 5)
        self.mount_table.setHorizontalHeaderLabels(
            ["Name", "Protocol", "Remote share", "Local mount", "Status"])
        self.mount_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mount_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mount_table.horizontalHeader().setStretchLastSection(True)
        self.mount_table.setMinimumHeight(145)
        page.add(self.mount_table)
        page.add(self.register(push("Refresh mounted sources", self.refresh_mounts, True)))
        box = QGroupBox("Add another read-only NFS or SMB source")
        form = QFormLayout(box)
        self.nas_name = QLineEdit()
        self.nas_name.setPlaceholderText("e.g. current, archive, imaging")
        self.nas_name.setMaxLength(32)
        form.addRow("Unique source name", self.nas_name)
        self.nas_protocol = QComboBox()
        self.nas_protocol.addItems(["NFS", "SMB"])
        form.addRow("Protocol", self.nas_protocol)
        self.nas_server = QLineEdit()
        self.nas_server.setPlaceholderText("192.168.0.146 or nas.internal")
        form.addRow("NAS server", self.nas_server)
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
        browse_actions = QHBoxLayout()
        browse_actions.addWidget(self.register(push(
            "Discover server shares / NFS exports", self.discover_shares, True)))
        browse_actions.addWidget(self.register(push(
            "Browse selected SMB share folders", self.discover_remote_folders, True)))
        page.layout_.addLayout(browse_actions)
        self.nas_discovery = QTableWidget(0, 3)
        self.nas_discovery.setHorizontalHeaderLabels(
            ["Share / folder", "Details", "Available for mapping"])
        self.nas_discovery.setEditTriggers(QTableWidget.NoEditTriggers)
        self.nas_discovery.setSelectionBehavior(QTableWidget.SelectRows)
        self.nas_discovery.setSelectionMode(QTableWidget.SingleSelection)
        self.nas_discovery.horizontalHeader().setStretchLastSection(True)
        self.nas_discovery.setMinimumHeight(145)
        self.nas_discovery.itemSelectionChanged.connect(self.select_discovery)
        page.add(self.nas_discovery)
        self.nas_browse_folder = QLineEdit()
        self.nas_browse_folder.setPlaceholderText("Optional SMB subfolder: Albums / Rock")
        form.addRow("Browse within share", self.nas_browse_folder)
        page.add(note("Select a discovered share to populate the mapping. SMB folder browsing uses "
                      "temporary protected credentials and does not mount or modify source files. "
                      "NFS shows exports advertised by the server; some NFSv4 servers disable export listing."))
        page.add(note("A system authentication dialog will ask permission to mount the NAS. SMB credentials are never included in command arguments or displayed in activity logs."))
        page.add(self.register(push("Connect and configure source", self.mount_nas)))
        page.add(self.register(push("Apply configuration to audio daemon", self.restart_daemon, True)))
        page.add(note("Each source mounts at /mnt/radio-music/NAME. Its original audio stays on that NAS. "
                      "Multiple NFS and SMB sources can coexist. A legacy mount directly at /mnt/radio-music "
                      "must be migrated safely before adding named sources."))
        page.finish()
        self.add_page(page)

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
        box = QGroupBox("Choose source, folder and Rivendell category")
        form = QFormLayout(box)
        self.import_source = QComboBox()
        self.import_source.addItem("Select a mounted source", "")
        form.addRow("NAS source", self.import_source)
        self.import_source.currentIndexChanged.connect(self._source_changed)
        self.import_group = QComboBox()
        self.import_group.addItem("Load existing station groups", "")
        form.addRow("Import into category / group", self.import_group)
        self.import_folder_path = QLineEdit()
        self.import_folder_path.setReadOnly(True)
        self.import_folder_path.setPlaceholderText("Entire selected share")
        form.addRow("Selected subfolder", self.import_folder_path)
        form.addRow("Preview up to", self.import_count)
        page.add(box)
        selection_actions = QHBoxLayout()
        selection_actions.addWidget(self.register(push("Refresh categories", self.load_groups, True)))
        selection_actions.addWidget(self.register(push("Manage groups in RDAdmin",
                            lambda: self.launch("rdadmin"), True)))
        selection_actions.addWidget(self.register(push("Browse source folders", self.browse_import_folders, True)))
        selection_actions.addWidget(self.register(push("Up one folder", self.import_folder_parent, True)))
        page.layout_.addLayout(selection_actions)
        self.import_folder_list = QListWidget()
        self.import_folder_list.setMinimumHeight(115)
        self.import_folder_list.itemDoubleClicked.connect(self.enter_import_folder)
        page.add(self.import_folder_list)
        actions = QHBoxLayout()
        actions.addWidget(self.register(push("Preview scan", self.scan_import)))
        actions.addWidget(self.register(push("Import all supported tracks", self.import_music, True)))
        page.layout_.addLayout(actions)
        page.add(note("Import into any existing Rivendell group, such as MUSIC, IDENTS, STINGS "
                      "or JINGLES if configured. Use RDAdmin to create new categories and "
                      "RDLogManager to place them in clocks/grids. Original audio stays read-only. "
                      "FLAC external playback is not yet qualified. Stop RDAirPlay before importing."))
        self.import_output = QPlainTextEdit()
        self.import_output.setReadOnly(True)
        self.import_output.setFont(QFont("DejaVu Sans Mono", 10))
        self.import_output.setMinimumHeight(210)
        page.add(self.import_output)
        page.finish()
        self.add_page(page)

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
        page.add(self.register(push("Open listener request page", self.open_listener, True)))
        page.add(note("Listener site: http://127.0.0.1:8787/requests (only on this machine). The station accepts submissions for moderation; external access requires a correctly secured TLS reverse proxy and client-specific rate limiting. Live insertion remains unqualified."))
        page.finish()
        self.add_page(page)

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
        self.add_page(page)

    def _audio(self):
        page = Panel("Audio routing",
            "Discover the actual JACK ports before connecting Rivendell outputs to the encoder inputs. Routing controls do not start or replace RDAirPlay.")
        page.add(self.register(push("Discover live JACK ports", lambda: self.execute(
            ["rdcomplete-jack-route", "--discover"], "audio-discover"))))
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
        self.add_page(page)

    def _scheduling(self):
        page = SchedulePanel(self)
        self.add_page(page)

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
        self.errors = bytearray()
        self.smb_secret = data
        for button in self.buttons:
            button.setEnabled(False)
        self.progress.show()
        self.status.setText(f"Running: {mode}. Do not close the application.")
        self.command = QProcess(self)
        self.command.setProcessChannelMode(QProcess.SeparateChannels)
        self.command.readyReadStandardOutput.connect(self._read_output)
        self.command.readyReadStandardError.connect(self._read_error)
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

    def _read_error(self):
        if self.command is None:
            return
        chunk = bytes(self.command.readAllStandardError())
        if len(self.errors) < 1024 * 1024:
            self.errors.extend(chunk[:1024 * 1024 - len(self.errors)])
        if self.mode != "catalog":
            line = chunk.decode("utf-8", "replace")
            if self.mode in ("scan", "import"):
                self.import_output.insertPlainText(line)
                self.import_output.ensureCursorVisible()
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
        self._read_error()
        mode = self.mode
        good = code == 0 and status == QProcess.NormalExit
        self.busy = False
        self.progress.hide()
        for button in self.buttons:
            button.setEnabled(True)
        self.status.setText(f"{mode}: {'completed' if good else 'failed (exit '+str(code)+')'}")
        if mode == "nas-discovery" and good:
            try:
                self._show_nas_discovery(bytes(self.output))
            except (ValueError, KeyError, TypeError) as exc:
                good = False
                self._alert(f"NAS discovery returned invalid data: {exc}")
        if mode == "group-list" and good:
            try:
                self._show_groups(bytes(self.output))
            except (ValueError, KeyError, TypeError) as exc:
                good = False
                self._alert(f"Group list unavailable: {exc}")
        if mode == "import-folders" and good:
            try:
                self._show_import_folders(bytes(self.output))
            except (ValueError, KeyError, TypeError) as exc:
                good = False
                self._alert(f"Could not browse source folders: {exc}")
        if mode == "mount" and good and self.pending_nas_mapping:
            try:
                name, folder = self.pending_nas_mapping
                self._save_source_folder(name, folder)
            except (OSError, ValueError, RuntimeError) as exc:
                self._alert(f"NAS mounted, but its default import folder could not be saved: {exc}")
            finally:
                self.pending_nas_mapping = None
        if mode == "mount" and not good:
            self.pending_nas_mapping = None
        if mode == "mount-list" and good:
            try:
                self._render_mounts(bytes(self.output))
            except (ValueError, KeyError, TypeError) as exc:
                good = False
                self._alert(f"NAS source inventory invalid: {exc}")
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
        if mode in ("mount", "mount-list", "nas-discovery", "group-list",
                     "import-folders", "import", "scan", "stream-check", "stream-start", "request-start", "route-save", "route-start", "schedule-enable", "audio-discover", "catalog", "restart-audio") and not good:
            details = (bytes(self.output) + b"\n" + bytes(self.errors)).decode("utf-8", "replace")[-1700:]
            self._alert(f"Operation failed (exit {code}).\n\n{details}")
        if mode in ("mount", "readiness") and good:
            QTimer.singleShot(0, self.refresh_mounts)
        if mode == "import" and good:
            QMessageBox.information(self, "Music import completed",
                                    "Import finished. Export an updated request catalog on the Listener requests page.")
        self.command.deleteLater()
        self.command = None
        self.output = bytearray()
        self.errors = bytearray()

    def readiness(self):
        self.health.clear()
        self.execute(["rdcomplete-selftest", "--json"], "readiness")

    def page_changed(self, page: int):
        if page == 2 and not self.groups_loaded and not self.busy:
            self.load_groups()

    def _discovery_command(self, mode: str):
        host = self.nas_server.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,252}", host):
            self._alert("Enter a valid NAS IP address or DNS hostname.")
            return
        smb = self.nas_protocol.currentText() == "SMB"
        args = ["rdcomplete-browse", "--protocol", "smb" if smb else "nfs",
                "--mode", mode, "--server", host]
        if mode == "folders":
            if not smb:
                self._alert("NFS folders are available after mounting an advertised export.")
                return
            source = self.nas_source.text().strip()
            prefix = f"//{host}/"
            if not source.startswith(prefix):
                self._alert("Select a discovered share first.")
                return
            args += ["--share", source[len(prefix):],
                     "--folder", self.nas_browse_folder.text().strip()]
        secret = None
        if smb:
            username = self.nas_username.text().strip()
            password = self.nas_password.text()
            if not username or not password:
                self._alert("Enter the SMB username and password to discover shares.")
                return
            secret = json.dumps({"username": username, "password": password}).encode("utf-8")
        self.nas_discovery_mode = mode
        self.execute(args, "nas-discovery", secret)

    def discover_shares(self):
        self._discovery_command("shares")

    def discover_remote_folders(self):
        self._discovery_command("folders")

    def _show_nas_discovery(self, raw: bytes):
        result = json.loads(raw)
        mode = self.nas_discovery_mode
        if mode == "shares":
            rows = result.get("shares")
        else:
            rows = [{"name": value, "mountable": True,
                     "description": "Directory"} for value in result.get("folders", [])]
        if not isinstance(rows, list):
            raise ValueError("NAS discovery returned an invalid share list")
        self.nas_discovery_rows = rows
        self.nas_discovery.setRowCount(len(rows))
        for r, item in enumerate(rows):
            for c, value in enumerate([
                item["name"], item.get("description", ""),
                "Selectable" if item.get("mountable") else "Unsupported share name",
            ]):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.nas_discovery.setItem(r, c, cell)
        self.status.setText(f"Discovered {len(rows)} {'shares/exports' if mode=='shares' else 'folders'}")

    def select_discovery(self):
        row = self.nas_discovery.currentRow()
        if row < 0 or row >= len(self.nas_discovery_rows):
            return
        choice = self.nas_discovery_rows[row]
        if not choice.get("mountable"):
            return
        if self.nas_discovery_mode == "shares":
            host = self.nas_server.text().strip()
            name = choice["name"]
            self.nas_source.setText(
                f"//{host}/{name}" if self.nas_protocol.currentText() == "SMB"
                else f"{host}:{name}")
            suggested = re.sub(r"[^a-z0-9_-]", "-", str(name).lower()).strip("-")
            if suggested and not self.nas_name.text():
                self.nas_name.setText(("share-" + suggested)[:32])
            self.nas_browse_folder.clear()
        else:
            folder = self.nas_browse_folder.text().strip()
            self.nas_browse_folder.setText("/".join(filter(None, (folder, choice["name"]))))

    def load_groups(self):
        self._root("list-groups", mode="group-list")

    def _show_groups(self, raw: bytes):
        result = json.loads(raw)
        groups = result.get("groups")
        if not isinstance(groups, list):
            raise ValueError("Invalid Rivendell group list")
        old = self.import_group.currentData()
        self.import_group.clear()
        self.import_group.addItem("Select a category", "")
        for group in groups:
            if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}", group):
                self.import_group.addItem(group, group)
        prior = self.import_group.findData(old)
        if prior > 0:
            self.import_group.setCurrentIndex(prior)
        else:
            music = self.import_group.findData("MUSIC")
            if music > 0:
                self.import_group.setCurrentIndex(music)
        self.groups_loaded = True

    def browse_import_folders(self):
        name = self.import_source.currentData()
        if not name:
            self._alert("Choose the NAS source first.")
            return
        if name != self.last_import_source:
            self._source_changed()
        self.execute(["rdcomplete-source-folders", "--source", name,
                      "--folder", self.import_folder], "import-folders")

    def _show_import_folders(self, raw: bytes):
        result = json.loads(raw)
        if not isinstance(result.get("folders"), list):
            raise ValueError("Invalid source folders listing")
        self.import_folder_path.setText(result["folder"] or "/ (entire source)")
        self.import_folder_list.clear()
        for folder in result["folders"]:
            self.import_folder_list.addItem(folder)

    def enter_import_folder(self, item):
        if self.busy:
            return
        folder = item.text()
        if folder in (".", "..") or "/" in folder or any(ord(c) < 32 for c in folder):
            return
        self.import_folder = "/".join(filter(None, (self.import_folder, folder)))
        self.browse_import_folders()

    def import_folder_parent(self):
        if self.busy:
            return
        self.import_folder = "/".join(self.import_folder.split("/")[:-1])
        self.browse_import_folders()

    def _load_source_folders(self):
        target = CONFIG / "nas-source-folders.json"
        if not target.exists() and not target.is_symlink():
            return {}
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("Unsafe NAS source folder settings; refusing to read")
        obj = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                            for k, v in obj.items()):
            raise ValueError("Invalid saved NAS folder settings")
        return obj

    def _save_source_folder(self, name: str, folder: str):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
            raise ValueError("Invalid source name")
        if folder and (len(folder) > 1024 or
                       any(not component or component in (".", "..") or
                           any(ord(ch) < 32 or ord(ch) == 127 for ch in component)
                           for component in folder.split("/"))):
            raise ValueError("Invalid selected source folder")
        if CONFIG.is_symlink():
            raise RuntimeError("Unsafe configuration directory")
        CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
        if CONFIG.stat().st_uid != os.getuid() or CONFIG.stat().st_mode & 0o077:
            raise RuntimeError("Station configuration directory owner or mode unsafe")
        target = CONFIG / "nas-source-folders.json"
        current = self._load_source_folders()
        current[name] = folder
        import tempfile
        fd, temp = tempfile.mkstemp(prefix=".nas-source-", dir=CONFIG)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o600)
                json.dump(current, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _source_changed(self):
        name = self.import_source.currentData()
        self.last_import_source = name or ""
        self.import_folder = ""
        if not name:
            self.import_folder_path.clear()
            return
        try:
            folder = self._load_source_folders().get(name, "")
            if folder:
                self.import_folder = folder
            self.import_folder_path.setText(self.import_folder or "/ (entire source)")
        except (OSError, ValueError, RuntimeError) as exc:
            self.import_folder_path.setText("Source folder settings unavailable")
            self._alert(str(exc))

    def mount_nas(self):
        name = self.nas_name.text().strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
            self._alert("Enter a unique source name (lowercase a-z, digits, - or _, starting with a letter).")
            return
        src = self.nas_source.text().strip()
        smb = self.nas_protocol.currentText() == "SMB"
        pattern = (r"//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+"
                   if smb else r"[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+")
        if not re.fullmatch(pattern, src):
            self._alert("Enter a valid full NAS share/export path.")
            return
        folder = self.nas_browse_folder.text().strip()
        if folder and (len(folder) > 1024 or
                       any(not component or component in (".", "..") or
                           any(ord(ch) < 32 or ord(ch) == 127 for ch in component)
                           for component in folder.split("/"))):
            self._alert("Choose a safe existing NAS subfolder, without parent traversal.")
            return
        creds = None
        if smb:
            user = self.nas_username.text()
            password = self.nas_password.text()
            if not user or not password or any(c in "\r\n=\\" for c in user) or "\n" in password or "\r" in password:
                self._alert("SMB username/password invalid or missing.")
                return
            creds = f"{user}\n{password}\n".encode()
        if not self._confirm("Add read-only NAS source",
                f"Add '{name}' from {src} at /mnt/radio-music/{name}?\n\n"
                "Every source keeps its own read-only mount and credentials. "
                "No original audio files will be copied or modified."):
            return
        self.nas_password.clear()
        self.pending_nas_mapping = (name, folder)
        self._root("mount-smb" if smb else "mount-nfs",
                   ["--source", src, "--name", name], creds, "mount")

    def restart_daemon(self):
        if not self._confirm("Restart Rivendell audio services",
                "Apply the NAS configuration by restarting the Rivendell service?\n\n"
                "RDAirPlay must be stopped, and any live playback would be interrupted."):
            return
        self._root("restart-audio", mode="restart-audio")

    def refresh_mounts(self):
        self.execute(["rdcomplete-mounts", "--json"], "mount-list")

    def _mount_selection(self):
        name = self.import_source.currentData()
        if not name:
            self._alert("Select a mounted source before scanning or importing.")
            return None
        group = self.import_group.currentData()
        if not group:
            self._alert("Select a destination category. Create new categories in RDAdmin.")
            return None
        if name != self.last_import_source:
            self._source_changed()
        args = [] if name == "legacy" else ["--name", name]
        if self.import_folder:
            args += ["--folder", self.import_folder]
        return args, group

    def _render_mounts(self, raw: bytes):
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError("Invalid NAS mount inventory")
        old = self.import_source.currentData()
        self.import_source.blockSignals(True)
        self.import_source.clear()
        self.import_source.addItem("Select a mounted source", "")
        self.mount_table.setRowCount(len(items))
        for r, item in enumerate(items):
            for c, value in enumerate([
                item["name"], item["protocol"], item["source"], item["path"],
                "Read-only · Online" if item["readonly"] else "Offline / Unsafe",
            ]):
                cell = QTableWidgetItem(str(value))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.mount_table.setItem(r, c, cell)
            if item["readonly_configured"]:
                self.import_source.addItem(
                    f'{item["name"]} · {item["protocol"]} · {item["source"]}' +
                    ("" if item["readonly"] else " · offline (check before import)"),
                    item["name"])
        index = self.import_source.findData(old)
        if index > 0:
            self.import_source.setCurrentIndex(index)
        elif self.import_source.count() == 2:
            self.import_source.setCurrentIndex(1)
        self.import_source.blockSignals(False)
        self._source_changed()

    def scan_import(self):
        selection = self._mount_selection()
        if selection is None:
            return
        selected, group = selection
        self.import_output.clear()
        self._root("scan", ["--group", group, *selected,
                            "--limit", str(self.import_count.value())], mode="scan")

    def import_music(self):
        selection = self._mount_selection()
        if selection is None:
            return
        selected, group = selection
        if not self._confirm("Import music metadata",
                f"Register supported new files into {group}? This creates cart records and "
                "small local reference files, but does NOT modify music stored on the NAS.\n\n"
                "RDAirPlay must be stopped. Existing carts will not be overwritten."):
            return
        self.import_output.clear()
        self._root("import", ["--group", group, *selected], mode="import")

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

    def open_listener(self):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        if not QDesktopServices.openUrl(QUrl("http://127.0.0.1:8787/requests")):
            self._alert("Could not open the local listener request page.")

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
