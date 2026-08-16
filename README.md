# API Central v2

A central agora faz duas coisas:

1. `/wake` acorda/verifica Kick, Warzone e RedSec em paralelo.
2. Atua como proxy, permitindo que os comandos do StreamElements usem uma
   única URL central sem juntar os códigos das APIs.

Rotas:
- `/health`
- `/wake`
- `/kick/<rota-da-kick>?...`
- `/warzone/<rota-do-warzone>?...`
- `/redsec/<rota-do-redsec>?...`

Exemplo genérico:
`https://api-central-sn7.onrender.com/kick/ROTARANK?usuario=USUARIO`

A central também dispara o aquecimento das três APIs em cada chamada, sem
obrigar a resposta principal a esperar pelas outras duas.

IMPORTANTE:
Não altere ainda os comandos do StreamElements até confirmar a rota atual
de cada API. Para trocar um comando, basta manter a rota e trocar o domínio
pela central, adicionando o prefixo correspondente.

Exemplo:
API original: https://EXEMPLO.onrender.com/alguma-rota?x=1
Central:      https://api-central-sn7.onrender.com/warzone/alguma-rota?x=1
