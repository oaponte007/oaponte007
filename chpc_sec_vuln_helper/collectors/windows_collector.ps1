#requires -Version 5.1
<#
.SYNOPSIS
    Collects the real, current security-relevant state of a Windows 10
    or 11 host into one JSON file -- built-in PowerShell only, nothing
    to install, meant to run directly on the (possibly airgapped)
    target. Run as Administrator for full coverage; anything that
    can't be checked without more privilege is skipped and noted in
    collector_warnings, never guessed.

    IMPORTANT: this script could not be executed or syntax-tested in
    the Linux environment it was written in (no PowerShell available
    there). It is written carefully against well-established, stable
    cmdlets, but spot-check its output against a real Windows 10/11
    machine before relying on it, the same way you'd want to verify
    any new security tooling before trusting its results.

.PARAMETER OutputPath
    Where to write the JSON. Defaults to .\collected.json in the
    current directory.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File windows_collector.ps1 -OutputPath collected.json
#>
param(
    [string]$OutputPath = ".\collected.json"
)

$ErrorActionPreference = "Stop"
$warnings = New-Object System.Collections.Generic.List[string]

function Try-Collect {
    param(
        [string]$Label,
        [scriptblock]$Block
    )
    try {
        return & $Block
    } catch {
        $warnings.Add("Could not collect '$Label': $($_.Exception.Message)")
        return $null
    }
}

# --- OS identity -----------------------------------------------------------
$osInfo = Try-Collect "OS version" {
    $cv = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $buildNumber = [int]$cv.CurrentBuildNumber
    $ubr = if ($cv.PSObject.Properties.Name -contains "UBR") { $cv.UBR } else { 0 }
    $majorVersion = if ($buildNumber -ge 22000) { 11 } else { 10 }
    [PSCustomObject]@{
        family        = "windows"
        name          = $cv.ProductName
        major_version = $majorVersion
        version_id    = $cv.DisplayVersion
        build         = "$buildNumber.$ubr"
    }
}
if (-not $osInfo) {
    $osInfo = [PSCustomObject]@{ family = "windows"; name = $null; major_version = $null; version_id = $null; build = $null }
}

# --- Installed hotfixes (informational) -------------------------------------
$hotfixes = Try-Collect "installed hotfixes" {
    @(Get-HotFix | ForEach-Object { $_.HotFixID })
}

# --- Installed software (informational, from registry uninstall keys) ------
$installedSoftware = Try-Collect "installed software" {
    $paths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName } |
        ForEach-Object { [PSCustomObject]@{ name = $_.DisplayName; version = $_.DisplayVersion } }
}

# --- Windows Defender --------------------------------------------------------
$defender = Try-Collect "Windows Defender status" {
    $status = Get-MpComputerStatus
    [PSCustomObject]@{
        enabled               = [bool]$status.AntivirusEnabled
        real_time_protection  = [bool]$status.RealTimeProtectionEnabled
    }
}

# --- Firewall ----------------------------------------------------------------
$firewallActive = Try-Collect "firewall profiles" {
    $profiles = Get-NetFirewallProfile
    -not ($profiles | Where-Object { -not $_.Enabled })
}

# --- SMBv1 ---------------------------------------------------------------
$smb1Enabled = Try-Collect "SMBv1 feature state" {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName "SMB1Protocol"
    $feature.State -eq "Enabled"
}

# --- Remote Desktop / NLA ------------------------------------------------
$rdp = Try-Collect "Remote Desktop settings" {
    $tsPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server"
    $nlaPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"
    $deny = (Get-ItemProperty -Path $tsPath -Name "fDenyTSConnections" -ErrorAction SilentlyContinue).fDenyTSConnections
    $nla = (Get-ItemProperty -Path $nlaPath -Name "UserAuthentication" -ErrorAction SilentlyContinue).UserAuthentication
    [PSCustomObject]@{
        enabled                        = ($deny -eq 0)
        network_level_authentication   = ($nla -eq 1)
    }
}

# --- Automatic updates -----------------------------------------------------
$autoUpdatesEnabled = Try-Collect "automatic updates policy" {
    $auPolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
    $noAutoUpdate = (Get-ItemProperty -Path $auPolicyPath -Name "NoAutoUpdate" -ErrorAction SilentlyContinue).NoAutoUpdate
    $service = Get-Service -Name "wuauserv" -ErrorAction SilentlyContinue
    if ($noAutoUpdate -eq 1) {
        $false
    } elseif ($service -and $service.StartType -eq "Disabled") {
        $false
    } else {
        $true
    }
}

