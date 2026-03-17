# Local BGM Library

Place royalty-free ambient music tracks in this folder for automatic BGM selection.

## File naming convention

Name files with mood tags for automatic matching:
- `calm-ambient-01.mp3` — calm, relaxing
- `upbeat-energy-01.mp3` — energetic, exciting
- `corporate-soft-01.mp3` — professional, neutral
- `cinematic-epic-01.mp3` — dramatic, cinematic

## Supported formats

MP3, WAV, M4A, OGG, FLAC

## How it works

The compose pipeline picks a track by mood tag matching or random selection,
trims it to the project duration, and mixes it at lower volume under narration.

If no tracks are present, BGM is silently skipped.
