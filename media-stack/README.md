# Busca e download de mídia dentro da VM

Implementado em 31/10/2026. Os cinco serviços estão ativos na VM e o Seerr já
tem conexão com Sonarr, Radarr e o Jellyfin existente. O login inicial foi
concluído pelo usuário; atualizar a página do Seerr para entrar no catálogo.
Os registros de validação ficam em `../state/`.

## Fluxo de uso

1. Abrir o Seerr em <http://192.168.250.10:5055>.
2. Procurar o título e solicitar somente as temporadas ou os episódios desejados.
3. Sonarr (séries/animes) ou Radarr (filmes) usa os indexadores do Prowlarr e envia
   o download ao qBittorrent. O perfil procura 1080p WEB/Blu-ray e admite 720p
   como alternativa; remux e outras resoluções ficam fora desse perfil.
4. Depois de concluir, a triagem verifica os arquivos, consulta o ClamAV e valida
   que o conteúdo de vídeo pode ser reconhecido. Uma cópia examinada é liberada
   para coleta e só então é enviada para importação no organizador.
5. O Fedora coleta automaticamente a biblioteca examinada e publica no Jellyfin,
   em **Lab - Filmes** e **Lab - Séries**. Não é preciso mover os arquivos.

O passo a passo ao ligar/desligar o notebook está em [USO-DIARIO.md](../USO-DIARIO.md).

Os indexadores Nyaa.si e Knaben foram testados e sincronizados com os dois
organizadores. AnimeTosho ficou de fora porque seu feed não resolveu por DNS
durante a configuração. A disponibilidade de cada título e a qualidade das
distribuições dependem das fontes; o perfil filtra os resultados encontrados.

No Knaben, a opção avançada **Prefer Magnet URL** fica habilitada. Em 02/11/2026,
links intermediários `knaben.org/live/dl/…` responderam HTTP 501 e impediram
o Sonarr de enviar distribuições encontradas para download. Preferir o magnet
usa o identificador oferecido pelo próprio indexador e evita esse intermediário.
Não altera os filtros de qualidade, idioma, episódio ou a triagem.

O Bazarr recebe as bibliotecas dos organizadores para procurar legendas, com
perfil pt-BR e inglês adicional obrigatório quando o áudio é inglês. Uma legenda
pt-BR não encerra a busca de inglês. Os provedores sem conta configurados
não garantem que exista legenda para todo título. Provedores que exigem conta
precisam de credenciais próprias cadastradas posteriormente pelo usuário.

### Recuperação de episódios monitorados

O serviço `media-recovery.timer` executa a reconciliação em intervalos de uma
hora. Quando um episódio monitorado e já lançado não tem arquivo no Sonarr,
ele procura primeiro uma cópia aprovada, exige identificação compatível entre
o nome da distribuição e a análise do Sonarr, e solicita importação por cópia.
Ele aguarda buscas ou importações já em andamento e não usa mídia não aprovada.

Se não houver cópia ou torrent correspondente, pode solicitar busca ao Sonarr,
que mantém seus filtros e indexadores configurados. Pacotes ou nomes que não
possam ser identificados bloqueiam a busca automática quando houver dúvida,
evitando duplicações. Há no máximo duas buscas ou quatro importações por rodada,
até três tentativas por episódio, com intervalo de 24 horas entre tentativas.
Isso não altera o limite de downloads simultâneos do qBittorrent.

O resultado da última rodada fica em `/var/lib/media-recovery/status.json` e
as tentativas em `/var/lib/media-recovery/attempts.json` dentro da VM. Uma
solicitação aceita pelo Sonarr não comprova que o download, importação ou
publicação foi concluído. O processo não cobre filmes nem substitui a revisão
manual de associações ambíguas ou fontes rejeitadas.

## Endereços

