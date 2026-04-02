param(
  [Parameter(Mandatory = $true)]
  [string]$TranscriptPath,
  [string]$Culture = "zh-CN",
  [double]$MinConfidence = 0.55
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech

$dir = Split-Path -Parent $TranscriptPath
if ($dir -and -not (Test-Path $dir)) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
if (-not (Test-Path $TranscriptPath)) {
  New-Item -ItemType File -Force -Path $TranscriptPath | Out-Null
}

try {
  $cultureInfo = [System.Globalization.CultureInfo]::GetCultureInfo($Culture)
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine($cultureInfo)
} catch {
  $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
}

$grammar = New-Object System.Speech.Recognition.DictationGrammar
$recognizer.LoadGrammar($grammar)
$recognizer.SetInputToDefaultAudioDevice()

Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognized -Action {
  $result = $Event.SourceEventArgs.Result
  if ($null -eq $result) {
    return
  }
  if ([string]::IsNullOrWhiteSpace($result.Text)) {
    return
  }
  if ($result.Confidence -lt $MinConfidence) {
    return
  }
  Add-Content -Path $TranscriptPath -Value $result.Text -Encoding UTF8
} | Out-Null

$recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

try {
  while ($true) {
    Start-Sleep -Seconds 1
  }
} finally {
  try {
    $recognizer.RecognizeAsyncStop()
  } catch {}
  try {
    $recognizer.Dispose()
  } catch {}
}
