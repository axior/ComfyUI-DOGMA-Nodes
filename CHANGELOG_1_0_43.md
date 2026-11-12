DOGMA Nodes 1.0.43

Includes the preview/timing/comparison fixes prepared for 1.0.42.

- Optional user-uploaded B/W video mask, matching the full source. White regenerates, black preserves.
- Source-pixel grow/contract and Gaussian feather, shared by mask preparation and final composition.
- Native H3 masked generation: source-seeded AV latent plus nested noise mask, with Ref2VA conditioning retained. Uses MaskVidExperiments mask geometry; no global model patches.
- Asynchronous CPU overlay video preview, cache invalidation after mask, source, selection or settings changes.
- Edit trials up to 512 px, multiple seeds or prompt variants; final original-size regeneration from the selected trial's saved configuration.
- Original audio retained in final output; trials and mask previews are silent.

Requires current native H3 masking support in ComfyUI and MVEx_MaskToLatentSpace from MaskVidExperiments. This node is present in the user's running ComfyUI.

Validation: real mask processing and export tests, installed MaskVidExperiments CPU temporal/spatial mapping, source/reference/noise-mask wiring with a deterministic H3 stand-in, frozen trial settings, 512x384 trial to 640x480 final, isolated browser tests. No new GPU H3 generation was run.