| Serviço | Endereço no Fedora |
| --- | --- |
| Painel de status local | <http://127.0.0.1:8765> |
| Jellyfin | <http://127.0.0.1:8096> |
| Seerr, catálogo e pedidos | <http://192.168.250.10:5055> |
| Sonarr, séries e animes | <http://192.168.250.10:8989> |
| Radarr, filmes | <http://192.168.250.10:7878> |
| Prowlarr, fontes de busca | <http://192.168.250.10:9696> |
| Bazarr, legendas | <http://192.168.250.10:6767> |
| qBittorrent, fila e estado da triagem | <http://192.168.250.10:8080> |

Esses endereços são acessíveis neste Fedora. O painel é iniciado com
`sudo bash scripts/start-lab.sh` ou, separadamente e sem sudo, com
`python3 scripts/start-status-panel.py`; não foi aberto para a rede local.

O Seerr autentica com o Jellyfin existente, já cadastrado em `192.168.250.1`,
porta `8096`, sem HTTPS. Usar o login do Jellyfin diretamente no Seerr.

Os organizadores e o Bazarr usam o usuário `lab`; consultar a senha sem publicar
as chaves de API:

```bash
python3 -c 'import json; print(json.load(open("/mnt/dados/lab/secrets/media-stack.json"))["password"])'
```

O qBittorrent mantém `admin` e a senha anterior em
`/mnt/dados/lab/secrets/qbittorrent-password`.

## Separação dos arquivos

Todos os caminhos abaixo são **dentro da VM**, em discos virtuais do HD:

| Caminho | Uso |
| --- | --- |
| `/opt/media-stack` | Compose, configurações persistentes e imagens fixadas por digest no `.env` |
| `/srv/downloads/incompletos` | Arquivos ainda baixando |
| `/srv/downloads/recebidos` | Originais terminados, ainda não aprovados |
| `/srv/downloads/aprovados/.em-analise` | Cópias privadas durante a análise |
| `/srv/downloads/aprovados/series`, `filmes`, `manuais` | Cópias aprovadas para coleta |
| `/srv/downloads/aprovados/STATUS/triagem.json` | Resultado e motivo de cada decisão |
| `/srv/downloads/biblioteca` | Organização e legendas dentro da VM, origem da coleta automática para o Jellyfin |

Os organizadores não recebem montagem de `recebidos`. A pasta `aprovados` é
montada somente para leitura nos organizadores. A importação automática comum
do cliente foi desativada; a triagem chama o comando de importação depois da
aprovação. O Seerr e o Prowlarr não recebem montagem das pastas de mídia.

Os downloads originais são mantidos para permitir seeding. A cópia aprovada e a
importação podem consumir espaço adicional no disco virtual. Não foi criado
monitoramento de espaço, remoção automática de mídia ou sistema de backup.

## Verificação antecipada de tamanho

O timer `media-download-watch.timer` também examina os nomes e tamanhos dos
arquivos selecionados em downloads de séries ainda em andamento. Vídeos de
2 GiB ou mais ficam registrados para consulta no painel local. Extras grandes
em pastas claramente identificadas como `Extras` ou `Featurettes` são retirados
da seleção somente se existir outro vídeo selecionado. Arquivos já baixados
não são apagados automaticamente.

Para um episódio grande identificado sem ambiguidade pelo Sonarr, a rotina
procura uma alternativa individual aprovada pelo perfil, abaixo de 2 GiB e com
fonte disponível. Se o Sonarr aceitar o envio, o arquivo grande é retirado da
seleção quando o pacote contém outro vídeo; um arquivo único é mantido. A
busca não garante download, aprovação nem publicação, e aguarda 24 horas para
repetir quando não encontra fonte. Casos ambíguos ficam para revisão. O painel
exibe o último registro em **Arquivos grandes detectados**. O acompanhamento
não altera torrents concluídos e não substitui a triagem ClamAV.

## Triagem e limites

Pacotes podem ter somente alguns episódios selecionados no qBittorrent. A
triagem examina e publica apenas os arquivos de mídia com prioridade de arquivo
maior que zero, exigindo que estejam completos. Arquivos não selecionados não
entram na cópia aprovada. Caminhos inválidos e tipos perigosos continuam
recusando a distribuição, mesmo quando não selecionados. Isso permite buscar
um episódio em outro pacote sem baixar novamente toda a temporada.

