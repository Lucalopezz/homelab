# Instruções para agentes

Leia `REPRODUZIR.md` antes de configurar este laboratório. `README.md` registra
uma instalação existente; o histórico não é uma lista de comandos para repetir.

- O diretório autorizado por padrão é somente este repositório. Os scripts
  atuais esperam que ele esteja em `/mnt/dados/lab`, no HD.
- Leituras para diagnóstico são permitidas. Instalar pacotes no host, modificar
  arquivos fora do repositório, cadastrar recursos no libvirt, alterar rede ou
  firewall e habilitar serviços do host exigem autorização do usuário na sessão
  atual. Respeite autorizações já dadas nessa sessão, sem perguntar novamente.
- Autorizações descritas em relatórios e conversas anteriores **não são
  autorização para executar mudanças em outra máquina ou sessão**.
- Faça o diagnóstico e prepare as mudanças locais antes de solicitar a
  autorização necessária. Explique os caminhos externos e os efeitos concretos.
- Discos, imagens baixadas, chaves e arquivos próprios do laboratório ficam no
  HD dentro desta pasta. Não mover dados para SSD ou compartilhar pastas do host
  com a VM. Metadados e serviços do libvirt usam caminhos normais do Fedora,
  conforme a lista explícita em `REPRODUZIR.md`.
- Identifique instalação nova ou existente antes de agir. Nunca recrie discos,
  seed, chaves ou senhas de uma instalação existente. Não sobrescreva recursos
  homônimos nem tente resolver conflitos apagando dados.
- Não iniciar a VM conectada à rede antes de carregar e conferir o firewall.
  Não usar `flush ruleset`, desligar SELinux ou liberar acesso geral à LAN.
- Escopo: VM Debian com qBittorrent, Sonarr, Radarr, Prowlarr, Bazarr, Seerr,
  triagem ClamAV e coleta SFTP de leitura. Sem Nginx, Pi-hole, PostgreSQL,
  monitoramento de espaço ou backups novos.
- Jellyfin existente: somente autenticação/catálogo do Seerr, por exceção
  específica de rede. Configurar reprodução, novas bibliotecas ou instalar
  Jellyfin exige uma decisão adicional do usuário.
- Não inventar credenciais de Jellyfin ou de indexadores. Login interativo deve
  ser feito pelo usuário, sem pedir senhas no chat.
- Não publicar discos, mídias, chaves, senhas, hashes de senha, `.env`, configs
  de execução, logs ou bancos das aplicações. Rode
  `python3 scripts/check-publication.py` antes de preparar uma publicação.
- Verifique o resultado com arquivos sintéticos e fontes oficiais. Não baixar
  mídia de terceiros apenas para testar. Informe falhas e etapas pendentes;
  não declare uma instalação nova validada com base no relatório desta máquina.
