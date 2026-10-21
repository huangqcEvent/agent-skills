<#
.SYNOPSIS
  Install or update PingCode MCP with credentials supplied outside the repository.
.DESCRIPTION
  Fetches a pinned upstream revision, applies an enhancement patch, builds the MCP,
  refreshes enterprise authentication, and registers it with Codex and Claude Code.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -DryRun
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Me "Your Name" -Project "PROJ"
#>
param(
  [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'pingcode-mcp'),
  [string]$RepoUrl = 'https://github.com/DennisCeltic/pingcode-mcp.git',
  [string]$Ref = '8a4f24e9e53cf7b5298ad9f513b19706599654b5',
  [string]$Me = '',
  [string]$Project = '',
  [string]$BaseUrl = '',
  [string]$CredentialsFile = '',
  [switch]$AuthOnly,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PatchFile = Join-Path $SkillRoot 'assets\upstream-fixes.patch'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Step([string]$Text) {
  Write-Host ''
  Write-Host "== $Text"
}

function Invoke-External([scriptblock]$Command) {
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & $Command } finally { $ErrorActionPreference = $previous }
}

function Resolve-Credentials {
  $source = ''
  $value = $null
  if (-not [string]::IsNullOrWhiteSpace($env:PINGCODE_CLIENT_ID) -or
      -not [string]::IsNullOrWhiteSpace($env:PINGCODE_CLIENT_SECRET)) {
    if ([string]::IsNullOrWhiteSpace($env:PINGCODE_CLIENT_ID) -or
        [string]::IsNullOrWhiteSpace($env:PINGCODE_CLIENT_SECRET)) {
      throw 'PINGCODE_CLIENT_ID 和 PINGCODE_CLIENT_SECRET 必须同时设置'
    }
    $value = [pscustomobject]@{
      baseUrl = $(if ($env:PINGCODE_BASE_URL) { $env:PINGCODE_BASE_URL } else { 'https://open.pingcode.com' })
      clientId = $env:PINGCODE_CLIENT_ID
      clientSecret = $env:PINGCODE_CLIENT_SECRET
    }
    $source = 'environment'
  } elseif (-not [string]::IsNullOrWhiteSpace($CredentialsFile)) {
    $path = [System.IO.Path]::GetFullPath($CredentialsFile)
    if (-not (Test-Path -LiteralPath $path)) { throw "凭据文件不存在：$path" }
    $value = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $source = $path
  }
  if ($null -eq $value) { return [pscustomobject]@{ value = $null; source = 'missing' } }
  if ([string]::IsNullOrWhiteSpace([string]$value.clientId) -or
      [string]::IsNullOrWhiteSpace([string]$value.clientSecret)) {
    throw '凭据不完整：需要 clientId 和 clientSecret'
  }
  if ([string]::IsNullOrWhiteSpace([string]$value.baseUrl)) {
    $value | Add-Member -NotePropertyName baseUrl -NotePropertyValue 'https://open.pingcode.com' -Force
  }
  if ($BaseUrl) { $value.baseUrl = $BaseUrl }
  elseif ($env:PINGCODE_BASE_URL) { $value.baseUrl = $env:PINGCODE_BASE_URL }
  return [pscustomobject]@{ value = $value; source = $source }
}

function ConvertTo-TomlString([string]$Value) {
  if ($Value.Contains("'")) { return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"' }
  return "'$Value'"
}

Write-Step '检查运行环境'
foreach ($cmd in 'node', 'npm', 'git') {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    throw "缺少 $cmd，请先安装并加入 PATH（Node 需要 >= 18）"
  }
}
$nodeExe = (Get-Command node).Source
$nodeVersion = ((Invoke-External { node -v }) | Out-String).Trim()
if ([int]($nodeVersion.TrimStart('v').Split('.')[0]) -lt 18) {
  throw "Node 版本过低（$nodeVersion），需要 >= 18"
}
if (-not (Test-Path -LiteralPath $PatchFile)) {
  throw "找不到补丁文件：$PatchFile"
}

$credentials = Resolve-Credentials
if ($DryRun) {
  Write-Step 'Dry run：不会拉取、构建、写认证或注册客户端'
  Write-Host "  InstallDir: $InstallDir"
  Write-Host "  RepoUrl:    $RepoUrl"
  Write-Host "  Ref:        $Ref"
  Write-Host "  Me:         $(if ($Me) { $Me } else { '<unset>' })"
  Write-Host "  Project:    $(if ($Project) { $Project } else { '<unset>' })"
  Write-Host "  BaseUrl:    $(if ($credentials.value) { $credentials.value.baseUrl } else { '<missing credentials>' })"
  Write-Host "  Credential: $($credentials.source)"
  exit 0
}
if (-not $credentials.value) {
  throw '缺少 PingCode 凭据：设置 PINGCODE_CLIENT_ID / PINGCODE_CLIENT_SECRET，或传入 -CredentialsFile'
}

