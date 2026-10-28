"""Flask server: wires the modules together and serves the user interface.

Listens on 127.0.0.1 only, so the program cannot be reached from other computers.
Started by postalprint/__main__.py (start.bat, the .exe or ``python -m postalprint``).

API error messages are user-facing and therefore in Danish.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from postalprint.addresses import online_check, postcodes, validation
from postalprint.labels import layout, pdf
from postalprint.paths import DATA_DIR
from postalprint.printing import printers
from postalprint.storage.store import Storage


def now() -> datetime:
    """The current local time with UTC offset, to the second."""
    return datetime.now().astimezone().replace(microsecond=0)


def create_app(data_dir: Path | None = None) -> Flask:
    """Creates the Flask app (application factory, so tests can use a temporary data folder).

    Args:
        data_dir: Where config, history and backups are stored. Defaults to paths.DATA_DIR.
    """
    app = Flask(__name__)
    app.json.ensure_ascii = False
    storage = Storage(data_dir or DATA_DIR)
    storage.cleanup_tmp()
    postcode_map = postcodes.load()
    # Labels that are printed but not yet confirmed. Their PDF is already on disk.
    pending: dict[str, dict] = {}
    app.config["STORAGE"] = storage
    app.config["PENDING"] = pending

    def error(message: str, status: int):
        return jsonify({"error": message}), status

    def send_to_printer(pdf_path: Path, pdf_url: str) -> dict:
        """Prints the PDF and describes the outcome for the UI. Errors are returned, not raised."""
        print_config = storage.load_config()["print"]
        result = {"pdf_url": pdf_url, "print_in_browser": False, "print_error": None}
        if print_config["mode"] == "dialog":
            result["print_in_browser"] = True
            return result
        try:
            printers.print_pdf(pdf_path, print_config)
        except printers.PrintError as exc:
            result["print_error"] = str(exc)
        return result

    def online_check_enabled() -> bool:
        return bool(storage.load_config()["address_check"]["online"])

    def ensure_pdf(entry: dict) -> Path:
        """Returns the path to a saved label, recreating the PDF from the history if it is missing."""
        relative = entry.get("pdf_file", "")
        path = storage.pdf_path(relative) if relative else None
        if path is None or not path.exists():
            rotation = storage.load_config()["print"]["rotation"]
            pdf_bytes = pdf.render_label(entry["recipient"], entry["sender"], rotation)
            relative = storage.save_label_pdf(entry["id"], entry["recipient"], pdf_bytes,
                                              datetime.fromisoformat(entry["printed_at"]))
            if relative != entry.get("pdf_file"):
                storage.update_entry(entry["id"], pdf_file=relative)
            path = storage.pdf_path(relative)
        return path

    def find_label(label_id: str) -> dict | None:
        return pending.get(label_id) or storage.get_entry(label_id)

    def status() -> dict:
        """Environment facts shown in Settings."""
        config = storage.load_config()
        return {
            "sumatra_path": printers.find_sumatra(config["print"]["sumatra_path"]),
            "sumatra_download_url": printers.SUMATRA_DOWNLOAD_URL,
            "sender_missing": validation.sender_missing(config["sender"]),
            "history_dir": str(storage.history_dir),
        }

    # --- Pages and static data -----------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/postcodes")
    def get_postcodes():
        """All postcodes, loaded once by the browser for instant city autofill."""
        return send_file(postcodes.POSTCODES_FILE, mimetype="application/json", max_age=3600)

    # --- Labels ---------------------------------------------------------

    @app.post("/api/labels/preview")
    def preview_label():
        """The exact layout the PDF will use, so the live preview matches the printed label."""
        body = request.get_json(silent=True) or {}
        recipient = validation.normalize(body.get("recipient") or {})
        sender = storage.load_config()["sender"]
        return jsonify(layout.build_layout(recipient, sender).to_dict())

    @app.post("/api/address/check")
    def check_address():
        """Online check (layer 2) while typing. Called by the browser after a short pause."""
        if not online_check_enabled():
            return jsonify(online_check.AddressCheck(online_check.SKIPPED).to_dict())
        body = request.get_json(silent=True) or {}
        street = validation.normalize_text(body.get("street"))
        postcode = validation.normalize_postcode(body.get("postcode"))
        return jsonify(online_check.check_address(street, postcode).to_dict())

    @app.post("/api/labels/print")
    def print_label():
        """Validates, renders, saves and prints a label.

        Responds 422 with errors, 409 with warnings (unless ``force`` is true),
        or 200 with the label id and the print outcome.
        """
        body = request.get_json(silent=True) or {}
        config = storage.load_config()
        sender = config["sender"]

        # Layer 1: offline checks. Errors block printing.
        result = validation.validate(body.get("recipient") or {}, sender, postcode_map, storage.recent_entries())
        if result.errors:
            return jsonify({"errors": result.errors, "warnings": result.warnings}), 422

        # Layer 2: online check. Only a warning, and skipped without internet.
        if config["address_check"]["online"]:
            check = online_check.check_address(result.recipient["street"], result.recipient["postcode"])
            if check.is_warning:
                result.warnings["address"] = check.message

        if result.warnings and not body.get("force"):
            return jsonify({"warnings": result.warnings}), 409

        label_id = str(uuid.uuid4())
        printed_at = now()
        pdf_bytes = pdf.render_label(result.recipient, sender, config["print"]["rotation"])
        # The PDF is saved BEFORE printing, so it exists even if printing fails
        pdf_file = storage.save_label_pdf(label_id, result.recipient, pdf_bytes, printed_at)
        pending[label_id] = {
            "id": label_id,
            "printed_at": printed_at.isoformat(),
            "recipient": result.recipient,
            "sender": dict(sender),  # stored per entry, so old labels can be recreated exactly
            "pdf_file": pdf_file,
            "reprints": 0,
        }
        response = send_to_printer(storage.pdf_path(pdf_file), f"/api/labels/{label_id}/pdf")
        return jsonify({"id": label_id, "recipient": result.recipient} | response)

    @app.post("/api/labels/<label_id>/confirm")
    def confirm_label(label_id: str):
        """The label came out fine: move it from pending to the history."""
        entry = pending.pop(label_id, None)
        if entry is None:
            return error("Etiketten findes ikke (er programmet blevet genstartet?).", 404)
        storage.append_history(entry)
        return jsonify({"ok": True})

    @app.post("/api/labels/<label_id>/reprint")
    def reprint_pending(label_id: str):
        entry = pending.get(label_id)
        if entry is None:
            return error("Etiketten findes ikke (er programmet blevet genstartet?).", 404)
        return jsonify({"id": label_id} | send_to_printer(storage.pdf_path(entry["pdf_file"]),
                                                          f"/api/labels/{label_id}/pdf"))

    @app.post("/api/labels/<label_id>/cancel")
    def cancel_label(label_id: str):
        """Drops a pending label without saving it to the history. The PDF stays on disk."""
        pending.pop(label_id, None)
        return jsonify({"ok": True})

    @app.get("/api/labels/<label_id>/pdf")
    def label_pdf_file(label_id: str):
        """Shows a pending or historical label's PDF in the browser."""
        entry = find_label(label_id)
        if entry is None:
            abort(404)
        path = ensure_pdf(entry)
        return send_file(path, mimetype="application/pdf", download_name=path.name)

    # --- History --------------------------------------------------------

    @app.get("/api/history")
    def history():
        return jsonify({"entries": storage.search_history(request.args.get("q", ""))})

    @app.post("/api/history/<entry_id>/reprint")
    def reprint_history(entry_id: str):
        """Prints a saved label again and counts the reprint if it succeeded."""
        entry = storage.get_entry(entry_id)
        if entry is None:
            return error("Etiketten findes ikke i historikken.", 404)
        response = send_to_printer(ensure_pdf(entry), f"/api/labels/{entry_id}/pdf")
        if not response["print_error"]:
            storage.increment_reprints(entry_id)
        return jsonify({"id": entry_id} | response)

    @app.post("/api/history/folder/open")
    def open_history_folder():
        """Opens data/historik/ in Explorer, for finding a PDF and printing it manually."""
        storage.history_dir.mkdir(parents=True, exist_ok=True)
        try:
            printers.open_file(storage.history_dir)
        except OSError as exc:
            return error(f"Mappen kunne ikke åbnes: {exc}", 500)
        return jsonify({"ok": True})

    # --- Settings -------------------------------------------------------

    @app.get("/api/config")
    def get_config():
        return jsonify({"config": storage.load_config(), "status": status()})

    @app.put("/api/config")
    def put_config():
        """Validates and saves Settings. Responds 422 with errors keyed as "sender.name" etc."""
        body = request.get_json(silent=True) or {}
        config = storage.load_config()
        sender, sender_errors = validation.validate_sender(body.get("sender") or {}, postcode_map)
        errors = {f"sender.{key}": message for key, message in sender_errors.items()}

        print_body = body.get("print") or {}
        mode = print_body.get("mode", config["print"]["mode"])
        if mode not in printers.MODES:
            errors["print.mode"] = "Ukendt print-tilstand."
        try:
            rotation = int(print_body.get("rotation", config["print"]["rotation"]))
        except (TypeError, ValueError):
            rotation = 0
        if rotation not in pdf.VALID_ROTATIONS:
            errors["print.rotation"] = "Rotation skal være 90 eller 270."
        if errors:
            return jsonify({"errors": errors}), 422

        config["sender"] = sender
        config["print"] = {
            "mode": mode,
            "printer_name": validation.normalize_text(print_body.get("printer_name", config["print"]["printer_name"])),
            # Paths copied from Explorer often come wrapped in quotes
            "sumatra_path": str(print_body.get("sumatra_path", config["print"]["sumatra_path"])).strip().strip('"'),
            "rotation": rotation,
        }
        online = body.get("address_check", {}).get("online", config["address_check"]["online"])
        config["address_check"] = {"online": bool(online)}
        storage.save_config(config)
        return jsonify({"config": storage.load_config(), "status": status()})

    @app.get("/api/printers")
    def get_printers():
        return jsonify({"printers": printers.list_printers()})

    @app.post("/api/calibration/print")
    def print_calibration():
        rotation = storage.load_config()["print"]["rotation"]
        path = storage.tmp_file("kalibrering.pdf")
        path.write_bytes(pdf.render_calibration(rotation))
        return jsonify(send_to_printer(path, "/api/calibration/pdf"))

    @app.get("/api/calibration/pdf")
    def calibration_pdf():
        path = storage.tmp_file("kalibrering.pdf")
        if not path.exists():
            abort(404)
        return send_file(path, mimetype="application/pdf", download_name="kalibrering.pdf")

    return app

