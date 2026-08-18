# API Central — browser-style wake v9

A Central mantém o endpoint `/wake` e o diagnóstico de status.

O despertar usa o mesmo comportamento do navegador: abre a URL em tentativas curtas, usa headers de navegador, fecha a tentativa quando recebe 502/503/504 ou timeout e abre novamente.

O Worker atual usa wake direto para evitar que a Central fique no caminho crítico do webhook da Kick, mas a Central continua disponível para diagnóstico e outros fluxos.

Estrutura do ZIP: arquivos do projeto diretamente na raiz, sem pastas extras.
