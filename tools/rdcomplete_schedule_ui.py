#!/usr/bin/python3
"""Integrated station-programming page for Rivendell Complete native Qt UI.

Creates an offline future Rivendell log with verified playable categories,
measured hard-ID length, optional jingle/bed, explicit preview and commit.
Never alters an existing or loaded log. Writes the protected 24-hour plan only
after a successful rdclilogedit commit using existing rdstationplan.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile

from PyQt5.QtCore import QDate, QProcess, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDateEdit, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget
)

STATE = Path.home() / ".local/state/rivendell-complete"
ROOT_HELPER = "/usr/local/libexec/rivendell-complete/rdcomplete_root.py"
GROUP_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}\Z")
LOG_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class ScheduleError(RuntimeError):
    pass


def secure_write(name: str, value, *, state: Path = STATE) -> Path:
    if name not in ("working-schedule-catalog.json", "working-schedule-config.json"):
        raise ScheduleError("Unexpected generated schedule filename")
    if state.is_symlink():
        raise ScheduleError("Station state directory may not be a symlink")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    entry = state.stat()
    if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != os.getuid() or entry.st_mode & 0o077:
        raise ScheduleError("Station state directory is unsafe")
    path = state / name
    if path.is_symlink() or (
        path.exists() and (
            not path.is_file() or path.stat().st_uid != os.getuid()
            or path.stat().st_mode & 0o077
        )
    ):
        raise ScheduleError("Generated scheduling cache is unsafe")
    fd, temp = tempfile.mkstemp(prefix=".schedule-", dir=state)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def validate_spec(groups: str, id_cart: int, jingle: int, fill_bed: int,
                  every: int, date: str, name: str) -> dict:
    rotation = [item.strip() for item in groups.split(",")]
    if not 1 <= len(rotation) <= 24 or any(not GROUP_RE.fullmatch(item) for item in rotation):
        raise ScheduleError("Select 1–24 existing rotation categories (e.g. MUSIC,GOLD).")
    if type(id_cart) is not int or not 1 <= id_cart <= 999999:
        raise ScheduleError("Choose a valid, actual top-of-hour identification cart.")
    for value in (jingle, fill_bed):
        if type(value) is not int or not 0 <= value <= 999999:
            raise ScheduleError("Jingle and bed carts must be 0–999999.")
    if not 1 <= every <= 25:
        raise ScheduleError("Jingle frequency outside 1–25 tracks.")
    try:
        day = QDate.fromString(date, "yyyy-MM-dd")
    except TypeError as exc:
        raise ScheduleError("Invalid broadcast date") from exc
    if not day.isValid() or day < QDate.currentDate():
        raise ScheduleError("Broadcast date must be today or later.")
    if not isinstance(name, str) or not LOG_RE.fullmatch(name):
        raise ScheduleError("Use a unique 1–64-character Rivendell log name.")
    return {
        "rotation": rotation, "id": id_cart, "jingle": jingle,
        "fill_bed": fill_bed, "every": every, "date": date, "log": name,
    }


def derive_config(spec: dict, data: dict) -> tuple[list[dict], dict]:
    tracks = data.get("tracks")
    specials = data.get("specials")
    if not isinstance(tracks, list) or not tracks or not isinstance(specials, dict):
        raise ScheduleError("No playable tracks in the selected rotation categories.")
    identity = specials.get("top_hour")
    if not isinstance(identity, dict) or identity.get("cart") != spec["id"]:
        raise ScheduleError("The station ID cart was not validated against Rivendell.")
    cfg = {
        "service": "Production",
        "rotation": spec["rotation"],
        "top_hour": {"cart": identity["cart"], "duration_ms": identity["duration_ms"]},
        "artist_separation_minutes": 120,
        "album_separation_minutes": 60,
        "title_separation_minutes": 1440,
        "max_segment_gap_ms": 30000,
        "max_requests_per_hour": 2,
    }
    for key, field in (("jingle", "jingle"), ("fill_bed", "fill_bed")):
        chosen = spec[field]
        if not chosen:
            continue
        card = specials.get(key)
        if not isinstance(card, dict) or card.get("cart") != chosen:
            raise ScheduleError(f"Selected {key} cart is not playable.")
        cfg[key] = {"cart": card["cart"], "duration_ms": card["duration_ms"]}
    if spec["jingle"]:
        cfg["jingle_every"] = spec["every"]
    return tracks, cfg


class SchedulePanel(QWidget):
    def __init__(self, host: QWidget):
        super().__init__()
        self.host = host
        self.preview_spec: dict | None = None
        self.pending_spec: dict | None = None
        self.proc: QProcess | None = None
        self.mode = ""
        self.stdout = bytearray()
        self.stderr = bytearray()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(14)
        heading = QLabel("Programming & scheduling")
        heading.setFont(QFont("DejaVu Sans", 22, QFont.Bold))
        outer.addWidget(heading)
        intro = QLabel("Turn imported music categories into a future 24-hour Production log. "
                       "Rivendell keeps control of the on-air audio engine.")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        box = QGroupBox("Create a future station log")
        fields = QFormLayout(box)
        self.groups = QLineEdit("MUSIC")
        self.groups.setPlaceholderText("MUSIC,GOLD,POWER")
        self.groups.setToolTip("Comma-separated existing groups. Repeating a group weights its rotation.")
        fields.addRow("Music rotation categories", self.groups)
        self.id_cart = QSpinBox()
        self.id_cart.setRange(0, 999999)
        self.id_cart.setSpecialValueText("Select real station ID cart")
        fields.addRow("Top-of-hour legal ID cart", self.id_cart)
        self.jingle_cart = QSpinBox()
        self.jingle_cart.setRange(0, 999999)
        self.jingle_cart.setSpecialValueText("No jingle cart")
        fields.addRow("Optional jingle cart", self.jingle_cart)
        self.jingle_every = QSpinBox()
        self.jingle_every.setRange(1, 25)
        self.jingle_every.setValue(4)
        fields.addRow("Jingle every N songs", self.jingle_every)
        self.fill_bed = QSpinBox()
        self.fill_bed.setRange(0, 999999)
        self.fill_bed.setSpecialValueText("No fill bed")
        fields.addRow("Optional timing bed", self.fill_bed)
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy-MM-dd")
        self.day.setMinimumDate(QDate.currentDate())
        self.day.setDate(QDate.currentDate().addDays(1))
        fields.addRow("Broadcast date", self.day)
        self.log = QLineEdit("RC" + self.day.date().toString("yyyyMMdd"))
        self.log.setMaxLength(64)
        fields.addRow("New Rivendell log", self.log)
        outer.addWidget(box)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("Preview category rotation")
        self.commit_button = QPushButton("Create future Rivendell log")
        self.commit_button.setEnabled(False)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.commit_button)
        outer.addLayout(actions)
        self.preview_button.clicked.connect(self.preview)
        self.commit_button.clicked.connect(self.commit)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("DejaVu Sans Mono", 10))
        self.output.setMinimumHeight(200)
        outer.addWidget(self.output)

        comment = QLabel("Lengths are read from actual CART records; the planner refuses "
                         "unfillable hours and protects all 24 legal IDs. The result is "
                         "a new offline log, never a replacement for the playing log. "
                         "Advanced commercials, clocks and hourly grids remain in RDLogManager.")
        comment.setWordWrap(True)
        outer.addWidget(comment)
        tools = QHBoxLayout()
        for text, binary in [
            ("Program hourly clocks / grids", "rdlogmanager"),
            ("Inspect future logs", "rdlogedit"),
            ("Manage ID / jingle carts", "rdlibrary"),
        ]:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, program=binary:
                                   self.host.launch(program))
            tools.addWidget(button)
        outer.addLayout(tools)
        outer.addStretch(1)
        self.status = QLabel("Preview a configured rotation before creating a future log.")
        outer.addWidget(self.status)

        for field in (self.groups, self.id_cart, self.jingle_cart, self.jingle_every,
                      self.fill_bed, self.day, self.log):
            signal = getattr(field, "textChanged", None) or getattr(field, "valueChanged", None) \
                     or getattr(field, "dateChanged", None)
            if signal is not None:
                signal.connect(self.invalidate)

    def invalidate(self, *_):
        self.commit_button.setEnabled(False)
        self.preview_spec = None

    def spec(self) -> dict:
        return validate_spec(
            self.groups.text(), self.id_cart.value(), self.jingle_cart.value(),
            self.fill_bed.value(), self.jingle_every.value(),
            self.day.date().toString("yyyy-MM-dd"), self.log.text().strip())

    def alert(self, message: str):
        QMessageBox.warning(self, "Production scheduling", message)

    def run(self, args: list[str], mode: str):
        if self.proc is not None:
            self.alert("A scheduling operation is already running.")
            return
        self.mode = mode
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.preview_button.setEnabled(False)
        self.commit_button.setEnabled(False)
        self.status.setText("Running " + mode + "...")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self.read_out)
        self.proc.readyReadStandardError.connect(self.read_err)
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(self.process_error)
        self.proc.start(args[0], args[1:])

    def read_out(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput())
        if len(self.stdout) + len(data) > 50 * 1024 * 1024:
            self.proc.kill()
            self.status.setText("Schedule output exceeded 50 MiB.")
            return
        self.stdout.extend(data)

    def read_err(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardError())
        if len(self.stderr) < 1024 * 1024:
            self.stderr.extend(data[:1024 * 1024 - len(self.stderr)])

    def process_error(self, failure):
        if failure == QProcess.FailedToStart:
            self.status.setText("Required scheduler executable missing.")

    def finished(self, code, exit_status):
        self.read_out()
        self.read_err()
        mode = self.mode
        good = code == 0 and exit_status == QProcess.NormalExit
        output = bytes(self.stdout)
        errors = bytes(self.stderr).decode("utf-8", "replace")[-2500:]
        self.proc.deleteLater()
        self.proc = None
        self.preview_button.setEnabled(True)
        if not good:
            self.preview_spec = None
            self.commit_button.setEnabled(False)
            self.status.setText(f"Schedule {mode} failed (exit {code}).")
            self.output.setPlainText(errors)
            self.alert(errors or "Schedule operation failed; no on-air changes were made.")
            return
        if mode == "catalog":
            try:
                spec = self.pending_spec
                if spec is None:
                    raise ScheduleError("No pending schedule configuration")
                result = json.loads(output)
                tracks, cfg = derive_config(spec, result)
                secure_write("working-schedule-catalog.json", tracks)
                secure_write("working-schedule-config.json", cfg)
            except (ValueError, TypeError, KeyError, OSError, ScheduleError) as exc:
                self.preview_spec = None
                self.status.setText("Schedule preparation failed.")
                self.alert(str(exc))
                return
            QTimer.singleShot(0, lambda: self.run_planner(False))
        elif mode == "preview":
            self.preview_spec = self.pending_spec
            self.commit_button.setEnabled(True)
            self.output.setPlainText(output.decode("utf-8", "replace")[:500000])
            self.status.setText("Schedule preview passed. Review the proposed log, then explicitly create it.")
        elif mode == "commit":
            self.preview_spec = None
            self.commit_button.setEnabled(False)
            self.output.setPlainText(errors or "Future log created.")
            self.status.setText("New future Rivendell log committed.")
            QMessageBox.information(
                self, "Future log created",
                "The new future log and its protected 24-hour ledger have been created. "
                "Review the log in RDLogEdit before loading it into RDAirPlay.")

    def preview(self):
        try:
            spec = self.spec()
        except ScheduleError as exc:
            self.alert(str(exc))
            return
        self.pending_spec = spec
        self.preview_spec = None
        self.output.clear()
        args = [
            "pkexec", "/usr/bin/python3", ROOT_HELPER, "schedule-catalog",
            "--groups", ",".join(dict.fromkeys(spec["rotation"])),
            "--id-cart", str(spec["id"]),
            "--jingle-cart", str(spec["jingle"]),
            "--fill-cart", str(spec["fill_bed"]),
        ]
        self.run(args, "catalog")

    def run_planner(self, commit: bool):
        spec = self.pending_spec
        if spec is None:
            self.alert("No schedule has been prepared.")
            return
        command = [
            "rdcomplete-stationplan",
            "--config", str(STATE / "working-schedule-config.json"),
            "--catalog", str(STATE / "working-schedule-catalog.json"),
            "--date", spec["date"],
            "--log-name", spec["log"],
        ]
        db = STATE / "requests.sqlite"
        if db.is_file() and not db.is_symlink():
            command += ["--requests-db", str(db)]
        if commit:
            folder = STATE / "plans"
            if folder.is_symlink():
                self.alert("Invalid protected scheduling ledger folder.")
                return
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            state = folder.stat()
            if state.st_uid != os.getuid() or state.st_mode & 0o077:
                self.alert("Schedule ledger directory permissions are unsafe.")
                return
            ledger = folder / (spec["date"] + ".plan.json")
            if ledger.exists() or ledger.is_symlink():
                self.alert("Protected schedule for this date exists. Refusing overwrite.")
                return
            command += ["--commit", "--report-json", str(ledger)]
        self.run(command, "commit" if commit else "preview")

    def commit(self):
        try:
            spec = self.spec()
        except ScheduleError as exc:
            self.alert(str(exc))
            return
        if spec != self.preview_spec or spec != self.pending_spec:
            self.alert("Preview the current scheduling selections first.")
            return
        if QMessageBox.question(
            self, "Create future Production log",
            f"Create the new log '{spec['log']}' for {spec['date']}?\n\n"
            "This writes a FUTURE Rivendell log only. The existing on-air log "
            "and media files will not be modified.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self.output.clear()
        self.run_planner(True)
