# Narrated demonstration

`output/demo.mp4` is the primary recording. `output/demo.webm` contains the same narrated walkthrough for compatibility with the original link. Both show the real application and real API responses in an isolated temporary database.

The recording follows the speech, with actions placed alongside the relevant explanation. There is no minimum-duration padding, no artificial API delay, and no simulated loading sequence. Short staggered transitions belong to the application itself and respect reduced-motion preferences. Chapter labels and a cursor indicator are recording-only annotations.

The walkthrough covers a request, a budget correction, untrusted reviews, exact approval, timeout-after-success reconciliation, repeated confirmation and reload, separately approved cancellation with bounded retry, and saving, correcting and forgetting memory.

## Reproduce

Optional authoring dependencies (not application dependencies): installed Chrome, Playwright, edge-tts, and imageio-ffmpeg.

```sh
python -m pip install playwright edge-tts imageio-ffmpeg
python -m playwright install ffmpeg
python tests/prepare_narration.py
python tests/record_demo.py --dry-run
python tests/record_demo.py
```

`docs/narration.json` contains the complete narration. The synthetic voice is Microsoft Edge's `en-US-AndrewMultilingualNeural`; generating it requires network access. Cached audio and raw recordings remain under ignored `output/narration/` and `output/recordings/`. The recorder measures each generated audio file and uses those durations, rather than a target video length. FFmpeg encodes the final H.264/AAC MP4 and VP8/Opus WebM. Browser capture is 25 fps.

The video is local. Publishing to Loom or YouTube is a separate action.
