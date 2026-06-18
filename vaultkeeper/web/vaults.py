from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app

from vaultkeeper.client import CouchDBError, ValidationError
from vaultkeeper.web.helpers import (
    _get_client,
    _is_admin,
    _current_user,
    _owns_vault,
    is_htmx,
    htmx_response,
    login_required,
    admin_required,
)

vaults = Blueprint("vaults", __name__)


@vaults.route("/vaults", methods=["GET", "POST"])
@login_required
def vaults_list():
    client = _get_client()

    if request.method == "POST":
        vault_name = request.form.get("vault_name", "").strip()
        if _is_admin():
            username = request.form.get("username", "").strip()
        else:
            username = _current_user()
            try:
                limits = client.get_effective_limits(username)
                max_vaults = limits["max_vaults"]
                if max_vaults is not None:
                    current_count = len(client.list_vaults_for_user(username))
                    if current_count >= max_vaults:
                        flash(
                            f"Vault limit reached ({max_vaults} vaults maximum). "
                            "Contact your administrator to increase the limit.",
                            "error",
                        )
                        return redirect(url_for("vaults.vaults_list"))
            except CouchDBError as e:
                current_app.logger.error(f"Error checking vault limit: {str(e)}")
                flash(str(e), "error")
                return redirect(url_for("vaults.vaults_list"))

        try:
            db_name = client.create_vault(username, vault_name)
            client.log_audit_event("vault.create", actor=_current_user(), target=db_name, details={"vault_name": vault_name, "owner": username})
            flash(f"Vault '{vault_name}' created.", "success")
            return redirect(url_for("vaults.vault_detail", db_name=db_name))
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when creating vault '{vault_name}': {str(e)}")
            flash(str(e), "error")
            return redirect(url_for("vaults.vaults_list"))

    try:
        if _is_admin():
            vault_list = []
            for db in client.list_all_vaults():
                meta = client.get_vault_meta(db) or {}
                vault_list.append({
                    "db_name": db,
                    "vault_name": meta.get("vault_name", db),
                    "username": meta.get("username", ""),
                })
        else:
            vault_list = client.list_vaults_for_user(_current_user())
    except CouchDBError as e:
        current_app.logger.error(f"Error listing vaults: {str(e)}")
        flash(str(e), "error")
        vault_list = []

    usernames = sorted({v["username"] for v in vault_list if v.get("username")}) if _is_admin() else []

    all_users = []
    if _is_admin():
        try:
            all_users = sorted(client.list_users())
        except CouchDBError as e:
            current_app.logger.error(f"Error listing users: {str(e)}")
            flash(str(e), "error")

    return render_template("vaults.html", vaults=vault_list, usernames=usernames, all_users=all_users)


@vaults.route("/vaults/<db_name>")
@login_required
def vault_detail(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("vaults.vaults_list"))

    client = _get_client()
    try:
        info = client.vault_info(db_name)
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching details for vault '{db_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("vaults.vaults_list"))
    return render_template("vault_detail.html", vault=info)


@vaults.route("/vaults/<db_name>/compact", methods=["POST"])
@login_required
def vault_compact(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("vaults.vaults_list"))

    client = _get_client()
    meta = client.get_vault_meta(db_name)
    vault_name = meta.get("vault_name", db_name) if meta else db_name
    try:
        client.compact_vault(db_name)
        client.log_audit_event("vault.compact", actor=_current_user(), target=db_name, details={"vault_name": vault_name})
        if is_htmx():
            return htmx_response(toast={"message": f"Compaction started for '{vault_name}'.", "type": "success"})
        flash(f"Compaction started for '{vault_name}'.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error trying to compact vault '{vault_name}': {str(e)}")
        if is_htmx():
            return htmx_response(status=422, toast={"message": str(e), "type": "error"})
        flash(str(e), "error")
    return redirect(url_for("vaults.vault_detail", db_name=db_name))


@vaults.route("/vaults/<db_name>/delete", methods=["POST"])
@login_required
def vault_delete(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("vaults.vaults_list"))

    client = _get_client()
    meta = client.get_vault_meta(db_name)
    vault_name = meta.get("vault_name", db_name) if meta else db_name
    try:
        client.delete_vault(db_name)
        client.log_audit_event("vault.delete", actor=_current_user(), target=db_name, details={"vault_name": vault_name})
        flash(f"Vault '{vault_name}' deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when trying to delete vault '{vault_name}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("vaults.vaults_list"))


@vaults.route("/vaults/<db_name>/setup-uri", methods=["GET", "POST"])
@login_required
def vault_setup_uri(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("vaults.vaults_list"))

    client = _get_client()
    try:
        if not client.db_exists(db_name):
            flash(f"Vault '{db_name}' not found.", "error")
            return redirect(url_for("vaults.vaults_list"))
    except CouchDBError as e:
        current_app.logger.error(f"Error: {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("vaults.vaults_list"))

    meta = client.get_vault_meta(db_name)
    if meta is None:
        flash(f"Vault metadata not found for '{db_name}'.", "error")
        return redirect(url_for("vaults.vaults_list"))
    username = meta.get("username", _current_user())
    vault_name = meta.get("vault_name", db_name)

    result = None
    if request.method == "POST":
        try:
            result = client.generate_setup_uri(
                username=username,
                user_password=request.form.get("user_password", ""),
                db_name=db_name,
                passphrase=request.form.get("passphrase") or None,
                uri_passphrase=request.form.get("uri_passphrase") or None,
            )
            client.log_audit_event("vault.setup_uri", actor=_current_user(), target=db_name, details={"vault_name": vault_name})
        except CouchDBError as e:
            current_app.logger.error(f"Error when generating Setup URI for '{vault_name}': {str(e)}")
            flash(str(e), "error")

    return render_template("setup_uri.html", db_name=db_name, username=username, vault_name=vault_name, result=result)


@vaults.route("/vaults/<db_name>/backup", methods=["POST"])
@admin_required
def vault_backup(db_name):
    return redirect(url_for("backup.backup_new", vault=db_name))


@vaults.route("/provision", methods=["GET", "POST"])
@admin_required
def provision():
    result = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        vault_name = request.form.get("vault_name", "").strip()
        user_password = request.form.get("user_password", "")
        client = _get_client()
        try:
            client.create_user(username, user_password)
            db_name = client.create_vault(username, vault_name)
            result = client.generate_setup_uri(username, user_password, db_name)
            result["db_name"] = db_name
            result["username"] = username
            client.log_audit_event("provision", actor=_current_user(), target=username, details={"vault_name": vault_name, "db_name": db_name})
            flash(f"Provisioned '{username}' with vault '{vault_name}'.", "success")
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when provisioning new vault '{vault_name}' for user '{username}': {str(e)}")
            flash(str(e), "error")

    return render_template("provision.html", result=result)
