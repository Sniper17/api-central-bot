SN7 CENTRAL - WAKE FIX v2

OBJETIVO
Corrigir o problema em que a Central retorna:
- kick: 200
- redsec: 200
- warzone: 502

A correção NÃO chama /wake nas APIs downstream.
Ela acessa a raiz "/" de cada API para provocar o cold start,
porque abrir a URL da API no navegador já demonstrou que acorda o Render.

Também há:
- chamadas em paralelo;
- timeout de 75 segundos;
- 2 tentativas adicionais;
- logs individuais;
- resultado individual de cada serviço.

VARIÁVEIS OPCIONAIS NO RENDER
KICK_WORKER_URL=https://sn7-kick-worker.onrender.com
REDSEC_API_URL=https://redsec-loadout-api.onrender.com
WARZONE_API_URL=https://warzone-api-qbn9.onrender.com
WAKE_REQUEST_TIMEOUT=75
WAKE_RETRIES=2
WAKE_RETRY_DELAY=3

START COMMAND
gunicorn --bind 0.0.0.0:$PORT app:app

IMPORTANTE
Esta versão é para substituir a Central que atualmente possui /wake.
O Worker da Kick já chama:
https://api-central-sn7.onrender.com/wake

Depois do deploy, teste:
https://api-central-sn7.onrender.com/wake

O esperado é:
warzone -> HTTP 200 -> ok=True

Mesmo que o primeiro request demore por causa do cold start, o endpoint
fica aguardando a resposta em vez de desistir rapidamente.


Atualização v3: adicionada GET /kick/ranking, encaminhando para https://kick-duelo-api.onrender.com/ranking. A rota /wake foi preservada.
