# DOGMA 1.0.59

Fix **Correggi scatti** rejecting valid videos whose duration is not an exact number of milliseconds. Preserve source-clock precision in both MP4 movie and video track headers instead of using the default 1000 Hz movie clock. Applies to the shared NVIDIA and software repair encoder. Strict duration, frame timestamp, fps, color and audio checks are unchanged; no tolerance is loosened and no extra processing pass is added.

Validation: real API output-node execution, corrected-copy export and UI record; 457-frame 24 fps failure case; 24/25/60 and 24000/1001, 30000/1001, 60000/1001 timing cases through both encoders; fractional-fps audio preserved; a deliberate one-frame duration mismatch still rejected; repair disabled, error retention, cancellation and concurrent output naming. No paid generation requests were made. Existing API Platform and standalone workflows remain compatible.
