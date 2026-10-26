# Run from the project root. Append only: preserve your existing ignore rules.
$rules = @('data/', 'backups/', 'workspace-export*.json', '*.sqlite3', '*.sqlite3-wal', '*.sqlite3-shm', '.env', '.venv/', '__pycache__/', '.pytest_cache/')
foreach ($rule in $rules) {
    if (!(Test-Path .gitignore) -or !((Get-Content .gitignore) -contains $rule)) {
        Add-Content -Path .gitignore -Value $rule
    }
}
Write-Output 'Private database, exports, backups, and environment files are now ignored.'
