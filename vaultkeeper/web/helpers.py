from functools import wraps

from flask import flash, redirect, session, url_for

from vaultkeeper.client import CouchDB


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
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if not session.get("is_admin"):
            flash("Admin access required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated
