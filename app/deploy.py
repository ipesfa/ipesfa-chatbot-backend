"""Webhook de deploy automático (GitHub push -> git pull + reinstalar deps
si cambiaron + reiniciar Passenger).

Implementado como ruta de Flask (no como script PHP aparte) porque
PassengerBaseURI toma control de TODA la carpeta de la app — un archivo
.php suelto ahí nunca se ejecutaría como PHP, cualquier request cae acá.
"""

import hashlib
import hmac
import os
import subprocess
import sys
from datetime import datetime

from flask import Blueprint, request

from .config import Config

deploy_bp = Blueprint("deploy", __name__)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True, timeout=120)
    return (result.stdout or "") + (result.stderr or "")


def _log(lines: list[str]) -> None:
    with open(os.path.join(REPO_DIR, "deploy.log"), "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


@deploy_bp.route("/deploy-webhook", methods=["POST"])
def deploy_webhook():
    secret = Config.WEBHOOK_SECRET
    if not secret:
        return "WEBHOOK_SECRET no configurado en el .env del servidor", 500

    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        return "Firma inválida", 403

    before = _run(["git", "rev-parse", "HEAD"]).strip()
    pull_output = _run(["git", "pull", "origin", "main"])
    after = _run(["git", "rev-parse", "HEAD"]).strip()

    log_lines = [f"== {datetime.now().isoformat()} ==", pull_output]

    if before != after:
        changed = _run(["git", "diff", "--name-only", before, after])
        if "requirements.txt" in changed:
            # sys.executable: el mismo intérprete que ya está corriendo esta
            # app (el del venv, vía PassengerPython) — garantiza usar el pip
            # correcto sin depender de activar el venv por separado.
            log_lines.append(_run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]))

        os.makedirs(os.path.join(REPO_DIR, "tmp"), exist_ok=True)
        open(os.path.join(REPO_DIR, "tmp", "restart.txt"), "w").close()
        log_lines.append("Restart solicitado.")
    else:
        log_lines.append("Sin cambios (ya estaba en el último commit).")

    _log(log_lines)
    return "OK\n"