O exame roda como usuário `triagem`, sem sudo, com rede limitada às APIs da
própria VM. O ClamAV usa socket Unix, sem porta TCP exposta. A aprovação exige:

- Arquivos completos e regulares; links simbólicos e caminhos que saem da pasta
  de recebidos são recusados.
- Ausência dos tipos bloqueados na distribuição, como executáveis, scripts,
  imagens de disco e arquivos compactados.
- Cópia independente, sem hardlink para a origem. Mudanças durante a cópia
  impedem a aprovação.
- Assinaturas recentes e resposta limpa do ClamAV; falha do scanner não aprova.
- Vídeo reconhecido pelo ffprobe ou legenda UTF-8 admitida pela política.

O orçamento agregado `MaxScanSize` é **5120 MiB**, separado do limite de
arquivo. Ele inclui o original e os dados internos analisados; usar o mesmo
valor nos dois limites retinha MP4 grandes mesmo abaixo do teto por arquivo.

O teto configurado por arquivo é **2560 MiB**, mas **não supera o limite
interno de aproximadamente 2 GiB do ClamAV 1.4.6**. Portanto, vídeos entre
2 e 2,5 GiB também podem ser retidos com `Heuristics.Limits.Exceeded.MaxFileSize`.
Esse alerta indica análise incompleta, não detecção de malware. Aumentar
`MaxFileSize` novamente não resolve esse limite do motor. Arquivos maiores e análises que atingem limites ficam para
revisão, sem serem expostos pela coleta. Os pacotes compactados não são
extraídos automaticamente. As legendas obtidas depois pelo Bazarr ficam na
biblioteca da VM e passam pela validação do exportador antes da coleta para
o Jellyfin. A conta SFTP manual continua mostrando a cópia aprovada original.

O scanner usa o ClamAV LTS 1.4.6 oficial, instalado isoladamente em
`/opt/clamav-release` dentro da VM, com checksum e assinatura GPG verificados.
O FreshClam está habilitado para atualizar as assinaturas. A atualização do
motor exige uma manutenção explícita; as imagens dos serviços também estão
fixadas por digest. Não atualizar rodando novamente os scripts de instalação
sem revisar o estado e a versão pretendida.

Triagem e exportação compartilham a trava de leitura
`/var/lib/media-triage/clamav-scan.lock`: só um cliente por vez solicita análise.
O tempo esperando essa trava não consome o prazo de **1260 segundos** do
cliente, que cobre os **1200 segundos** permitidos no motor. Timeout continua
impedindo a aprovação. O limite antigo de 660 segundos podia abandonar uma
solicitação enquanto o motor ainda trabalhava nela, atrasando as seguintes.
O prazo do `ffprobe` é de 180 segundos: o limite anterior de 45 segundos
expirava em arquivos válidos quando o HD estava ocupado. Falha ou timeout
continuam impedindo a aprovação; o serviço tenta novamente erros temporários.
O bootstrap cria a trava, modo 440, com dono `triagem:triagem`. Ao atualizar
uma instalação existente, preparar esse arquivo antes de ativar o código;
não substituir uma trava em uso. `triage.py --only HASH` prioriza um único
torrent concluído sem ignorar nenhuma validação.

Uma falha ao atualizar a etiqueta no qBittorrent não desfaz uma aprovação
nem apaga o destino ou o comando de importação já registrado. A etiqueta é
tentada novamente; se existir um destino sem estado de aprovação confiável,
a triagem o deixa para revisão antes de copiar ou analisar outra vez.

No qBittorrent:

| Tag | Significado |
| --- | --- |
| `triagem-aprovada` | Cópia examinada e liberada; nenhuma ameaça detectada |
| `triagem-reprovado` | Conteúdo detectado ou distribuição recusada pela política; torrent pausado |
| `triagem-revisao` | Limite de análise/formato exige revisão manual; torrent pausado |
| `triagem-pendente` | Erro ou indisponibilidade temporária; cópia não liberada |
| `erro-sem-progresso` | Download sem progresso por 15 minutos; pausado para liberar a fila, dados preservados |

