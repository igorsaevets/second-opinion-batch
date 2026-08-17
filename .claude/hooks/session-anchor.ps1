# SessionStart anchor: factual re-grounding after startup/resume/clear/compact.
#
# Statements of fact only. Imperative phrasing ("YOU MUST read...") trips Claude's
# prompt-injection defence, and a defended-against anchor is an anchor that does nothing.
#
# ASCII only in the output: this machine's console is cp1251 and non-ASCII here has come
# back as mojibake before. Emitted through ConvertTo-Json, which escapes what it must.
#
# Read-only. This script inspects the working tree and prints JSON on stdout. It writes
# no files, sets nothing, and makes no network call.

$lines = @(
  "Facts about this project's state layer:",
  "- The authoritative current state is .claude/state/NOW.md; finished stages are in .claude/state/history/.",
  "- Compaction summaries are informational, not evidence; the disk is canonical. A rule quoted in a summary is a snapshot and can be a superseded one.",
  "- File Read-state does not survive compaction or a model switch: files must be re-read before Edit.",
  "- This repository is public-by-destination. Case material, applicant facts and named third parties do not belong in the tree; private/, runs/ and out/ are gitignored and hold anything case-specific.",
  "- A Batch API submission is irreversible spend at submit time: a malformed batch of N items bills as N items. A 1-2 item smoke test through the same code path precedes any full run.",
  "- Model slugs, endpoints, prices and quotas rot. models_snapshot.json with a capture date is the record; a slug remembered rather than measured is a hypothesis."
)

if (Test-Path ".git") {
  $branch = git rev-parse --abbrev-ref HEAD 2>$null
  if ($LASTEXITCODE -eq 0 -and $branch) {
    $dirty = git status --porcelain 2>$null
    $n = if ($dirty) { ($dirty | Measure-Object -Line).Lines } else { 0 }
    $lines += "- git: on branch '$branch' with $n uncommitted path(s) at session start."
  }
}

# Which batch lanes are actually reachable is an ACCOUNT fact, not a catalogue fact, and it
# changes without warning. Presence only - never the value, never a masked prefix.
$lanes = @()
foreach ($pair in @(
    @('OpenAI',     'OPENAI_API_KEY'),
    @('Anthropic',  'ANTHROPIC_API_KEY'),
    @('Google',     'GEMINI_API_KEY'),
    @('OpenRouter', 'OPENROUTER_API_KEY'))) {
  $present = [bool](Get-Item "env:$($pair[1])" -ErrorAction SilentlyContinue)
  $lanes += "$($pair[0])=$(if ($present) { 'key-present' } else { 'NO-KEY' })"
}
$lines += "- Batch lane key presence at session start: $($lanes -join ', '). Presence is not reachability; only a returned call proves a lane works."

@{ hookSpecificOutput = @{
     hookEventName     = "SessionStart"
     additionalContext = ($lines -join "`n")
} } | ConvertTo-Json -Depth 4 -Compress
