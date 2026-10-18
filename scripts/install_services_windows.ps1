$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$InstallDir = "C:\Complynex_Services"
if (-Not (Test-Path -Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
    Write-Host "Created directory $InstallDir"
}

# 1. Download and Extract Redis
$RedisZip = "$InstallDir\Redis.zip"
$RedisDir = "$InstallDir\Redis"
if (-Not (Test-Path -Path $RedisDir)) {
    Write-Host "Downloading Redis for Windows..."
    Invoke-WebRequest -Uri "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip" -OutFile $RedisZip
    Write-Host "Extracting Redis..."
    Expand-Archive -Path $RedisZip -DestinationPath $RedisDir -Force
    Remove-Item $RedisZip
    Write-Host "Redis installed to $RedisDir"
} else {
    Write-Host "Redis is already installed."
}

# 2. Download and Extract Elasticsearch
$ESZip = "$InstallDir\Elasticsearch.zip"
$ESVersion = "8.13.2"
$ESExtractedDir = "$InstallDir\elasticsearch-$ESVersion"
$ESTargetDir = "$InstallDir\Elasticsearch"

if (-Not (Test-Path -Path $ESTargetDir)) {
    Write-Host "Downloading Elasticsearch $ESVersion for Windows..."
    Invoke-WebRequest -Uri "https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-$ESVersion-windows-x86_64.zip" -OutFile $ESZip
    Write-Host "Extracting Elasticsearch (this may take a minute)..."
    Expand-Archive -Path $ESZip -DestinationPath $InstallDir -Force
    Rename-Item -Path $ESExtractedDir -NewName "Elasticsearch"
    Remove-Item $ESZip
    
    # Configure Elasticsearch for local dev without SSL initially to match our dev setup
    $YamlPath = "$ESTargetDir\config\elasticsearch.yml"
    Add-Content -Path $YamlPath -Value "`nxpack.security.enabled: false"
    Add-Content -Path $YamlPath -Value "xpack.security.enrollment.enabled: false"
    Add-Content -Path $YamlPath -Value "ingest.geoip.downloader.enabled: false"
    Write-Host "Elasticsearch configured for local development and installed to $ESTargetDir"
} else {
    Write-Host "Elasticsearch is already installed."
}

Write-Host "`nInstallation Complete."
Write-Host "To start Redis: Run '$RedisDir\redis-server.exe'"
Write-Host "To start Elasticsearch: Run '$ESTargetDir\bin\elasticsearch.bat'"

