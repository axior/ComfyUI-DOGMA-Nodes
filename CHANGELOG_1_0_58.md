# DOGMA 1.0.58

Add `DOGMASeedanceVideoFix`, a standalone native VIDEO adapter for the existing 1.0.57 stutter repair. It takes only the generated video and returns the corrected video, with progress, cancellation and a clear result status. No API jobs or original-footage input. Native LoadVideo and SaveVideo complete the three-node workflow. Keep SaveVideo codec auto to avoid a second re-encode. Existing nodes and the API Platform repair engine are unchanged; no new dependencies.
