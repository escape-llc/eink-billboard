# 1. Setup paths
$sourceDir = "./python/tests/.storage"
$outDir = "./.ignore"   # git-ignored folder for transient output (the zip and the secret string)
$tempDir = "$outDir/temp_storage_zip"
$zipPath = "$outDir/storage.zip"
$secretPath = "$outDir/secret_string.txt"
$excludeList = @("datasources", "plugins") # Names of folders to skip

# 2. Clean up any old temp data
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir

# 3. Copy files while preserving structure and excluding folders
Get-ChildItem -Path $sourceDir -Recurse | Where-Object {
    $shouldExclude = $false
    foreach ($ex in $excludeList) {
        if ($_.FullName -like "*\$ex\*") { $shouldExclude = $true; break }
    }
    -not $shouldExclude -and -not $_.PSIsContainer
} | ForEach-Object {
    $destFile = $_.FullName.Replace((Get-Item $sourceDir).FullName, $tempDir)
    $destFolder = Split-Path $destFile
    if (-not (Test-Path $destFolder)) { New-Item -ItemType Directory -Path $destFolder -Force }
    Copy-Item $_.FullName -Destination $destFile
}

# 4. Zip the temp folder and encode
#    Note: the root folder is not present in the archive, only subfolders and files.
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -Force
[Convert]::ToBase64String([IO.File]::ReadAllBytes($zipPath)) | Out-File -Force -FilePath $secretPath

# 5. Final cleanup
Remove-Item $tempDir -Recurse -Force

# Post:
# 1. take .ignore/secret_string.txt and create a secret in GitHub with the content of that file.
# 2. delete .ignore/storage.zip and .ignore/secret_string.txt (they hold the storage, including any API keys).
# 3. add a step in the workflow to decode the secret and unzip it before running tests.
#    echo "${{ secrets.TEST_STORAGE_B64 }}" | base64 --decode > storage.zip
#    unzip -o storage.zip -d /same/path/as/sourceDir || true
