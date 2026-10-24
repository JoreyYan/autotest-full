param(
  [string]$Root = "D:\code\autotest"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

Write-Host "[1/6] Build frontend dist..."
Push-Location "$Root\frontend"
npm run build
Pop-Location

Write-Host "[2/6] Ensure PyInstaller..."
python -m pip install --upgrade pyinstaller

Write-Host "[3/6] Build backend exe..."
python -m PyInstaller --noconfirm --clean --onefile --name smarton-backend "$Root\run_backend.py"

Write-Host "[4/6] Build launcher exe..."
python -m PyInstaller --noconfirm --clean --onefile --name smarton-launcher "$Root\launcher.py"

$release = "$Root\release\smarton-test-system"
Write-Host "[5/6] Assemble release folder: $release"
if (Test-Path $release) { Remove-Item -Recurse -Force $release }
New-Item -ItemType Directory -Force -Path $release | Out-Null
New-Item -ItemType Directory -Force -Path "$release\frontend" | Out-Null
New-Item -ItemType Directory -Force -Path "$release\products" | Out-Null
New-Item -ItemType Directory -Force -Path "$release\results" | Out-Null

Copy-Item "$Root\dist\smarton-backend.exe" "$release\smarton-backend.exe" -Force
Copy-Item "$Root\dist\smarton-launcher.exe" "$release\smarton-launcher.exe" -Force
Copy-Item "$Root\config.json" "$release\config.json" -Force
Copy-Item "$Root\frontend\dist" "$release\frontend\dist" -Recurse -Force
Copy-Item "$Root\products\*.json" "$release\products" -Force

# sync to release ROOT: publish_release.py packages from release/ root.
# missing this sync caused the v1.6.0 bad-package incident (old exe published as new).
Copy-Item "$Root\dist\smarton-backend.exe" "$Root\release\smarton-backend.exe" -Force
Copy-Item "$Root\dist\smarton-launcher.exe" "$Root\release\smarton.exe" -Force
if (Test-Path "$Root\release\frontend\dist") { Remove-Item -Recurse -Force "$Root\release\frontend\dist" }
New-Item -ItemType Directory -Force -Path "$Root\release\frontend" | Out-Null
Copy-Item "$Root\frontend\dist" "$Root\release\frontend\dist" -Recurse -Force
Copy-Item "$Root\CHANGELOG.md" "$Root\release\CHANGELOG.md" -Force

Set-Content "$release\README.txt" -Encoding utf8 -Value @(
  "run smarton-launcher.exe to start.",
  "check COM port and config.json before first run."
)

Write-Host "[6/6] Done."
Write-Host "Release path: $release"
