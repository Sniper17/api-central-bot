# API Central v1

Primeira etapa: um despertador central para as três APIs.

APIs configuradas:
- Kick: https://kick-duelo-api.onrender.com
- Warzone: https://warzone-api-qbn9.onrender.com
- RedSec/BF: https://redsec-loadout-api.onrender.com

Rotas:
- `/` -> teste simples
- `/health` -> verifica se a central está online
- `/wake` -> chama as três APIs em paralelo

IMPORTANTE:
Esta v1 ainda NÃO substitui os comandos do StreamElements.
Primeiro vamos provar que a central consegue acordar as três APIs.
Depois adicionaremos o roteamento dos comandos (`!rank`, `!bf svd`, `!classe c9`, etc.)
sem mexer nas APIs originais.
