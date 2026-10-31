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

Os indexadores Nyaa.si e Knaben foram testados e sincronizados com os dois
organizadores. AnimeTosho ficou de fora porque seu feed não resolveu por DNS
durante a configuração. A disponibilidade de cada título e a qualidade das
distribuições dependem das fontes; o perfil filtra os resultados encontrados.

O Bazarr recebe as bibliotecas dos organizadores para procurar legendas, com
perfil pt-BR e inglês como alternativa. Os provedores sem conta configurados
não garantem que exista legenda para todo título. Provedores que exigem conta
precisam de credenciais próprias cadastradas posteriormente pelo usuário.

## Endereços

| Serviço | Endereço no Fedora |
| --- | --- |
| Seerr, catálogo e pedidos | <http://192.168.250.10:5055> |
| Sonarr, séries e animes | <http://192.168.250.10:8989> |
| Radarr, filmes | <http://192.168.250.10:7878> |
| Prowlarr, fontes de busca | <http://192.168.250.10:9696> |
| Bazarr, legendas | <http://192.168.250.10:6767> |
| qBittorrent, fila e estado da triagem | <http://192.168.250.10:8080> |

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
| `/srv/downloads/biblioteca` | Organização e legendas dentro da VM; ainda sem integração de arquivos com o Jellyfin |

Os organizadores não recebem montagem de `recebidos`. A pasta `aprovados` é
montada somente para leitura nos organizadores. A importação automática comum
do cliente foi desativada; a triagem chama o comando de importação depois da
aprovação. O Seerr e o Prowlarr não recebem montagem das pastas de mídia.

Os downloads originais são mantidos para permitir seeding. A cópia aprovada e a
importação podem consumir espaço adicional no disco virtual. Não foi criado
monitoramento de espaço, remoção automática de mídia ou sistema de backup.

## Triagem e limites

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

O limite automático por arquivo é **2047 MiB**: o ClamAV utilizado tem limite
técnico de 2 GB. Arquivos maiores e análises que atingem limites ficam para
revisão, sem serem expostos pela coleta. Os pacotes compactados não são
extraídos automaticamente. As legendas obtidas depois pelo Bazarr ficam na
biblioteca da VM; o fluxo de reprodução/coleta dessa biblioteca será tratado
na etapa do Jellyfin.

O scanner usa o ClamAV LTS 1.4.6 oficial, instalado isoladamente em
`/opt/clamav-release` dentro da VM, com checksum e assinatura GPG verificados.
O FreshClam está habilitado para atualizar as assinaturas. A atualização do
motor exige uma manutenção explícita; as imagens dos serviços também estão
fixadas por digest. Não atualizar rodando novamente os scripts de instalação
sem revisar o estado e a versão pretendida.

No qBittorrent:

| Tag | Significado |
| --- | --- |
| `triagem-aprovada` | Cópia examinada e liberada; nenhuma ameaça detectada |
| `triagem-reprovado` | Conteúdo detectado ou distribuição recusada pela política; torrent pausado |
| `triagem-revisao` | Limite de análise/formato exige revisão manual; torrent pausado |
| `triagem-pendente` | Erro ou indisponibilidade temporária; cópia não liberada |

Uma aprovação reduz riscos e não garante ausência de malware. Não executar
arquivos coletados automaticamente. O resultado registra SHA256 dos arquivos
liberados em `TRIAGEM.json` junto da cópia.

Sonarr e Radarr exibem o aviso **Enable Completed Download Handling**. Essa
opção fica desativada de propósito: habilitá-la permitiria tentar importar os
originais antes da triagem. A importação é solicitada pela triagem somente
depois de liberar a cópia examinada.

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

A conexão com Jellyfin é exclusiva para autenticação e catálogo. A única
exceção nova no firewall do Fedora permite a VM acessar
`192.168.250.1:8096`. Nenhuma biblioteca/pasta do Fedora foi compartilhada com
a VM e não foi configurado o fornecimento dos novos vídeos ao Jellyfin.

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

Um hash recusado só deve ser reexaminado após entender o motivo. O administrador
pode executar dentro da VM:

```bash
sudo -u triagem python3 /opt/media-stack/triage/triage.py --retry HASH_DO_TORRENT
```

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

O Fedora não foi reiniciado nesta etapa. Os resultados não incluem um teste de
reprodução pelo Jellyfin, que ainda não recebe esses arquivos.

## Referências

- [Seerr](https://docs.seerr.dev/)
- [Sonarr API](https://sonarr.tv/docs/api/)
- [Radarr API](https://radarr.video/docs/api/)
- [Prowlarr API](https://prowlarr.com/docs/api/)
- [ClamAV: limites e configuração](https://manpages.debian.org/trixie/clamav-daemon/clamd.conf.5.en.html)
- [Arquivo de teste EICAR](https://www.eicar.org/download-anti-malware-testfile/)
