import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, Response, jsonify, request
import requests

app = Flask(__name__)

SERVICES = {
    "kick": os.getenv("KICK_API_URL", "https://kick-duelo-api.onrender.com"),
    "warzone": os.getenv("WARZONE_API_URL", "https://warzone-api-qbn9.onrender.com"),
    "redsec": os.getenv("REDSEC_API_URL", "https://redsec-loadout-api.onrender.com"),
}

TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "20"))
WAKE_TIMEOUT = float(os.getenv("WAKE_TIMEOUT", "30"))

def wake_service(name, url):
    try:
        # Use the root endpoint for all services. The Kick API is known to
        # return HTTP 200 there; this avoids depending on a /health route
        # that may not exist on older deployed versions.
        r = requests.get(url.rstrip("/") + "/", timeout=WAKE_TIMEOUT)
        return {"service": name, "status": r.status_code, "ok": r.status_code < 500}
    except requests.RequestException as e:
        return {"service": name, "status": None, "ok": False, "error": type(e).__name__}

def wake_all():
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda item: wake_service(*item), SERVICES.items()))

def background_wake():
    # Fire-and-forget: don't make the user's command wait for the other APIs.
    pool = ThreadPoolExecutor(max_workers=3)
    pool.submit(wake_all)
    pool.shutdown(wait=False)

def proxy(service, path):
    if service not in SERVICES:
        return Response("Serviço não encontrado.", status=404)

    # Every command also triggers the three warm-up calls.
    background_wake()

    target = SERVICES[service].rstrip("/") + "/" + path.lstrip("/")
    try:
        r = requests.get(
            target,
            params=request.args,
            headers={"User-Agent": "api-central-sn7/2.0"},
            timeout=TIMEOUT,
        )
        content_type = r.headers.get("Content-Type", "text/plain; charset=utf-8")
        return Response(r.content, status=r.status_code, content_type=content_type)
    except requests.RequestException as e:
        return Response(
            f"⚠️ Serviço {service} ainda está acordando. Tente novamente em alguns segundos. ({type(e).__name__})",
            status=502,
        )

@app.get("/")
def home():
    return "🌐 API CENTRAL v2 ONLINE • /health • /wake"

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "api-central",
        "version": "2.2.0",
        "services": SERVICES,
        "routes": ["/wake", "/kick/<rota>", "/warzone/<rota>", "/redsec/<rota>"],
    })

@app.get("/wake")
def wake():
    # This one waits for all three checks and reports their status.
    results=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(wake_service, name, url) for name,url in SERVICES.items()]
        for f in futures:
            results.append(f.result())
    results.sort(key=lambda x:x["service"])
    return jsonify({"ok": True, "message": "⚡ Serviços acionados em paralelo.", "services": results})

@app.get("/kick/<path:path>")
def kick_proxy(path):
    return proxy("kick", path)

@app.get("/warzone/<path:path>")
def warzone_proxy(path):
    return proxy("warzone", path)

@app.get("/redsec/<path:path>")
def redsec_proxy(path):
    return proxy("redsec", path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
