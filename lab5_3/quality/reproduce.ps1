param([string]$Python = "python", [string]$Run = (Get-Date -Format "yyyyMMdd_HHmmss"))
# Независимые имена и каталоги позволяют повторять опыт без перезаписи результатов.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$oldHttp = $env:HTTP_PROXY; $oldHttps = $env:HTTPS_PROXY
$env:HTTP_PROXY = ''; $env:HTTPS_PROXY = ''
function Crawl([string]$Spider, [string[]]$Arguments) {
    & $Python -m scrapy crawl $Spider @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Scrapy exit code $LASTEXITCODE" }
}
try {
    $cache = "cache_$Run"
    Crawl 'quotes' @('-a', "run_id=${Run}_cold", '-s', "JOBDIR=jobstate/${Run}_cold", '-s', 'HTTPCACHE_ENABLED=True', '-s', "HTTPCACHE_DIR=$cache", '-s', "DATABASE_PATH=data/${Run}_cold.db", '-O', "data/${Run}_cold.jsonl")
    Crawl 'quotes' @('-a', "run_id=${Run}_warm", '-s', "JOBDIR=jobstate/${Run}_warm", '-s', 'HTTPCACHE_ENABLED=True', '-s', "HTTPCACHE_DIR=$cache", '-s', "DATABASE_PATH=data/${Run}_warm.db", '-O', "data/${Run}_warm.jsonl")
    $job = "jobstate/${Run}_resume"
    Crawl 'quotes' @('-a', "run_id=${Run}_pause", '-s', "JOBDIR=$job", '-s', 'CLOSESPIDER_ITEMCOUNT=20', '-s', 'HTTPCACHE_ENABLED=True', '-s', "HTTPCACHE_DIR=$cache", '-s', "DATABASE_PATH=data/${Run}_resume.db", '-O', "data/${Run}_pause.jsonl")
    Get-ChildItem -Recurse $job | Select-Object FullName,Length | ConvertTo-Json | Set-Content -Encoding UTF8 "data/${Run}_paused_listing.json"
    Crawl 'quotes' @('-a', "run_id=${Run}_resume", '-s', "JOBDIR=$job", '-s', 'CLOSESPIDER_ITEMCOUNT=300', '-s', 'HTTPCACHE_ENABLED=True', '-s', "HTTPCACHE_DIR=$cache", '-s', "DATABASE_PATH=data/${Run}_resume.db", '-O', "data/${Run}_resume.jsonl")
    Crawl 'quotes' @('-a', "run_id=${Run}_30", '-a', 'max_pages=3', '-s', "JOBDIR=jobstate/${Run}_30", '-s', "DATABASE_PATH=data/${Run}_30.db", '-O', "data/${Run}_30.jsonl")
    Copy-Item "data/${Run}_cold.db" "data/${Run}_tags.db"
    Crawl 'tags' @('-a', "run_id=${Run}_tags", '-s', "JOBDIR=jobstate/${Run}_tags", '-s', "DATABASE_PATH=data/${Run}_tags.db", '-O', "data/${Run}_tags.jsonl")
} finally { $env:HTTP_PROXY = $oldHttp; $env:HTTPS_PROXY = $oldHttps }
