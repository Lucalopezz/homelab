# Painel e recuperação de episódios faltantes

## Acesso futuro pelo PC na rede local

O usuário pretende acessar este notebook pelo PC do apartamento, via SSH e
pelas interfaces do laboratório. Nesta etapa, os acessos continuam restritos
ao próprio Fedora; não foi alterado firewall nem aberta porta para a LAN.
Antes de implementar, identificar os endereços e serviços necessários,
definir autenticação e regras restritas ao PC/rede local, e conferir como
proteger o painel atualmente ligado somente em `127.0.0.1`. Evitar publicar
serviços diretamente na internet e preservar o isolamento da VM. Preparar e
validar as alterações antes de aplicá-las.

## Atualização de 03/11/2026

Foi preparado `media-stack/recover-missing.py`, executado pelo timer da VM
`media-recovery.timer`. Ele reconcilia episódios monitorados usando primeiro
cópias aprovadas; só solicita buscas para faltas sem fonte identificada, com
bloqueio conservador diante de nomes ou pacotes ambíguos. O estado das rodadas
e das tentativas fica em `/var/lib/media-recovery`. A rotina não altera o
limite de downloads e não contorna o Sonarr, os filtros ou a triagem.

O processo é limitado a séries monitoradas e não garante encontrar fontes,
resolver qualquer numeração ambígua ou confirmar a presença no Jellyfin. O
painel existente ainda precisa apresentar os comandos, seus resultados e as
ações manuais descritas abaixo. A associação automática não substitui essa
etapa nem a revisão de arquivos não reconhecidos.

## Decisão de 02/11/2026

Na decisão original, o usuário preferiu esperar os downloads em andamento
antes de implementar esta melhoria. A atualização acima registra o que já foi
instalado; os itens ainda descritos como futuros continuam pendentes.

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

### Recuperação de publicação: incidente de 02/11/2026

O diagnóstico encontrou 14 episódios de Bleach (S17E27–E40) bloqueados porque
o registro do pacote virou `revisao` com o motivo "Já existe uma cópia aprovada
com esse identificador", apesar de existir `TRIAGEM.json` na cópia aprovada.
Family Guy S24E13 e Clone Wars S02E12 tinham cópias menores e antigas na
biblioteca, com originais aprovados completos. Clone Wars S02E18 foi retido
durante uma alteração do arquivo e saiu da lista na execução seguinte.

A rotina administrativa `media-stack/recover-publication.py` foi criada para
esse tipo de recuperação. Sem `--apply` apresenta o plano; com `--apply`:

- Para o conflito específico de pasta já aprovada, verifica a propriedade e
  as permissões do manifesto, o identificador e os SHA256 de todos os arquivos
  antes de recuperar o registro. A recuperação não se aplica a detecção de
  malware ou a outros motivos de revisão. O exportador continua conferindo
  separadamente os arquivos organizados contra os hashes aprovados.
- Para uma cópia incompleta selecionada com `--repair-path`, exige um original
  aprovado correspondente, um destino menor e sem alteração recente. Copia
  para um temporário, confere SHA256, sincroniza e troca o destino atomicamente.
  Uma mudança no destino durante a operação cancela a substituição.
- Preserva a cópia parcial em `biblioteca/.recuperacao`, fora da coleta, sem
  apagá-la automaticamente. Esses arquivos continuam ocupando espaço até uma
  eventual limpeza explicitamente autorizada.

A rotina usa trava por torrent; não agenda buscas, não baixa novamente e não
foi adicionada aos timers. Antes do uso administrativo, conferir também que
não há importações do organizador em execução sobre os destinos escolhidos.
O arquivo pode ser executado dentro da VM por stdin, evitando instalação de
outro serviço. Os testes sintéticos estão em `media-stack/test_recover_publication.py`.

No futuro painel, acrescentar **Recuperar aprovação existente** e
**Refazer cópia aprovada**, com motivo e resultado visíveis. A evolução
automática deve ainda:

