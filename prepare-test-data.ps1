# 1. Setup paths
$sourceDir = "./python/tests/.storage"
$tempDir = "./.temp_storage_zip"
$excludeList = @("datasources", "plugins") # Names of folders to skip

# 2. Clean up any old temp data
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
Compress-Archive -Path "$tempDir\*" -DestinationPath "storage.zip" -Force
[Convert]::ToBase64String([IO.File]::ReadAllBytes("storage.zip")) | Out-File -Force -FilePath "secret_string.txt"

# 5. Final cleanup
Remove-Item $tempDir -Recurse -Force

# Post:
# 1. take the secret_string.txt and create a secret in GitHub with the content of that file.
# 2. delete the file.
# 3. add a step in the workflow to decode the secret and unzip it before running tests.
#    echo "${{ secrets.TEST_STORAGE_B64 }}" | base64 --decode > storage.zip
#    unzip -o storage.zip -d /same/path/as/sourceDir || true
