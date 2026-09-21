import re
import torch
import torch.nn.functional as F


class DOGMANonSemanticTilePromptV565:
    """Closed-vocabulary Phase-2 prompt composer.
    Qwen is allowed to report only restoration defects. Any semantic/object words
    in the VLM response are ignored, so Klein never receives a tile inventory.
    """
    _DEFECTS = {
        "grain": ("grain", "film grain", "noise"),
        "speckles": ("speckle", "speckles", "speckling"),
        "mush": ("mush", "mushy", "smear", "smeared"),
        "blur": ("blur", "blurry", "soft focus"),
        "compression": ("compression", "jpeg", "block artifact", "blocking"),
        "aliasing": ("aliasing", "jaggies", "jagged"),
        "texture_loss": ("texture loss", "lost texture", "flat texture", "texture_loss"),
        "edge_softness": ("edge softness", "soft edges", "edge_softness"),
        "color_noise": ("color noise", "chroma noise", "colour noise", "color_noise"),
        "banding": ("banding", "posterization", "posterisation"),
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "vlm_report": ("STRING", {"forceInput": True, "multiline": True}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "defect_report")
    FUNCTION = "compose"
    CATEGORY = "DOGMA/v56.5"

    def compose(self, vlm_report):
        raw = re.sub(r"\s+", " ", str(vlm_report or "").lower()).strip()
        found = []
        for key, terms in self._DEFECTS.items():
            if any(term in raw for term in terms):
                found.append(key)

        if not found:
            found = ["grain", "speckles", "mush", "blur", "texture_loss", "edge_softness"]

        defects = ", ".join(found)
        report = "DEFECTS: " + defects

        prompt = (
            "Enhance and clean the existing reference pixels only. "
            f"Reduce only these restoration defects where visibly present: {defects}. "
            "The reference image is the sole authority for all semantic content; this instruction intentionally names no scene subject. "
            "Recover clean photographic micro-detail only inside already-existing pixel-supported boundaries. "
            "Preserve the exact camera, composition, perspective, geometry, object count, positions, silhouettes, occlusions, visible text glyphs, materials, colors, exposure, lighting, shadows, reflections and empty regions. "
            "Never infer content from context. A partially visible element touching a tile boundary must remain partial and in the same location; never complete or relocate it. "
            "Do not add, duplicate, remove, move, replace, recolor, redesign, complete, reinterpret or invent anything."
        )
        return (prompt, report)


class DOGMANovelStructureGuardV565:
    """Reject coherent medium/large structures invented by a generated tile.
    Fine detail is left alone; coherent generated-only structures are restored
    toward the source before tile-edge anchoring and Steudio combine.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "generated": ("IMAGE",),
            "source": ("IMAGE",),
            "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
            "threshold": ("FLOAT", {"default": 0.055, "min": 0.01, "max": 0.20, "step": 0.005}),
            "analysis_long_side": ("INT", {"default": 512, "min": 256, "max": 1024, "step": 64}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "novelty_mask", "info")
    FUNCTION = "guard"
    CATEGORY = "DOGMA/v56.5"

    @staticmethod
    def _align(source, generated):
        s = source[..., :3].float().to(generated.device)
        b, h, w, _ = generated.shape
        if s.shape[1:3] != (h, w):
            s = F.interpolate(
                s.movedim(-1, 1),
                size=(h, w),
                mode="bicubic",
                align_corners=False,
                antialias=True,
            ).movedim(1, -1)
        if s.shape[0] != b:
            s = s[:1].expand(b, -1, -1, -1) if s.shape[0] == 1 else s[:b]
        return s

    @staticmethod
    def _grad(luma):
        dx = F.pad((luma[:, :, :, 1:] - luma[:, :, :, :-1]).abs(), (0, 1, 0, 0))
        dy = F.pad((luma[:, :, 1:, :] - luma[:, :, :-1, :]).abs(), (0, 0, 0, 1))
        return torch.sqrt(dx * dx + dy * dy + 1e-8)

    def guard(self, generated, source, strength, threshold, analysis_long_side):
        g = generated[..., :3].float().clamp(0, 1)
        s = self._align(source, g).clamp(0, 1)
        _, h, w, _ = g.shape

        long_side = max(256, min(1024, int(analysis_long_side)))
        scale = min(1.0, long_side / float(max(h, w)))
        ah = max(64, int(round(h * scale)))
        aw = max(64, int(round(w * scale)))

        gc = F.interpolate(g.movedim(-1, 1), size=(ah, aw), mode="area")
        sc = F.interpolate(s.movedim(-1, 1), size=(ah, aw), mode="area")

        # Suppress micro-detail before comparison. This guard targets coherent
        # new subjects/structures, not legitimate sharpening.
        gb = F.avg_pool2d(gc, 7, stride=1, padding=3)
        sb = F.avg_pool2d(sc, 7, stride=1, padding=3)

        color_difference = (gb - sb).abs().mean(dim=1, keepdim=True)

        gl = 0.2126 * gb[:, 0:1] + 0.7152 * gb[:, 1:2] + 0.0722 * gb[:, 2:3]
        sl = 0.2126 * sb[:, 0:1] + 0.7152 * sb[:, 1:2] + 0.0722 * sb[:, 2:3]

        generated_edges = self._grad(gl)
        source_edges = self._grad(sl)
        new_edge_energy = F.relu(generated_edges - source_edges * 1.20)

        novelty = color_difference + 0.30 * new_edge_energy
        novelty = F.avg_pool2d(novelty, 9, stride=1, padding=4)

        low = max(0.005, float(threshold))
        high = max(low + 0.01, low * 2.20)

        mask = ((novelty - low) / (high - low)).clamp(0, 1)
        mask = mask * mask * (3.0 - 2.0 * mask)

        # Coherence filtering removes isolated micro-detail changes.
        mask = F.avg_pool2d(mask, 7, stride=1, padding=3)
        mask = ((mask - 0.12) / 0.48).clamp(0, 1)
        mask = mask * mask * (3.0 - 2.0 * mask)
        mask = F.max_pool2d(mask, 5, stride=1, padding=2)
        mask = F.avg_pool2d(mask, 7, stride=1, padding=3)

        full_mask = F.interpolate(mask, size=(h, w), mode="bilinear", align_corners=False).clamp(0, 1)

        amount = max(0.0, min(1.0, float(strength)))
        alpha = (full_mask * amount).clamp(0, 1)

        out = (
            g.movedim(-1, 1) * (1.0 - alpha)
            + s.movedim(-1, 1) * alpha
        ).movedim(1, -1).clamp(0, 1)

        coverage = float((full_mask > 0.25).float().mean().item()) * 100.0
        peak = float(full_mask.max().item()) if full_mask.numel() else 0.0

        info = (
            f"v56.5 novel-structure guard | strength={amount:.2f} threshold={low:.3f} "
            f"analysis={aw}x{ah} | guarded coverage={coverage:.2f}% peak={peak:.2f} | "
            "coherent generated-only structures revert toward source; micro-detail passes"
        )

        return (out, full_mask[:, 0], info)


NODE_CLASS_MAPPINGS = {
    "DOGMANonSemanticTilePromptV565": DOGMANonSemanticTilePromptV565,
    "DOGMANovelStructureGuardV565": DOGMANovelStructureGuardV565,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DOGMANonSemanticTilePromptV565": "DOGMA v56.5 Non-Semantic Tile Prompt",
    "DOGMANovelStructureGuardV565": "DOGMA v56.5 Novel Structure Guard",
}
