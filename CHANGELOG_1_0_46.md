DOGMA Nodes 1.0.46

- Explicit original-size edit sampling: match selected trial (default), Turbo Ref2Video 4-step, or standard without Turbo with a chosen step count. Existing saved trials are supported.
- Final mode reaches both the normal finish action and immediate promotion during an active trial batch, while source/prompt/seed/references/mask stay frozen to the chosen trial.
- Save complete effective sampling settings with new trials and recover the known Turbo preset for 1.0.45 trial records.
- Validate the native joint AV edit mask before sampling: grid shape, finite range, nonempty video edit area and zero audio mask. Record the sampled mask coverage in the output metadata.
- Preserve an existing video mask when audio locking is requested. This fixes a fragile generic sampler branch; current edit calls already keep audio locking off and use the native audio mask.
- Show each saved final's originating trial, seed and sampling mode; distinguish historical outputs while a new final is still running.
- Develop the approved edit using its saved generated AV latents, a learned latent upscale and partial denoise under the original native edit mask. Older trials explicitly encode their approved video; missing new checkpoints stop without falling back to the source.
- Use the approved trial as Video 1 in guided development, at its existing reference resolution, instead of reintroducing the source wall or inflating reference tokens.
- Default to preserve mode: resize the approved edited video inside its saved mask without new inference or applying feather/fades twice. Keep H3 development and source-based regeneration as explicit options.
- Save new trial checkpoints and file fingerprints. Retain full prompt/seed/source/reference/mask provenance on each final.
- Always copy completed edit finals to the selected destination (the Comfy output root when empty). Show the path and allow opening the folder or copying a completed final elsewhere without regenerating it.
- Commit manually typed folder paths in one confirmation and propagate the latest destination when promoting a trial during an active batch.
- Include edit results in the open-folder lookup; update displayed paths when an existing final is copied.

Validation: native mask/export regressions, explicit final-mode switching, method/destination propagation during active-batch promotion, production sample() handoff with audio locking off/on and missing-mask rejection, isolated browser Standard and preserve finals and copy controls. A real 1664x1248 H3 Turbo 4-step guided render from the user's legacy approved trial completed; the native mask was present. Both preserve and guided exports retain all 97 source timestamps and unchanged audio packets. GPU guided development took 213.7 seconds in the isolated verification, including preparation and export. The guided result still introduced wall artifacts: it is optional, not the default. CPU neural stand-ins were used for the wider regression matrix; Standard sampling was not separately rerun on the real GPU.

Guided refinement can change generated details. Preserve mode keeps the approved appearance by resizing pixels; it does not synthesize new high-resolution detail.
