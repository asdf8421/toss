param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretDir = Join-Path $projectRoot ".streamlit"
$secretPath = Join-Path $secretDir "secrets.toml"

Write-Host "Groq 토큰은 화면에 표시되지 않으며 이 PC의 프로젝트 폴더에만 저장됩니다."
$secureToken = Read-Host "Groq API token (gsk_...)" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($token) -or -not $token.StartsWith("gsk_")) {
        throw "Groq 토큰 형식이 올바르지 않습니다. 보통 gsk_ 로 시작합니다."
    }
    $escaped = $token.Replace("\", "\\").Replace('"', '\"')
    New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
    $preserved = @()
    if (Test-Path -LiteralPath $secretPath) {
        $preserved = Get-Content -LiteralPath $secretPath | Where-Object {
            $_ -notmatch '^\s*GROQ_API_KEY\s*=' -and $_ -notmatch '^\s*GROQ_MODEL\s*='
        }
    }
    $content = (@($preserved) + @(
        "GROQ_API_KEY = `"$escaped`"",
        'GROQ_MODEL = "openai/gpt-oss-120b"'
    )) -join [Environment]::NewLine
    $content += [Environment]::NewLine
    [IO.File]::WriteAllText($secretPath, $content, [Text.UTF8Encoding]::new($false))
    Write-Host "저장 완료: .streamlit/secrets.toml (Git 제외 대상)"
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $token = $null
    $escaped = $null
}

& (Join-Path $projectRoot "venv\Scripts\python.exe") (Join-Path $projectRoot "verify_setup.py") --groq
exit $LASTEXITCODE
