# Reproduzir o laboratório de downloads

Este roteiro foi extraído da instalação feita em Fedora 44 x86_64 e Debian 13
amd64. É destinado a uma pessoa ou LLM que tenha acesso ao terminal da máquina.
Os comandos indicam explicitamente se rodam no **Fedora** ou **dentro da VM**.

O resultado é uma VM com qBittorrent, Sonarr, Radarr, Prowlarr, Bazarr, Seerr,
ClamAV e coleta SFTP somente de leitura. O Jellyfin existente fornece apenas
login e catálogo ao Seerr. A etapa opcional de reprodução no Jellyfin existente
está em `JELLYFIN.md` e na seção 15. Nginx, Pi-hole, PostgreSQL, monitoramento
de espaço e backups não fazem parte deste roteiro.

Clonar traz os modelos, não os dados privados: uma instalação nova começa com
discos vazios, novas chaves e novas senhas. Não é um procedimento de restauração.

## 1. Identificar instalação nova ou existente

**Fedora, sem sudo:**

```bash
pwd
findmnt --target /mnt/dados/lab
ls -ld /mnt/dados/lab
virsh --readonly -c qemu:///system list --all
virsh --readonly -c qemu:///system net-list --all
```

Também conferir a existência de `disks/`, `secrets/`, `state/host-configured`
e das unidades `lab-downloads-firewall.service` e `lab-downloads-docker.service`.
Se o libvirt ainda não estiver instalado, registrar isso como pendência; não
confundir um erro de conexão com prova de que não existem recursos.

**Se já houver VM, discos, chaves ou credenciais, ir para a seção 14.** Não
executar a sequência de criação sobre esta instalação atual.

Os scripts estão fixados em `/mnt/dados/lab`. O caminho precisa ser uma pasta
do HD montado em `/mnt/dados`. Em outro destino, adaptar todas as referências
antes de executar, inclusive XML, SSH, SELinux, scripts e testes. Não criar
um symlink para disfarçar armazenamento no SSD.

## 2. Fazer o diagnóstico antes de modificar o Fedora

**Fedora, leituras:**

```bash
cat /etc/os-release
uname -m
free -h
df -h /mnt/dados
findmnt --mountpoint /mnt/dados
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,ROTA
test -c /dev/kvm
ip -br address
ip route show table all
systemctl is-active firewalld docker libvirtd virtqemud virtnetworkd
virsh --readonly -c qemu:///system net-list --all
getenforce
ls -Zd /mnt/dados /mnt/dados/lab
```

Conferir redes de VPNs, redes libvirt inclusive inativas e, se houver Docker no
host, as sub-redes dos containers. Os valores do modelo são:

| Recurso | Valor do modelo |
| --- | --- |
| Diretório no HD | `/mnt/dados/lab` |
| VM / rede libvirt | `lab-downloads` |
| Bridge / sub-rede | `virbr-dl` / `192.168.250.0/24` |
| Gateway / VM | `192.168.250.1` / `192.168.250.10` |
| MAC da VM | `52:54:00:dd:00:10` |
| Rede Docker dentro da VM | `172.30.40.0/24` |
| Recursos | 2 vCPUs, 6144 MiB RAM |
| Discos qcow2 independentes | Sistema 20 GiB, dados 400 GiB |
| Jellyfin existente | Acessível no gateway do host, TCP 8096 |

Não usar sub-redes sobrepostas ou MAC duplicado. Se adaptar um valor, localizar
**todas** as referências com `rg`, revisar e atualizar configurações e testes
em conjunto. O código espera o hostname da VM `lab-downloads`.

Verificar também:

- O Fedora deve continuar utilizável com 6 GiB destinados à VM.
- O HD deve ter espaço para os discos crescerem e suas cópias de mídia.
- O QEMU deve oferecer a máquina `pc-q35-10.2` do XML. Consultar
  `qemu-system-x86_64 -machine help`; se necessário, escolher uma máquina Q35
  disponível e validar o XML, sem alterar uma VM existente.
- A distribuição/arquitetura alvo é Fedora x86_64 com SELinux e Debian amd64.
  Outro sistema exige adaptação; não executar comandos `dnf`/SELinux às cegas.

## 3. Apresentar e autorizar as mudanças externas

Preparar os arquivos locais primeiro. Na sessão de instalação, obter autorização
do usuário para as mudanças concretas abaixo, salvo se já estiverem autorizadas
nessa sessão. O histórico deste repositório não concede autorização.

