import os
import time
import concurrent.futures
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

SERVICES = {
    "kick": os.getenv(
        "KICK_WORKER_URL",
        "https://sn7-kick-worker.onrender.com"
    ).strip().rstrip("/"),
    "redsec": os.getenv(
        "REDSEC_API_URL",
        "https://redsec-loadout-api.onrender.com"
    ).strip().rstrip("/"),
    "warzone": os.getenv(
        "WARZONE_API_URL",
        "https://warzone-api-qbn9.onrender.com"
    ).strip().rstrip("/"),
}

# Acordar uma API do Render pode levar alguns segundos.
# O /wake precisa terminar antes do timeout do worker da Central.
# Os requests são curtos e independentes: uma API ruim não trava as outras.
# O Render Free pode levar cerca de um minuto para sair do cold start.
# A Central fica aguardando a API realmente responder antes de devolver sucesso.
WAKE_REQUEST_TIMEOUT = max(5.0, float(os.getenv("WAKE_REQUEST_TIMEOUT", "12")))
WAKE_MAX_WAIT = max(60.0, float(os.getenv("WAKE_MAX_WAIT", "120")))
WAKE_POLL_INTERVAL = max(10.0, float(os.getenv("WAKE_POLL_INTERVAL", "10")))

# Mantidos por compatibilidade com variáveis antigas.
REQUEST_TIMEOUT = WAKE_REQUEST_TIMEOUT
RETRIES = int(os.getenv("WAKE_RETRIES", "0"))
RETRY_DELAY = WAKE_POLL_INTERVAL


def wake_service(name, base_url):
    """Acorda uma API e só retorna sucesso quando ela estiver respondendo."""
    url = base_url + "/"
    started = time.time()
    deadline = started + WAKE_MAX_WAIT
    attempt = 0
    last_status = None
    last_error = None

    while time.time() < deadline:
        attempt += 1
        attempt_started = time.time()
        remaining = max(1.0, deadline - time.time())
        timeout = min(WAKE_REQUEST_TIMEOUT, remaining)

        try:
            print(
                f"[WAKE] {name}: tentativa {attempt} -> {url} "
                f"(restam {remaining:.1f}s)",
                flush=True,
            )
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            )
            last_status = response.status_code
            elapsed = time.time() - started

            print(
                f"[WAKE] {name}: HTTP {response.status_code} "
                f"em {time.time()-attempt_started:.1f}s (total {elapsed:.1f}s)",
                flush=True,
            )

            if 200 <= response.status_code < 400:
                return {
                    "ok": True,
                    "service": name,
                    "status": response.status_code,
                    "attempt": attempt,
                    "elapsed": round(elapsed, 1),
                }

            last_error = f"HTTP {response.status_code}: {response.text[:300]}"

        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[WAKE] {name}: erro na tentativa {attempt}: {last_error}",
                flush=True,
            )

        if time.time() + WAKE_POLL_INTERVAL >= deadline:
            break
        print(
            f"[WAKE] {name}: ainda iniciando. Nova verificação em "
            f"{WAKE_POLL_INTERVAL:.1f}s.",
            flush=True,
        )
        time.sleep(WAKE_POLL_INTERVAL)

    elapsed = time.time() - started
    print(
        f"[WAKE] {name}: não ficou pronto dentro de {elapsed:.1f}s.",
        flush=True,
    )
    return {
        "ok": False,
        "service": name,
        "status": last_status,
        "attempt": attempt,
        "elapsed": round(elapsed, 1),
        "error": last_error or "tempo máximo de espera atingido",
    }


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-until-ready-v5-10s",
        "services": SERVICES,
        "wake": {
            "timeout_seconds": REQUEST_TIMEOUT,
            "max_wait_seconds": WAKE_MAX_WAIT,
            "poll_interval_seconds": WAKE_POLL_INTERVAL,
            "mode": "trigger_once_then_check_every_10s",
        },
    })


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-until-ready-v5-10s",
    })


@app.get("/wake/trigger")
def wake_trigger_alias():
    """Compatibilidade: o Worker usa /wake/trigger."""
    return wake_trigger()


