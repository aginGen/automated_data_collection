param([Parameter(ValueFromRemainingArguments=$true)][string[]]$LauncherArgs)
& python (Join-Path $PSScriptRoot 'launch.py') @LauncherArgs
exit $LASTEXITCODE