| Local | Mudança prevista |
| --- | --- |
| Pacotes e unidades de virtualização do Fedora | Instalar somente dependências ausentes e ativar a conexão libvirt necessária |
| `/etc/nftables/lab-downloads.nft` | Tabela exclusiva `inet lab_download_guard` |
| `/etc/nftables/lab-downloads-docker.sh` | Compatibilidade com encaminhamento do Docker do host, quando aplicável |
| `/etc/systemd/system/lab-downloads-{firewall,docker}.service` | Persistência das regras exclusivas do lab |
| Política SELinux local | Regras de contexto apenas para diretórios necessários e `lab/disks` |
| `/etc/libvirt`, `/var/lib/libvirt`, `/run`, logs normais | Metadados de VM/rede; discos continuam no HD em `lab/disks` |
| Disco virtual da VM | Instalação/configuração de pacotes, contas, serviços e Docker dentro do Debian |

Não alterar os containers existentes do Fedora, não reiniciar seu Docker,
não usar `flush ruleset`, não desativar SELinux e não compartilhar pastas do
host com a VM. A exceção Jellyfin permite somente o destino gateway:8096; ela
não transforma a VM em cliente livre da rede doméstica.

Caso o usuário não tenha um Jellyfin existente, concluir os outros serviços e
deixar a etapa Seerr pendente. Instalar Jellyfin ou escolher outro autenticador
é uma decisão adicional, não uma dependência a instalar silenciosamente.

A etapa opcional de reprodução também atualiza/recria o Jellyfin existente,
guarda sua configuração em `lab/jellyfin/runtime` e instala as unidades
`lab-jellyfin-sync.service` e `.timer` no Fedora. Ela exige a autorização
específica descrita em `JELLYFIN.md`; não é parte silenciosa da instalação base.

## 4. Instalar somente as dependências ausentes

**Fedora, após autorização:** conferir os comandos `virsh`, `virt-xml-validate`,
`qemu-img`, `qemu-system-x86_64`, `genisoimage`, `nft`, `iptables`, `semanage`,
`restorecon`, `ssh`, `scp`, `curl`, `python3` e `git`.

Os pacotes de referência são `qemu-kvm`, `qemu-img`, `libvirt`, `libvirt-client`,
`virt-manager` (opcional para interface gráfica), `genisoimage`, `nftables`,
`iptables-nft`, `policycoreutils-python-utils`, `openssh-clients`, `curl`,
`python3`, `python3-requests` e `git`. Resolver os nomes na versão real do
Fedora e instalar apenas o necessário com `dnf`.

Verificar as unidades disponíveis antes de ativar libvirt. Instalações modulares
usam, por exemplo, `virtqemud.socket` e `virtnetworkd.socket`; instalações
monolíticas usam `libvirtd`. Não habilitar os dois modelos indiscriminadamente.
Confirmar que `virsh -c qemu:///system list --all` funciona e que existe o grupo
`qemu`. **Não instalar Docker no Fedora por causa deste roteiro.**

## 5. Baixar a imagem e preparar os arquivos locais

**Fedora, somente instalação nova, sem sudo:**

```bash
cd /mnt/dados/lab
mkdir -p images state secrets disks backups coleta
chmod 700 state secrets backups
curl --fail --location --output images/SHA512SUMS \
  https://cloud.debian.org/images/cloud/trixie/20261026-2643/SHA512SUMS
curl --fail --location --output images/debian-13-genericcloud-amd64.qcow2.part \
  https://cloud.debian.org/images/cloud/trixie/20261026-2643/debian-13-genericcloud-amd64.qcow2
python3 scripts/prepare-local.py
```

O script verifica SHA512 antes de usar a imagem, cria discos independentes,
gera chaves SSH e senha aleatória, cria o cloud-init e `disks/seed.iso`.
O SHA512SUMS é obtido por HTTPS; isso não deve ser descrito como verificação
de assinatura GPG da imagem. Se esse build não estiver disponível, consultar
o diretório oficial, registrar a substituição e validar seus arquivos de
integridade. Não remover a verificação para contornar um download falho.

Não repetir `prepare-local.py` em uma VM instalada. Não publicar o seed, os
discos, as chaves ou o cloud-init gerado.

## 6. Cadastrar a VM com o firewall carregado