1. Separar falha de download, falha de importação e retenção de publicação;
   tentar reparar cópias existentes antes de procurar outra distribuição.
2. Tornar a triagem idempotente depois de uma interrupção entre a publicação
   da pasta aprovada e o registro no SQLite. Uma pasta existente deve ser
   conferida e reconciliada, sem descartar o registro anterior por conflito.
3. Substituir a exclusão antecipada do registro feita por `--retry` por uma
   recuperação sob trava, preservando a evidência anterior e o histórico.
4. Tratar mudanças durante cópia/importação como espera temporária; conferir
   conclusão do comando, estabilidade e integridade antes de publicar.
5. Detectar cópias parciais antigas sem depender apenas do estado "aprovado"
   ou "importado" e recuperar somente a partir de bytes aprovados verificáveis.
   Antes de automatizar a substituição, confirmar a origem pelo identificador
   do download, histórico de importação e episódio/arquivo do organizador.
   Tamanho menor ou nome parecido, isoladamente, não provam uma cópia interrompida;
   uma versão transcodificada ou uma alteração intencional deve ir para revisão.
6. Manter tentativas e checkpoints persistentes, evitando repetir conferências
   de um pacote inteiro após cada interrupção. Só ativar ações automáticas
   depois de validar concorrência, interrupções e os controles do organizador.

### Faltantes sem download e falha de entrega do indexador

Também foram identificados seis episódios solicitados de Family Guy sem torrent,
sem registro de triagem e sem evento de download: S22E03/E07/E09 e S24E05/E08/E09.
As temporadas 21 e 23 estavam completas; o pedido do Seerr cobre 21–24.
Uma nova busca encontrou fontes para S22E03, mas a entrega falhou em um endereço
intermediário do Knaben com HTTP 501. O Sonarr passou a omitir temporariamente
esse indexador após as falhas; o rótulo "API Grab Limit reached" no log do Sonarr
não provou uma quota configurada: os limites locais de consulta/download estavam
vazios e o erro original no Prowlarr era o HTTP 501.

A opção suportada `torrentBaseSettings.preferMagnetUrl` foi habilitada apenas
no Knaben; os testes de conexão do Prowlarr e do Sonarr passaram. O modelo de
instalação passou a usar a mesma preferência. Não foram removidos limites de
provedor nem alterados os filtros de seleção para corrigir esse transporte.

O futuro script precisa comparar o pedido com os arquivos e a fila completa,
mesmo quando não há um torrent marcado com erro. Também deve distinguir:

- Nenhum resultado de busca.
- Resultados rejeitados pelo perfil (exibir o motivo, sem ignorá-lo).
- Fonte válida encontrada, mas entrega ao cliente falhou.
- Indexador temporariamente indisponível, com nova tentativa após o recuo.
- Torrent aceito pelo cliente, mas ainda aguardando metadados ou peers.

Registrar o comando da busca e conferir os torrents aceitos ao final. A mensagem
final de uma busca com vários episódios pode refletir só o último episódio;
não usar "0 reports downloaded" isoladamente como total de toda a operação.

### Critérios gerais

Em 02/11/2026, a fonte avulsa de Clone Wars S05E11 ficou sem metadados e foi
retida pelo watcher. A alternativa encontrada foi um pacote de temporada,
selecionando somente o E11. A triagem foi ajustada para ignorar mídia com
prioridade de arquivo zero, preservando as barreiras de caminho, tipos
perigosos, análise e conclusão dos arquivos selecionados. A alteração foi
validada com testes sintéticos e instalada sem interromper a triagem em curso;
novas execuções carregam o código atualizado. O futuro painel deve distinguir
seleção de arquivos de prioridade da fila e conferir a lista selecionada antes
de iniciar um pacote, sem deixar downloads de episódios duplicados habilitados.

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
