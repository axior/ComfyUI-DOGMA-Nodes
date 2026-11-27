# DOGMA 1.0.62

- Fix false Seedream rejection of odd Custom dimensions. Preserve the exact requested width and height, including 2816 × 1485.
- Respect preset precedence over unused Custom fields. Check Seedream's actual megapixel/range/aspect limits before queueing and identify the relevant fields.
- Reveal invalid fields and clear their validation error after correction. Release submission state and queue hooks even when preparation or native submission fails; allow a manual retry without restart.
- Replace a reference when files are dropped onto its thumbnail. Preserve slot/state/role and clear obsolete masks/crops/previews. Keep the original reference if upload fails; validate image/video and First/Last constraints before upload.
- No changes to workflow IDs, API authentication, backend generation or video repair. No paid requests or automatic retries during verification.

Validation: exact Custom payload and preset regression tests; real Seedream limits; upload failures and replacement routing with hidden references; image/video and First/Last roles; Run and queue failure/retry cleanup. Browser preview confirmed invalid-field focus, correction to 2816 × 1485, and successful mocked resubmission after a simulated Comfy error. Package integrity and JavaScript syntax checked.
