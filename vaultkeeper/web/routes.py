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
)

from vaultkeeper.client import CouchDB, CouchDBError, ValidationError

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Jinja2 filter
# ---------------------------------------------------------------------------

@bp.app_template_filter("fmt_bytes")
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


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        expected_user = os.environ.get("COUCHDB_USER", "")
        expected_pass = os.environ.get("COUCHDB_PASSWORD", "")

        if username == expected_user and password == expected_pass:
            try:
                CouchDB(username=username, password=password).ping()
                session["logged_in"] = True
                return redirect(url_for("main.dashboard"))
            except CouchDBError as e:
                flash(str(e), "error")
        else:
            flash("Invalid credentials.", "error")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def dashboard():
    client = _get_client()
    try:
        server_info = client.ping()
        user_count = len(client.list_users())
        vault_count = len(client.list_all_vaults())
    except CouchDBError as e:
        flash(str(e), "error")
        server_info, user_count, vault_count = None, 0, 0
    return render_template(
        "dashboard.html",
        server_info=server_info,
        user_count=user_count,
        vault_count=vault_count,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    client = _get_client()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            client.create_user(username, password)
            flash(f"User '{username}' created.", "success")
        except (CouchDBError, ValidationError) as e:
            flash(str(e), "error")
        return redirect(url_for("main.users"))

    try:
        user_list = client.list_users()
    except CouchDBError as e:
        flash(str(e), "error")
        user_list = []
    return render_template("users.html", users=user_list)


@bp.route("/users/<username>")
@login_required
def user_detail(username):
    client = _get_client()
    try:
        if not client.user_exists(username):
            flash(f"User '{username}' not found.", "error")
            return redirect(url_for("main.users"))
        vaults = client.list_vaults_for_user(username)
    except CouchDBError as e:
        flash(str(e), "error")
        vaults = []
    return render_template("user_detail.html", username=username, vaults=vaults)


@bp.route("/users/<username>/delete", methods=["POST"])
@login_required
def user_delete(username):
    client = _get_client()
    try:
        client.delete_user(username)
        flash(f"User '{username}' deleted.", "success")
    except CouchDBError as e:
        flash(str(e), "error")
    return redirect(url_for("main.users"))


@bp.route("/users/<username>/passwd", methods=["POST"])
@login_required
def user_passwd(username):
    client = _get_client()
    try:
        client.change_password(username, request.form.get("password", ""))
        flash(f"Password updated for '{username}'.", "success")
    except CouchDBError as e:
        flash(str(e), "error")
    return redirect(url_for("main.user_detail", username=username))


# ---------------------------------------------------------------------------
# Vaults
# ---------------------------------------------------------------------------

@bp.route("/vaults", methods=["GET", "POST"])
@login_required
def vaults():
    client = _get_client()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        vault_name = request.form.get("vault_name", "").strip()
        try:
            db_name = client.create_vault(username, vault_name)
            flash(f"Vault '{db_name}' created.", "success")
            return redirect(url_for("main.vault_detail", db_name=db_name))
        except (CouchDBError, ValidationError) as e:
            flash(str(e), "error")
            return redirect(url_for("main.vaults"))

    try:
        vault_list = client.list_all_vaults()
    except CouchDBError as e:
        flash(str(e), "error")
        vault_list = []
    return render_template("vaults.html", vaults=vault_list)


@bp.route("/vaults/<db_name>")
@login_required
def vault_detail(db_name):
    client = _get_client()
    try:
        info = client.vault_info(db_name)
    except CouchDBError as e:
        flash(str(e), "error")
        return redirect(url_for("main.vaults"))
    return render_template("vault_detail.html", vault=info)


@bp.route("/vaults/<db_name>/compact", methods=["POST"])
@login_required
def vault_compact(db_name):
    client = _get_client()
    try:
        client.compact_vault(db_name)
        flash(f"Compaction started for '{db_name}'.", "success")
    except CouchDBError as e:
        flash(str(e), "error")
    return redirect(url_for("main.vault_detail", db_name=db_name))


@bp.route("/vaults/<db_name>/delete", methods=["POST"])
@login_required
def vault_delete(db_name):
    client = _get_client()
    try:
        client.delete_vault(db_name)
        flash(f"Vault '{db_name}' deleted.", "success")
    except CouchDBError as e:
        flash(str(e), "error")
    return redirect(url_for("main.vaults"))


@bp.route("/vaults/<db_name>/setup-uri", methods=["GET", "POST"])
@login_required
def vault_setup_uri(db_name):
    client = _get_client()
    if not client.db_exists(db_name):
        flash(f"Vault '{db_name}' not found.", "error")
        return redirect(url_for("main.vaults"))

    parts = db_name.split("_", 2)
    username = parts[1] if len(parts) >= 2 else ""

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
            flash(str(e), "error")

    return render_template("setup_uri.html", db_name=db_name, username=username, result=result)


# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------

@bp.route("/provision", methods=["GET", "POST"])
@login_required
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
            flash(str(e), "error")

    return render_template("provision.html", result=result)
