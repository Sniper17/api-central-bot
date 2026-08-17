
import os
import time
import concurrent.futures
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# O Kick Worker chama /wake a partir de um evento recebido.
# Portanto NÃO devemos chamar o próprio Kick Worker novamente:
# isso gera requisições desnecessárias/429 e pode contribuir para timeout.
SERVICES = {
    "redsec": os.getenv(
        "REDSEC_API_URL",
        "https://redsec-loadout-api.onrender.com"
    ).strip().rstrip("/"),
    "warzone": os.getenv(
        "WARZONE_API_URL",
        "https://warzone-api-qbn9.onrender.com"
    ).strip().rstrip("/"),
}

# Rotas REAIS das APIs usadas pelos comandos do bot.
# RedSec: !bf -> /classe?arma=...
# Warzone: !classe/!meta -> /meta?tipo=...
REDSEC_WAKE_PATH = os.getenv(
    "REDSEC_WAKE_PATH",
    "/classe?arma=svd"
).strip()

WARZONE_WAKE_PATH = os.getenv(
    "WARZONE_WAKE_PATH",
    "/meta?tipo=ar"
).strip()

# Render Free pode colocar o serviço para dormir.
# Acordar uma API pode demorar dezenas de segundos.
# Cold start do Render Free.
REQUEST_TIMEOUT = int(os.getenv("WAKE_REQUEST_TIMEOUT", "25"))
RETRIES = int(os.getenv("WAKE_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("WAKE_RETRY_DELAY", "12"))


def wake_service(name, base_url):
    """
    Faz GET em uma rota real da API para provocar cold start.
    Usa as mesmas rotas que o bot utiliza para entregar os loadouts.
    """
    if name == "redsec":
        url = base_url + REDSEC_WAKE_PATH
    elif name == "warzone":
        url = base_url + WARZONE_WAKE_PATH
    else:
        url = base_url + "/"

    last_status = None
    last_error = None
    started = time.time()

    for attempt in range(1, RETRIES + 2):
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

            print(
                f"[WAKE] {name}: HTTP {response.status_code} "
                f"em {time.time() - started:.1f}s",
                flush=True
            )

            # Qualquer resposta HTTP significa que o serviço respondeu.
            # 2xx/3xx é considerado sucesso.
            if 200 <= response.status_code < 400:
                return {
                    "ok": True,
                    "service": name,
                    "status": response.status_code,
                    "attempt": attempt,
                    "elapsed": round(time.time() - started, 1),
                }

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[WAKE] {name}: erro na tentativa {attempt}: "
                f"{last_error}",
                flush=True
            )

        if attempt <= RETRIES:
            time.sleep(RETRY_DELAY)

    return {
        "ok": False,
        "service": name,
        "status": last_status,
        "attempt": RETRIES + 1,
        "elapsed": round(time.time() - started, 1),
        "error": last_error,
    }


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-v6-real-routes",
        "services": SERVICES,
    })


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "api-central-sn7",
        "version": "wake-v6-real-routes",
    })


@app.get("/wake")
def wake():
    print("========================================", flush=True)
    print("[CENTRAL WAKE] Solicitação recebida.", flush=True)
    print(
        f"[CENTRAL WAKE] timeout={REQUEST_TIMEOUT}s "
        f"retries={RETRIES}",
        flush=True
    )

    results = []

    # Não chamamos o Kick Worker: ele já está acordado e foi quem
    # iniciou este /wake. Acordamos somente as APIs downstream.
    # Sequencial evita dois cold starts pesados simultaneamente no plano Free.
    for name, url in SERVICES.items():
        results.append(wake_service(name, url))

    overall_ok = all(item["ok"] for item in results)

    print("[CENTRAL WAKE] Resultado:", results, flush=True)
    print("========================================", flush=True)

    # Mantemos HTTP 200 para que o Worker consiga enxergar
    # o resultado individual das APIs sem perder o diagnóstico.
    return jsonify({
        "ok": overall_ok,
        "message": "Serviços downstream acionados pelas rotas reais.",
        "services": results,
    }), 200


# Proxy da API Central para o ranking da Kick-Duelo API.
# O /wake permanece inalterado.
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
