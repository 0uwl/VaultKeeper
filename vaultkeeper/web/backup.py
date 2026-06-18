import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from vaultkeeper.client import BACKUP_DIR_DEFAULT, CouchDBError
from vaultkeeper.web.helpers import _current_user, _get_client, admin_required

backup = Blueprint("backup", __name__)


def _backup_dir() -> str:
    return os.environ.get("VAULTKEEPER_BACKUP_DIR", BACKUP_DIR_DEFAULT)


@backup.route("/backups")
@admin_required
def backups_list():
    client = _get_client()
    try:
        backups = client.list_backups(_backup_dir())
    except Exception as e:
        current_app.logger.error(f"Error listing backups: {e}")
        flash(str(e), "error")
        backups = []
    return render_template("backups.html", backups=backups)


@backup.route("/backups/new", methods=["GET", "POST"])
@admin_required
def backup_new():
    client = _get_client()

    if request.method == "POST":
        selected_dbs = request.form.getlist("databases")
        include_users = "include_users" in request.form
        include_config = "include_config" in request.form

        if not selected_dbs and not include_users and not include_config:
            flash("Select at least one database to back up.", "warning")
            return redirect(url_for("backup.backup_new"))

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"vaultkeeper_backup_{ts}.tar.gz"
        dest_path = os.path.join(_backup_dir(), filename)

        try:
            manifest = client.backup(
                dest_path=dest_path,
                databases=selected_dbs,
                include_users=include_users,
                include_config=include_config,
            )
            db_count = len(manifest["databases"])
            client.log_audit_event(
                "backup.create",
                actor=_current_user(),
                details={
                    "filename": filename,
                    "databases": list(manifest["databases"].keys()),
                },
            )
            flash(f"Backup '{filename}' created ({db_count} database(s)).", "success")
            return redirect(url_for("backup.backups_list"))
        except CouchDBError as e:
            current_app.logger.error(f"Backup failed: {e}")
            flash(str(e), "error")
            return redirect(url_for("backup.backup_new"))

    preselect = request.args.get("vault")
    try:
        vault_dbs = client.list_all_vaults()
        vaults = []
        for db in vault_dbs:
            meta = client.get_vault_meta(db) or {}
            vaults.append({
                "db_name": db,
                "vault_name": meta.get("vault_name", db),
                "username": meta.get("username", ""),
                "selected": db == preselect,
            })
    except CouchDBError as e:
        current_app.logger.error(f"Error loading vaults for backup form: {e}")
        flash(str(e), "error")
        vaults = []

    return render_template("backup_new.html", vaults=vaults)


@backup.route("/backups/upload", methods=["GET", "POST"])
@admin_required
def backup_upload():
    if request.method == "POST":
        file = request.files.get("archive")
        if not file or not file.filename:
            flash("Select a backup archive to upload.", "warning")
            return redirect(url_for("backup.backup_upload"))

        filename = secure_filename(file.filename)
        if not filename.endswith(".tar.gz"):
            flash("Backup archives must be a .tar.gz file.", "error")
            return redirect(url_for("backup.backup_upload"))

        backup_dir = _backup_dir()
        os.makedirs(backup_dir, exist_ok=True)
        dest_path = os.path.join(backup_dir, filename)
        if os.path.exists(dest_path):
            flash(f"A backup named '{filename}' already exists.", "error")
            return redirect(url_for("backup.backup_upload"))

        file.save(dest_path)

        client = _get_client()
        try:
            manifest = client.read_backup_manifest(dest_path)
        except CouchDBError as e:
            os.remove(dest_path)
            flash(f"Upload rejected - not a usable backup archive: {e}", "error")
            return redirect(url_for("backup.backup_upload"))

        client.log_audit_event(
            "backup.upload",
            actor=_current_user(),
            details={
                "filename": filename,
                "databases": list(manifest["databases"].keys()),
            },
        )
        flash(f"Backup '{filename}' uploaded ({len(manifest['databases'])} database(s)).", "success")
        return redirect(url_for("backup.backups_list"))

    return render_template("backup_upload.html")


@backup.route("/backups/<filename>/download")
@admin_required
def backup_download(filename):
    filename = os.path.basename(filename)
    path = os.path.join(_backup_dir(), filename)
    if not os.path.isfile(path):
        flash("Backup file not found.", "error")
        return redirect(url_for("backup.backups_list"))
    return send_file(path, as_attachment=True, download_name=filename)


@backup.route("/backups/<filename>/delete", methods=["POST"])
@admin_required
def backup_delete(filename):
    filename = os.path.basename(filename)
    path = os.path.join(_backup_dir(), filename)
    client = _get_client()
    try:
        client.delete_backup(path)
        client.log_audit_event(
            "backup.delete",
            actor=_current_user(),
            details={"filename": filename},
        )
        flash(f"Backup '{filename}' deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error deleting backup '{filename}': {e}")
        flash(str(e), "error")
    return redirect(url_for("backup.backups_list"))


@backup.route("/backups/<filename>/restore", methods=["GET", "POST"])
@admin_required
def backup_restore(filename):
    filename = os.path.basename(filename)
    path = os.path.join(_backup_dir(), filename)
    client = _get_client()

    try:
        manifest = client.read_backup_manifest(path)
    except CouchDBError as e:
        flash(str(e), "error")
        return redirect(url_for("backup.backups_list"))

    if request.method == "POST":
        selected_dbs = request.form.getlist("databases")
        if not selected_dbs:
            flash("Select at least one database to restore.", "warning")
            return redirect(url_for("backup.backup_restore", filename=filename))

        try:
            results = client.restore(path, selected_dbs)
            total_docs = sum(results.values())
            client.log_audit_event(
                "backup.restore",
                actor=_current_user(),
                details={
                    "filename": filename,
                    "databases": selected_dbs,
                    "total_docs": total_docs,
                },
            )
            flash(
                f"Restore complete: {total_docs} document(s) across {len(results)} database(s).",
                "success",
            )
            return redirect(url_for("backup.backups_list"))
        except CouchDBError as e:
            current_app.logger.error(f"Restore from '{filename}' failed: {e}")
            flash(str(e), "error")

    return render_template("backup_restore.html", filename=filename, manifest=manifest)
