DOGMA Nodes 1.0.52

- Clear HDR V4 front panel: choose final resolution, input colour encoding, linear EXR master primaries, optional MOV transfer, seed and output prefix in one visible settings node.
- Original resolution is a genuine single-stage native-resolution path: canvas follows source dimensions aligned to LTX's grid, final export restores the exact original dimensions. A lazy selector skips the latent upsampler, stage-2 guide/sampler and associated model branches. It does not run a 4K render then downscale the result.
- Optional 4K retains the existing full-HD stage 1, latent x2 upscale, three-step stage 2 and UHD fitting/letterboxing.
- Input choices distinguish SDR sRGB, Rec.709 gamma 2.4, linear Rec.709/ACEScg, ACEScct, Rec.709-primaries LogC3, BT.2020 HLG/PQ. Internal model encoding is always ACEScct and is no longer presented as an output colour selector.
- EXR master: linear ACEScg AP1/D60 (default) or linear Rec.709 D65, always RGB HALF with matching chromaticities and ZIP16. MOV: BT.2020 HLG (default), BT.2020 PQ, or disabled; both movie transfers use ProRes 4444 with 10-bit 4:4:4 encoder input and original PCM24 audio.
- Keep generation and delivery producers separate inside the visible settings group. Changing only EXR primaries, MOV transfer or output prefix reuses the model branch through Comfy's normal cache when available, rather than invalidating it through a combined settings object. The summary uses the actual delivery choices.
- Existing 1.0.51 node IDs remain available. Their export helper retains the prior default resolution, colour, filenames and signature; new keyword-only colour/delivery controls are optional. No changes to H3 workflows, Torch/CUDA, model files, or declared runtime dependencies.
- Same Manager package and JSON for Windows and Linux. No separate node pack or one-off installer. Automatic pre-decode checkpoint is retained inside the processing group; no manual resume path appears in the main panel.

Validation uses native Comfy schemas/loader, complete previous package registration, both lazy-resolution branches, graph endpoints and the backend canvas/guide wiring, original/4K geometry, actual HALF EXR colour/metadata and HLG/PQ MOV headers/timestamps/audio. Model inference on a remote pod is not part of the local verification.
