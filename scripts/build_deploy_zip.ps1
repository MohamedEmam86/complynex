$source = "C:\Users\Dina\Downloads\ComplyNex_CMS"
$target = "C:\Users\Dina\Downloads\ComplyNex_Deploy_Clean"
$zipPath = "C:\Users\Dina\Downloads\ComplyNex_Release_Version.zip"

if (Test-Path $target) { Remove-Item -Recurse -Force $target }
New-Item -ItemType Directory -Path $target

# Essential Directories
$dirs = @("admin", "aml", "auth", "blacklist", "blueprints", "cobec", "coi", "complaints", "consumer_protection", "cyber", "dashboard", "data", "data_protection", "database", "merchant_kyc", "models", "policies", "portal", "reporting", "screening", "services", "static", "templates", "tracker", "training", "users", "utils", "whistleblowing", "uploads")

foreach ($dir in $dirs) {
    if (Test-Path "$source\$dir") {
        Copy-Item -Path "$source\$dir" -Destination "$target\$dir" -Recurse -Force
    }
}

# Essential Files
$files = @("app.py", "run.py", "config.py", ".env", "requirements.txt", "complynex_cms.db", "start_complynex.bat", "README_Deployment.txt")

foreach ($file in $files) {
    Copy-Item -Path "$source\$file" -Destination "$target\$file" -Force
}

# Clean unwanted cache files
Get-ChildItem -Path $target -Include "__pycache__" -Recurse -Force | Remove-Item -Recurse -Force
Get-ChildItem -Path $target -Include "*.pyc" -Recurse -Force | Remove-Item -Force

# Create Zip
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Set-Location $target
tar.exe -a -c -f $zipPath *
Set-Location $source

Write-Host "Deployment package created successfully at: $zipPath"
