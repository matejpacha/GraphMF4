"""Guided TXT import with editable column names and live numeric preview."""

from __future__ import annotations

from csv import Error as CsvError
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.txt_import import import_txt_to_mf4, parse_txt_values, read_txt_table


class TxtImportThread(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, source, destination, options, parent=None):
        super().__init__(parent)
        self.source = source
        self.destination = destination
        self.options = options

    def run(self):
        try:
            output = import_txt_to_mf4(self.source, self.destination, **self.options)
            self.completed.emit(str(output))
        except Exception as exc:
            self.failed.emit(str(exc))


class TxtImportDialog(QDialog):
    def __init__(self, source: str, loaded_files: list[str], parent=None):
        super().__init__(parent)
        self.source = source
        self.output_path: str | None = None
        self._loaded_files = {Path(path).resolve() for path in loaded_files}
        self._rows = []
        self._names = []
        self._name_edits = []
        self._thread = None
        self.setWindowTitle("Import TXT → MF4")
        self.resize(940, 650)
        layout = QVBoxLayout(self)
        source_label = QLabel(f"Zdroj: {Path(source).name}")
        source_label.setToolTip(source)
        layout.addWidget(source_label)
        hint = QLabel(
            "1. Nastavte formát a čas.  2. Upravte názvy sloupců.  "
            "3. Uložte MF4 — soubor se přidá do aktuálního projektu.\n"
            "První řádek je hlavička; data musí být číselná. Náhled ukazuje až 10 vzorků."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self._delimiter = QComboBox()
        for label, value in [
            ("Tabulátor", "\t"),
            ("Středník", ";"),
            ("Čárka", ","),
            ("Mezera", " "),
        ]:
            self._delimiter.addItem(label, value)
        form.addRow("Oddělovač sloupců:", self._delimiter)
        self._decimal = QComboBox()
        self._decimal.addItem("Čárka (1,25)", ",")
        self._decimal.addItem("Tečka (1.25)", ".")
        form.addRow("Desetinný formát:", self._decimal)
        self._has_time = QComboBox()
        self._has_time.addItems(["Ne — pravidelné vzorkování", "Ano — vybrat sloupec"])
        form.addRow("Obsahuje sloupec času:", self._has_time)
        self._time_column = QComboBox()
        form.addRow("Časový sloupec (sekundy):", self._time_column)
        self._period = QDoubleSpinBox()
        self._period.setDecimals(9)
        self._period.setRange(0.000000001, 1_000_000)
        self._period.setValue(0.01)
        self._period.setSuffix(" s")
        form.addRow("Perioda vzorkování:", self._period)
        layout.addLayout(form)
        layout.addWidget(QLabel("Názvy signálů — upravte textová pole nad tabulkou:"))
        self._headers = QTableWidget(1, 0)
        self._headers.setMaximumHeight(62)
        self._headers.verticalHeader().hide()
        layout.addWidget(self._headers)
        self._preview = QTableWidget()
        self._preview.verticalHeader().setDefaultSectionSize(24)
        self._preview.setMinimumHeight(280)
        self._preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview)
        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        self._save.setText("Uložit MF4 a načíst…")
        self._buttons.accepted.connect(self._import)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._delimiter.currentIndexChanged.connect(self._read_preview)
        for control in (self._decimal, self._has_time, self._time_column):
            control.currentIndexChanged.connect(self._refresh_preview)
        self._period.valueChanged.connect(self._refresh_preview)
        self._read_preview()

    def _read_preview(self):
        self._headers.clearContents()
        self._name_edits = []
        self._time_column.blockSignals(True)
        self._time_column.clear()
        try:
            header, self._rows = read_txt_table(
                self.source, self._delimiter.currentData(), limit=10
            )
            # Preserve the real sample's repeated ItemNote headers as unique editable names.
            used = set()
            self._names = []
            for index, text in enumerate(header):
                base = text.strip() or f"Signal_{index + 1}"
                name, suffix = base, 2
                while name in used:
                    name = f"{base}_{suffix}"
                    suffix += 1
                used.add(name)
                self._names.append(name)
            self._headers.setColumnCount(len(header))
            self._headers.setHorizontalHeaderLabels([str(i + 1) for i in range(len(header))])
            for index, name in enumerate(self._names):
                edit = QLineEdit(name)
                self._name_edits.append(edit)
                self._headers.setCellWidget(0, index, edit)
                edit.textChanged.connect(self._names_changed)
                self._time_column.addItem(f"{index + 1}: {name}", index)
        except (OSError, UnicodeError, ValueError, CsvError) as exc:
            self._rows = []
            self._names = []
            self._status.setText(str(exc))
            self._save.setEnabled(False)
            self._preview.setRowCount(0)
            return
        finally:
            self._time_column.blockSignals(False)
        self._refresh_preview()

    def _names_changed(self):
        self._names = [edit.text().strip() for edit in self._name_edits]
        for index, name in enumerate(self._names):
            self._time_column.setItemText(index, f"{index + 1}: {name}")
        self._refresh_preview()

    def _options(self):
        return dict(
            names=list(self._names),
            delimiter=self._delimiter.currentData(),
            decimal=self._decimal.currentData(),
            time_column=self._time_column.currentIndex() if self._has_time.currentIndex() else None,
            period=self._period.value(),
        )

    def _refresh_preview(self):
        has_time = bool(self._has_time.currentIndex())
        self._time_column.setEnabled(has_time)
        self._period.setEnabled(not has_time)
        self._save.setEnabled(False)
        self._preview.clear()
        self._preview.setColumnCount(len(self._names) + (not has_time))
        self._preview.setHorizontalHeaderLabels(
            self._names if has_time else ["Čas [s]", *self._names]
        )
        self._preview.setRowCount(len(self._rows))
        # Keep the original values visible even when the selected format is invalid.
        for row_index, (_, row) in enumerate(self._rows):
            for column, value in enumerate(row[: len(self._names)]):
                self._preview.setItem(row_index, column + (not has_time), QTableWidgetItem(value))
        try:
            if self._delimiter.currentData() == "," and self._decimal.currentData() == ",":
                raise ValueError("Čárku nelze použít zároveň pro sloupce i desetinná místa.")
            time, values = parse_txt_values(
                self._rows,
                self._names,
                self._decimal.currentData(),
                self._time_column.currentIndex() if has_time else None,
                self._period.value(),
            )
            for row_index, row in enumerate(values):
                displayed = row if has_time else [time[row_index], *row]
                for column, value in enumerate(displayed):
                    self._preview.setItem(row_index, column, QTableWidgetItem(f"{value:.12g}"))
            self._status.setText(
                f"Náhled: {len(values)} vzorků. Při importu se ověří všechny řádky. "
                + (
                    "Časový sloupec bude použit jako časová osa."
                    if has_time
                    else "Čas začíná v 0 s; jeden řádek = jeden vzorek."
                )
            )
            self._save.setEnabled(True)
        except ValueError as exc:
            self._status.setText(str(exc))
        self._preview.resizeColumnsToContents()

    def _import(self):
        destination, _ = QFileDialog.getSaveFileName(
            self, "Uložit MF4", str(Path(self.source).with_suffix(".mf4")), "MF4 (*.mf4)"
        )
        if not destination:
            return
        path = Path(destination)
        if path.suffix.lower() != ".mf4":
            path = path.with_suffix(".mf4")
            if (
                path.exists()
                and QMessageBox.question(
                    self,
                    "Přepsat soubor?",
                    f"Přepsat {path.name}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        if path.resolve() in self._loaded_files:
            QMessageBox.warning(
                self, "Soubor je používán", "Zvolte jiný název než soubor v projektu."
            )
            return
        progress = QProgressDialog("Import a ukládání MF4…", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._thread = TxtImportThread(self.source, path, self._options(), self)
        self._thread.completed.connect(self._completed)
        self._thread.failed.connect(
            lambda message: QMessageBox.critical(self, "Import selhal", message)
        )
        self._thread.finished.connect(progress.accept)
        self._thread.start()
        progress.exec()
        self._thread.wait()
        if self.output_path:
            self.accept()

    def _completed(self, path):
        self.output_path = path
