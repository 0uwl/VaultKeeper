import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
)

from vaultkeeper.client import CouchDB, CouchDBError
from vaultkeeper.web.helpers import _get_client, admin_required, _current_user

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        admin_user = os.environ.get("COUCHDB_USER", "")
        admin_pass = os.environ.get("COUCHDB_PASSWORD", "")

        if username == admin_user and password == admin_pass:
            try:
                CouchDB(username=username, password=password).ping()
                session["logged_in"] = True
                session["username"] = username
                session["is_admin"] = True
                _get_client().log_audit_event("login.success", actor=username)
                return redirect(url_for("main.dashboard"))
            except CouchDBError as e:
                current_app.logger.error(f"Error when logging in: {str(e)}")
                flash(str(e), "error")
        else:
            client = _get_client()
            try:
                if client.authenticate_user(username, password):
                    session["logged_in"] = True
                    session["username"] = username
                    session["is_admin"] = False
                    client.log_audit_event("login.success", actor=username)
                    return redirect(url_for("main.dashboard"))
                else:
                    current_app.logger.error(f"Invalid credentials for user '{username}'")
                    client.log_audit_event("login.failure", actor="anonymous", target=username)
                    flash("Invalid credentials.", "error")
            except CouchDBError as e:
                current_app.logger.error(f"Error when logging in: {str(e)}")
                flash(str(e), "error")

    return render_template("login.html")


@auth.route("/logout", methods=["POST"])
def logout():
    actor = _current_user()
    _get_client().log_audit_event("logout", actor=actor)
    session.clear()
    return redirect(url_for("auth.login"))


@auth.route("/enroll/<token>", methods=["GET", "POST"])
def enroll(token):
    client = _get_client()
    invitation = client.get_invitation(token)

    if invitation is None:
        return render_template("enroll.html", invalid=True, token=token)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not username:
            flash("Username is required.", "error")
        elif not password:
            flash("Password is required.", "error")
        elif password != password_confirm:
            flash("Passwords do not match.", "error")
        else:
            try:
                client.create_user(username, password)
                client.consume_invitation(token, username)
                client.log_audit_event("user.enroll", actor=username, details={"token": token[:8]})
                flash(f"Account created. Welcome, {username}! You can now log in.", "success")
                return redirect(url_for("auth.login"))
            except CouchDBError as e:
                current_app.logger.error(f"Enrollment error: {str(e)}")
                flash(str(e), "error")

    return render_template("enroll.html", invalid=False, token=token)


@auth.route("/invitations", methods=["GET", "POST"])
@admin_required
def invitations():
    client = _get_client()
    invite_url = None

    if request.method == "POST":
        try:
            expiry_hours = int(request.form.get("expiry_hours") or 72)
            token = client.create_invitation(expiry_hours=expiry_hours)
            invite_url = url_for("auth.enroll", token=token, _external=True)
            client.log_audit_event("invitation.create", actor=_current_user(), target=token[:8], details={"expiry_hours": expiry_hours})
            flash("Invitation created.", "success")
        except (CouchDBError, ValueError) as e:
            current_app.logger.error(f"Error creating invitation: {str(e)}")
            flash(str(e), "error")

    try:
        invitation_list = client.list_invitations()
        now = datetime.now(timezone.utc)
        for inv in invitation_list:
            inv["expired"] = datetime.fromisoformat(inv["expires_at"]) < now
    except CouchDBError as e:
        current_app.logger.error(f"Error listing invitations: {str(e)}")
        flash(str(e), "error")
        invitation_list = []

    return render_template("invitations.html", invitations=invitation_list, invite_url=invite_url)


@auth.route("/invitations/<token>/delete", methods=["POST"])
@admin_required
def invitation_delete(token):
    client = _get_client()
    try:
        client.delete_invitation(token)
        client.log_audit_event("invitation.delete", actor=_current_user(), target=token[:8])
        flash("Invitation deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error deleting invitation: {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("auth.invitations"))
