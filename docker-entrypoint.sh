#!/bin/sh
set -e
exec gunicorn "vaultkeeper.web.app:create_app()"
