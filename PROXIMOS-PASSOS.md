# Painel e recuperação de episódios faltantes

## Decisão de 02/11/2026

O usuário decidiu esperar os downloads atuais terminarem antes de implementar
esta melhoria. Este documento registra o próximo trabalho; não agenda sua
execução e não indica que o painel ou as novas tentativas já estejam ativos.

Direção escolhida: **ampliar o script existente e criar um painel por cima,
começando pelos botões manuais e pelo acompanhamento completo; depois ativar
as tentativas automáticas**. O mecanismo de recuperação deve servir tanto ao
painel quanto à linha de comando, sem duplicar as regras.

Separadamente, o limite atual do qBittorrent passa a quatro downloads
simultâneos, com dois uploads e seis torrents ativos no total. Isso não altera
a quantidade de análises simultâneas do ClamAV.

## O que existe hoje

- Sonarr e Radarr controlam os títulos monitorados e oferecem buscas manuais.
  Sonarr permite buscar por episódio, temporada ou em Wanted → Missing.
- `media-stack/download-watch.py` identifica falta de progresso por 15 minutos
  observados em download ativo, etiqueta `erro-sem-progresso` e pausa o torrent.
  Tempo na fila, pausado ou com a VM desligada não conta. Ele não busca substitutos.
- `media-stack/triage/triage.py` copia, analisa e valida os arquivos; registra
  resultados em SQLite e em `STATUS/triagem.json`. Ainda faltam registros
  detalhados durante cada etapa em execução.
- A aprovação da triagem pode indicar que o comando de importação foi enviado;
  não comprova que o organizador já importou nem que o Jellyfin recebeu o vídeo.
- O sincronizador mantém `jellyfin/state/published.json` e `last-run.json`.
  A publicação no HD deve ser distinguida da presença efetiva no catálogo do Jellyfin.

## Primeira etapa: acompanhamento e ações manuais

Mostrar por série/temporada os episódios esperados, disponíveis e pendentes,
com uma linha por episódio e a data da última atualização de cada fonte.
Se uma aplicação estiver indisponível, mostrar estado desconhecido ou dado
antigo com seu horário; não interpretar falha de consulta como episódio ausente.

| Estado | Evidência a apresentar |
| --- | --- |
| Sem fonte | Episódio monitorado e já lançado, sem arquivo nem download correspondente; última busca e resultado |
| Buscando | Comando de busca em execução e seu andamento |
| Na fila / baixando | Estado real do qBittorrent, progresso, velocidade e peers conectados |
| Travado | Tempo observado sem progresso, motivo e tentativas anteriores |
| Aguardando análise | Download completo e ainda sem resultado vigente da triagem |
| Em análise | Etapa registrada, arquivo atual, início e tempo decorrido |
| Revisão / reprovado / erro temporário | Motivo concreto da triagem e ação elegível |
| Aprovado / importação pendente | Resultado da triagem e estado real do comando de importação |
| Importado / aguardando cópia | Arquivo confirmado no Sonarr/Radarr e estado da coleta |
| Publicado / aguardando catálogo | Arquivo publicado no HD, ainda sem confirmação no Jellyfin |
| Disponível no Jellyfin | Item e arquivo confirmados pela API do Jellyfin |

Acrescentar registros persistentes na triagem para distinguir cópia,
espera pela trava do scanner, antivírus e validação de mídia. Exibir etapa,
arquivo e tempo; não inventar porcentagem ou previsão de término do ClamAV.

Botões previstos:

- **Buscar faltantes** de uma série, temporada ou episódio.
- **Buscar outra fonte** para um download travado ou uma distribuição inadequada.
- **Tentar novamente** uma etapa com erro temporário, quando elegível.
- **Ver motivo e histórico**, com fonte, tentativa, resultado e próxima ação.

Antes de buscar, cruzar os episódios do organizador com os arquivos dos torrents,
inclusive pacotes de temporada e numeração absoluta de anime. Um episódio
completo aguardando triagem não deve gerar outra cópia por aparecer como
faltante no Sonarr. Exigir correspondência confiável de série e episódio;
casos ambíguos precisam ficar visíveis para decisão manual.

Buscas devem usar Sonarr/Radarr e os indexadores já cadastrados. Se for preciso
consultar diretamente o Prowlarr, validar série, numeração, idioma, qualidade,
tamanho e motivos de rejeição antes de selecionar uma fonte. Não usar a busca
direta para ignorar rejeições silenciosamente. Informar ausência de fonte válida.

## Segunda etapa: tentativas automáticas

- Aproveitar a detecção do watcher existente, com um único responsável pela
  recuperação para evitar ações concorrentes sobre o mesmo torrent.
- Buscar substitutos apenas para episódios realmente sem fonte utilizável.
- Persistir tentativas e fontes que falharam, impedindo repetição da mesma
  distribuição e duplicação de buscas já em execução.
- Definir intervalo, recuo após erros e quantidade máxima de tentativas antes
  de ativar o modo automático. Estes valores ainda não foram escolhidos.
- Tratar falha de indexador, erro de API e falta de fonte como situações diferentes.
- Preservar dados e motivos de falha. Limpar registros antigos somente após
  confirmar a substituição, sem apagar arquivos automaticamente.
- Manter a triagem obrigatória. Não liberar arquivos reprovados ou com análise
  incompleta por meio de um botão de repetição; erros temporários podem ser repetidos.

## Implantação e validação futuras

Preparar a implementação no repositório e validar com respostas simuladas e
arquivos sintéticos, sem baixar mídia de terceiros apenas para testar. Cobrir
reinício da VM, APIs indisponíveis, arquivos completos aguardando triagem,
pacotes com vários episódios, numeração de anime, fontes repetidas e falhas de
importação/coleta. Confirmar que as ações manuais não criam downloads duplicados.

Preferir um painel local restrito ao próprio computador, sem ampliar acesso
à LAN/internet. A arquitetura de execução e eventuais unidades de serviço
serão definidas na implementação; mudanças externas seguem `AGENTS.md` e
`REPRODUZIR.md`. Não acrescentar Nginx, monitoramento de espaço ou backups.

Cleanuparr foi considerado como alternativa pronta para recuperação de torrents,
mas não cobre por si só os estados da triagem e coleta personalizados deste lab.
A direção acordada foi ampliar o mecanismo existente e integrar os estados.

## Referências

- [Sonarr: Wanted / Missing](https://wiki.servarr.com/sonarr/wanted)
- [Sonarr: como encontra episódios](https://wiki.servarr.com/sonarr/faq)
- [Cleanuparr: buscas de substituição](https://cleanuparr.github.io/docs/configuration/seeker/)