@app.get("/trigger")
def wake_trigger():
    """Dispara o cold start sem manter a requisição aberta até a API acordar."""
    requested = (request.args.get("service") or "").strip().lower()
    selected = SERVICES if not requested or requested == "all" else {requested: SERVICES.get(requested, "")}
    if requested and requested not in SERVICES and requested != "all":
        return jsonify({"ok": False, "error": f"Serviço inválido: {requested}", "available": sorted(SERVICES)}), 400

    results = []
    for name, base_url in selected.items():
        if not base_url:
            continue
        try:
            # Um timeout curto é intencional: o objetivo aqui é só iniciar o
            # cold start. A confirmação acontece em /status a cada 10s.
            r = requests.get(base_url + "/", timeout=min(5.0, WAKE_REQUEST_TIMEOUT), allow_redirects=True)
            results.append({"service": name, "status": r.status_code, "triggered": True})
            print(f"[TRIGGER] {name}: HTTP {r.status_code}", flush=True)
        except requests.RequestException as exc:
            results.append({"service": name, "status": None, "triggered": True, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[TRIGGER] {name}: cold start disparado/timeout curto: {exc}", flush=True)

    return jsonify({"ok": True, "message": "Cold start disparado.", "services": results}), 202


@app.get("/status")
def wake_status():
    """Checa se o serviço já está realmente respondendo. Esta rota é curta."""
    requested = (request.args.get("service") or "").strip().lower()
    if requested not in SERVICES:
        return jsonify({"ready": False, "error": "Informe service=kick|redsec|warzone"}), 400
    base_url = SERVICES[requested]
    try:
        r = requests.get(base_url + "/", timeout=min(8.0, WAKE_REQUEST_TIMEOUT), allow_redirects=True)
        ready = 200 <= r.status_code < 400
        print(f"[STATUS] {requested}: HTTP {r.status_code} ready={ready}", flush=True)
        return jsonify({"ready": ready, "service": requested, "status": r.status_code}), 200
    except requests.RequestException as exc:
        print(f"[STATUS] {requested}: ainda iniciando ({type(exc).__name__})", flush=True)
        return jsonify({"ready": False, "service": requested, "status": None}), 200


@app.get("/wake")
def wake():
    """
    /wake sem parâmetro acorda os três serviços em paralelo.
    /wake?service=redsec ou /wake?service=warzone acorda somente o alvo
    necessário para um comando, aguardando ele ficar realmente pronto.
    """
    requested = (request.args.get("service") or "").strip().lower()
    if requested and requested not in SERVICES:
        return jsonify({
            "ok": False,
            "error": f"Serviço inválido: {requested}",
            "available": sorted(SERVICES),
        }), 400

    selected = {requested: SERVICES[requested]} if requested else SERVICES

    print("========================================", flush=True)
    print("[CENTRAL WAKE] Solicitação recebida.", flush=True)
    print(
        f"[CENTRAL WAKE] alvo={requested or 'todos'} "
        f"max_wait={WAKE_MAX_WAIT}s poll={WAKE_POLL_INTERVAL}s",
        flush=True,
    )

    started = time.time()
    results = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(selected)
    ) as executor:
        futures = {
            executor.submit(wake_service, name, url): name
            for name, url in selected.items()
        }

        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "ok": False,
                    "service": name,
                    "status": None,
                    "attempt": 0,
                    "elapsed": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"[WAKE] {name}: exceção isolada: {exc}", flush=True)
            results.append(result)

    results.sort(key=lambda item: item["service"])
    overall_ok = all(item["ok"] for item in results)
    total_elapsed = time.time() - started

    print(
        f"[CENTRAL WAKE] Concluído em {total_elapsed:.1f}s. "
        f"overall_ok={overall_ok}",
        flush=True,
    )
    for item in results:
        print(
            f"[CENTRAL WAKE] {item['service']} -> HTTP {item.get('status')} | "
            f"ok={item['ok']} | tentativa={item.get('attempt')} | "
            f"tempo={item.get('elapsed')}s",
            flush=True,
        )
    print("========================================", flush=True)

    return jsonify({
        "ok": overall_ok,
        "message": "Serviço pronto." if requested else "Serviços prontos.",
        "elapsed": round(total_elapsed, 1),
        "services": results,
    }), 200


# Proxy da API Central para o ranking da Kick-Duelo API.
KICK_DUELO_URL = os.getenv(
    "KICK_DUELO_API_URL",
    "https://kick-duelo-api.onrender.com"
).strip().rstrip("/")


@app.get("/kick/ranking")
def kick_ranking():
    """Encaminha /kick/ranking para a rota /ranking da Kick-Duelo API."""
    url = KICK_DUELO_URL + "/ranking"
    try:
        response = requests.get(
            url,
            timeout=int(os.getenv("KICK_RANKING_TIMEOUT", "75")),
            allow_redirects=True,
        )

        print(
            f"[KICK RANKING] {url} -> HTTP {response.status_code}",
            flush=True
        )

        content_type = response.headers.get(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        return response.text, response.status_code, {
            "Content-Type": content_type
        }

    except requests.RequestException as exc:
        print(f"[KICK RANKING] erro: {exc}", flush=True)
        return f"unable to make request: {exc}", 502


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
