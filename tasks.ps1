<#
.SYNOPSIS
    Developer commands for Windows (PowerShell 5.1+ / 7+). Same targets as the Makefile.

.EXAMPLE
    .\tasks.ps1 help
    .\tasks.ps1 check
    .\tasks.ps1 smoke

    If scripts are blocked by execution policy, run once per session:
    Set-ExecutionPolicy -Scope Process Bypass
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'venv', 'install', 'lint', 'fmt', 'typecheck', 'test', 'check',
                 'up', 'down', 'logs', 'produce', 'smoke')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Python launcher first (python.org installs), then python on PATH (venv, Store, conda).
# Inside an activated venv, prefer the venv interpreter.
function Get-Python {
    if ($env:VIRTUAL_ENV) { return @('python') }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @('py', '-3') }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @('python') }
    throw 'Python 3.10+ not found. Install it from python.org or the Microsoft Store.'
}

# Run a native command and stop on a non-zero exit code
# ($ErrorActionPreference does not apply to native executables in PowerShell 5.1).
function Invoke-Native {
    param([string[]]$Command)
    $exe = $Command[0]
    $rest = @()
    if ($Command.Length -gt 1) { $rest = $Command[1..($Command.Length - 1)] }
    & $exe @rest
    if ($LASTEXITCODE -ne 0) {
        throw "'$($Command -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Python {
    param([string[]]$Arguments)
    # @() keeps a one-element result an array (PowerShell unrolls it on return).
    Invoke-Native (@(Get-Python) + $Arguments)
}

$help = [ordered]@{
    venv      = 'Create .venv (activate: .\.venv\Scripts\Activate.ps1)'
    install   = 'Install runtime + dev dependencies into the active environment'
    lint      = 'ruff: lint + formatting check'
    fmt       = 'ruff: apply formatting and safe fixes'
    typecheck = 'mypy --strict'
    test      = 'pytest (integration tests need MongoDB and RabbitMQ, else they are skipped)'
    check     = 'Everything CI runs on the code (lint, typecheck, test)'
    up        = 'Build and start the stack, wait until healthy'
    down      = 'Stop the stack and remove its volumes'
    logs      = 'Follow application logs'
    produce   = 'Publish the 4 demo messages (python producer.py)'
    smoke     = 'Reviewer scenario end to end against the running stack'
}

switch ($Task) {
    'help' {
        Write-Host 'Usage: .\tasks.ps1 <task>'
        foreach ($name in $help.Keys) { Write-Host ('  {0,-10} {1}' -f $name, $help[$name]) }
    }
    'venv'      { Invoke-Python @('-m', 'venv', '.venv') }
    'install'   { Invoke-Python @('-m', 'pip', 'install', '-r', 'requirements-dev.txt') }
    'lint' {
        Invoke-Python @('-m', 'ruff', 'check', '.')
        Invoke-Python @('-m', 'ruff', 'format', '--check', '.')
    }
    'fmt' {
        Invoke-Python @('-m', 'ruff', 'format', '.')
        Invoke-Python @('-m', 'ruff', 'check', '--fix', '.')
    }
    'typecheck' { Invoke-Python @('-m', 'mypy') }
    'test'      { Invoke-Python @('-m', 'pytest', '-rs') }
    'check' {
        & $PSCommandPath lint
        & $PSCommandPath typecheck
        & $PSCommandPath test
    }
    'up'      { Invoke-Native @('docker', 'compose', 'up', '--build', '-d', '--wait') }
    'down'    { Invoke-Native @('docker', 'compose', 'down', '-v') }
    'logs'    { Invoke-Native @('docker', 'compose', 'logs', '-f', 'app') }
    'produce' { Invoke-Python @('producer.py') }
    'smoke' {
        & $PSCommandPath up
        Invoke-Python @('scripts/smoke_check.py')
    }
}
