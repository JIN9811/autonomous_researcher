param(
    [int]$Port = 8765,
    [string]$RemoteAddress = ""
)

$ErrorActionPreference = "Stop"
$ruleName = "Autonomous Researcher PyAutoGUI Bridge"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session."
}

$params = @{
    DisplayName = $ruleName
    Direction = "Inbound"
    Action = "Allow"
    Protocol = "TCP"
    LocalPort = $Port
    Profile = "Private"
}

if ($RemoteAddress) {
    $params.RemoteAddress = $RemoteAddress
}

New-NetFirewallRule @params
Write-Host "Created firewall rule: $ruleName"
Write-Host "Port: $Port"
if ($RemoteAddress) {
    Write-Host "RemoteAddress: $RemoteAddress"
} else {
    Write-Host "RemoteAddress: any private-profile host"
}
