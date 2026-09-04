# Локальный статический сервер для папки web/ — без Python и Node, только Windows PowerShell.
# Запуск:   powershell -ExecutionPolicy Bypass -File tools\serve.ps1
# Остановка: Ctrl+C в этом окне.

param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

$root = Join-Path (Split-Path -Parent $PSScriptRoot) 'web'
if (-not (Test-Path $root)) {
    Write-Error "Не найдена папка web/ по пути $root"
    exit 1
}

$mime = @{
    '.html' = 'text/html; charset=utf-8'
    '.css'  = 'text/css; charset=utf-8'
    '.js'   = 'application/javascript; charset=utf-8'
    '.json' = 'application/json; charset=utf-8'
    '.svg'  = 'image/svg+xml'
    '.png'  = 'image/png'
    '.jpg'  = 'image/jpeg'
    '.jpeg' = 'image/jpeg'
    '.gif'  = 'image/gif'
    '.ico'  = 'image/x-icon'
    '.woff' = 'font/woff'
    '.woff2'= 'font/woff2'
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()

Write-Host ""
Write-Host "  PurpJob — локальный сервер" -ForegroundColor Magenta
Write-Host "  http://localhost:$Port" -ForegroundColor White
Write-Host "  Папка: $root"
Write-Host "  Остановить: Ctrl+C"
Write-Host ""

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response

        # Путь из URL -> путь на диске, с защитой от выхода за пределы web/
        $relative = [System.Uri]::UnescapeDataString($request.Url.AbsolutePath).TrimStart('/')
        if ([string]::IsNullOrWhiteSpace($relative)) { $relative = 'index.html' }
        $target = Join-Path $root $relative
        if (Test-Path $target -PathType Container) { $target = Join-Path $target 'index.html' }

        $fullRoot = [System.IO.Path]::GetFullPath($root)
        $fullTarget = [System.IO.Path]::GetFullPath($target)

        if ($fullTarget.StartsWith($fullRoot) -and (Test-Path $fullTarget -PathType Leaf)) {
            $ext = [System.IO.Path]::GetExtension($fullTarget).ToLower()
            $type = $mime[$ext]
            if (-not $type) { $type = 'application/octet-stream' }

            $bytes = [System.IO.File]::ReadAllBytes($fullTarget)
            $response.ContentType = $type
            $response.ContentLength64 = $bytes.Length
            $response.OutputStream.Write($bytes, 0, $bytes.Length)
            Write-Host ("200  /{0}" -f $relative)
        }
        else {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes('<meta charset="utf-8"><h1>404</h1><p>Файл не найден.</p>')
            $response.StatusCode = 404
            $response.ContentType = 'text/html; charset=utf-8'
            $response.ContentLength64 = $bytes.Length
            $response.OutputStream.Write($bytes, 0, $bytes.Length)
            Write-Host ("404  /{0}" -f $relative) -ForegroundColor DarkYellow
        }

        $response.OutputStream.Close()
    }
}
finally {
    $listener.Stop()
    $listener.Close()
    Write-Host "Сервер остановлен."
}
