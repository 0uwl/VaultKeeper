from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app

from vaultkeeper.client import CouchDBError
from vaultkeeper.web.helpers import _get_client, _is_admin, login_required, admin_required, _current_user

main = Blueprint("main", __name__)


@main.app_template_filter("fmt_bytes")
def fmt_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


@main.route("/health", methods=["GET"])
def health_check():
    return "VaultKeeper is running!", 200


@main.route("/")
@login_required
def dashboard():
    client = _get_client()

    if not _is_admin():
        username = _current_user()
        try:
            vaults_basic = client.list_vaults_for_user(username)
        except CouchDBError as e:
            current_app.logger.error(f"Error fetching vaults for '{username}': {str(e)}")
            flash(str(e), "error")
            vaults_basic = []
        vaults = []
        for v in vaults_basic:
            try:
                info = client.vault_info(v["db_name"])
                info["db_name"] = info["name"]
                vaults.append(info)
            except CouchDBError as e:
                current_app.logger.error(f"Error fetching info for vault '{v['db_name']}': {str(e)}")
                vaults.append({**v, "doc_count": None, "data_size": None})
        return render_template("user_dashboard.html", username=username, vaults=vaults)

    try:
        server_info = client.ping()
        user_count = len(client.list_users())
        vault_count = len(client.list_all_vaults())
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching CouchDB info: {str(e)}")
        flash(str(e), "error")
        server_info, user_count, vault_count = None, 0, 0
    try:
        recent_events = client.list_audit_log(limit=10)
    except CouchDBError:
        recent_events = []
    return render_template(
        "dashboard.html",
        server_info=server_info,
        user_count=user_count,
        vault_count=vault_count,
        recent_events=recent_events,
    )


@main.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    client = _get_client()

    if request.method == "POST":
        try:
            max_vaults_raw = request.form.get("default_max_vaults", "").strip()
            max_size_raw = request.form.get("default_max_vault_size_bytes", "").strip()
            default_max_vaults = int(max_vaults_raw) if max_vaults_raw else None
            default_max_vault_size_bytes = int(max_size_raw) if max_size_raw else None
            client.set_server_settings(default_max_vaults, default_max_vault_size_bytes)
            client.log_audit_event("settings.update", actor=_current_user(), details={"default_max_vaults": default_max_vaults, "default_max_vault_size_bytes": default_max_vault_size_bytes})
            flash("Server settings updated.", "success")
        except (CouchDBError, ValueError) as e:
            current_app.logger.error(f"Error updating server settings: {str(e)}")
            flash(str(e), "error")
        return redirect(url_for("main.settings"))

    try:
        server_settings = client.get_server_settings()
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching server settings: {str(e)}")
        flash(str(e), "error")
        server_settings = {"default_max_vaults": None, "default_max_vault_size_bytes": None}

    return render_template("settings.html", server_settings=server_settings)
