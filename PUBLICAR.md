# Publicar o roteiro no GitHub

O repositório deve conter **código, modelos e documentação**. Ele não é uma
cópia da VM em funcionamento nem um backup dos seus arquivos.

## O que acompanha o repositório

- `README.md`, `REPRODUZIR.md`, `PUBLICAR.md`, `JELLYFIN.md`, `USO-DIARIO.md` e `AGENTS.md`.
- `scripts/`, `config/`, `media-stack/`, `jellyfin/` e `cloud-init/setup-guest.sh`,
  respeitando os arquivos gerados excluídos pelo `.gitignore`.
- `media-stack/images.lock.json`: referências públicas das imagens utilizadas,
  sem chaves de API ou senhas.
- `.gitignore`, que exclui os arquivos privados e gerados.

Os IPs privados, nomes de rede e caminhos dos exemplos não são credenciais,
mas revelam parte do desenho do laboratório. Revise a documentação se não
quiser publicar esses detalhes. Não é necessário publicar dados reais para
reproduzir a configuração.

## O que fica somente no computador

| Arquivos | Motivo |
| --- | --- |
| `secrets/` | Senhas e chaves SSH privadas |
| `cloud-init/user-data`, `meta-data`, `network-config` | Dados gerados; user-data contém chaves públicas e hash de senha |
| `disks/`, `images/` | Discos da VM, seed e imagens baixadas |
| `.env`, `credentials.json`, `appdata/` | Configuração de execução e credenciais das aplicações |
| `state/`, `coleta/`, `backups/` | Logs, resultados locais e arquivos pessoais |
| `jellyfin/biblioteca`, `runtime`, `state`, `.em-recebimento` | Vídeos, quarentena, usuários/catálogo e temporários do servidor |

Nunca use `git add -f` nesses caminhos. Não envie a pasta inteira como ZIP:
o `.gitignore` só orienta o Git, não remove arquivos de um arquivo compactado.

## Preparar e revisar

Na raiz do projeto, sem sudo:

```bash
cd /mnt/dados/lab
python3 scripts/check-publication.py
```

A auditoria lista os candidatos em `state/publication-files.txt`, procura
credenciais locais conhecidas e alguns formatos de chave/token, e considera
arquivos já rastreados caso exista um repositório. Ela não é uma prova de que
nenhum segredo existe e não examina commits antigos ou o histórico remoto.

Se ainda não houver `.git`, inicializar:

```bash
git init -b main
```

Adicionar os caminhos explícitos evita depender de `git add .`:

```bash
git add .gitignore AGENTS.md README.md REPRODUZIR.md PUBLICAR.md JELLYFIN.md USO-DIARIO.md
git add scripts/ config/ media-stack/ jellyfin/ cloud-init/setup-guest.sh
python3 scripts/check-publication.py
git diff --cached --stat
git diff --cached
git status --short
```

Revise o conteúdo antes de criar o commit. Se a auditoria apontar um arquivo
privado já adicionado, retire-o do índice com `git restore --staged CAMINHO`
(ou `git rm --cached CAMINHO` em um repositório sem commit), preservando a cópia
local. Se um segredo já entrou em um commit, excluí-lo no próximo commit não o
remove do histórico: interrompa a publicação e trate o histórico e a credencial.

## Enviar

Depois da revisão, crie um repositório vazio na sua conta do GitHub e use a URL
real dele:

```bash
git commit -m "Documenta homelab de downloads isolado em VM"
git remote add origin URL_REAL_DO_REPOSITORIO
git push -u origin main
```

Se `origin` já existir, confira `git remote -v` antes de alterá-lo. Autentique
pelo mecanismo do Git/GitHub; não coloque tokens na URL ou nos arquivos.

## Clonar e pedir a instalação

Em um HD montado no destino adequado, clone para uma **pasta nova**:

```bash
git clone URL_REAL_DO_REPOSITORIO /mnt/dados/lab
cd /mnt/dados/lab
```

Não clone por cima desta instalação atual. Em outro caminho ou sistema, a LLM
precisa adaptar os caminhos fixos antes de executar os scripts.

Prompt para fornecer à LLM:

> Leia AGENTS.md e REPRODUZIR.md. Quero reproduzir este laboratório nesta
> máquina, mantendo todos os discos e dados próprios no HD. Comece pelo
> diagnóstico, identifique recursos existentes e prepare os arquivos locais.
> Depois apresente as mudanças concretas necessárias fora desta pasta e
> aguarde minha autorização para aplicá-las. Após a autorização, execute as
> etapas em ordem, valide o resultado e registre as evidências locais. Não
> recrie dados existentes e não amplie o acesso à LAN. Se eu escolher conectar
> um Jellyfin existente, siga também JELLYFIN.md, apresentando as mudanças
> externas antes de aplicá-las. Quando chegar ao login do Seerr/Jellyfin, me oriente a fazê-lo
> diretamente na interface, sem pedir minhas senhas no chat.

Clonar cria uma nova instalação com novas credenciais e dados vazios. Recuperar
downloads, biblioteca, configurações de usuário ou estado da VM antiga exige
os dados privados originais e é uma tarefa diferente.
