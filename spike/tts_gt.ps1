param([string]$TextFile, [string]$OutWav, [string]$OutJson)
# Synteza mowy z zapisem prawdziwego poczatku kazdego slowa (zdarzenia SpeakProgress).
Add-Type -AssemblyName System.Speech
$text = Get-Content -Raw -Encoding UTF8 $TextFile
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Paulina Desktop')
# 16 kHz mono: przy domyslnych 22,05 kHz AudioPosition jest liczone tak, jakby plik mial 16 kHz.
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($OutWav, $format)
Register-ObjectEvent -InputObject $s -EventName SpeakProgress -SourceIdentifier tts.word | Out-Null
Register-ObjectEvent -InputObject $s -EventName SpeakCompleted -SourceIdentifier tts.done | Out-Null
$s.SpeakAsync($text) | Out-Null
Wait-Event -SourceIdentifier tts.done | Out-Null
$words = @(Get-Event -SourceIdentifier tts.word | ForEach-Object {
  [pscustomobject]@{ w = $_.SourceEventArgs.Text; s = [math]::Round($_.SourceEventArgs.AudioPosition.TotalSeconds, 3) }
})
$s.SetOutputToNull()
$s.Dispose()
$json = $words | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($OutJson, $json, (New-Object System.Text.UTF8Encoding $false))
Write-Output "OK $($words.Count) words"
