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
