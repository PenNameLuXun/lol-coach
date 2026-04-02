param(
  [string]$TranscriptPath = "",
  [string]$Culture = "zh-CN",
  [double]$MinConfidence = 0.55,
  [ValidateSet("file", "stdout")]
  [string]$OutputMode = "file"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech

function Write-Diagnostic {
  param([string]$Message)
  if ($env:LOL_COACH_DEBUG_STT -notin @("1", "true", "True", "yes", "on")) {
    return
  }
  [Console]::Error.WriteLine($Message)
}

if ($OutputMode -eq "file") {
  if ([string]::IsNullOrWhiteSpace($TranscriptPath)) {
    throw "TranscriptPath is required when OutputMode=file"
  }
  $dir = Split-Path -Parent $TranscriptPath
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  if (-not (Test-Path $TranscriptPath)) {
    New-Item -ItemType File -Force -Path $TranscriptPath | Out-Null
  }
}

try {
  $cultureInfo = [System.Globalization.CultureInfo]::GetCultureInfo($Culture)
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($cultureInfo)
  $effectiveCulture = $cultureInfo.Name
} catch {
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
  $effectiveCulture = "default"
}

$grammar = New-Object System.Speech.Recognition.DictationGrammar
$recognizer.LoadGrammar($grammar)
$recognizer.SetInputToDefaultAudioDevice()
Write-Diagnostic "[WinSTT] ready culture=$effectiveCulture output=$OutputMode confidence=$MinConfidence"

$sourceId = "LOLCoachSpeechRecognized"
$detectedSourceId = "LOLCoachSpeechDetected"
$rejectedSourceId = "LOLCoachSpeechRejected"

Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognized -SourceIdentifier $sourceId | Out-Null
Register-ObjectEvent -InputObject $recognizer -EventName SpeechDetected -SourceIdentifier $detectedSourceId | Out-Null
Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognitionRejected -SourceIdentifier $rejectedSourceId | Out-Null

$recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

try {
  while ($true) {
    $evt = Wait-Event -Timeout 1
    if ($null -eq $evt) {
      continue
    }
    try {
      if ($evt.SourceIdentifier -eq $detectedSourceId) {
        Write-Diagnostic "[WinSTT] speech detected"
        continue
      }
      if ($evt.SourceIdentifier -eq $rejectedSourceId) {
        $rejected = $evt.SourceEventArgs.Result
        if ($null -ne $rejected) {
          Write-Diagnostic "[WinSTT] rejected text=$($rejected.Text) confidence=$($rejected.Confidence)"
        } else {
          Write-Diagnostic "[WinSTT] rejected"
        }
        continue
      }
      if ($evt.SourceIdentifier -ne $sourceId) {
        continue
      }
      $result = $evt.SourceEventArgs.Result
      if ($null -eq $result) {
        continue
      }
      if ([string]::IsNullOrWhiteSpace($result.Text)) {
        continue
      }
      if ($result.Confidence -lt $MinConfidence) {
        Write-Diagnostic "[WinSTT] below threshold text=$($result.Text) confidence=$($result.Confidence)"
        continue
      }
      if ($OutputMode -eq "stdout") {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Write-Output $result.Text
        continue
      }
      Add-Content -Path $TranscriptPath -Value $result.Text -Encoding UTF8
    } finally {
      Remove-Event -EventIdentifier $evt.EventIdentifier -ErrorAction SilentlyContinue
    }
  }
} finally {
  try {
    Unregister-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
  } catch {}
  try {
    Unregister-Event -SourceIdentifier $detectedSourceId -ErrorAction SilentlyContinue
  } catch {}
  try {
    Unregister-Event -SourceIdentifier $rejectedSourceId -ErrorAction SilentlyContinue
  } catch {}
  try {
    $recognizer.RecognizeAsyncStop()
  } catch {}
  try {
    $recognizer.Dispose()
  } catch {}
}
