from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for, current_app

from vaultkeeper.client import CouchDBError, ValidationError
from vaultkeeper.web.helpers import (
    _get_client,
    _is_admin,
    _current_user,
    is_htmx,
    htmx_response,
    login_required,
    admin_required,
)

users = Blueprint("users", __name__)


@users.route("/users", methods=["GET", "POST"])
@admin_required
def users_list():
    client = _get_client()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            client.create_user(username, password)
            client.log_audit_event("user.create", actor=_current_user(), target=username)
            if is_htmx():
                html = render_template("_partials/user_row.html", username=username)
                return htmx_response(
                    html,
                    toast={"message": f"User '{username}' created.", "type": "success"},
                    triggers={"clear-form": True},
                )
            flash(f"User '{username}' created.", "success")
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when creating user '{username}': {str(e)}")
            if is_htmx():
                return htmx_response(status=422, toast={"message": str(e), "type": "error"})
            flash(str(e), "error")
        return redirect(url_for("users.users_list"))

    try:
        user_list = client.list_users()
    except CouchDBError as e:
        current_app.logger.error(f"Error when listing users: {str(e)}")
        flash(str(e), "error")
        user_list = []

    try:
        invitation_list = client.list_invitations()
        now = datetime.now(timezone.utc)
        for inv in invitation_list:
            inv["expired"] = datetime.fromisoformat(inv["expires_at"]) < now
    except CouchDBError as e:
        current_app.logger.error(f"Error when listing invitations: {str(e)}")
        invitation_list = []

    invite_url = session.pop("pending_invite_url", None)
    active_tab = request.args.get("tab", "users")

    return render_template(
        "users.html",
        users=user_list,
        invitations=invitation_list,
        invite_url=invite_url,
        active_tab=active_tab,
    )


@users.route("/users/<username>")
@login_required
def user_detail(username):
    if not _is_admin() and _current_user() != username:
        flash("Access denied.", "error")
        return redirect(url_for("main.dashboard"))

    client = _get_client()
    try:
        if not client.user_exists(username):
            current_app.logger.error(f"User '{username}' not found")
            flash(f"User '{username}' not found.", "error")
            return redirect(url_for("main.dashboard"))
        vaults = client.list_vaults_for_user(username)
    except CouchDBError as e:
        current_app.logger.error(f"Error when listing vaults for '{username}': {str(e)}")
        flash(str(e), "error")
        vaults = []

    limits = None
    server_settings = None
    if _is_admin():
        try:
            limits = client.get_user_limits(username)
            server_settings = client.get_server_settings()
        except CouchDBError:
            pass

    return render_template(
        "user_detail.html",
        username=username,
        vaults=vaults,
        limits=limits,
        server_settings=server_settings,
    )


@users.route("/users/<username>/delete", methods=["POST"])
@admin_required
def user_delete(username):
    client = _get_client()
    delete_vaults = request.form.get("delete_vaults") == "1"
    try:
        client.delete_user(username, delete_vaults=delete_vaults)
        client.log_audit_event(
            "user.delete", actor=_current_user(), target=username, details={"delete_vaults": delete_vaults}
        )
        if is_htmx():
            return htmx_response(toast={"message": f"User '{username}' deleted.", "type": "success"})
        flash(f"User '{username}' deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when deleting user '{username}': {str(e)}")
        if is_htmx():
            return htmx_response(status=422, toast={"message": str(e), "type": "error"})
        flash(str(e), "error")
    return redirect(url_for("users.users_list"))


@users.route("/users/<username>/passwd", methods=["POST"])
@login_required
def user_passwd(username):
    if _current_user() != username:
        flash("Access denied.", "error")
        return redirect(url_for("main.dashboard"))

    client = _get_client()
    try:
        client.change_password(username, request.form.get("password", ""))
        client.log_audit_event("user.passwd", actor=_current_user(), target=username)
        flash(f"Password updated for '{username}'.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when changing password for user '{username}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("users.user_detail", username=username))


@users.route("/users/<username>/limits", methods=["POST"])
@admin_required
def user_limits(username):
    client = _get_client()
    try:
        max_vaults_raw = request.form.get("max_vaults", "").strip()
        max_size_raw = request.form.get("max_vault_size_bytes", "").strip()
        max_vaults = int(max_vaults_raw) if max_vaults_raw else None
        max_vault_size_bytes = int(max_size_raw) if max_size_raw else None
        client.set_user_limits(username, max_vaults, max_vault_size_bytes)
        client.log_audit_event("user.limits", actor=_current_user(), target=username, details={"max_vaults": max_vaults, "max_vault_size_bytes": max_vault_size_bytes})
        flash(f"Limits updated for '{username}'.", "success")
    except (CouchDBError, ValueError) as e:
        current_app.logger.error(f"Error setting limits for '{username}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("users.user_detail", username=username))
