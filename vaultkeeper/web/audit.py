from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app

from vaultkeeper.client import CouchDBError
from vaultkeeper.web.helpers import _get_client, admin_required, _current_user

audit = Blueprint("audit", __name__)


@audit.route("/audit")
@admin_required
def audit_log():
    client = _get_client()
    try:
        events = client.list_audit_log(limit=200)
    except CouchDBError as e:
        current_app.logger.error(f"Error fetching audit log: {str(e)}")
        flash(str(e), "error")
        events = []
    return render_template("audit.html", events=events)


@audit.route("/audit/delete", methods=["POST"])
@admin_required
def audit_delete():
    client = _get_client()
    pairs = []
    for entry in request.form.getlist("sel"):
        if "|" in entry:
            doc_id, rev = entry.split("|", 1)
            pairs.append((doc_id, rev))
    try:
        count = client.purge_audit_events(pairs)
        client.log_audit_event("audit.delete", actor=_current_user(), details={"count": count})
        flash(f"Deleted {count} audit event(s).", "success")
    except CouchDBError as e:
        current_app.logger.error(f"Error deleting audit events: {e}")
        flash(str(e), "error")
    return redirect(url_for("audit.audit_log"))
