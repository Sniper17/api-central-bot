import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify
import requests

app = Flask(__name__)

# APIs atuais
SERVICES = {
    "kick": os.getenv("KICK_API_URL", "https://kick-duelo-api.onrender.com"),
    "warzone": os.getenv("WARZONE_API_URL", "https://warzone-api-qbn9.onrender.com"),
    "redsec": os.getenv("REDSEC_API_URL", "https://redsec-loadout-api.onrender.com"),
}

TIMEOUT = float(os.getenv("WAKE_TIMEOUT", "8"))

def wake_service(name, url):
    """Touch the service without making the central request wait too long."""
    try:
        r = requests.get(url.rstrip("/") + "/", timeout=TIMEOUT)
        return {
            "service": name,
            "status": r.status_code,
            "ok": r.status_code < 500,
        }
    except requests.RequestException as e:
        return {
            "service": name,
            "status": None,
            "ok": False,
            "error": type(e).__name__,
        }

def wake_all():
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(wake_service, name, url)
                for name, url in SERVICES.items()]
        for job in as_completed(jobs):
            results.append(job.result())
    return sorted(results, key=lambda x: x["service"])

@app.get("/")
def home():
    return (
        "🌐 API CENTRAL ONLINE • use /health ou /wake"
    )

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "api-central",
        "version": "1.0.0",
        "services": {
            "kick": SERVICES["kick"],
            "warzone": SERVICES["warzone"],
            "redsec": SERVICES["redsec"],
        },
    })

@app.get("/wake")
def wake():
    results = wake_all()
    return jsonify({
        "ok": True,
        "message": "⚡ Serviços acionados em paralelo.",
        "services": results,
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
