# Scripts de uso diário

Os comandos abaixo são executados no Fedora, na raiz do repositório. Eles usam a
instalação do laboratório descrita em [REPRODUZIR.md](REPRODUZIR.md): a VM
`lab-downloads`, a rede privada `192.168.250.0/24`, o Jellyfin existente e as
credenciais geradas em `secrets/`. Eles não instalam nem recriam o laboratório.
Em outra topologia, adapte e valide os endereços e caminhos antes de usá-los.
Não envie credenciais, estados ou arquivos de mídia para o repositório.

## Partida e painel

```bash
cd /mnt/dados/lab
sudo bash scripts/start-lab.sh
```

O comando imprime os endereços, inicia a VM existente e abre o painel local em
<http://127.0.0.1:8765>. Para iniciar somente o painel, sem sudo:

```bash
python3 scripts/start-status-panel.py
```

O painel e as páginas da VM são destinados ao navegador deste Fedora. Ele
consulta os títulos monitorados atuais e indica falhas das fontes consultadas.

## Consultar uma série

```bash
python3 media-stack/series-status.py --list
python3 media-stack/series-status.py --title "Nome exato no Sonarr"
python3 media-stack/series-status.py --id 1 --seasons 1,2
```

Os exemplos de IDs e títulos precisam ser substituídos pelos da instalação.
A consulta é somente leitura. Os totais compreendem episódios monitorados e
já lançados; não incluem temporadas especiais ou episódios futuros. Se o
catálogo estiver incompleto ou não for possível associar a série com segurança,
o comando informa erro em vez de afirmar que está completa.

Para solicitar uma releitura da biblioteca e esperar o término:

```bash
python3 media-stack/series-status.py --id 1 --rescan --wait
```

Esse comando espera importações e releituras em execução antes de enviar outra
releitura; o prazo padrão é de seis horas, ajustável com `--timeout SEGUNDOS`.
Sem `--wait`, ele informa que há trabalho em andamento e não inicia uma
releitura concorrente. A releitura não baixa episódios. Após terminar, o
relatório mostra o estado no Sonarr e no Jellyfin naquele momento; a cópia para
o Jellyfin pode continuar depois. A recuperação automática de faltantes e suas
limitações estão em [media-stack/README.md](media-stack/README.md).

## Limpar originais já publicados

Comece sempre pela consulta, que não altera torrents nem arquivos:

```bash
python3 media-stack/clean-published-packages.py --list
python3 media-stack/clean-published-packages.py --category sonarr --title "Parte do nome do torrent" --list
python3 media-stack/clean-published-packages.py --category radarr --max-torrents 2 --list
```

`--category sonarr` limita a séries; `radarr`, a filmes. O filtro `--title`
procura no nome do torrent, ignorando maiúsculas. `--max-torrents` limita a
quantidade de torrents, mantendo juntos todos os candidatos do mesmo pacote.
Sem filtros, a consulta abrange todos os candidatos elegíveis.

Depois de revisar, acrescente `--apply` aos mesmos filtros para executar:

```bash
ionice -c 3 python3 -u media-stack/clean-published-packages.py --category sonarr --title "Parte do nome do torrent" --apply
```

Cada arquivo precisa estar aprovado, corresponder a uma cópia no catálogo do
Jellyfin e passar por conferências de conteúdo e estabilidade antes de ser
removido da pasta de recebidos da VM. Arquivos sem correspondência segura não
são removidos. As cópias aprovadas e publicadas são preservadas. O torrent
que contém um original removido é retirado do qBittorrent e deixa de
compartilhar; arquivos sem correspondência desse pacote permanecem na VM.

O progresso da execução fica em `state/cleanup-packages-status.json` e no
painel. Se houver um plano interrompido, execute `--apply` **sem filtros** para
tentar retomá-lo; o script não o substitui silenciosamente por um novo plano.
A limpeza é interrompida ao desligar o computador e não reinicia sozinha.
Quando houver divergência, ela para para revisão. O espaço liberado dentro da
VM não necessariamente reduz o arquivo de disco virtual no Fedora.

## Desligar a VM após a limpeza

Para consultar o agendamento atual, sem desligar:

```bash
python3 media-stack/shutdown-after-cleanup.py
```

Para agendar o desligamento gracioso depois da limpeza em andamento:

```bash
python3 -u media-stack/shutdown-after-cleanup.py --apply
```

**Com `--apply`, se a limpeza já estiver concluída e os serviços estiverem
ociosos, a VM pode desligar em seguida.** O comando aguarda downloads,
triagem, importações e sincronização pendentes; se a limpeza parar ou falhar,
a VM fica ligada para revisão. O Jellyfin do Fedora permanece ligado. O
agendamento é um processo temporário e não retorna sozinho após um reinício.

Por padrão, ele acompanha `state/cleanup-packages-status.json` e o processo
`clean-published-packages.py`. Para outra rotina compatível, informe um estado
em `state/` com `--cleanup-status state/arquivo.json` e o nome do processo com
`--cleanup-process nome.py`. O arquivo deve registrar `state` (`limpando`,
`concluido` ou `erro`) e `pid`; estados ausentes, desconhecidos ou um processo
interrompido não autorizam o desligamento. O comando atua somente na VM deste
laboratório e não muda firewall ou rede.

## Testes locais

```bash
python3 -m unittest discover -s media-stack -p 'test_series_status.py'
python3 -m unittest discover -s media-stack -p 'test_clean_published_packages.py'
python3 -m unittest discover -s media-stack -p 'test_shutdown_after_cleanup.py'
```

Os testes usam dados sintéticos e não baixam mídia nem desligam a VM. Para
publicação de código, siga [PUBLICAR.md](PUBLICAR.md) e rode a checagem indicada.
