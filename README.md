# VM de downloads no HD

Para montar uma instalação nova após clonar, siga [REPRODUZIR.md](REPRODUZIR.md).
Para publicar somente código e documentação, siga [PUBLICAR.md](PUBLICAR.md).
O fluxo de reprodução no servidor existente está em [JELLYFIN.md](JELLYFIN.md).
Para ligar, usar e desligar, siga [USO-DIARIO.md](USO-DIARIO.md).
As instruções para uma LLM estão em [AGENTS.md](AGENTS.md); não reutilize
autorizações antigas nem execute a criação sobre uma VM já instalada.

> Etapa de busca e download implementada: Sonarr, Radarr, Prowlarr, Seerr,
> Bazarr e triagem ClamAV dentro da VM. O Jellyfin existente recebe cópias
> examinadas por coleta iniciada pelo Fedora, em uma montagem de leitura.
> A única exceção de API ao
> bloqueio da VM é `192.168.250.1:8096`; os outros serviços/LAN seguem bloqueados.
> A VM está usando 6 GiB de RAM. Não foram
> adicionados monitoramento de espaço ou backups nesta etapa.

**Começar pelo [Seerr](http://192.168.250.10:5055)**. Sonarr e Radarr já estão
cadastrados; basta atualizar a página após o login. Os acessos, as credenciais,
o fluxo de aprovação e os limites estão em [media-stack/README.md](media-stack/README.md).
A integração de arquivos com o Jellyfin está descrita em
[JELLYFIN.md](JELLYFIN.md), com biblioteca separada no HD e leitura apenas.
O volume da VM foi ampliado online de 200 para **400 GiB**, preservando dados.

Escopo: Debian 13 + qBittorrent-nox em KVM, administração por SSH e coleta de
arquivos via SFTP de leitura. Todos os discos e arquivos próprios do laboratório
ficam em `/mnt/dados/lab`. Não há Nginx, Pi-hole ou banco de dados nesta etapa.

## Base instalada em 30/10/2026

A lista registra a instalação inicial. A etapa de mídia concluída em 31/10/2026
alterou RAM, destinos do qBittorrent, chroot da coleta e a exceção do Jellyfin,
conforme descrito abaixo e no documento da etapa.

- Fedora 44; KVM, QEMU, libvirt, nftables, genisoimage e ferramentas SELinux já instalados.
- `/mnt/dados` é o HD `/dev/sda1`, ext4; cerca de 728 GiB livres na inspeção inicial.
- Imagem oficial Debian 13 genericcloud amd64, build `20261026-2643`, baixada por HTTPS.
- SHA512 conferido contra `SHA512SUMS` obtido por HTTPS do servidor oficial.
  Esse arquivo não é uma assinatura GPG; não foi alegada validação por assinatura.
- Discos independentes, sem backing file: sistema 20 GiB e downloads 200 GiB.
  São arquivos qcow2 que crescem conforme o uso; 220 GiB não foram pré-alocados.
- Chaves SSH dedicadas e senha aleatória do painel geradas somente em `secrets/`.
- Seed cloud-init aplicado; os esquemas de usuário e rede foram validados dentro do Debian.
- VM e rede cadastradas no libvirt e iniciadas após autorização explícita do usuário.
- Firewall ativo; internet e isolamento contra Fedora/LAN verificados com contadores.
- Coleta SFTP verificada: leitura permitida, envio e remoção negados.
- qBittorrent 5.1.0 instalado, habilitado dentro da VM e acessível pelo Fedora.
- Download real de uma amostra de 4,8 MB do torrent oficial Debian concluído;
  torrent de teste e seus dados removidos em seguida.
- Disco indisponível: início do cliente negado; montagem restaurada após o teste.
- Reinício da VM validado: dados, SSH e configurações preservados; cloud-init
  terminou com `status: done`, sem erros ou avisos recuperáveis.
- VM permanece ligada, sem torrents ativos. VM e rede continuam sem autostart no Fedora.

## Recursos e endereços

| Recurso | Valor |
| --- | --- |
| Nome no libvirt | `lab-downloads` |
| CPU / RAM | 2 vCPUs / 6144 MiB |
| Disco do sistema | `disks/system.qcow2`, 20 GiB, VirtIO |
| Disco de downloads | `disks/downloads.qcow2`, 400 GiB, VirtIO |
| Seed de instalação | `disks/seed.iso` |
| Rede NAT / bridge | `lab-downloads` / `virbr-dl` |
| Sub-rede / gateway | `192.168.250.0/24` / `192.168.250.1` |
| IP / MAC da VM | `192.168.250.10` / `52:54:00:dd:00:10` |
| Painel após instalação | <http://192.168.250.10:8080> |
| Login do painel | `admin`; senha em `secrets/qbittorrent-password` |
| Limite inicial de upload | 256 KiB/s, ajustável no painel |
| Administração SSH | `labadmin`, chave `secrets/admin_ed25519` |
| Coleta SFTP | `coleta`, chave `secrets/coleta_ed25519` |
| Inicialização automática | VM e rede desativadas |

O usuário `torrent` executa o cliente sem sudo. O administrador `labadmin` tem
sudo dentro da VM para manutenção. São credenciais diferentes da conta de coleta.
Não há compartilhamento de diretórios do host, USB, interface gráfica ou clipboard.

## Mudanças no Fedora autorizadas e aplicadas

O usuário autorizou estas mudanças nesta conversa. O script
`scripts/configure-host.sh` e o complemento `scripts/configure-docker-compat.sh`
aplicaram a configuração administrativa:

1. Instala `/etc/nftables/lab-downloads.nft` e
   `/etc/systemd/system/lab-downloads-firewall.service`; habilita e carrega esse serviço.
   Cria somente a tabela `inet lab_download_guard`, sem limpar regras existentes.
   O Docker estava descartando o encaminhamento da VM. Foram acrescentadas duas
   exceções IPv4 na cadeia `DOCKER-USER`, restritas a `virbr-dl` e à sub-rede da VM;
   o bloqueio de destinos internos continua sendo aplicado antes dessas exceções.
   O auxiliar `/etc/nftables/lab-downloads-docker.sh` e o serviço
   `/etc/systemd/system/lab-downloads-docker.service` reaplicam essas exceções ao
   iniciar o Docker. O Docker e seus containers não foram reiniciados.
2. Adiciona regras persistentes de contexto SELinux para `/mnt/dados` (só esse
   diretório, tipo `mnt_t`), `/mnt/dados/lab` (só esse diretório) e
   `/mnt/dados/lab/disks(/.*)?` (`virt_image_t`). Aplica os rótulos apenas nesses
   caminhos. O diretório `/mnt/dados` estava `unlabeled_t` na inspeção; não é
   necessário relabelar recursivamente o HD, desligar o SELinux ou mudar sua política.
3. Dá ao grupo `qemu` acesso somente à pasta `disks/` e seus três arquivos.
4. Cadastra a rede e a VM `lab-downloads` no libvirt de sistema. Isso grava metadados
   em `/etc/libvirt`; o libvirt também usa seus caminhos normais de estado e logs
   em `/run` e `/var`. **Os discos e o conteúdo da VM continuam no HD.**
5. Mantém VM e rede sem autostart. A partida foi feita separadamente pelo script abaixo.

O script de partida `scripts/start-vm.sh` recarrega o firewall, verifica sua tabela,
inicia a rede NAT e só então inicia a VM. A instalação de pacotes Debian acontece
dentro de `system.qcow2`, após esse primeiro boot. Não se prevê instalar pacotes
adicionais no Fedora.

Os scripts param se encontram recursos homônimos ou sobreposição de sub-rede.
Uma falha intermediária pode deixar alterações parciais; não repetir às cegas.
Antes de executar novamente, conferir os erros e os recursos que já foram criados.

O cadastro inicial **já foi executado**. Não repetir `configure-host.sh` em uma
instalação existente. Para iniciar a VM quando estiver desligada:

```bash
cd /mnt/dados/lab
sudo bash scripts/start-lab.sh
```

## Instalação automática dentro da VM

O cloud-init configura contas por chave, instala `qbittorrent-nox` e prepara o
disco adicional. A formatação só é permitida para o dispositivo com serial
`lab-downloads`, tamanho exato de 400 GiB e sem assinatura existente.
O disco vira `/srv/downloads`; a configuração exige essa montagem para iniciar
`qbittorrent-nox@torrent.service`.

Na configuração atual, as pastas `incompletos`, `recebidos`, `aprovados` e
`biblioteca` ficam nesse disco; as configurações e o
estado do cliente ficam no disco do sistema. O painel exige autenticação;
UPnP/NAT-PMP e descoberta de peers na LAN começam desligados. A fila permite
quatro downloads simultâneos, até dois uploads e seis torrents ativos no total.
O upload começa limitado a 256 KiB/s; ajustar ao
desempenho da conexão pelo painel.

A primeira instalação falhou porque o encaminhamento do Docker impedia a saída
da VM. Após a correção, os pacotes foram instalados, as duas etapas que falharam
foram executadas novamente e o reinício confirmou o cloud-init sem erros.
Os logs originais foram preservados. A atualização disponível de `tzdata` também
foi aplicada dentro do Debian; não foram instalados pacotes adicionais no Fedora.

O SFTP usa `internal-sftp -R`, sem shell ou encaminhamento, com chroot em
`/srv/downloads/aprovados`. A conta só recebe as cópias liberadas pela triagem;
originais, incompletos e a área privada de análise ficam inacessíveis.
Não executar arquivos coletados automaticamente.

Depois do boot, aguardar a conclusão:

```bash
ssh -F config/ssh_config lab-downloads-admin 'cloud-init status --wait --long'
ssh -F config/ssh_config lab-downloads-admin \
  'sudo test -f /var/lib/lab-downloads-ready && systemctl is-active qbittorrent-nox@torrent'
```

Para investigar um erro da instalação:

```bash
ssh -F config/ssh_config lab-downloads-admin \
  'sudo tail -n 100 /var/log/cloud-init-output.log /var/log/lab-downloads-setup.log'
```

Não recriar o seed ou as chaves de uma instalação em uso. O seed contém apenas
as chaves públicas e o hash da senha do painel; ainda assim, tratar imagens,
discos, logs e backups como privados. As chaves privadas locais não têm senha
para permitir a automação e ficam em pasta de modo 700, com arquivos de modo 600.

## Acesso e operação depois da validação

Abrir <http://192.168.250.10:8080> no Fedora. Ler a senha localmente:

```bash
cat /mnt/dados/lab/secrets/qbittorrent-password
```

Coletar arquivos em uma pasta deste laboratório, preservando a regra de não
escrever fora de `lab`:

```bash
mkdir -p /mnt/dados/lab/coleta
cd /mnt/dados/lab/coleta
sftp -F /mnt/dados/lab/config/ssh_config lab-downloads-coleta
# ls
# get nome-do-arquivo
# bye
```

O arquivo de hosts SSH conhecidos fica em `state/known_hosts`; não é preciso
alterar `~/.ssh`. A chave do host da VM é registrada no primeiro acesso.

Encerrar e conferir o desligamento assíncrono:

```bash
sudo virsh -c qemu:///system shutdown lab-downloads
virsh --readonly -c qemu:///system list --all
```

## Validação executada

| Teste | Resultado |
| --- | --- |
| Esquemas cloud-init de usuário e rede | Válidos |
| API sem autenticação / com a senha gerada | Acesso negado / login válido |
| Pastas, fila (dois downloads na validação inicial), UPnP, descoberta local e execução automática | Configurações conferidas pela API |
| Download BitTorrent oficial | Amostra de 4,8 MB recebida; 33 seeds conectados no registro; teste removido |
| VM → internet | HTTPS para Debian funciona |
| VM → SSH do Fedora e IPs físicos do host | Bloqueados |
| VM → Jellyfin pelo gateway `192.168.250.1:8096` | Permitido exclusivamente para autenticação/catálogo do Seerr |
| VM → painel do roteador `192.168.0.1:80` | Bloqueado; o mesmo destino funcionava no Fedora |
| Contadores nftables | Aumento nas regras de bloqueio `input` e `forward` |
| SFTP | Download permitido; upload e remoção negados |
| Volume indisponível | Com a montagem temporariamente mascarada e desmontada, o cliente não iniciou; montagem e serviço restaurados |
| Reinício da VM | Arquivo do volume coletado novamente e comparado; configurações e credenciais mantidas |
| Cloud-init depois do reinício | `done`, sem erros ou avisos recuperáveis |

O teste de montagem simula um disco indisponível. Quando o disco existe e pode
ser montado, `RequiresMountsFor` permite que o systemd o monte antes de iniciar o
cliente. A propriedade verificada é não iniciar gravando no diretório da raiz
quando o volume necessário está indisponível.

Os registros ficam em `state/isolation-test.txt`, `state/qbittorrent-check.json`,
`state/torrent-smoke.json` e `state/verification.md`. Os arquivos artificiais de
coleta usados no teste foram removidos após a verificação de persistência.

O Fedora não foi reiniciado para não interromper o uso pessoal e os containers
existentes. Conferir os dois serviços de firewall antes de usar a VM depois de
um reinício do host. O bloqueio IPv6 está configurado; não foi feito teste com
uma rota IPv6 global na VM.

```bash
sudo nft list table inet lab_download_guard
systemctl status lab-downloads-firewall.service lab-downloads-docker.service --no-pager
ssh -F config/ssh_config lab-downloads-admin \
  'curl -I --connect-timeout 5 https://www.debian.org'
ssh -F config/ssh_config lab-downloads-admin \
  'curl --connect-timeout 3 --max-time 4 http://192.168.250.1:8096'
```

A política permite DHCP/DNS no gateway, a exceção do Jellyfin e respostas às
conexões iniciadas pelo Fedora. Bloqueia as demais conexões da VM para os
intervalos internos listados e IPv6.
Novas redes internas com prefixos públicos exigem ajuste antes de usar a VM nelas.
Não há encaminhamento da porta P2P ou do painel para a LAN/internet.

Backups de disco devem ser feitos com a VM desligada ou por um procedimento
consistente de snapshots. O disco virtual limita a capacidade dentro da VM;
acompanhar o espaço livre do HD, pois qcow2 e snapshots ainda o consomem.

## Próximo passo acordado

Em 02/11/2026, o usuário pediu quatro downloads simultâneos. O teto total foi
ajustado para seis torrents ativos, permitindo os quatro downloads e os dois
uploads já configurados. A alteração usa as preferências do qBittorrent, sem
recriar a VM nem repetir a instalação.

Depois que os downloads atuais terminarem, implementar o painel de acompanhamento
e a recuperação de faltantes descritos em [PROXIMOS-PASSOS.md](PROXIMOS-PASSOS.md).
A implementação foi adiada pelo usuário; não há ativação agendada.

## Referências oficiais

- [Imagem Debian e arquivos de integridade](https://cloud.debian.org/images/cloud/trixie/20261026-2643/)
- [Cloud-init NoCloud](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html)
- [Rede NAT e isolamento de portas no libvirt](https://libvirt.org/formatnetwork.html)
- [Discos e dispositivos no XML do libvirt](https://libvirt.org/formatdomain.html)
- [Serviço fornecido no pacote Debian qBittorrent](https://packages.debian.org/trixie/amd64/qbittorrent-nox/filelist)
- [Formato do hash da senha no qBittorrent](https://github.com/qbittorrent/qBittorrent/blob/release-5.1.0/src/base/utils/password.cpp)
- [Manual do nftables](https://netfilter.org/projects/nftables/manpage.html)
- [Exceções na cadeia de usuário do Docker](https://docs.docker.com/engine/network/firewall-iptables/)