Revisar `config/downloads-guard.nft`, os dois XMLs e `scripts/configure-host.sh`.
Conferir ausência de VM/rede/bridge/arquivos homônimos. O script também verifica
rotas e valida NFT/XML antes de cadastrar os recursos.

O modelo SELinux contém regras novas criadas com `semanage fcontext -a`. Se já
houver uma regra equivalente, revisar a regra existente antes de decidir por
uma alteração específica; não apagar políticas ou reexecutar o script após
falha sem conferir o que já foi aplicado.

**Fedora, após autorização:**

```bash
sudo bash scripts/configure-host.sh --apply-reviewed-host-changes
sudo systemctl status lab-downloads-firewall.service lab-downloads-docker.service --no-pager
sudo nft list table inet lab_download_guard
```

O cadastro preserva VM e rede sem autostart. A memória do XML já é 6 GiB; numa
instalação nova não é necessário executar `configure-media-host.sh` ou
`restart-media-vm.sh`, usados na evolução da instalação original.

Não confundir sucesso do serviço de compatibilidade com prova de internet:
sem `DOCKER-USER`, nenhuma regra iptables é adicionada. Validar o encaminhamento
real; outros backends/firewalls podem exigir uma adaptação específica.

## 7. Primeiro boot e qBittorrent

**Fedora:**

```bash
sudo bash scripts/start-vm.sh
ssh -F config/ssh_config lab-downloads-admin 'cloud-init status --wait --long'
ssh -F config/ssh_config lab-downloads-admin \
  'sudo test -f /var/lib/lab-downloads-ready'
```

O SSH pode demorar a responder no primeiro boot. Confira a rede e o estado da
VM e tente novamente com intervalo; não recrie a VM por causa dessa espera.
Uma VM nova usa `state/known_hosts` novo. Se houver conflito com uma chave
antiga, conferir a identidade da VM antes de atualizar o registro.

Dentro da VM, o setup só formata o disco com serial `lab-downloads`, tamanho
de 400 GiB e sem assinatura existente. Ele monta em `/srv/downloads` e exige
essa montagem para iniciar o qBittorrent. A conta `labadmin` tem sudo somente
na VM; `torrent` executa o cliente sem privilégios administrativos.

Conferir montagem, contas e conectividade antes da próxima etapa:

```bash
ssh -F config/ssh_config lab-downloads-admin \
  'findmnt /srv/downloads; id torrent; systemctl is-active qbittorrent-nox@torrent.service'
ssh -F config/ssh_config lab-downloads-admin \
  'curl --fail --head --connect-timeout 8 https://www.debian.org'
```

O código de mídia espera UID/GID `1001:1001` para `torrent` e usa
`1100:1100` para `midia`, `1101:1101` para `triagem`. Se os IDs divergirem ou
já estiverem ocupados, adaptar os usos coerentemente antes do bootstrap.

Se a instalação de pacotes falhar por falta de rede, ler os logs de cloud-init
e `/var/log/lab-downloads-setup.log`, corrigir a causa e concluir somente as
etapas que falharam. Não mascarar erros nem alegar que `cloud-init` terminou
limpo quando o relatório indicar falhas.

## 8. Gerar credenciais e transferir o código de mídia

**Fedora, instalação nova:**

```bash
python3 scripts/prepare-media-secrets.py
ssh -F config/ssh_config lab-downloads-admin \
  'install -d -m 700 /home/labadmin/media-stack-upload'
scp -F config/ssh_config -r media-stack/. \
  lab-downloads-admin:/home/labadmin/media-stack-upload/
scp -F config/ssh_config secrets/media-stack.json \
  lab-downloads-admin:/home/labadmin/media-stack-credentials.json
scp -F config/ssh_config scripts/install-media-prerequisites.sh \
  lab-downloads-admin:/home/labadmin/install-media-prerequisites.sh
```

Esse envio usa a chave dedicada e não imprime credenciais. Depois preparar a
instalação no Debian, recusando sobrescrever uma pasta já instalada:

```bash
ssh -F config/ssh_config lab-downloads-admin 'sudo bash -s' <<'VM'
set -euo pipefail
test "$(hostname)" = lab-downloads
test ! -e /opt/media-stack
install -d -m 755 /opt/media-stack
cp -R /home/labadmin/media-stack-upload/. /opt/media-stack/
install -m 600 /home/labadmin/media-stack-credentials.json /opt/media-stack/credentials.json
bash /home/labadmin/install-media-prerequisites.sh
python3 /opt/media-stack/bootstrap.py
VM
```

