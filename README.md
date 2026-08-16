# API Central v2.2

Correção do wake-up da Kick.

A Kick v13.7.1 responde HTTP 200 no endpoint `/`, então a central usa `/`
para acordar os três serviços. Não depende de `/health` da Kick.

- timeout de wake: 30s
- Kick: https://kick-duelo-api.onrender.com/
- Warzone: https://warzone-api-qbn9.onrender.com/
- RedSec: https://redsec-loadout-api.onrender.com/

Não altere os comandos do StreamElements ainda.
