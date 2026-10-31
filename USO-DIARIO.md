# Uso diário do laboratório

## Ao ligar o notebook

No terminal do Fedora:

```bash
cd /mnt/dados/lab
sudo bash scripts/start-lab.sh
```

O comando confere o HD e o firewall, inicia a VM existente, mantém o Jellyfin
em execução e ativa a coleta automática. Pode ser usado novamente se a VM já
estiver ligada: ele não recria discos nem reinicia os torrents.

No HD, o boot da VM e das aplicações pode levar alguns minutos. Na partida
fria, a cópia de mídia aguarda o Seerr responder para não disputar o disco com
a inicialização. Se a interface ainda não abrir, aguarde; não repita instaladores.

## Escolher e acompanhar

| O que fazer | Onde |
| --- | --- |
| Procurar e solicitar filmes, séries e temporadas | [Seerr](http://192.168.250.10:5055) |
| Acompanhar downloads e tags da triagem | [qBittorrent](http://192.168.250.10:8080) |
| Assistir em **Lab - Filmes** ou **Lab - Séries** | [Jellyfin](http://127.0.0.1:8096) |
| Investigar séries/importações | [Sonarr](http://192.168.250.10:8989) |
| Investigar filmes/importações | [Radarr](http://192.168.250.10:7878) |

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

## Se algo não aparecer

- `100%` no qBittorrent significa download terminado; análise, importação e
  cópia para o Jellyfin ainda podem estar em andamento.
- A tag `triagem-aprovada` indica que uma cópia foi liberada. O contador de
  pendentes da sincronização diminui conforme os lotes chegam ao HD.
- `triagem-revisao`, `triagem-reprovado` ou `triagem-pendente` exigem conferir o
  motivo. Arquivos individuais acima de **2047 MiB** e distribuições compactadas
  não são liberados automaticamente por esta política.
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

O volume de downloads tem **400 GiB**, compartilhados entre originais, cópias
aprovadas e biblioteca organizada. A cópia do Jellyfin ocupa espaço adicional
no HD em `lab/jellyfin/biblioteca`; não é um link para os arquivos brutos.

Jellyfin recebe a biblioteca somente para leitura. Isso e o antivírus reduzem
riscos, mas não garantem proteção absoluta contra vulnerabilidades ao processar
mídia. Os detalhes, a atualização e a reprodução da configuração estão em
[JELLYFIN.md](JELLYFIN.md).