if (-not $AuthOnly) {
  Write-Step "准备 MCP 源码：$InstallDir"
  if (Test-Path -LiteralPath $InstallDir) {
    $items = @(Get-ChildItem -LiteralPath $InstallDir -Force)
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir '.git')) -and $items.Count -gt 0) {
      throw "安装目录已存在且不是 Git 仓库：$InstallDir；请换一个 -InstallDir"
    }
  }
  New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  if (-not (Test-Path -LiteralPath (Join-Path $InstallDir '.git'))) {
    Invoke-External { git -C $InstallDir init -q }
    Invoke-External { git -C $InstallDir config core.autocrlf false }
    Invoke-External { git -C $InstallDir remote add origin $RepoUrl }
  } else {
    $origin = ((Invoke-External { git -C $InstallDir remote get-url origin }) | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
      Invoke-External { git -C $InstallDir remote add origin $RepoUrl }
    } elseif ($origin -ne $RepoUrl) {
      throw "现有仓库 origin 为 $origin，与 -RepoUrl $RepoUrl 不一致"
    }
  }
  Invoke-External { git -C $InstallDir -c core.autocrlf=false fetch -q --depth 1 origin $Ref }
  if ($LASTEXITCODE -ne 0) {
    Invoke-External { git -C $InstallDir cat-file -e "$Ref^{commit}" 2>$null }
    if ($LASTEXITCODE -ne 0) { throw '拉取上游失败；检查网络、镜像地址或锁定提交' }
    Write-Host '  网络拉取失败，使用本地已有的锁定提交'
    $target = $Ref
  } else {
    $target = 'FETCH_HEAD'
  }
  Invoke-External { git -C $InstallDir -c core.autocrlf=false reset -q --hard $target }
  if ($LASTEXITCODE -ne 0) { throw 'git reset --hard 失败；先关闭占用安装目录的客户端' }
  Invoke-External { git -C $InstallDir clean -fdq -- src scripts }

  Push-Location $InstallDir
  try {
    Write-Step '应用增强补丁'
    $applyPatch = $PatchFile
    $patchText = [System.IO.File]::ReadAllText($PatchFile, $Utf8NoBom)
    if ($patchText.Contains("`r`n")) {
      $applyPatch = Join-Path $env:TEMP 'pingcode-upstream-fixes.lf.patch'
      [System.IO.File]::WriteAllText($applyPatch, ($patchText -replace "`r`n", "`n"), $Utf8NoBom)
    }
    foreach ($relative in ([regex]::Matches($patchText, '(?m)^diff --git a/(.+?) b/') | ForEach-Object { $_.Groups[1].Value })) {
      $file = Join-Path $InstallDir ($relative -replace '/', '\')
      if (-not (Test-Path -LiteralPath $file)) { continue }
      $bytes = [System.IO.File]::ReadAllBytes($file)
      if ($bytes -contains 13) {
        [System.IO.File]::WriteAllText($file, ([System.IO.File]::ReadAllText($file) -replace "`r`n", "`n"), $Utf8NoBom)
      }
    }
    Invoke-External { git -c core.autocrlf=false apply $applyPatch }
    if ($applyPatch -ne $PatchFile) { Remove-Item -LiteralPath $applyPatch -ErrorAction SilentlyContinue }
    if ($LASTEXITCODE -ne 0) { throw 'git apply 失败：补丁与锁定提交不匹配' }

    Write-Step '安装依赖并构建'
    Invoke-External { npm install --no-audit --no-fund }
    if ($LASTEXITCODE -ne 0) { throw 'npm install 失败' }
    Invoke-External { npm run build }
    if ($LASTEXITCODE -ne 0) { throw 'npm run build 失败' }
  } finally {
    Pop-Location
  }
}

$indexJs = Join-Path $InstallDir 'dist\index.js'
if (-not (Test-Path -LiteralPath $indexJs)) {
  throw "找不到构建产物：$indexJs；去掉 -AuthOnly 完整运行一次"
}