O timer `media-download-watch.timer` confere a fila a cada minuto dentro da
VM. Conta apenas tempo observado em download ativo, incluindo espera de
metadados; tempo na fila, pausado ou com a VM desligada não conta. Não altera
o limite de quatro downloads simultâneos. A pré-verificação de arquivos
grandes pode solicitar alternativas conforme descrito acima.
Para revisar, filtre a etiqueta `erro-sem-progresso` no qBittorrent. Depois de
resolver a fonte, remova a etiqueta e retome o torrent manualmente. A etiqueta
é um aviso administrativo; não simula um erro de disco no cliente.

Após instalar as unidades na VM, habilitar com
`sudo systemctl enable --now media-download-watch.timer`. Consultar
`journalctl -u media-download-watch.service` para ver as retenções. O estado
privado fica em `/var/lib/media-download-watch/observations.json`.

Uma aprovação reduz riscos e não garante ausência de malware. Não executar
arquivos coletados automaticamente. O resultado registra SHA256 dos arquivos
liberados em `TRIAGEM.json` junto da cópia.

Sonarr e Radarr exibem o aviso **Enable Completed Download Handling**. Essa
opção fica desativada de propósito: habilitá-la permitiria tentar importar os
originais antes da triagem. A importação é solicitada pela triagem somente
depois de liberar a cópia examinada.

## Filmes longos e versões menores

O perfil opcional **Lab - filmes compactos (720p ou SD)** aceita WEB/Bluray
720p, WEB/Bluray SD e DVD, sem capturas de cinema ou upgrades automáticos.
Um formato de tamanho obrigatório limita o total da distribuição a **1.8 na
unidade GB do Radarr**, abaixo de 2 GiB; a triagem ainda precisa aprovar cada
arquivo. A restrição vale apenas nesse perfil. As definições globais de
tamanho e o perfil padrão não são alterados.

Para escolher, abra o filme no Radarr, clique em **Editar**, selecione esse
**Perfil de qualidade** e salve. No Seerr, o perfil também aparece nas opções
avançadas de solicitação, quando a conta tem permissão para alterá-lo.
Essa escolha não converte nem apaga automaticamente uma versão já baixada.

Em uma instalação que ainda não tem esse perfil, o script
`python3 scripts/configure-compact-movies.py` mostra a proposta;
`python3 scripts/configure-compact-movies.py --apply` cria o perfil via API.
Ele recusa substituir recursos com o mesmo nome.

## Coleta e Jellyfin

A conta `coleta` usa chroot em `/srv/downloads/aprovados` e SFTP somente para
leitura. Ela não consegue consultar os originais de `recebidos`.

```bash
cd /mnt/dados/lab/coleta
sftp -F /mnt/dados/lab/config/ssh_config lab-downloads-coleta
# ls
# cd series
# get -r "nome-da-pasta-aprovada"
# bye
```

A integração automática com o servidor do Fedora está em [JELLYFIN.md](../JELLYFIN.md).
O host inicia uma coleta SFTP separada e monta a biblioteca recebida somente
para leitura no Jellyfin. A exceção de API continua restrita a
`192.168.250.1:8096`; nenhuma pasta do Fedora é compartilhada com a VM.

## Operação

As aplicações e a triagem iniciam dentro da VM quando o volume está disponível.
A VM continua com partida explícita pelo Fedora. Para consultar o resultado:

```bash
cd /mnt/dados/lab
ssh -F config/ssh_config lab-downloads-admin \
  'sudo docker compose -f /opt/media-stack/compose.yaml --project-directory /opt/media-stack ps'
ssh -F config/ssh_config lab-downloads-admin \
  'sudo journalctl -u media-triage.service -n 50 --no-pager'
```