# --- Local password/lockout policy (parsed from `net accounts`) -----------
$localPasswordPolicy = Try-Collect "local password policy" {
    $lines = net accounts
    $minLen = $null
    $lockoutThreshold = $null
    foreach ($line in $lines) {
        if ($line -match "Minimum password length\s*:\s*(\d+)") { $minLen = [int]$Matches[1] }
        if ($line -match "Lockout threshold\s*:\s*(\d+|Never)") {
            $lockoutThreshold = if ($Matches[1] -eq "Never") { 0 } else { [int]$Matches[1] }
        }
    }
    [PSCustomObject]@{ min_length = $minLen; lockout_threshold = $lockoutThreshold }
}

# --- Guest account -----------------------------------------------------------
$guestAccountEnabled = Try-Collect "Guest account status" {
    (Get-LocalUser -Name "Guest" -ErrorAction Stop).Enabled
}

# --- UAC -----------------------------------------------------------------
$uacEnabled = Try-Collect "UAC policy" {
    $value = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "EnableLUA" -ErrorAction Stop).EnableLUA
    $value -eq 1
}

# --- BitLocker on the system drive ----------------------------------------
$bitlockerStatus = Try-Collect "BitLocker status" {
    $systemDrive = $env:SystemDrive
    $volume = Get-BitLockerVolume -MountPoint $systemDrive -ErrorAction Stop
    ($volume.VolumeStatus -as [string]).ToLower()
}

# --- SmartScreen -----------------------------------------------------------
$smartScreenEnabled = Try-Collect "SmartScreen policy" {
    $policyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\System"
    $policyValue = (Get-ItemProperty -Path $policyPath -Name "EnableSmartScreen" -ErrorAction SilentlyContinue).EnableSmartScreen
    if ($null -ne $policyValue) {
        [int]$policyValue -ne 0
    } else {
        $explorerPath = "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer"
        $explorerValue = (Get-ItemProperty -Path $explorerPath -Name "SmartScreenEnabled" -ErrorAction SilentlyContinue).SmartScreenEnabled
        if ($null -ne $explorerValue) { $explorerValue -ne "Off" } else { $true }
    }
}

# --- PowerShell execution policy --------------------------------------------
$executionPolicy = Try-Collect "PowerShell execution policy" {
    (Get-ExecutionPolicy).ToString()
}

# --- Remote Registry service -------------------------------------------------
$remoteRegistryRunning = Try-Collect "Remote Registry service" {
    $service = Get-Service -Name "RemoteRegistry" -ErrorAction Stop
    $service.Status -eq "Running"
}

# --- AutoPlay (simplified: checks the policy key that fully disables it) ---
$autoplayEnabled = Try-Collect "AutoPlay policy" {
    $policyPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"
    $value = (Get-ItemProperty -Path $policyPath -Name "NoDriveTypeAutoRun" -ErrorAction SilentlyContinue).NoDriveTypeAutoRun
    if ($null -eq $value) { $true } else { ([int]$value -band 0xFF) -lt 0xFF }
}

# --- Listening ports (informational) ----------------------------------------
$listeningPorts = Try-Collect "listening ports" {
    Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Select-Object -First 200 |
        ForEach-Object { [PSCustomObject]@{ port = $_.LocalPort; proto = "tcp"; address = $_.LocalAddress } }
}

# --- Assemble and write ------------------------------------------------------
$result = [PSCustomObject]@{
    schema_version           = 1
    hostname                 = $env:COMPUTERNAME
    collected_at             = (Get-Date).ToUniversalTime().ToString("o")
    os                       = $osInfo
    hotfixes                 = $hotfixes
    installed_software       = $installedSoftware
    defender                 = $defender
    firewall_active          = $firewallActive
    smb1_enabled              = $smb1Enabled
    rdp                      = $rdp
    auto_updates_enabled      = $autoUpdatesEnabled
    local_password_policy     = $localPasswordPolicy
    guest_account_enabled     = $guestAccountEnabled
    uac_enabled               = $uacEnabled
    bitlocker_system_drive_status = $bitlockerStatus
    smartscreen_enabled       = $smartScreenEnabled
    powershell_execution_policy = $executionPolicy
    remote_registry_running   = $remoteRegistryRunning
    autoplay_enabled          = $autoplayEnabled
    listening_ports           = $listeningPorts
    collector_warnings        = @($warnings)
}

$json = $result | ConvertTo-Json -Depth 6
# Windows PowerShell 5.1's `-Encoding UTF8` writes a UTF-8 byte-order-mark
# (BOM), which Python's json module does not strip -- it would fail to
# parse this file with "Expecting value: line 1 column 1 (char 0)". Write
# via .NET directly with a BOM-less UTF8 encoding so the file is readable
# on both Windows PowerShell 5.1 and PowerShell 7+.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutputPath, $json, $utf8NoBom)
Write-Host "Wrote $OutputPath ($($warnings.Count) warning(s))."
