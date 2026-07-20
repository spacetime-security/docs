[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return @($output | ForEach-Object { $_.ToString() })
}

function Assert-Exact {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not $Condition) {
        throw "FAIL: $Message"
    }
}

function Normalize-Path {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
}

$repo = Normalize-Path (@(Invoke-Git -Arguments @("rev-parse", "--show-toplevel"))[0])
$gitAtRepo = @("-C", $repo)

$currentBranch = (Invoke-Git -Arguments ($gitAtRepo + @("branch", "--show-current"))) -join "`n"
Assert-Exact ($currentBranch -ceq "main") "current branch must be main (got: $currentBranch)"

$localBranches = @(Invoke-Git -Arguments ($gitAtRepo + @("branch", "--format=%(refname:short)")))
Assert-Exact ($localBranches.Count -eq 1 -and $localBranches[0] -ceq "main") "local branches must be exactly [main]"

$trackingBranches = @(Invoke-Git -Arguments ($gitAtRepo + @("for-each-ref", "--format=%(refname:short)", "refs/remotes")))
Assert-Exact ($trackingBranches.Count -eq 1 -and $trackingBranches[0] -ceq "origin/main") "remote-tracking branches must be exactly [origin/main]"

$worktrees = @(
    Invoke-Git -Arguments ($gitAtRepo + @("-c", "core.quotePath=false", "worktree", "list", "--porcelain")) |
        Where-Object { $_.StartsWith("worktree ", [StringComparison]::Ordinal) } |
        ForEach-Object { Normalize-Path $_.Substring(9) }
)
Assert-Exact ($worktrees.Count -eq 1) "exactly one worktree must exist"
Assert-Exact ($worktrees[0] -ceq $repo) "the sole worktree must be the canonical repository root"

$status = @(Invoke-Git -Arguments ($gitAtRepo + @("status", "--porcelain=v1", "--untracked-files=all")))
Assert-Exact ($status.Count -eq 0) "working tree must be clean"

$mainSha = @(Invoke-Git -Arguments ($gitAtRepo + @("rev-parse", "main")))[0]
$trackingSha = @(Invoke-Git -Arguments ($gitAtRepo + @("rev-parse", "origin/main")))[0]
Assert-Exact ($mainSha -ceq $trackingSha) "main and origin/main must have the same SHA"

$remoteLines = @(Invoke-Git -Arguments ($gitAtRepo + @("ls-remote", "--heads", "origin")))
Assert-Exact ($remoteLines.Count -eq 1) "origin must expose exactly one branch"
$remoteParts = @($remoteLines[0] -split "\s+")
Assert-Exact ($remoteParts.Count -eq 2 -and $remoteParts[1] -ceq "refs/heads/main") "the sole remote branch must be main"
Assert-Exact ($remoteParts[0] -ceq $mainSha) "main, origin/main, and GitHub main must have the same SHA"

$commonGitDir = @(Invoke-Git -Arguments ($gitAtRepo + @("rev-parse", "--git-common-dir")))[0]
if (-not [IO.Path]::IsPathRooted($commonGitDir)) {
    $commonGitDir = Join-Path $repo $commonGitDir
}
$lease = Join-Path (Normalize-Path $commonGitDir) "spacetime-uow.json"
Assert-Exact (-not (Test-Path -LiteralPath $lease)) "no active UOW lease may exist"

Write-Output "PASS: canonical trunk state"
