from datetime import datetime, timezone
import os
from functools import wraps

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

from vaultkeeper.client import CouchDB, CouchDBError, ValidationError, CONFIG_DB, db_name_to_vault_parts

index = Blueprint("index", __name__)


# ---------------------------------------------------------------------------
# Jinja2 filter
# ---------------------------------------------------------------------------

@index.app_template_filter("fmt_bytes")
def fmt_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_client() -> CouchDB:
    return CouchDB()


def _is_admin() -> bool:
    return session.get("is_admin", False)


def _current_user() -> str:
    return session.get("username", "")


def _owns_vault(db_name: str) -> bool:
    if _is_admin():
        return True
    return db_name.startswith(f"vault_{_current_user()}_")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("index.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("index.login"))
        if not session.get("is_admin"):
            flash("Admin access required.", "error")
            return redirect(url_for("index.dashboard"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@index.route("/health", methods=["GET"])
def health_check():
    return "VaultKeeper is running!", 200


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@index.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index.dashboard"))

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
                return redirect(url_for("index.dashboard"))
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
                    return redirect(url_for("index.dashboard"))
                else:
                    current_app.logger.error(f"Invalid credentials for user '{username}'")
                    flash("Invalid credentials.", "error")
            except CouchDBError as e:
                current_app.logger.error(f"Error when logging in: {str(e)}")
                flash(str(e), "error")

    return render_template("login.html")


@index.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index.login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@index.route("/")
@login_required
def dashboard():
    client = _get_client()

    if not _is_admin():
        username = _current_user()
        try:
            vaults = client.list_vaults_for_user(username)
        except CouchDBError as e:
            current_app.logger.error(f"Error fetching vaults for '{username}': {str(e)}")
            flash(str(e), "error")
            vaults = []
        return render_template("user_dashboard.html", username=username, vaults=vaults)

    try:
        server_info = client.ping()
        user_count = len(client.list_users())
        vault_count = len(client.list_all_vaults())
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching CouchDB info: {str(e)}")
        flash(str(e), "error")
        server_info, user_count, vault_count = None, 0, 0
    return render_template(
        "dashboard.html",
        server_info=server_info,
        user_count=user_count,
        vault_count=vault_count,
    )


# ---------------------------------------------------------------------------
# Enrollment (no auth required)
# ---------------------------------------------------------------------------

@index.route("/enroll/<token>", methods=["GET", "POST"])
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
                flash(f"Account created. Welcome, {username}! You can now log in.", "success")
                return redirect(url_for("index.login"))
            except CouchDBError as e:
                current_app.logger.error(f"Enrollment error: {str(e)}")
                flash(str(e), "error")

    return render_template("enroll.html", invalid=False, token=token)


# ---------------------------------------------------------------------------
# Invitations (admin only)
# ---------------------------------------------------------------------------

@index.route("/invitations", methods=["GET", "POST"])
@admin_required
def invitations():
    client = _get_client()
    invite_url = None

    if request.method == "POST":
        try:
            expiry_hours = int(request.form.get("expiry_hours") or 72)
            token = client.create_invitation(expiry_hours=expiry_hours)
            invite_url = url_for("index.enroll", token=token, _external=True)
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


@index.route("/invitations/<token>/delete", methods=["POST"])
@admin_required
def invitation_delete(token):
    client = _get_client()
    try:
        client.delete_invitation(token)
        flash("Invitation deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error deleting invitation: {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.invitations"))


# ---------------------------------------------------------------------------
# Users (admin only, except own user detail and passwd)
# ---------------------------------------------------------------------------

@index.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    client = _get_client()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            client.create_user(username, password)
            flash(f"User '{username}' created.", "success")
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when creating user '{username}': {str(e)}")
            flash(str(e), "error")
        return redirect(url_for("index.users"))

    try:
        user_list = client.list_users()
    except CouchDBError as e:
        current_app.logger.error(f"Error when listing users: {str(e)}")
        flash(str(e), "error")
        user_list = []
    return render_template("users.html", users=user_list)


@index.route("/users/<username>")
@login_required
def user_detail(username):
    if not _is_admin() and _current_user() != username:
        flash("Access denied.", "error")
        return redirect(url_for("index.dashboard"))

    client = _get_client()
    try:
        if not client.user_exists(username):
            current_app.logger.error(f"User '{username}' not found")
            flash(f"User '{username}' not found.", "error")
            return redirect(url_for("index.dashboard"))
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


@index.route("/users/<username>/delete", methods=["POST"])
@admin_required
def user_delete(username):
    client = _get_client()
    try:
        client.delete_user(username)
        flash(f"User '{username}' deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when deleting user '{username}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.users"))


@index.route("/users/<username>/passwd", methods=["POST"])
@login_required
def user_passwd(username):
    if not _is_admin() and _current_user() != username:
        flash("Access denied.", "error")
        return redirect(url_for("index.dashboard"))

    client = _get_client()
    try:
        client.change_password(username, request.form.get("password", ""))
        flash(f"Password updated for '{username}'.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when changing password for user '{username}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.user_detail", username=username))


