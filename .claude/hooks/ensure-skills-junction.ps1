# SessionStart hook: make .claude\skills a directory junction to .agents\skills.
#
# .agents\skills is the tracked copy of the skills; .claude\skills is git-ignored
# (git would follow the junction and commit every skill twice), so a fresh clone
# has no junction and Claude Code finds no skills. This recreates it.
#
# Idempotent: silent when the junction is already correct. Never deletes or
# replaces anything that exists. Always exits 0 so it can never block a session.
$ErrorActionPreference = 'Stop'

function Notify([string]$msg) { @{ systemMessage = $msg } | ConvertTo-Json -Compress }

try {
    $root = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR }
            else { (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }

    $targetDir = Join-Path $root '.agents\skills'
    if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) { exit 0 }  # nothing to link to
    $target = (Resolve-Path -LiteralPath $targetDir).Path

    $link = Join-Path $root '.claude\skills'
    $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue

    if ($item) {
        $current = [string]($item.Target | Select-Object -First 1)
        $correct = ($item.LinkType -eq 'Junction') -and
                   ($current.TrimEnd('\') -ieq $target.TrimEnd('\'))
        if (-not $correct) {
            Notify ".claude\skills exists but is not a junction to .agents\skills; left unchanged. Remove or fix it by hand."
        }
        exit 0   # correct: stay silent
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $link) | Out-Null
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    Notify "Created junction .claude\skills -> .agents\skills. If no skills are listed, restart the session."
}
catch {
    Notify "ensure-skills-junction failed: $($_.Exception.Message)"
}
exit 0
