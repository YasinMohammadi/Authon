Set-StrictMode -Version Latest

. "$PSScriptRoot\..\Authon.ps1" -NoGui

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("authon-test-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $root | Out-Null

try {
    $source = Join-Path $root "alice-auth.json"
    $target = Join-Path $root "auth.json"
    '{"token":"alice"}' | Set-Content -LiteralPath $source -Encoding UTF8
    '{"token":"old"}' | Set-Content -LiteralPath $target -Encoding UTF8

    $result = Activate-ProfileAuth -SourcePath $source -TargetPath $target -ProfileName "Alice"
    $targetJson = Get-Content -LiteralPath $target -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($targetJson.token -ne "alice") {
        throw "Expected target auth to contain alice token."
    }
    if (-not (Test-Path -LiteralPath $result["backup_path"])) {
        throw "Expected backup file to exist."
    }

    $bad = Join-Path $root "bad-auth.json"
    "{bad" | Set-Content -LiteralPath $bad -Encoding UTF8
    $threw = $false
    try {
        Activate-ProfileAuth -SourcePath $bad -TargetPath $target -ProfileName "Bad" | Out-Null
    }
    catch {
        $threw = $true
    }
    if (-not $threw) {
        throw "Expected invalid JSON activation to fail."
    }

    if ((Normalize-SwitchTime "9:05") -ne "09:05") {
        throw "Expected time normalization to pad hours."
    }

    "Authon PowerShell tests passed."
}
finally {
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