Um hash recusado só deve ser reexaminado após entender o motivo. Se o motivo
for "Já existe uma cópia aprovada com esse identificador", usar a recuperação
abaixo antes de `--retry`: apagar o registro e tentar copiar tudo novamente
reproduz o conflito. Para outros casos elegíveis, o administrador pode executar
dentro da VM:

```bash
sudo -u triagem python3 /opt/media-stack/triage/triage.py --retry HASH_DO_TORRENT
```

### Recuperação administrativa de publicação

`recover-publication.py` recupera o registro de uma pasta já examinada após
conferir seu manifesto e SHA256. Também pode substituir uma cópia incompleta
na biblioteca a partir da cópia aprovada, com temporário e troca atômica.
Não se aplica a reprovações por malware nem a outros motivos de revisão.

No Fedora, apresentar o plano sem alterar a mídia:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -F config/ssh_config lab-downloads-admin \
  'sudo -n python3 - --hash HASH_DO_TORRENT' < media-stack/recover-publication.py
```

Após revisar o motivo, acrescentar `--apply` ao comando remoto para conferir
os arquivos e aplicar a recuperação. Para uma cópia incompleta específica,
acrescentar também `--repair-path "series/Série/Season 1/episódio.mkv"`, com
o caminho exato relativo à biblioteca. Conferir antes que não há importação
ativa sobre esse destino. A rotina se recusa a substituir cópias recentes,
arquivos que mudem durante a operação ou destinos que não sejam menores que
o original aprovado. Os parciais são preservados em `biblioteca/.recuperacao`,
fora da publicação; não são apagados automaticamente.

Não há timer dessa recuperação. A integração ao painel e as condições para
ações automáticas estão em [PROXIMOS-PASSOS.md](../PROXIMOS-PASSOS.md).

## Validação concluída

- Seerr inicializado, busca de catálogo respondendo e testes de conexão com
  Sonarr/Radarr concluídos; ambos usam o perfil e as pastas definidos acima.
- Nyaa.si e Knaben testados no Prowlarr e presentes nos dois organizadores.
- Vídeo sintético aprovado; EICAR e executável disfarçado de MP4 recusados.
- Importação no Radarr confirmada com outro vídeo sintético, com áudio e dez
  minutos de duração. Nenhum vídeo externo foi baixado nesse teste. A entrada,
  o torrent e os arquivos artificiais foram removidos após a conferência.
- Coleta SFTP: conteúdo e SHA256 conferidos; envio, remoção, acesso a originais
  e acesso à área privada de análise negados.
- VM acessando internet e a API autorizada do Jellyfin; SSH do Fedora, roteador
  e Jellyfin pelos IPs físicos do host continuam bloqueados. Os mesmos destinos
  responderam ao Fedora para comparação.
- Serviços e timer habilitados dentro da VM, com 6 GiB de RAM em uso.

A etapa inicial não incluía reprodução. A integração e seus testes posteriores
estão em [JELLYFIN.md](../JELLYFIN.md) e nos relatórios privados de `state/`.

## Referências

- [Seerr](https://docs.seerr.dev/)
- [Sonarr API](https://sonarr.tv/docs/api/)
- [Radarr API](https://radarr.video/docs/api/)
- [Prowlarr API](https://prowlarr.com/docs/api/)
- [ClamAV: limites e configuração](https://manpages.debian.org/trixie/clamav-daemon/clamd.conf.5.en.html)
- [Arquivo de teste EICAR](https://www.eicar.org/download-anti-malware-testfile/)


Legendas anexas em CP1252/Latin-1 ou UTF-16 com BOM podem ser convertidas para
UTF-8 **na cópia privada de análise**, quando a estrutura SRT/ASS/VTT é
reconhecida e não há controles binários. A cópia convertida é examinada de novo
pelo ClamAV e recebe seu próprio SHA256. O original do torrent não é alterado;
formatos inválidos continuam retidos. Há trava por hash para impedir duas
triagens simultâneas do mesmo torrent.
