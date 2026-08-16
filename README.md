# API Central v2.1

Correção do wake-up da Kick.

O Render gratuito pode demorar mais de 8 segundos para acordar uma aplicação.
Por isso a central agora:
- aguarda até 30 segundos por um serviço durante `/wake`;
- consulta `/health` da Kick para o wake, em vez de `/`;
- mantém Warzone e RedSec como estavam;
- preserva o proxy `/kick/<rota>`, `/warzone/<rota>` e `/redsec/<rota>`.

Não altere ainda os comandos do StreamElements.
Primeiro confirme `/health` e `/wake`.
