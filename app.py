import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

SERVICES = {
    "kick": os.getenv("KICK_API_URL", "https://kick-duelo-api.onrender.com").rstrip("/"),
    "warzone": os.getenv("WARZONE_API_URL", "https://warzone-api-qbn9.onrender.com").rstrip("/"),
    "redsec": os.getenv("REDSEC_API_URL", "https://redsec-loadout-api.onrender.com").rstrip("/"),
}

WAKE_PATHS = {
    "kick": os.getenv("KICK_WAKE_PATH", "/"),
    "warzone": os.getenv("WARZONE_WAKE_PATH", "/"),
    "redsec": os.getenv("REDSEC_WAKE_PATH", "/"),
}

# Importante: o Render pode encerrar uma requisição HTTP longa antes de 3 minutos.
# Por isso não bloqueamos 180s em uma única chamada. A Central acorda em background
# e tenta o comando real várias vezes por uma janela total configurável.
TOTAL_RETRY_WINDOW = min(max(int(os.getenv("COMMAND_RETRY_WINDOW", "90")), 30), 95)
RETRY_INTERVAL = min(max(float(os.getenv("COMMAND_RETRY_INTERVAL", "5")), 2), 10)
CONNECT_TIMEOUT = 5
REQUEST_TIMEOUT = min(max(int(os.getenv("COMMAND_REQUEST_TIMEOUT", "12")), 5), 20)
WAKE_TIMEOUT = min(max(int(os.getenv("WAKE_REQUEST_TIMEOUT", "20")), 8), 30)
WAKE_COOLDOWN = min(max(int(os.getenv("WAKE_COOLDOWN", "15")), 0), 120)

_executor = ThreadPoolExecutor(max_workers=8)
_wake_lock = threading.Lock()
_last_wake = {name: 0.0 for name in SERVICES}


def wake_url(name):
    path = WAKE_PATHS[name] or "/"
    if not path.startswith("/"):
        path = "/" + path
    return SERVICES[name] + path


def wake_service(name, force=False):
    """Faz um pedido curto para tirar o serviço do cold start."""
    now = time.monotonic()
    with _wake_lock:
        if not force and now - _last_wake[name] < WAKE_COOLDOWN:
            return {"service": name, "skipped": True}
        _last_wake[name] = now

    try:
        started = time.monotonic()
        r = requests.get(
            wake_url(name),
            timeout=(CONNECT_TIMEOUT, WAKE_TIMEOUT),
            headers={"User-Agent": "SN7-Central-Wake/3.0"},
        )
        elapsed = round(time.monotonic() - started, 2)
        print(f"[WAKE] {name} HTTP {r.status_code} em {elapsed}s", flush=True)
        return {"service": name, "status": r.status_code, "elapsed": elapsed}
    except requests.RequestException as exc:
        elapsed = round(time.monotonic() - started, 2)
        print(f"[WAKE] {name} ainda acordando ({elapsed}s): {exc}", flush=True)
        return {"service": name, "status": None, "elapsed": elapsed, "error": str(exc)}


def schedule_wake(name, force=False):
    if name not in SERVICES:
        return False
    _executor.submit(wake_service, name, force)
    return True


def wake_all(force=False):
    for name in SERVICES:
        schedule_wake(name, force=force)
    return True


def build_target(service, subpath):
    target = SERVICES[service] + "/" + subpath.lstrip("/")
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8", errors="ignore")
    return target


def clean_headers():
    return {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "connection"}
    }


def friendly_failure(service, elapsed):
    # Nunca devolve o HTML gigante de erro do Render para o chat.
    return Response(
        f"⚠️ {service.capitalize()} ainda está iniciando. A tentativa levou {int(elapsed)}s. Tente o comando novamente em alguns segundos.",
        status=503,
        content_type="text/plain; charset=utf-8",
    )


