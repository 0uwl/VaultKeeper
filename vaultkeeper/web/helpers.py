import json
from functools import wraps

from flask import flash, make_response, redirect, request, session, url_for

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


def is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def htmx_response(html: str = "", status: int = 200, toast: dict | None = None, triggers: dict | None = None):
    resp = make_response(html, status)
    all_triggers: dict = {}
    if toast:
        all_triggers["show-toast"] = toast
    if triggers:
        all_triggers.update(triggers)
    if all_triggers:
        resp.headers["HX-Trigger"] = json.dumps(all_triggers)
    return resp


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