As instalações seguintes rodam **dentro da VM**. O script instala Docker CE
pelo repositório oficial Debian, FFmpeg, bibliotecas Python e a base Debian do
ClamAV. O bootstrap configura permissões, unidades, contas e chroot da coleta.
Não executar `chown -R root` ou `chmod -R` em uma `appdata` já criada.

## 9. Ativar o motor ClamAV e suas assinaturas

O motor registrado na instalação original é o ClamAV LTS **1.4.6**, instalado
em `/opt/clamav-release`. O pacote Debian encontrado naquela ocasião era
1.4.3; a instalação não usa esse motor antigo para aprovar arquivos.

Antes de repetir em data futura, verificar suporte e avisos de segurança nas
fontes oficiais. A versão fixada reproduz a instalação, mas não se atualiza
sozinha. Se precisar substituí-la, revisar URL, SHA256, assinatura, bibliotecas,
serviços e testes; não trocar somente o número da versão ou usar `latest`.

O script `install-current-clamav.sh` contém o SHA256 do pacote e verifica sua
assinatura GPG com a chave oficial. Conferir a identidade esperada da chave:
`5BAD CA26 65EF 59DC F8A2 3D8B 707F 0DB4 8083 6771`.

**A partir do Fedora, comandos remotos dentro da VM:**

```bash
ssh -F config/ssh_config lab-downloads-admin 'sudo bash -s' <<'VM'
set -euo pipefail
bash /opt/media-stack/install-current-clamav.sh
systemctl stop clamav-freshclam.service
/usr/local/bin/freshclam --config-file=/etc/clamav/freshclam.conf
systemctl enable --now clamav-freshclam.service clamav-daemon.service
/usr/local/bin/clamscan --version
systemctl is-active clamav-freshclam.service clamav-daemon.service
stat -c '%a %U:%G' /run/clamav/clamd.ctl
VM
```

O socket deve pertencer a `clamav:clamav`, modo `660`. O binário universal não
usa a ativação por socket do pacote Debian: `clamav-daemon.socket` fica
mascarado e o daemon usa a unidade própria. Se não houver base atualizada,
concluir a atualização e conferir logs antes de ativar a triagem. Não aprovar
arquivos apenas para contornar a ausência do antivírus.

## 10. Subir os serviços com as imagens fixadas

`media-stack/images.lock.json` contém as cinco referências públicas por digest
da instalação original. `pull-images.py` usa esse manifesto, verifica a
arquitetura e gera um `.env` privado com a chave do Seerr. Ele recusa substituir
um `.env` existente.

**Comandos remotos dentro da VM:**

```bash
ssh -F config/ssh_config lab-downloads-admin \
  'sudo python3 /opt/media-stack/pull-images.py'
ssh -F config/ssh_config lab-downloads-admin \
  'sudo python3 /opt/media-stack/configure-apps.py'
ssh -F config/ssh_config lab-downloads-admin \
  'sudo docker compose --project-directory /opt/media-stack ps'
```

O primeiro download das imagens e a inicialização podem demorar no HD. Esperar
e examinar logs, em vez de iniciar múltiplas cópias dos instaladores.

O configurador ajusta o qBittorrent, qualidade e credenciais dos organizadores,
Prowlarr, indexadores que passarem no teste e perfil de legendas do Bazarr.
O perfil busca pt-BR e também inglês quando o áudio é inglês, sem considerar
pt-BR suficiente para encerrar a busca de inglês. Sonarr/Radarr importam
legendas `srt`, `ass` e `vtt` que passaram pela triagem junto do vídeo.
O relatório `/opt/media-stack/indexers-result.json` distingue fontes disponíveis
de pendentes. Na instalação original funcionaram Nyaa.si e Knaben; fontes e
provedores externos podem mudar. Falha de uma fonte não justifica desativar
TLS ou ampliar acesso a redes internas.

## 11. Login interativo e finalização do Seerr

Abrir no **Fedora** <http://192.168.250.10:5055>. O usuário deve cadastrar o
Jellyfin existente em `192.168.250.1`, porta `8096`, sem HTTPS, e fazer o login
diretamente na interface. Não pedir usuário/senha no chat, copiá-los para o
repositório ou tentar contornar a autenticação.

Depois de o usuário concluir o login:

```bash
ssh -F config/ssh_config lab-downloads-admin \
  'sudo python3 /opt/media-stack/configure-seerr.py'
```