def proxy_with_retry(service, target):
    """Acorda e tenta o comando real repetidamente.

    Isso é mais confiável que esperar 180s numa única requisição. Se o Render
    devolver 502/503/504 durante o cold start, esperamos e tentamos novamente.
    Assim que a API estiver viva, o POST/GET original é enviado normalmente.
    """
    body = request.get_data()
    headers = clean_headers()
    method = request.method
    deadline = time.monotonic() + TOTAL_RETRY_WINDOW
    attempt = 0
    last_status = None

    while time.monotonic() < deadline:
        attempt += 1
        remaining = max(1, deadline - time.monotonic())
        timeout = min(REQUEST_TIMEOUT, remaining)
        try:
            started = time.monotonic()
            r = requests.request(
                method=method,
                url=target,
                headers=headers,
                data=body,
                timeout=(CONNECT_TIMEOUT, timeout),
                allow_redirects=False,
            )
            elapsed_req = round(time.monotonic() - started, 2)
            last_status = r.status_code
            print(
                f"[PROXY] {service} tentativa {attempt} -> HTTP {r.status_code} em {elapsed_req}s",
                flush=True,
            )

            # 2xx/3xx/4xx do próprio endpoint são respostas reais: não repetir.
            # Só repetimos os erros típicos do cold start/proxy do Render.
            if r.status_code not in {502, 503, 504}:
                excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
                response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded]
                return Response(
                    r.content,
                    status=r.status_code,
                    headers=response_headers,
                    content_type=r.headers.get("content-type"),
                )

        except requests.RequestException as exc:
            print(f"[PROXY] {service} tentativa {attempt} sem resposta: {exc}", flush=True)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(RETRY_INTERVAL, remaining))

    elapsed = TOTAL_RETRY_WINDOW
    print(f"[PROXY] {service} não acordou dentro da janela de {elapsed}s. último status={last_status}", flush=True)
    return friendly_failure(service, elapsed)


@app.get("/")
def index():
    return jsonify({
        "online": True,
        "service": "API Central",
        "version": "wake-gambiarra-3.0",
        "services": SERVICES,
        "command_retry_window": TOTAL_RETRY_WINDOW,
    })


@app.get("/health")
def health():
    wake_all()
    return jsonify({
        "online": True,
        "wake_triggered": list(SERVICES.keys()),
        "message": "Kick, Warzone e RedSec receberam wake em background.",
    }), 200


@app.get("/wake")
def wake():
    service = (request.args.get("service") or "").strip().lower()
    force = request.args.get("force") in {"1", "true", "yes"}
    if service:
        if service not in SERVICES:
            return jsonify({"ok": False, "error": "service inválido"}), 400
        schedule_wake(service, force=force)
        return jsonify({"ok": True, "wake_triggered": [service]}), 202
    wake_all(force=force)
    return jsonify({"ok": True, "wake_triggered": list(SERVICES.keys())}), 202


@app.get("/wake/<service>")
def wake_service_route(service):
    service = service.lower()
    if service not in SERVICES:
        return jsonify({"ok": False, "error": "service inválido"}), 400
    schedule_wake(service, force=True)
    return jsonify({"ok": True, "wake_triggered": [service]}), 202


@app.route(
    "/<service>", defaults={"subpath": ""},
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
@app.route(
    "/<service>/<path:subpath>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
def proxy(service, subpath):
    service = service.lower()
    if service not in SERVICES:
        return jsonify({"error": "service não encontrado"}), 404

    # Primeiro dispara o wake sem bloquear. Depois já tentamos o endpoint real.
    # Se a API estiver dormindo, os 502/503/504 são repetidos automaticamente.
    schedule_wake(service)
    target = build_target(service, subpath)
    print(f"[COMMAND] {service} -> {target}", flush=True)
    return proxy_with_retry(service, target)


@app.get("/status")
def status():
    return jsonify({
        "online": True,
        "version": "wake-gambiarra-3.0",
        "command_retry_window": TOTAL_RETRY_WINDOW,
        "retry_interval": RETRY_INTERVAL,
        "services": {
            name: {"url": url, "wake_path": WAKE_PATHS[name]}
            for name, url in SERVICES.items()
        },
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
