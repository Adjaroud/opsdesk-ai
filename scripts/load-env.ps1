# Literal, allow-listed .env loader. No evaluation, output, interpolation or network.
# Existing process environment wins so provider/model overrides remain explicit.
$opsEnvFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
$opsEnvAllowed = @('OPSDESK_LLM_PROVIDER', 'OPSDESK_LLM_MODEL', 'OPSDESK_LLM_TIMEOUT_SECONDS', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'OPSDESK_DB', 'OPSDESK_API_URL')
if (Test-Path -LiteralPath $opsEnvFile) {
    foreach ($opsEnvLine in Get-Content -LiteralPath $opsEnvFile -Encoding UTF8) {
        if ($opsEnvLine -match '^\s*([A-Z_]+)\s*=(.*)$') {
            $opsEnvName = $Matches[1]
            $opsEnvValue = $Matches[2].Trim()
            if ($opsEnvValue.Length -ge 2 -and (($opsEnvValue.StartsWith('"') -and $opsEnvValue.EndsWith('"')) -or ($opsEnvValue.StartsWith("'") -and $opsEnvValue.EndsWith("'")))) {
                $opsEnvValue = $opsEnvValue.Substring(1, $opsEnvValue.Length - 2)
            }
            if ($opsEnvName -in $opsEnvAllowed -and [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($opsEnvName, 'Process'))) {
                [Environment]::SetEnvironmentVariable($opsEnvName, $opsEnvValue, 'Process')
            }
        }
    }
}
# Do not leave a duplicate secret in PowerShell variables after dot-sourcing.
Remove-Variable opsEnvLine, opsEnvValue, opsEnvName, opsEnvAllowed, opsEnvFile, Matches -ErrorAction SilentlyContinue
