import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

SERVICES = {
    "kick": os.getenv("KICK_API_URL", "https://kick-duelo-api.onrender.com").rstrip("/"),
    "warzone": os.getenv("WARZONE_API_URL", "https://warzone-api-qbn9.onrender.com").rstrip("/"),
    "redsec": os.getenv("REDSEC_API_URL", "https://redsec-loadout-api.onrender.com").rstrip("/"),
}

# Endpoint usado para tirar cada serviço do cold start.
# Pode ser alterado no Render sem precisar mexer no código.
WAKE_PATHS = {
    "kick": os.getenv("KICK_WAKE_PATH", "/"),
    "warzone": os.getenv("WARZONE_WAKE_PATH", "/"),
    "redsec": os.getenv("REDSEC_WAKE_PATH", "/"),
}

_executor = ThreadPoolExecutor(max_workers=3)
_wake_lock = threading.Lock()
_last_wake = 0.0
WAKE_COOLDOWN = int(os.getenv("WAKE_COOLDOWN", "20"))

# Para comandos: a Central pode esperar até 3 minutos pelo cold start.
# O tempo é configurável, mas limitado a 180s para evitar travar indefinidamente.
COMMAND_WAKE_TIMEOUT = min(max(int(os.getenv("COMMAND_WAKE_TIMEOUT", "180")), 15), 180)
COMMAND_REQUEST_TIMEOUT = min(max(int(os.getenv("COMMAND_REQUEST_TIMEOUT", "30")), 10), 60)


def _wake_url(name: str) -> str:
    base = SERVICES[name]
    path = WAKE_PATHS[name] or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _ping_service(name: str, timeout=None):
    """Acorda um serviço. Pode demorar durante cold start."""
    timeout = timeout or COMMAND_WAKE_TIMEOUT
    url = _wake_url(name)
    try:
        started = time.monotonic()
        r = requests.get(
            url,
            timeout=(5, timeout),
            headers={"User-Agent": "SN7-Central-Wake/2.0"},
        )
        elapsed = round(time.monotonic() - started, 2)
        print(f"[WAKE] {name} -> HTTP {r.status_code} em {elapsed}s", flush=True)
        return {"service": name, "status": r.status_code, "elapsed": elapsed}
    except requests.RequestException as exc:
        elapsed = round(time.monotonic() - started, 2) if 'started' in locals() else 0
        print(f"[WAKE] {name} -> erro após {elapsed}s: {exc}", flush=True)
        return {"service": name, "status": None, "elapsed": elapsed, "error": str(exc)}


def wake_all(force=False):
    """Dispara Kick + Warzone + RedSec em paralelo sem bloquear /wake."""
    global _last_wake
    now = time.monotonic()

    with _wake_lock:
        if not force and (now - _last_wake) < WAKE_COOLDOWN:
            return False
        _last_wake = now

    for name in SERVICES:
        _executor.submit(_ping_service, name, COMMAND_WAKE_TIMEOUT)
    return True


def _wake_one(name: str, force=False):
    if name not in SERVICES:
        return False
    _executor.submit(_ping_service, name, COMMAND_WAKE_TIMEOUT)
    return True


def _wake_one_and_wait(name: str):
    """Para comandos: espera o serviço acordar, no máximo 3 minutos."""
    print(f"[WAKE-CMD] Aguardando {name} por até {COMMAND_WAKE_TIMEOUT}s...", flush=True)
    result = _ping_service(name, COMMAND_WAKE_TIMEOUT)
    print(f"[WAKE-CMD] {name} finalizado: {result}", flush=True)
    return result


@app.get("/")
def index():
    return jsonify({
        "online": True,
        "service": "API Central",
        "version": "wake-gambiarra-2.0",
        "command_wake_timeout": COMMAND_WAKE_TIMEOUT,
        "services": SERVICES,
    })


@app.get("/health")
def health():
    triggered = wake_all()
    return jsonify({
        "online": True,
        "wake_triggered": triggered,
        "services": list(SERVICES.keys()),
        "message": "Kick, Warzone e RedSec recebem wake em paralelo.",
    }), 200


@app.get("/wake")
def wake():
    service = (request.args.get("service") or "").strip().lower()
    force = request.args.get("force") in {"1", "true", "yes"}

    if service:
        if service not in SERVICES:
            return jsonify({"ok": False, "error": "service inválido"}), 400
        _wake_one(service, force=force)
        return jsonify({
            "ok": True,
            "wake_triggered": [service],
            "message": f"Wake de {service} disparado em background.",
        }), 202

    triggered = wake_all(force=force)
    return jsonify({
        "ok": True,
        "wake_triggered": ["kick", "warzone", "redsec"],
        "coalesced": not triggered,
        "message": "Os 3 serviços receberam o wake em paralelo.",
    }), 202


@app.get("/wake/<service>")
def wake_service(service):
    service = service.lower()
    if service not in SERVICES:
        return jsonify({"ok": False, "error": "service inválido"}), 400
    _wake_one(service, force=True)
    return jsonify({"ok": True, "wake_triggered": [service]}), 202


@app.route("/<service>", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@app.route("/<service>/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def proxy(service, subpath):
    """
    Proxy para /kick/..., /warzone/... e /redsec/....

    Para comandos, primeiro espera o cold start do serviço por até 3 minutos.
    Só depois encaminha a requisição real. Isso evita a corrida que causava
    502/timeout quando o wake e o comando eram enviados ao mesmo tempo.
    """
    service = service.lower()
    if service not in SERVICES:
        return jsonify({"error": "service não encontrado"}), 404

    # O wake do comando é SÍNCRONO: esperamos até 3 min, conforme pedido.
    wake_result = _wake_one_and_wait(service)

    base = SERVICES[service]
    target = base + "/" + subpath.lstrip("/")
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8", errors="ignore")

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length"}
    }

    try:
        r = requests.request(
            method=request.method,
            url=target,
            headers=headers,
            data=request.get_data(),
            timeout=(5, COMMAND_REQUEST_TIMEOUT),
            allow_redirects=False,
        )
        excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded]
        return Response(
            r.content,
            status=r.status_code,
            headers=response_headers,
            content_type=r.headers.get("content-type"),
        )
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "service": service,
            "target": target,
            "wake": wake_result,
            "error": "A API destino não respondeu após o período de espera.",
            "detail": str(exc),
        }), 504


@app.get("/status")
def status():
    return jsonify({
        "online": True,
        "command_wake_timeout": COMMAND_WAKE_TIMEOUT,
        "command_request_timeout": COMMAND_REQUEST_TIMEOUT,
        "services": {
            name: {"url": url, "wake_path": WAKE_PATHS[name]}
            for name, url in SERVICES.items()
        },
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
