# DOGMA Nodes 1.0.40 — H3 Director Video Edit

Adds a fourth Director mode for a bounded edit of a long source clip. The editor
offers draggable timeline handles, thumbnails, live seek, zoom and additional
references. H3 Ref2VA generates only the selection at the original canvas size
(temporary padding is cropped), without upscale, RIFE or staged finishing.
The edited selection is composited into a full-length export with original audio.
The source video is re-encoded; it is not a bit-exact stream copy. Native H3 is
24 fps; source timestamps are retained without motion interpolation. Selection
lengths follow the supported frame grid and available reference budget.

Adding test prompts preserves scroll and focuses the new prompt. Existing
Director modes and node IDs remain available. No additional custom-node pack.
Requires FFmpeg on PATH or imageio-ffmpeg, and the existing H3 dependencies.

Validation: nine media/integration tests, 291 timeline constraints, browser
interaction checks. Full H3 GPU inference and visual seam quality remain untested.
Use DOGMA_H3_DIRECTOR_V4.json. Restart ComfyUI and reload the browser after updating.
