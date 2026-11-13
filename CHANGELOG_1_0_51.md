DOGMA Nodes 1.0.51

- Integrate HDR finishing into the existing comfyui-dogma-nodes Manager package. No separate node pack, installer, Torch/CUDA update or model download.
- Add DOGMAHDRColorChunkedV1 for per-frame SDR-to-ACEScct conversion using the native Comfy colour transform and fp32 intermediates.
- Add DOGMAHDRSaveStreamingV1: consume raw decoded ACEScct one frame at a time, restore source proportions in UHD, save ACEScg RGB HALF EXRs with ZIP16 and AP1/D60 chromaticities, and optionally write ProRes 4444 HLG with original PCM24 audio. Preserve original frame count and rational frame rate; omit only LTX temporal padding. Return paths rather than additional complete IMAGE batches. Unique output folders, completion manifest and atomic final MOV name.
- Add DOGMAHDRCheckpointV1 before decode; its lazy recovery branch loads a saved latent without running the samplers again. Recovery requires the same source video and compatible VAE.
- Preserve previous node IDs, modules, frontend and H3 workflows. HDR registration is optional on older Comfy versions: failure to import the new HDR module does not remove existing DOGMA nodes. HDR requires ComfyUI >=0.45.0; no new declared runtime dependency.
- Updated HDR workflow keeps the existing BF16 model, HDR LoRA and scene embedding, fp32 VAE, tile settings and two-stage 8+3 sampling.

Validation: graph consistency, native colour equivalence, actual HALF EXR round-trip including negative/extended values, ACES metadata, actual ProRes HLG and PCM24 audio, exact rational timestamps, trim/padding, latent save/recovery, unique folders and output boundaries. The unchanged finishing function was additionally exercised on a synthetic shared-frame UHD 144-frame/6-second export, with 0.43 GiB additional peak process RAM. This measurement isolates finishing and is not a full LTX inference/decode or a SimplePod run. Live Comfy installations were not modified.