Write-Step '刷新 PingCode 认证'
$creds = $credentials.value
$AuthDir = Join-Path $env:USERPROFILE '.pingcode-mcp'
$AuthFile = Join-Path $AuthDir 'auth.json'
$SettingsFile = Join-Path $AuthDir 'settings.json'
New-Item -ItemType Directory -Path $AuthDir -Force | Out-Null

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tokenUrl = '{0}/v1/auth/token?grant_type=client_credentials&client_id={1}&client_secret={2}' -f `
  ([string]$creds.baseUrl).TrimEnd('/'),
  [uri]::EscapeDataString([string]$creds.clientId),
  [uri]::EscapeDataString([string]$creds.clientSecret)
try {
  $response = Invoke-RestMethod -Uri $tokenUrl -Method Get -Headers @{ Accept = 'application/json' } -TimeoutSec 60
} catch {
  throw "换取企业令牌失败：$($_.Exception.Message)"
}
if (-not $response.access_token) { throw '接口未返回 access_token' }

$nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$rawExpiresIn = 2592000
if ($null -ne $response.expires_in) { $rawExpiresIn = [double]$response.expires_in }
if ($rawExpiresIn -gt 1000000000) {
  $expiresAt = [int64]$rawExpiresIn * 1000
  $expiresIn = [int64][math]::Max(0, [math]::Floor(($expiresAt - $nowMs) / 1000))
} else {
  $expiresIn = [int64][math]::Floor($rawExpiresIn)
  $expiresAt = $nowMs + $expiresIn * 1000
}
$state = [ordered]@{
  config = [ordered]@{
    baseUrl = ([string]$creds.baseUrl).TrimEnd('/')
    tokenType = 'enterprise'
    isPrivate = $false
  }
  enterprise = [ordered]@{
    clientId = [string]$creds.clientId
    clientSecret = [string]$creds.clientSecret
  }
  tokens = [ordered]@{
    accessToken = [string]$response.access_token
    refreshToken = [string]$response.refresh_token
    expiresIn = $expiresIn
    expiresAt = $expiresAt
  }
}
[System.IO.File]::WriteAllText($AuthFile, ($state | ConvertTo-Json -Depth 5), $Utf8NoBom)
$validUntil = [DateTimeOffset]::FromUnixTimeMilliseconds($expiresAt).LocalDateTime.ToString('yyyy-MM-dd HH:mm')
Write-Host "  认证已写入 $AuthFile（令牌至 $validUntil）"

Write-Step '保存用户级设置'
$settings = [ordered]@{}
if (Test-Path -LiteralPath $SettingsFile) {
  $existing = Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($property in $existing.PSObject.Properties) { $settings[$property.Name] = $property.Value }
}
if ($Me) { $settings['me'] = $Me }
if ($Project) { $settings['default_project'] = $Project }
[System.IO.File]::WriteAllText($SettingsFile, ($settings | ConvertTo-Json -Depth 3), $Utf8NoBom)
if ($settings['me']) {
  Write-Host "  当前用户：$($settings['me'])，默认项目：$(if ($settings['default_project']) { $settings['default_project'] } else { '<全部>' })"
} else {
  Write-Host '  未设置当前用户；下次运行时传 -Me "<PingCode 显示名>"'
}

Write-Step '注册到 Codex'
$CodexDir = Join-Path $env:USERPROFILE '.codex'
$CodexConfig = Join-Path $CodexDir 'config.toml'
New-Item -ItemType Directory -Path $CodexDir -Force | Out-Null
$existingConfig = ''
if (Test-Path -LiteralPath $CodexConfig) {
  $existingConfig = [System.IO.File]::ReadAllText($CodexConfig, [System.Text.Encoding]::UTF8)
}
if ($existingConfig -match '(?m)^\s*\[mcp_servers\.pingcode\]') {
  if ($existingConfig.Contains($indexJs)) {
    Write-Host '  已注册且路径一致'
  } else {
    Write-Host '  检测到已有 [mcp_servers.pingcode]，但路径不同；请手动清理旧配置块后重跑'
  }
} else {
  $block = @(
    '# PingCode MCP (registered by setup.ps1)',
    '[mcp_servers.pingcode]',
    ('command = ' + (ConvertTo-TomlString $nodeExe)),
    ('args = [' + (ConvertTo-TomlString $indexJs) + ']')
  ) -join "`n"
  $newConfig = $existingConfig
  if ($newConfig.Length -gt 0) {
    if (-not $newConfig.EndsWith("`n")) { $newConfig += "`n" }
    $newConfig += "`n"
  }
  [System.IO.File]::WriteAllText($CodexConfig, $newConfig + $block + "`n", $Utf8NoBom)
  Write-Host "  已写入 $CodexConfig"
}

Write-Step '注册到 Claude Code（如已安装）'
if (Get-Command claude -ErrorAction SilentlyContinue) {
  Invoke-External { claude mcp remove pingcode --scope user 2>$null | Out-Null }
  Invoke-External { claude mcp add --scope user pingcode -- $nodeExe $indexJs }
  if ($LASTEXITCODE -eq 0) {
    Write-Host '  已注册'
  } else {
    Write-Host "  注册失败；手动执行：claude mcp add --scope user pingcode -- `"$nodeExe`" `"$indexJs`""
  }
} else {
  Write-Host '  未检测到 claude 命令，跳过'
}

Write-Step '状态检查'
Push-Location $InstallDir
try {
  Invoke-External { node dist\cli.js status }
  if ($LASTEXITCODE -ne 0) { throw 'MCP 状态检查失败' }
} finally {
  Pop-Location
}

Write-Host ''
Write-Host 'PingCode MCP 安装完成。重启 Codex / Claude Code 后即可使用 pingcode__* 工具。'