O script testa e cadastra Sonarr/Radarr, seleciona perfil e diretórios e finaliza
o Seerr. Atualizar a página para entrar no catálogo. Essa etapa não fornece
os novos arquivos ao Jellyfin nem configura reprodução.

## 12. Validar a triagem antes de liberar o uso

**Fedora:**

```bash
python3 media-stack/triage/test_paths.py
python3 scripts/check_qbittorrent.py
ssh -F config/ssh_config lab-downloads-admin \
  'sudo python3 /opt/media-stack/test-pipeline.py'
```

Resultados esperados: vídeo sintético aprovado; EICAR (arquivo de teste do
antivírus) e executável disfarçado de MP4 reprovados. O teste não baixa mídia
externa. Ele remove os torrents e originais artificiais, mas deixa uma cópia
aprovada para conferir a coleta. O resultado com caminho e SHA256 fica em
`/opt/media-stack/pipeline-test-result.json`. EICAR pode gerar alertas esperados
de antivírus; não tratá-lo como mídia real nem publicar esses dados.

Testar o SFTP a partir de `lab/coleta`: baixar a amostra aprovada e comparar o
SHA256 com o relatório. Tentativas de enviar/remover arquivos, listar
`/recebidos` e listar `/.em-analise` devem falhar. Conferir que o cliente torrent
não consegue ler a cópia aprovada. Remover somente as fixtures conhecidas ao
terminar, preservando as evidências em `state/`.

Conferir também:

| Verificação | Resultado obrigatório |
| --- | --- |
| Seerr → Sonarr/Radarr | Testes de conexão aprovados, diretórios/perfil corretos |
| Busca do catálogo | Retorna metadados |
| Prowlarr → organizadores | Fontes testadas e sincronizadas |
| qBittorrent | Login exigido, quatro downloads, dois uploads e seis torrents ativos no total, destinos corretos, autorun e UPnP desativados |
| Organizadores → originais | Nenhuma montagem de `recebidos` |
| Organizadores → aprovados | Montagem somente de leitura |
| Completed Download Handling | Desativado; o aviso correspondente é esperado |
| Importação após triagem | Comando aceito e arquivo sintético registrado na biblioteca |
| Arquivo acima do limite do motor (aproximadamente 2 GiB no ClamAV 1.4.6) | Revisão manual, sem liberação automática, mesmo com teto configurado de 2560 MiB |
| Scanner indisponível ou assinatura antiga | Sem aprovação |
| Volume indisponível | qBittorrent e stack não iniciam gravando na raiz |
| Reinício gracioso da VM | Configurações, volume, serviços e arquivos persistem |

Para testar importação real, usar vídeo **sintético com áudio e duração acima
de 90 segundos**, associado temporariamente a metadados de uma obra de licença
aberta, sem solicitar download externo. O Radarr rejeita vídeo sem áudio como
arquivo incompleto. Conferir arquivo importado e tamanho pela API; depois
remover apenas a entrada e as fixtures criadas pelo teste. Um comando com
status `completed` sozinho não comprova que um arquivo foi importado.

Antes de executar `scripts/verify-isolation.sh`, adaptar os destinos físicos e
o IP do roteador à máquina real. Escolher serviços comprovadamente acessíveis
pelo Fedora para comparação; destino desligado não demonstra isolamento.
O script exige privilégios para ler os contadores, mas não altera regras.

O isolamento deve permitir internet e gateway:8096 do Jellyfin e negar conexões
iniciadas pela VM para SSH do Fedora e demais serviços da LAN. Conferir os
contadores nftables. IPv6 está bloqueado; não alegar teste com rota IPv6 global
se ele não foi executado.

Habilitar o timer após conferir o scanner:

```bash
ssh -F config/ssh_config lab-downloads-admin 'sudo bash -s' <<'VM'
set -euo pipefail
systemctl enable --now media-triage.timer
systemctl enable --now media-download-watch.timer
systemctl enable --now media-recovery.timer
systemctl start media-triage.service
systemctl is-active lab-media.service media-triage.timer clamav-daemon.service clamav-freshclam.service qbittorrent-nox@torrent.service
VM
```

Não reiniciar o Fedora nem interromper downloads reais como parte de um teste
sem combinar isso com o usuário. Registrar quais reinícios foram de fato feitos.

## 13. Entregar o estado final

