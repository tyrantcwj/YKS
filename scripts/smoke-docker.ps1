param(
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

function Read-DotEnvValue {
    param(
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath ".env")) {
        return ""
    }

    $line = Get-Content -LiteralPath ".env" |
        Where-Object { $_ -match "^\s*$Name\s*=" } |
        Select-Object -Last 1

    if (-not $line) {
        return ""
    }

    return ($line -replace "^\s*$Name\s*=\s*", "").Trim().Trim('"').Trim("'")
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found on PATH. Install Docker Desktop or Docker Engine first."
}

Write-Host "Building and starting pokemon-price-watch..."
docker compose up --build -d

try {
    $healthUrl = "http://127.0.0.1:8000/healthz"
    $homeUrl = "http://127.0.0.1:8000/"
    $deadline = (Get-Date).AddSeconds(90)
    $healthy = $false

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 $healthUrl
            if ($response.StatusCode -eq 200 -and $response.Content -match '"ok"\s*:\s*true') {
                $healthy = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 3
        }
    }

    if (-not $healthy) {
        docker compose logs --tail=100
        throw "Health check did not pass within 90 seconds."
    }

    $authPassword = Read-DotEnvValue "AUTH_PASSWORD"
    $authUsername = Read-DotEnvValue "AUTH_USERNAME"
    if ([string]::IsNullOrWhiteSpace($authUsername)) {
        $authUsername = "admin"
    }

    if ([string]::IsNullOrWhiteSpace($authPassword)) {
        $home = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 $homeUrl
        if ($home.StatusCode -ne 200 -or $home.Content -notmatch "Card ID") {
            throw "Home page did not render the subscription form."
        }
    } else {
        try {
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 $homeUrl | Out-Null
            throw "Home page was reachable without credentials even though AUTH_PASSWORD is set."
        } catch {
            if ([int]$_.Exception.Response.StatusCode -ne 401) {
                throw
            }
        }

        $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${authUsername}:${authPassword}"))
        $home = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Headers @{ Authorization = "Basic $token" } $homeUrl
        if ($home.StatusCode -ne 200 -or $home.Content -notmatch "Card ID") {
            throw "Authenticated home page did not render the subscription form."
        }
    }

    Write-Host "Docker smoke test passed."
} finally {
    if (-not $KeepRunning) {
        Write-Host "Stopping compose services..."
        docker compose down
    }
}
