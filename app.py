import os
import time
import concurrent.futures
import requests
from flask import Flask, jsonify

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
REQUEST_TIMEOUT = float(os.getenv("WAKE_REQUEST_TIMEOUT", "8"))
RETRIES = int(os.getenv("WAKE_RETRIES", "1"))
RETRY_DELAY = float(os.getenv("WAKE_RETRY_DELAY", "1"))


def wake_service(name, base_url):
    """
    Faz GET na raiz da API para provocar cold start.

    Cada serviço é tratado isoladamente. Se uma API retornar 502 ou
    estourar o timeout, registramos o erro e seguimos sem bloquear
    os outros serviços nem o /wake da Central.
    """
    url = base_url + "/"
    last_status = None
    last_error = None
    started = time.time()

    for attempt in range(1, RETRIES + 2):
        attempt_started = time.time()

        try:
            print(
                f"[WAKE] {name}: tentativa {attempt} -> {url}",
                flush=True
            )

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            last_status = response.status_code
            elapsed_attempt = time.time() - attempt_started
            elapsed_total = time.time() - started

            print(
                f"[WAKE] {name}: HTTP {response.status_code} "
                f"em {elapsed_attempt:.1f}s (total {elapsed_total:.1f}s)",
                flush=True
            )

            # 2xx/3xx = serviço respondeu e está acordado.
            if 200 <= response.status_code < 400:
                return {
                    "ok": True,
                    "service": name,
                    "status": response.status_code,
                    "attempt": attempt,
                    "elapsed": round(elapsed_total, 1),
                }

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            elapsed_total = time.time() - started

            print(
                f"[WAKE] {name}: erro na tentativa {attempt}: "
                f"{last_error} (total {elapsed_total:.1f}s)",
                flush=True
            )

        # No máximo uma nova tentativa curta.
        if attempt <= RETRIES:
            time.sleep(RETRY_DELAY)

    elapsed_total = time.time() - started

    print(
        f"[WAKE] {name}: desistindo após {RETRIES + 1} tentativa(s) "
        f"em {elapsed_total:.1f}s. A Central continuará normalmente.",
        flush=True
    )

    return {
        "ok": False,
        "service": name,
        "status": last_status,
        "attempt": RETRIES + 1,
        "elapsed": round(elapsed_total, 1),
        "error": last_error,
    }


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-safe-parallel-v3",
        "services": SERVICES,
        "wake": {
            "timeout_seconds": REQUEST_TIMEOUT,
            "retries": RETRIES,
            "retry_delay_seconds": RETRY_DELAY,
        },
    })


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-safe-parallel-v3",
    })


@app.get("/wake")
def wake():
    print("========================================", flush=True)
    print("[CENTRAL WAKE] Solicitação recebida.", flush=True)
    print(
        f"[CENTRAL WAKE] timeout={REQUEST_TIMEOUT}s "
        f"retries={RETRIES} delay={RETRY_DELAY}s",
        flush=True
    )
    print(
        "[CENTRAL WAKE] Kick, RedSec e Warzone serão acionados "
        "em paralelo; falha de um não bloqueia os demais.",
        flush=True
    )

    started = time.time()
    results = []

    # Os três serviços são chamados em paralelo.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(SERVICES)
    ) as executor:
        futures = {
            executor.submit(wake_service, name, url): name
            for name, url in SERVICES.items()
        }

        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                # Uma exceção inesperada de um serviço não derruba o /wake.
                result = {
                    "ok": False,
                    "service": name,
                    "status": None,
                    "attempt": 0,
                    "elapsed": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(
                    f"[WAKE] {name}: exceção isolada: {exc}",
                    flush=True
                )

            results.append(result)

    results.sort(key=lambda item: item["service"])
    overall_ok = all(item["ok"] for item in results)
    total_elapsed = time.time() - started

    print(
        f"[CENTRAL WAKE] Concluído em {total_elapsed:.1f}s. "
        f"overall_ok={overall_ok}",
        flush=True
    )
    for item in results:
        print(
            f"[CENTRAL WAKE] {item['service']} -> "
            f"HTTP {item.get('status')} | ok={item['ok']} | "
            f"tentativa={item.get('attempt')} | "
            f"tempo={item.get('elapsed')}s",
            flush=True
        )
    print("========================================", flush=True)

    # Mantém HTTP 200 para o Worker receber o diagnóstico mesmo quando
    # uma API downstream estiver fria/indisponível.
    return jsonify({
        "ok": overall_ok,
        "message": "Serviços acionados em paralelo.",
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
