# API Central v3 — Keepalive/Warm-up

Tentativa A para resolver o cold start sem usar outro servidor.

A central:
- mantém o `/wake` síncrono para diagnóstico;
- em qualquer `/kick/...`, `/warzone/...` ou `/redsec/...`, inicia um warm-up
  não bloqueante das três APIs;
- em `/health`, também inicia o warm-up. Isso permite usar um monitor externo
  para pingar a central periodicamente;
- evita várias tempestades de wake simultâneas com um lock;
- continua usando chamadas paralelas;
- não altera as APIs originais.

TESTE:
1. Deploy.
2. Abra `/health` e `/wake` e confirme 200 nas três.
3. Depois use o `!rank` pela rota central.
4. Espere o período de sleep.
5. Use `!rank` e, depois de alguns segundos, teste `!bf svd`.

Se o Render matar a instância da central imediatamente após a resposta, o
warm-up em background não poderá continuar; nesse caso a solução B (celular
ou outro host sempre ligado) será a mais confiável.


Versão atualizada: /wake aguarda a API alvo ficar realmente disponível e aceita ?service=redsec ou ?service=warzone.
