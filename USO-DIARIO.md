# Uso diário do laboratório

## Ao ligar o notebook

No terminal do Fedora:

```bash
cd /mnt/dados/lab
sudo bash scripts/start-lab.sh
```

O comando confere o HD e o firewall, inicia a VM existente, mantém o Jellyfin
em execução, ativa a coleta automática e inicia o painel local com o usuário
que chamou o sudo. Pode ser usado novamente se a VM já
estiver ligada: ele não recria discos nem reinicia os torrents.

No HD, o boot da VM e das aplicações pode levar alguns minutos. Na partida
fria, a cópia de mídia aguarda o Seerr responder para não disputar o disco com
a inicialização. Se a interface ainda não abrir, aguarde; não repita instaladores.

## Escolher e acompanhar

| O que fazer | Onde |
| --- | --- |
| Acompanhar o andamento do laboratório | [Painel de status](http://127.0.0.1:8765) |
| Procurar e solicitar filmes, séries e temporadas | [Seerr](http://192.168.250.10:5055) |
| Acompanhar downloads e tags da triagem | [qBittorrent](http://192.168.250.10:8080) |
| Assistir em **Lab - Filmes** ou **Lab - Séries** | [Jellyfin](http://127.0.0.1:8096) |
| Investigar séries/importações | [Sonarr](http://192.168.250.10:8989) |
| Investigar filmes/importações | [Radarr](http://192.168.250.10:7878) |
| Investigar fontes de busca | [Prowlarr](http://192.168.250.10:9696) |
| Procurar e acompanhar legendas | [Bazarr](http://192.168.250.10:6767) |

Esses endereços são para abrir no navegador deste Fedora. O painel fica restrito
a `127.0.0.1`; as páginas da VM usam a rede privada já existente. Se for
preciso iniciar apenas o painel, sem sudo:

```bash
cd /mnt/dados/lab
python3 scripts/start-status-panel.py
```

O resumo consulta as séries e os filmes monitorados no Sonarr/Radarr a cada
atualização, incluindo novos pedidos, e compara os itens com a biblioteca do
laboratório no Jellyfin. Para séries, conta episódios monitorados já lançados;
o Sonarr pode mostrar outro total por incluir episódios futuros. Se um serviço
não responder, o painel informa que a consulta está indisponível. O estado da
limpeza pontual de 03/11 é histórico e não confirma que pedidos novos terminaram.

O painel continua aberto em segundo plano até o computador desligar ou o
processo ser encerrado; ele é iniciado novamente pelo comando de partida do
laboratório. Se a porta estiver ocupada, o script avisa e não encerra outro
programa. O registro fica em `state/painel-local.log`.

Seerr e Jellyfin usam seu login do Jellyfin, preservado na atualização. No
qBittorrent, o usuário é `admin`; a senha fica em `secrets/qbittorrent-password`.
Sonarr/Radarr/Prowlarr/Bazarr usam `lab`, com senha em `secrets/media-stack.json`.
Não envie esses arquivos ao GitHub ou pelo chat.

## Os arquivos precisam ser movidos?

**Não.** O caminho normal é automático:

1. Você pede pelo Seerr.
2. Sonarr/Radarr busca uma distribuição e envia ao qBittorrent.
3. Depois do download, a triagem examina e libera uma cópia.
4. O organizador importa essa cópia; o Bazarr pode acrescentar legendas.
5. O Fedora coleta os arquivos permitidos, confere SHA256 e publica na biblioteca.
6. O Jellyfin atualiza **Lab - Filmes** e **Lab - Séries**.

Os timers consultam a cada dois minutos. A transferência inicial de uma
biblioteca grande demora mais no HD; ela é feita em lotes, sem exigir que você
mova arquivos. Cópias concluídas têm checkpoint para evitar começar tudo de
novo após uma interrupção. Depois da primeira cópia, arquivos inalterados não
são baixados outra vez pelo sincronizador.

Adicionar um torrent diretamente ao qBittorrent **não cadastra automaticamente
um filme/série no organizador**. Para usar o fluxo completo, prefira solicitar
pelo Seerr. Downloads manuais aprovados ficam disponíveis para coleta SFTP;
se necessário, é preciso identificá-los e importá-los no Sonarr/Radarr usando
as cópias aprovadas, sem apontar para os originais brutos.

A fila permite **quatro downloads simultâneos**, até dois uploads e seis
torrents ativos no total. A velocidade de download não tem teto configurado.

O painel já mostra informações de acompanhamento; ações manuais mais completas
e melhorias na recuperação de faltantes continuam em [próximos passos](PROXIMOS-PASSOS.md).

## Se algo não aparecer

- `100%` no qBittorrent significa download terminado; análise, importação e
  cópia para o Jellyfin ainda podem estar em andamento.
- Para filme, o **Radarr** é a alternativa ao catálogo do Seerr: abrir
  <http://192.168.250.10:7878>, entrar com o usuário `lab`, selecionar **Movies
  → Add New Movie**, procurar o título e escolher **Add Movie**. O Radarr envia
  o download ao qBittorrent. Para série, o Sonarr fica em
  <http://192.168.250.10:8989>. Um container marcado `Up` ainda pode estar
  esperando o HD antes de aceitar conexões; conferir a página do serviço.
- A tag `triagem-aprovada` indica que uma cópia foi liberada. O contador de
  pendentes da sincronização diminui conforme os lotes chegam ao HD.
- `triagem-revisao`, `triagem-reprovado` ou `triagem-pendente` exigem conferir o
  motivo. Arquivos individuais acima de **2560 MiB** e distribuições compactadas
  não são liberados automaticamente por esta política.
- O painel mostra **Arquivos grandes detectados** quando a pré-verificação
  encontra mídia que pode ultrapassar o limite do ClamAV. Ela pode ignorar
  extras grandes e procurar episódios menores; veja o estado registrado, pois
  a busca não garante que haverá uma fonte disponível.
- Um aviso `Heuristics.Limits.Exceeded.MaxScanSize` significa limite de análise
  atingido, não uma confirmação de malware. O orçamento agregado foi ajustado
  para 5120 MiB, mantendo o teto individual de 2560 MiB.
- Após a atualização do Jellyfin para 12.4, use **Ctrl+Shift+R** para recarregar
  a interface. As bibliotecas novas têm o prefixo **Lab -**.

Para consultar sem alterar nada:

```bash
systemctl status lab-jellyfin-sync.timer --no-pager
cat /mnt/dados/lab/jellyfin/state/last-run.json
virsh --readonly -c qemu:///system list --all
```

`pending` é a quantidade aguardando os próximos lotes; `held` registra arquivos
que não puderam ser publicados. A VM desligada pode gerar erro de conexão no
sincronizador; ele retoma quando ela voltar. As cópias já recebidas continuam
no Jellyfin.

## Se o filme estiver sem legenda

No reprodutor do Jellyfin, abrir **Legendas / CC** e escolher a faixa desejada.
Nesta instalação, o idioma preferido do usuário é inglês e o modo de legenda
é **Sempre reproduzir**. Para os dois Star Wars, as legendas em inglês que
acompanharam os downloads foram recuperadas e publicadas junto dos vídeos.

Se não houver nenhuma faixa, ligar o laboratório e abrir **Bazarr → Movies**
(ou **Series**). Conferir o perfil de idioma e usar a busca do título. A busca
manual permite escolher uma legenda compatível com a versão do vídeo; o nome
da distribuição e a sincronização também importam.

Em **Settings → Providers**, cadastrar diretamente as credenciais de um
provedor que ofereça português, quando exigidas. Não enviar senha ou chave no
chat. O perfil busca pt-BR e exige também inglês quando o áudio é inglês;
uma legenda pt-BR não encerra essa busca. Isso não garante disponibilidade: se um provedor
estiver indisponível ou não encontrar resultados, a busca pode terminar sem
baixar legenda.

Sonarr/Radarr importam também arquivos `srt`, `ass` e `vtt` da cópia aprovada.
Legendas acrescentadas pelo Bazarr passam pela validação da publicação e pela
coleta para o Fedora. Depois da coleta, atualizar o filme no Jellyfin e reabrir
o reprodutor. As legendas já copiadas continuam disponíveis com a VM desligada.

## Limpeza após importação de 03/11/2026

O processo pontual `media-stack/clean-after-import.py` aguarda o comando de
importação 5238 terminar e confirma os episódios solicitados no Sonarr e no
catálogo do Jellyfin antes de iniciar `clean-published-copies.py`. Ele mantém
o estado em `state/cleanup-after-import-status.json` e os resultados em
`state/cleanup-after-import.log`; o painel local apresenta esse estado.

A limpeza confere as duas cópias, a aprovação e o catálogo antes de remover
vídeos recebidos individualmente. Não remove pacotes com vários vídeos, as
cópias aprovadas ou organizadas, e não é uma limpeza de todas as duplicações.
O torrent removido deixa de compartilhar. Um erro interrompe a limpeza para
revisão. A espera é um processo temporário: desligar o computador interrompe
o agendamento; ele não é iniciado automaticamente após o reinício.

## Encerrar

Para parar downloads/VM, mantendo o Jellyfin disponível para assistir ao que
já foi copiado:

```bash
cd /mnt/dados/lab
sudo bash scripts/stop-lab.sh
```

Para parar também o Jellyfin:

```bash
sudo bash scripts/stop-lab.sh --all
```

O desligamento é gracioso e não apaga os downloads. Confirme o estado `shut off`
com `virsh --readonly -c qemu:///system list --all` antes de desligar o notebook.
Não use `virsh destroy` nem remova arquivos qcow2 para resolver uma espera.

## Armazenamento e isolamento

Nesta instalação, o volume de downloads tem **500 GiB**, compartilhados entre originais, cópias
aprovadas e biblioteca organizada. A cópia do Jellyfin ocupa espaço adicional
no HD em `lab/jellyfin/biblioteca`; não é um link para os arquivos brutos.

Jellyfin recebe a biblioteca somente para leitura. Isso e o antivírus reduzem
riscos, mas não garantem proteção absoluta contra vulnerabilidades ao processar
mídia. Os detalhes, a atualização e a reprodução da configuração estão em
[JELLYFIN.md](JELLYFIN.md).
