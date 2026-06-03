# Local BGM Library

Place royalty-free ambient music tracks in this folder for automatic BGM selection.
Do not add tracks without source/license metadata. Final-quality renders now warn
when a BGM file is used without provenance.

## File naming convention

Name files with mood tags for automatic matching:
- `calm-ambient-01.mp3` — calm, relaxing
- `upbeat-energy-01.mp3` — energetic, exciting
- `energetic-cut-01.mp3` — fast Shorts/list energy
- `tech-house/minimal-techno-01.mp3` — source-ready support alias for calm/upbeat Shorts
- `corporate-soft-01.mp3` — professional, neutral
- `cinematic-epic-01.mp3` — dramatic, cinematic

## Supported formats

MP3, WAV, M4A, OGG, FLAC

## How it works

The compose pipeline first matches the template/scene mood, then checks
license-ready alias folders before falling back to the whole library. Current
aliases include `calm -> tech-house`, `upbeat/energetic -> tech-house`, and
`tense -> cinematic`. This keeps routine Shorts from getting stuck on one
default bed when the requested mood folder does not yet have enough
source/license metadata.

The final pick uses a deterministic `projectId:templateType` selection key.
This keeps exports repeatable while still rotating across multiple local
candidates instead of silently reusing one default track.

Final quality reports record:

- `candidateCount`
- `selectionMood`
- `selectionMethod`
- `selectionKey`

If the selected mood has fewer than two candidates, or the render lacks this
selection evidence, `bgmAssetRotation` is reported as a warning.

If no tracks are present, BGM is silently skipped.

## Source metadata

For every downloaded BGM file, add one of these sidecars:

- Same-file sidecar: `starter.mp3.json`
- Same-stem sidecar: `starter.json`
- Folder map: `sources.json`

Example:

```json
{
  "starter.mp3": {
    "provider": "youtube-audio-library",
    "title": "Starter",
    "sourceUrl": "https://studio.youtube.com/channel/...",
    "sourceLicense": "YouTube Audio Library - attribution not required",
    "attribution": ""
  }
}
```

Preferred free BGM/SFX sources are YouTube Audio Library, Mixkit, Pixabay
Music, Freesound CC0/CC BY, Wikimedia Commons, KOGL Type 1/public assets, and
Gongu copyright sources. Keep the download page URL and attribution/license
text even when attribution is not required.

## Rotation checklist

For each production mood folder:

- Keep at least two source/license-ready tracks.
- Keep metadata sidecars next to the track or in `sources.json`.
- Avoid repeatedly selecting cafe/coffee beds unless the scene specifically
  calls for that ambience; use varied rhythm, room tone, SFX, and texture beds
  across candidates.
- Use `storage/asset-packets/<projectId>/free-asset-sourcing-worksheet.md` to
  record which BGM source was collected for the current project.
- Re-render after adding tracks so the manifest captures the deterministic
  BGM selection evidence.