@index.route("/users/<username>/limits", methods=["POST"])
@admin_required
def user_limits(username):
    client = _get_client()
    try:
        max_vaults_raw = request.form.get("max_vaults", "").strip()
        max_size_raw = request.form.get("max_vault_size_bytes", "").strip()
        max_vaults = int(max_vaults_raw) if max_vaults_raw else None
        max_vault_size_bytes = int(max_size_raw) if max_size_raw else None
        client.set_user_limits(username, max_vaults, max_vault_size_bytes)
        flash(f"Limits updated for '{username}'.", "success")
    except (CouchDBError, ValueError) as e:
        current_app.logger.error(f"Error setting limits for '{username}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.user_detail", username=username))


# ---------------------------------------------------------------------------
# Vaults
# ---------------------------------------------------------------------------

@index.route("/vaults", methods=["GET", "POST"])
@login_required
def vaults():
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
                        return redirect(url_for("index.vaults"))
            except CouchDBError as e:
                current_app.logger.error(f"Error checking vault limit: {str(e)}")
                flash(str(e), "error")
                return redirect(url_for("index.vaults"))

        try:
            db_name = client.create_vault(username, vault_name)
            flash(f"Vault '{db_name}' created.", "success")
            return redirect(url_for("index.vault_detail", db_name=db_name))
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when creating vault '{vault_name}': {str(e)}")
            flash(str(e), "error")
            return redirect(url_for("index.vaults"))

    try:
        if _is_admin():
            vault_list = client.list_all_vaults()
        else:
            vault_list = client.list_vaults_for_user(_current_user())
    except CouchDBError as e:
        current_app.logger.error(f"Error listing vaults: {str(e)}")
        flash(str(e), "error")
        vault_list = []
    return render_template("vaults.html", vaults=vault_list)


@index.route("/vaults/<db_name>")
@login_required
def vault_detail(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("index.vaults"))

    client = _get_client()
    try:
        _, vault_name = db_name_to_vault_parts(db_name)
    except ValidationError as e:
        current_app.logger.error(f"Error parsing database name '{db_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("index.vaults"))
    try:
        info = client.vault_info(db_name)
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching details for vault '{vault_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("index.vaults"))
    return render_template("vault_detail.html", vault=info)


@index.route("/vaults/<db_name>/compact", methods=["POST"])
@login_required
def vault_compact(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("index.vaults"))

    client = _get_client()
    try:
        _, vault_name = db_name_to_vault_parts(db_name)
    except ValidationError as e:
        current_app.logger.error(f"Error parsing database name '{db_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("index.vaults"))
    try:
        client.compact_vault(db_name)
        flash(f"Compaction started for '{vault_name}'.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error trying to compact vault '{vault_name}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.vault_detail", db_name=db_name))


@index.route("/vaults/<db_name>/delete", methods=["POST"])
@login_required
def vault_delete(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("index.vaults"))

    client = _get_client()
    try:
        _, vault_name = db_name_to_vault_parts(db_name)
    except ValidationError as e:
        current_app.logger.error(f"Error parsing database name '{db_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("index.vaults"))
    try:
        client.delete_vault(db_name)
        flash(f"Vault '{vault_name}' deleted.", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error when trying to delete vault '{vault_name}': {str(e)}")
        flash(str(e), "error")
    return redirect(url_for("index.vaults"))


@index.route("/vaults/<db_name>/setup-uri", methods=["GET", "POST"])
@login_required
def vault_setup_uri(db_name):
    if not _owns_vault(db_name):
        flash("Access denied.", "error")
        return redirect(url_for("index.vaults"))

    client = _get_client()
    try:
        if not client.db_exists(db_name):
            flash(f"Vault '{db_name}' not found.", "error")
            return redirect(url_for("index.vaults"))
    except CouchDBError as e:
        current_app.logger.error(f"Error: {str(e)}")
        flash(str(e), "error")

    try:
        username, vault_name = db_name_to_vault_parts(db_name)
    except ValidationError as e:
        current_app.logger.error(f"Error parsing database name '{db_name}': {str(e)}")
        flash(str(e), "error")
        return redirect(url_for("index.vaults"))

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
        except CouchDBError as e:
            current_app.logger.error(f"Error when generating Setup URI for '{vault_name}': {str(e)}")
            flash(str(e), "error")

    return render_template("setup_uri.html", db_name=db_name, username=username, result=result)


# ---------------------------------------------------------------------------
# Server settings (admin only)
# ---------------------------------------------------------------------------

@index.route("/settings", methods=["GET", "POST"])
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
            flash("Server settings updated.", "success")
        except (CouchDBError, ValueError) as e:
            current_app.logger.error(f"Error updating server settings: {str(e)}")
            flash(str(e), "error")
        return redirect(url_for("index.settings"))

    try:
        server_settings = client.get_server_settings()
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching server settings: {str(e)}")
        flash(str(e), "error")
        server_settings = {"default_max_vaults": None, "default_max_vault_size_bytes": None}

    return render_template("settings.html", server_settings=server_settings)


# ---------------------------------------------------------------------------
# Provision (admin only)
# ---------------------------------------------------------------------------

@index.route("/provision", methods=["GET", "POST"])
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
            flash(f"Provisioned '{username}' with vault '{db_name}'.", "success")
        except (CouchDBError, ValidationError) as e:
            current_app.logger.error(f"Error when provisioning new vault '{vault_name}' for user '{username}': {str(e)}")
            flash(str(e), "error")

    return render_template("provision.html", result=result)