Gravar em `state/verification.md` as versões efetivas, testes executados,
resultados, serviços habilitados, recursos usados e qualquer etapa pendente.
Não incluir senhas/chaves nos logs ou no relatório.

Os acessos e o uso diário estão em [media-stack/README.md](media-stack/README.md).
As contas dos organizadores usam `lab`, com senha em
`secrets/media-stack.json`; o qBittorrent usa `admin`, com senha em
`secrets/qbittorrent-password`; Seerr usa o login Jellyfin.

VM e rede ficam sem autostart no Fedora; os serviços iniciam dentro da VM.
Partida diária: `sudo bash scripts/start-lab.sh`. Parada graciosa:
`sudo bash scripts/stop-lab.sh`, seguida da conferência
com `virsh --readonly -c qemu:///system list --all`.

O material deste repositório documenta uma instalação validada, mas a nova
sequência de clonagem não foi reexecutada do zero em outra VM nesta etapa de
documentação. A instalação alvo precisa realizar suas próprias verificações.

## 14. Retomar uma instalação existente

1. Não executar `prepare-local.py`, gerar novamente credenciais, formatar discos
   ou repetir `configure-host.sh` sobre recursos existentes.
2. Ler os relatórios privados em `state/`, conferir estado libvirt, montagem,
   regras carregadas, serviços, `.env` privado e logs dentro da VM.
3. Identificar a última etapa realmente concluída. Um arquivo de estado sozinho
   não substitui a inspeção do resultado.
4. Corrigir somente a etapa pendente. Copiar arquivos individuais para a VM;
   não sobrescrever `appdata`, `credentials.json`, `.env` ou a biblioteca.
5. Se a mudança exigir serviço/VM reiniciado, explicar o impacto e usar parada
   graciosa. Não usar `virsh destroy` para acelerar uma espera.
6. Tratar atualização de imagens, motor antivírus e senhas como manutenção
   explícita, preservando dados e verificando compatibilidade. Não remover
   `.env` para forçar `pull-images.py` a executar novamente.

## 15. Conectar os arquivos ao Jellyfin existente (opcional)

Seguir [JELLYFIN.md](JELLYFIN.md) depois de validar a base. Essa etapa acrescenta
manifesto de mídia/legendas examinadas na VM, conta SFTP somente de leitura,
coleta iniciada pelo Fedora, validação SHA256 e bibliotecas separadas no HD.
Os arquivos chegam a uma montagem somente de leitura do Jellyfin.

O usuário da instalação original escolheu o servidor existente do Fedora.
Em outra instalação, confirmar essa escolha: a reprodução em outra VM teria
uma barreira mais forte contra falhas em decodificadores. Não afirmar que
antivírus ou somente leitura impedem qualquer comprometimento do host.

## 16. Capacidade do volume de downloads

Instalações novas usam 400 GiB. A instalação original começou com 200 GiB e foi
ampliada online, sem desligar a VM ou formatar o volume, com
`scripts/expand-downloads-400g.sh`. A operação usa `virsh blockresize` no disco
em uso e `resize2fs` dentro da VM; não executar `qemu-img resize` em um qcow2
aberto pelo QEMU. Nunca reduzir o tamanho do dispositivo.

Os 400 GiB são a capacidade compartilhada do volume, não 400 GiB para cada
etapa do fluxo. As cópias da biblioteca do Jellyfin consomem espaço adicional
no HD do host. O qcow2 continua crescendo conforme o uso, sem pré-alocar tudo.
O uso diário está em [USO-DIARIO.md](USO-DIARIO.md).

## Fontes para conferir versões e comportamento

- [Debian Cloud: build utilizado](https://cloud.debian.org/images/cloud/trixie/20261026-2643/)
- [Docker Engine no Debian](https://docs.docker.com/engine/install/debian/)
- [Firewall do Docker](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Redes do libvirt](https://libvirt.org/formatnetwork.html)
- [ClamAV: instalação](https://docs.clamav.net/manual/Installing.html)
- [Releases oficiais do ClamAV](https://github.com/Cisco-Talos/clamav/releases)
- [Segurança do pacote ClamAV no Debian](https://security-tracker.debian.org/tracker/source-package/clamav)
- [Seerr](https://docs.seerr.dev/)
- [Sonarr API](https://sonarr.tv/docs/api/)
- [Radarr API](https://radarr.video/docs/api/)
- [Prowlarr API](https://prowlarr.com/docs/api/)
