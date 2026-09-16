

import math
import re
import torch
import numpy as np
import torch.nn.functional as F
import node_helpers
import comfy.utils


def _clean_category(line):
    s = str(line or "").strip()
    s = re.sub(r"^\s*[-*•]+\s*", "", s)
    s = re.sub(r"^\s*\d+\s*[\).\-\:]\s*", "", s)
    s = s.strip().strip("`").strip()
    # Keep only the category part if the model ignored instructions and added an explanation.
    for sep in (" — ", " - ", ": ", " -> ", " => "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > 60:
        s = s[:60].rsplit(" ", 1)[0]
    return s


class DOGMAScenePlanSlots:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "planner_text": ("STRING", {"multiline": True, "forceInput": True}),
                "global_target": ("STRING", {
                    "multiline": True,
                    "default": "Milan, Italy, 1972–1978. Preserve the source composition, object count, positions, camera, lighting and photographic character."
                }),
            }
        }

    RETURN_TYPES = (
        "STRING",
        "STRING","STRING","STRING",
        "STRING","STRING","STRING",
        "STRING","STRING","STRING",
        "STRING","STRING","STRING",
        "STRING","STRING","STRING",
        "STRING","STRING","STRING",
    )
    RETURN_NAMES = (
        "plan_preview",
        "category_1","sam_prompt_1","edit_prompt_1",
        "category_2","sam_prompt_2","edit_prompt_2",
        "category_3","sam_prompt_3","edit_prompt_3",
        "category_4","sam_prompt_4","edit_prompt_4",
        "category_5","sam_prompt_5","edit_prompt_5",
        "category_6","sam_prompt_6","edit_prompt_6",
    )
    FUNCTION = "build"
    CATEGORY = "DOGMA/Semantic Detailer"

    def _policy(self, category, target):
        c = category.lower()

        vehicles = ("car","cars","vehicle","vehicles","automobile","automobiles","traffic",
                    "bus","buses","truck","trucks","van","vans","motorcycle","motorcycles",
                    "bicycle","bicycles")
        people = ("person","people","pedestrian","pedestrians","human","humans","crowd","crowds")
        architecture = ("building","buildings","architecture","facade","facades","façade","façades",
                        "house","houses","tower","towers","storefront","storefronts")
        roads = ("road","roads","street","streets","sidewalk","sidewalks","pavement","pavements",
                 "curb","curbs","asphalt","crosswalk","crosswalks")
        street_objects = ("traffic light","traffic lights","street light","street lights",
                          "street lamp","street lamps","sign","signs","traffic sign","traffic signs",
                          "pole","poles","bollard","bollards","bench","benches","street furniture")
        vegetation = ("tree","trees","vegetation","grass","bush","bushes","shrub","shrubs","plants","foliage")
        sky = ("sky","cloud","clouds")

        if any(k in c for k in vehicles):
            sam = "car:300,bus:80,truck:80,van:80,motorcycle:80,bicycle:80"
            edit = (
                f"Correct the vehicles visible in the reference image so they are coherent, realistic and consistent with {target} "
                "Repair malformed bodies, wheels, windows, fused vehicles and impossible perspective. "
                "Replace clearly anachronistic vehicles with plausible equivalents for that setting. "
                "Preserve vehicle count, positions, directions, approximate sizes and colors. Do not add vehicles."
            )
        elif any(k in c for k in people):
            sam = "person:250,pedestrian:250"
            edit = (
                f"Correct the people visible in the reference image so they are anatomically coherent, realistic and consistent with {target} "
                "Preserve person count, poses, positions, scale, direction and approximate clothing colors. "
                "Do not add or remove people."
            )
        elif any(k in c for k in architecture):
            sam = "building:100,facade:100"
            edit = (
                f"Correct the architecture visible in the reference image so it is coherent and consistent with {target} "
                "Repair malformed façade edges, windows, balconies and structural details. "
                "Preserve building identity and geometry. Do not modernize, add signage, copy text or invent readable text."
            )
        elif any(k in c for k in roads):
            sam = "road:40,sidewalk:80,curb:80,crosswalk:50"
            edit = (
                f"Correct the road, sidewalk and curb geometry visible in the reference image so it is coherent and consistent with {target} "
                "Preserve road layout, curb positions, perspective and existing markings. "
                "Do not create new lanes, vehicles, signs or text."
            )
        elif any(k in c for k in street_objects):
            sam = "traffic light:80,street lamp:100,traffic sign:100,pole:120,bollard:80,bench:50"
            edit = (
                f"Correct the street objects visible in the reference image so they are coherent, realistic and consistent with {target} "
                "Preserve their count, positions, function and approximate silhouette. "
                "Do not add objects, duplicate objects or invent readable text."
            )
        elif any(k in c for k in vegetation):
            sam = "tree:150,bush:150,grass:50,vegetation:150"
            edit = (
                f"Correct the vegetation visible in the reference image so it is coherent, natural and consistent with {target} "
                "Preserve the layout, occupied areas and overall density. Do not add unrelated objects."
            )
        elif any(k in c for k in sky):
            sam = "sky:20,cloud:80"
            edit = (
                f"Correct only visible defects in the sky and clouds so they remain natural and consistent with {target} "
                "Preserve lighting, haze, cloud placement and photographic character."
            )
        elif c in ("none", "__none__", "unused", "n/a"):
            sam = "nonexistent_placeholder_object_xyz:1"
            edit = "Preserve the reference image unchanged."
        else:
            simple = re.sub(r"[^a-zA-Z0-9 \-_/]", "", category).strip() or "object"
            sam = f"{simple}:150"
            edit = (
                f"Correct the {simple} visible in the reference image so it is coherent, realistic and consistent with {target} "
                f"Preserve the number, identity, position, scale and orientation of the existing {simple}. "
                f"Do not add new {simple} or unrelated objects."
            )
        return sam, edit

    def build(self, planner_text, global_target):
        target = re.sub(r"\s+", " ", str(global_target).strip())
        raw_lines = str(planner_text or "").replace(",", "\n").splitlines()
        cats = []
        seen = set()
        for line in raw_lines:
            c = _clean_category(line)
            if not c:
                continue
            key = c.lower()
            if key not in seen:
                seen.add(key)
                cats.append(c)
            if len(cats) == 6:
                break

        while len(cats) < 6:
            cats.append("__none__")

        outputs = []
        preview = []
        for i, cat in enumerate(cats, 1):
            sam, edit = self._policy(cat, target)
            outputs.extend([cat, sam, edit])
            preview.append(
                f"SLOT {i}\n"
                f"category: {cat}\n"
                f"SAM: {sam}\n"
                f"KLEIN: {edit}"
            )

        return ("\n\n".join(preview), *outputs)


def _mask_bbox(mask, threshold=0.5):
    m = mask > threshold
    if not torch.any(m):
        return None
    ys, xs = torch.where(m)
    return (
        int(xs.min().item()), int(ys.min().item()),
        int(xs.max().item()) + 1, int(ys.max().item()) + 1,
        int(m.sum().item())
    )


def _boxes_close(a, b, distance):
    ax1, ay1, ax2, ay2, _ = a
    bx1, by1, bx2, by2, _ = b
    return not (
        ax2 + distance < bx1 or bx2 + distance < ax1 or
        ay2 + distance < by1 or by2 + distance < ay1
    )


def _expanded_rect(group, W, H, context_factor, min_crop_side):
    x1 = min(item[1][0] for item in group)
    y1 = min(item[1][1] for item in group)
    x2 = max(item[1][2] for item in group)
    y2 = max(item[1][3] for item in group)

    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)

    tw = max(min_crop_side, int(math.ceil(bw * context_factor)))
    th = max(min_crop_side, int(math.ceil(bh * context_factor)))
    tw = min(tw, W)
    th = min(th, H)

    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5
    sx = int(round(cx - tw * 0.5))
    sy = int(round(cy - th * 0.5))
    sx = max(0, min(sx, W - tw))
    sy = max(0, min(sy, H - th))

    # Flux.2 latent dimensions must be divisible by 16.
    ex = min(W, sx + tw)
    ey = min(H, sy + th)
    sx = max(0, sx - (sx % 16))
    sy = max(0, sy - (sy % 16))
    ex = min(W, int(math.ceil(ex / 16.0) * 16))
    ey = min(H, int(math.ceil(ey / 16.0) * 16))
    # If image edge itself is not divisible by 16, shrink end safely.
    if (ex - sx) % 16:
        ex -= (ex - sx) % 16
    if (ey - sy) % 16:
        ey -= (ey - sy) % 16

    if ex <= sx:
        ex = min(W, sx + 16)
    if ey <= sy:
        ey = min(H, sy + 16)

    return sx, sy, ex, ey


def _group_span(group):
    x1 = min(item[1][0] for item in group)
    y1 = min(item[1][1] for item in group)
    x2 = max(item[1][2] for item in group)
    y2 = max(item[1][3] for item in group)
    return x2-x1, y2-y1


def _split_group_to_max(group, W, H, context_factor, min_crop_side, max_crop_side):
    rect = _expanded_rect(group, W, H, context_factor, min_crop_side)
    sx, sy, ex, ey = rect
    if max(ex - sx, ey - sy) <= max_crop_side or len(group) <= 1:
        return [group]

    span_x, span_y = _group_span(group)
    axis = 0 if span_x >= span_y else 1

    ordered = sorted(
        group,
        key=lambda item: ((item[1][0] + item[1][2]) * 0.5) if axis == 0
                         else ((item[1][1] + item[1][3]) * 0.5)
    )
    mid = max(1, len(ordered)//2)
    left = ordered[:mid]
    right = ordered[mid:]
    if not right:
        return [group]
    return (
        _split_group_to_max(left, W, H, context_factor, min_crop_side, max_crop_side)
        + _split_group_to_max(right, W, H, context_factor, min_crop_side, max_crop_side)
    )


class DOGMANativeClusteredMaskCrops:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "masks": ("MASK",),
                "merge_distance": ("INT", {"default": 512, "min": 0, "max": 4096, "step": 16}),
                "context_factor": ("FLOAT", {"default": 1.15, "min": 1.0, "max": 3.0, "step": 0.05}),
                "min_mask_area": ("INT", {"default": 12, "min": 1, "max": 1000000, "step": 1}),
                "min_crop_side": ("INT", {"default": 1024, "min": 128, "max": 8192, "step": 16}),
                "max_crop_side": ("INT", {"default": 4096, "min": 512, "max": 8192, "step": 16}),
                "max_groups": ("INT", {"default": 12, "min": 1, "max": 128, "step": 1}),
                "mask_threshold": ("FLOAT", {"default": 0.5, "min": 0.01, "max": 0.99, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "DOGMA_STITCH")
    RETURN_NAMES = ("crops", "crop_masks", "stitch")
    OUTPUT_IS_LIST = (True, True, True)
    FUNCTION = "make_crops"
    CATEGORY = "DOGMA/Semantic Detailer"

    def make_crops(self, image, masks, merge_distance, context_factor, min_mask_area,
                   min_crop_side, max_crop_side, max_groups, mask_threshold):
        if image.ndim != 4 or image.shape[0] < 1:
            raise ValueError("DOGMA Native Clustered Mask Crops expects at least one IMAGE.")

        src = image[0:1, ..., :3]
        H, W = int(src.shape[1]), int(src.shape[2])

        if masks.ndim == 2:
            masks = masks.unsqueeze(0)
        masks = masks.float()
        if masks.shape[-2:] != (H, W):
            masks = F.interpolate(
                masks.unsqueeze(1), size=(H, W),
                mode="bilinear", align_corners=False
            ).squeeze(1)

        valid = []
        for i in range(int(masks.shape[0])):
            box = _mask_bbox(masks[i], mask_threshold)
            if box is not None and box[4] >= min_mask_area:
                valid.append((i, box))

        if not valid:
            # Safe no-op sentinel: one native crop and a zero mask.
            side = min(max(min_crop_side, 16), W, H)
            side -= side % 16
            side = max(16, side)
            sx = max(0, ((W - side)//2) // 16 * 16)
            sy = max(0, ((H - side)//2) // 16 * 16)
            crop = src[:, sy:sy+side, sx:sx+side, :]
            zero = torch.zeros((1, side, side), dtype=torch.float32, device=masks.device)
            meta = {
                "x": sx, "y": sy, "width": side, "height": side,
                "source_width": W, "source_height": H,
                "group_id": -1, "members": [], "noop": True
            }
            return ([crop], [zero], [meta])

        n = len(valid)
        parent = list(range(n))
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a,b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for a in range(n):
            for b in range(a+1, n):
                if _boxes_close(valid[a][1], valid[b][1], merge_distance):
                    union(a,b)

        clusters = {}
        for k,item in enumerate(valid):
            clusters.setdefault(find(k), []).append(item)

        groups = list(clusters.values())
        groups.sort(key=lambda g: sum(item[1][4] for item in g), reverse=True)

        split_groups = []
        for g in groups:
            split_groups.extend(
                _split_group_to_max(
                    g, W, H, context_factor, min_crop_side, max_crop_side
                )
            )
        split_groups.sort(key=lambda g: sum(item[1][4] for item in g), reverse=True)
        split_groups = split_groups[:max_groups]

        crops, crop_masks, stitch = [], [], []
        for gid, group in enumerate(split_groups):
            sx, sy, ex, ey = _expanded_rect(group, W, H, context_factor, min_crop_side)
            # Enforce max size after expansion by centered clipping if a single huge object remains.
            if ex - sx > max_crop_side:
                cx = (sx + ex)//2
                sx = max(0, min(W-max_crop_side, cx-max_crop_side//2))
                sx = (sx//16)*16
                ex = min(W, sx+max_crop_side)
            if ey - sy > max_crop_side:
                cy = (sy + ey)//2
                sy = max(0, min(H-max_crop_side, cy-max_crop_side//2))
                sy = (sy//16)*16
                ey = min(H, sy+max_crop_side)

            w, h = ex-sx, ey-sy
            w -= w % 16
            h -= h % 16
            if w < 16 or h < 16:
                continue
            ex, ey = sx+w, sy+h

            union_mask = torch.zeros((H,W), device=masks.device, dtype=torch.float32)
            members = []
            for mask_idx, _ in group:
                union_mask = torch.maximum(union_mask, masks[mask_idx])
                members.append(int(mask_idx))

            crop = src[:, sy:ey, sx:ex, :]
            crop_mask = union_mask[sy:ey, sx:ex].unsqueeze(0)

            crops.append(crop)
            crop_masks.append(crop_mask)
            stitch.append({
                "x": int(sx), "y": int(sy), "width": int(w), "height": int(h),
                "source_width": int(W), "source_height": int(H),
                "group_id": int(gid), "members": members, "noop": False
            })

        if not crops:
            raise ValueError("DOGMA Native Clustered Mask Crops produced no valid crops.")

        return (crops, crop_masks, stitch)


class DOGMAStitchCrops:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_image": ("IMAGE",),
                "patches": ("IMAGE",),
                "masks": ("MASK",),
                "stitch": ("DOGMA_STITCH",),
                "mask_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    INPUT_IS_LIST = True
    FUNCTION = "stitch_crops"
    CATEGORY = "DOGMA/Semantic Detailer"

    def stitch_crops(self, base_image, patches, masks, stitch, mask_strength):
        if not base_image:
            raise ValueError("DOGMA Stitch Crops received no base image.")

        result = base_image[0].clone()[..., :3]
        strength = float(mask_strength[0] if isinstance(mask_strength, list) else mask_strength)
        count = min(len(patches), len(masks), len(stitch))

        for i in range(count):
            patch, mask, meta = patches[i], masks[i], stitch[i]
            if patch is None or mask is None or meta is None or meta.get("noop", False):
                continue

            if patch.ndim == 3:
                patch = patch.unsqueeze(0)
            if mask.ndim == 2:
                mask = mask.unsqueeze(0)

            x, y = int(meta["x"]), int(meta["y"])
            w, h = int(meta["width"]), int(meta["height"])
            if w <= 0 or h <= 0:
                continue

            if patch.shape[1] != h or patch.shape[2] != w:
                patch = F.interpolate(
                    patch[..., :3].movedim(-1,1), size=(h,w),
                    mode="bicubic", align_corners=False
                ).movedim(1,-1).clamp(0,1)
            else:
                patch = patch[..., :3].clamp(0,1)

            if mask.shape[-2:] != (h,w):
                mask = F.interpolate(
                    mask.unsqueeze(1).float(), size=(h,w),
                    mode="bilinear", align_corners=False
                ).squeeze(1)
            mask = (mask.float().clamp(0,1) * strength).unsqueeze(-1)

            region = result[:, y:y+h, x:x+w, :]
            rh, rw = region.shape[1], region.shape[2]
            patch = patch[:, :rh, :rw, :]
            mask = mask[:, :rh, :rw, :]

            result[:, y:y+rh, x:x+rw, :] = patch * mask + region * (1.0-mask)

        return (result,)



class DOGMAClusteredMaskCrops:
    """Backward-compatible v5/v6 crop node."""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "masks": ("MASK",),
                "target_size": ("INT", {"default": 2048, "min": 512, "max": 4096, "step": 64}),
                "merge_distance": ("INT", {"default": 96, "min": 0, "max": 1024, "step": 8}),
                "context_factor": ("FLOAT", {"default": 1.45, "min": 1.0, "max": 4.0, "step": 0.05}),
                "min_mask_area": ("INT", {"default": 24, "min": 1, "max": 1000000, "step": 1}),
                "min_crop_side": ("INT", {"default": 160, "min": 32, "max": 4096, "step": 8}),
                "max_groups": ("INT", {"default": 24, "min": 1, "max": 256, "step": 1}),
                "mask_threshold": ("FLOAT", {"default": 0.5, "min": 0.01, "max": 0.99, "step": 0.01}),
            }
        }
    RETURN_TYPES = ("IMAGE", "MASK", "DOGMA_STITCH")
    RETURN_NAMES = ("crops", "crop_masks", "stitch")
    OUTPUT_IS_LIST = (True, True, True)
    FUNCTION = "make_crops"
    CATEGORY = "DOGMA/Semantic Detailer"

    def make_crops(self, image, masks, target_size, merge_distance, context_factor,
                   min_mask_area, min_crop_side, max_groups, mask_threshold):
        if image.ndim != 4 or image.shape[0] < 1:
            raise ValueError("DOGMA Clustered Mask Crops expects at least one IMAGE.")
        src = image[0:1, ..., :3]
        H, W = int(src.shape[1]), int(src.shape[2])
        if masks.ndim == 2:
            masks = masks.unsqueeze(0)
        masks = masks.float()
        if masks.shape[-2:] != (H, W):
            masks = F.interpolate(masks.unsqueeze(1), size=(H,W), mode="bilinear", align_corners=False).squeeze(1)

        valid = []
        for i in range(int(masks.shape[0])):
            b = _mask_bbox(masks[i], mask_threshold)
            if b is not None and b[4] >= min_mask_area:
                valid.append((i,b))

        if not valid:
            side = min(W,H)
            sx, sy = max(0,(W-side)//2), max(0,(H-side)//2)
            crop = src[:,sy:sy+side,sx:sx+side,:]
            crop = F.interpolate(crop.movedim(-1,1), size=(target_size,target_size), mode="bicubic", align_corners=False).movedim(1,-1).clamp(0,1)
            zero = torch.zeros((1,target_size,target_size), device=masks.device, dtype=torch.float32)
            return ([crop],[zero],[{"x":sx,"y":sy,"width":side,"height":side,"source_width":W,"source_height":H,"group_id":-1,"members":[],"noop":True}])

        n=len(valid); parent=list(range(n))
        def find(x):
            while parent[x]!=x:
                parent[x]=parent[parent[x]]; x=parent[x]
            return x
        def union(a,b):
            ra,rb=find(a),find(b)
            if ra!=rb: parent[rb]=ra
        for a in range(n):
            for b in range(a+1,n):
                if _boxes_close(valid[a][1],valid[b][1],merge_distance): union(a,b)
        clusters={}
        for k,item in enumerate(valid): clusters.setdefault(find(k),[]).append(item)
        groups=list(clusters.values())
        groups.sort(key=lambda g:sum(item[1][4] for item in g),reverse=True)
        groups=groups[:max_groups]

        crops=[]; crop_masks=[]; stitch=[]
        for gid,g in enumerate(groups):
            x1=min(i[1][0] for i in g); y1=min(i[1][1] for i in g)
            x2=max(i[1][2] for i in g); y2=max(i[1][3] for i in g)
            bw=max(1,x2-x1); bh=max(1,y2-y1)
            side=max(min_crop_side,int(math.ceil(max(bw,bh)*context_factor)))
            side=min(side,W,H)
            cx=(x1+x2)*0.5; cy=(y1+y2)*0.5
            sx=int(round(cx-side/2)); sy=int(round(cy-side/2))
            sx=max(0,min(sx,W-side)); sy=max(0,min(sy,H-side))
            union_mask=torch.zeros((H,W),device=masks.device,dtype=torch.float32)
            members=[]
            for idx,_ in g:
                union_mask=torch.maximum(union_mask,masks[idx]); members.append(int(idx))
            crop=src[:,sy:sy+side,sx:sx+side,:]
            cm=union_mask[sy:sy+side,sx:sx+side].unsqueeze(0)
            crop=F.interpolate(crop.movedim(-1,1),size=(target_size,target_size),mode="bicubic",align_corners=False).movedim(1,-1).clamp(0,1)
            cm=F.interpolate(cm.unsqueeze(1),size=(target_size,target_size),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            crops.append(crop); crop_masks.append(cm)
            stitch.append({"x":sx,"y":sy,"width":side,"height":side,"source_width":W,"source_height":H,"target_size":target_size,"group_id":gid,"members":members,"noop":False})
        return (crops,crop_masks,stitch)



class DOGMACategoryMaskGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK",),
                "category": ("STRING", {"forceInput": True}),
            }
        }
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("masks",)
    FUNCTION = "gate"
    CATEGORY = "DOGMA/Semantic Detailer"

    def gate(self, masks, category):
        c = str(category or "").strip().lower()
        if c in ("", "none", "__none__", "unused", "n/a"):
            return (torch.zeros_like(masks),)
        return (masks,)



class DOGMAVisionResizeMaxSide:
    """
    Downscale-only image preparation for VLMs.
    Keeps aspect ratio and caps the longest side, avoiding huge vision tensors.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "max_side": ("INT", {
                    "default": 1024,
                    "min": 256,
                    "max": 4096,
                    "step": 64
                }),
                "multiple": ("INT", {
                    "default": 16,
                    "min": 1,
                    "max": 64,
                    "step": 1
                }),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "resize"
    CATEGORY = "DOGMA/Semantic Detailer"

    def resize(self, image, max_side, multiple):
        if image.ndim != 4 or image.shape[0] < 1:
            raise ValueError("DOGMA Vision Resize expects IMAGE [B,H,W,C].")

        h = int(image.shape[1])
        w = int(image.shape[2])
        longest = max(h, w)

        if longest <= int(max_side):
            return (image, f"Qwen input unchanged: {w}x{h}")

        scale = float(max_side) / float(longest)
        nw = max(int(multiple), int(round((w * scale) / multiple)) * int(multiple))
        nh = max(int(multiple), int(round((h * scale) / multiple)) * int(multiple))

        # Never exceed max_side because of rounding.
        if max(nw, nh) > int(max_side):
            if nw >= nh:
                nw = (int(max_side) // int(multiple)) * int(multiple)
                nh = max(int(multiple), int(round((h * (nw / w)) / multiple)) * int(multiple))
            else:
                nh = (int(max_side) // int(multiple)) * int(multiple)
                nw = max(int(multiple), int(round((w * (nh / h)) / multiple)) * int(multiple))

        x = image[..., :3].movedim(-1, 1)
        y = F.interpolate(
            x,
            size=(nh, nw),
            mode="bicubic",
            align_corners=False,
            antialias=True
        )
        y = y.movedim(1, -1).clamp(0, 1)

        return (y, f"Qwen input: {w}x{h} -> {nw}x{nh} (max side {max_side})")


class DOGMAImageAfterText:
    """
    Passes IMAGE through unchanged, but creates an explicit graph dependency
    on a STRING. Used to guarantee that the VLM planner finishes/unloads
    before the heavy upscale branch starts.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "dependency": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pass_after_text"
    CATEGORY = "DOGMA/Semantic Detailer"

    def pass_after_text(self, image, dependency):
        return (image,)



class DOGMAUnionMacroCrops:
    """
    Takes ONE semantic union mask (or unions any accidental mask batch) and
    creates the MINIMUM number of large native-resolution crops needed to
    cover it. Overlap exists for model context, but stitch ownership is
    partitioned so the same pixels are not pasted twice.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "masks": ("MASK",),
                "context_px": ("INT", {
                    "default": 160, "min": 0, "max": 2048, "step": 16
                }),
                "min_crop_side": ("INT", {
                    "default": 2048, "min": 256, "max": 8192, "step": 16
                }),
                "max_crop_side": ("INT", {
                    "default": 4096, "min": 512, "max": 8192, "step": 16
                }),
                "overlap": ("INT", {
                    "default": 768, "min": 0, "max": 2048, "step": 16
                }),
                "max_crops": ("INT", {
                    "default": 8, "min": 1, "max": 64, "step": 1
                }),
                "mask_threshold": ("FLOAT", {
                    "default": 0.5, "min": 0.01, "max": 0.99, "step": 0.01
                }),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "DOGMA_STITCH", "STRING")
    RETURN_NAMES = ("crops", "crop_masks", "stitch", "info")
    OUTPUT_IS_LIST = (True, True, True, False)
    FUNCTION = "make_crops"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _snap_down(v, q=16):
        return max(0, (int(v) // q) * q)

    @staticmethod
    def _snap_up(v, q=16):
        return int(math.ceil(float(v) / q) * q)

    @staticmethod
    def _axis_windows(start, end, max_side, overlap):
        start = int(start)
        end = int(end)
        span = end - start

        if span <= max_side:
            return [(start, end)]

        overlap = min(int(overlap), int(max_side) - 16)
        step = max(16, int(max_side) - overlap)

        starts = [start]
        while starts[-1] + max_side < end:
            nxt = starts[-1] + step
            if nxt + max_side >= end:
                nxt = end - max_side
            if nxt <= starts[-1]:
                break
            starts.append(nxt)

        result = []
        for s in starts:
            e = min(end, s + max_side)
            s = max(start, e - max_side)
            pair = (int(s), int(e))
            if not result or pair != result[-1]:
                result.append(pair)
        return result

    @staticmethod
    def _best_vertical_split(mask, left_window, right_window, y1, y2):
        # Choose the emptiest column inside the contextual overlap, so we
        # avoid splitting through a vehicle/person whenever possible.
        lo = max(left_window[0], right_window[0])
        hi = min(left_window[1], right_window[1])
        if hi <= lo + 1:
            return (left_window[1] + right_window[0]) // 2

        strip = mask[y1:y2, lo:hi]
        density = strip.sum(dim=0)
        return lo + int(torch.argmin(density).item())

    @staticmethod
    def _best_horizontal_split(mask, top_window, bottom_window, x1, x2):
        lo = max(top_window[0], bottom_window[0])
        hi = min(top_window[1], bottom_window[1])
        if hi <= lo + 1:
            return (top_window[1] + bottom_window[0]) // 2

        strip = mask[lo:hi, x1:x2]
        density = strip.sum(dim=1)
        return lo + int(torch.argmin(density).item())

    def make_crops(self, image, masks, context_px, min_crop_side,
                   max_crop_side, overlap, max_crops, mask_threshold):

        if image.ndim != 4 or image.shape[0] < 1:
            raise ValueError("DOGMA Union Macro Crops expects IMAGE [B,H,W,C].")

        src = image[0:1, ..., :3]
        H, W = int(src.shape[1]), int(src.shape[2])

        if masks.ndim == 2:
            masks = masks.unsqueeze(0)

        masks = masks.float()
        if masks.shape[-2:] != (H, W):
            masks = F.interpolate(
                masks.unsqueeze(1),
                size=(H, W),
                mode="bilinear",
                align_corners=False
            ).squeeze(1)

        # Always collapse to ONE category union mask.
        union = masks.max(dim=0).values.clamp(0, 1)

        box = _mask_bbox(union, mask_threshold)
        if box is None:
            side = min(max(int(min_crop_side), 256), W, H)
            side = max(16, side - side % 16)
            sx = self._snap_down(max(0, (W - side) // 2))
            sy = self._snap_down(max(0, (H - side) // 2))
            crop = src[:, sy:sy+side, sx:sx+side, :]
            zero = torch.zeros(
                (1, side, side),
                dtype=torch.float32,
                device=union.device
            )
            meta = {
                "x": sx, "y": sy, "width": side, "height": side,
                "source_width": W, "source_height": H,
                "group_id": -1, "members": [], "noop": True
            }
            return ([crop], [zero], [meta], "No mask pixels: safe no-op crop.")

        x1, y1, x2, y2, area = box
        pad = int(context_px)

        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(W, x2 + pad)
        y2 = min(H, y2 + pad)

        # Expand small dimensions so Klein gets substantial scene context.
        bw, bh = x2 - x1, y2 - y1
        target_w = min(W, max(bw, int(min_crop_side)))
        target_h = min(H, max(bh, int(min_crop_side)))

        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5

        x1 = max(0, min(W - target_w, int(round(cx - target_w * 0.5))))
        y1 = max(0, min(H - target_h, int(round(cy - target_h * 0.5))))
        x2 = x1 + target_w
        y2 = y1 + target_h

        x1 = self._snap_down(x1)
        y1 = self._snap_down(y1)
        x2 = min(W, self._snap_up(x2))
        y2 = min(H, self._snap_up(y2))

        # Keep crop dimensions divisible by 16.
        if (x2 - x1) % 16:
            x2 -= (x2 - x1) % 16
        if (y2 - y1) % 16:
            y2 -= (y2 - y1) % 16

        if x2 <= x1 or y2 <= y1:
            raise ValueError("DOGMA Union Macro Crops produced an invalid union rectangle.")

        max_side = int(max_crop_side)
        xwins = self._axis_windows(x1, x2, max_side, overlap)
        ywins = self._axis_windows(y1, y2, max_side, overlap)

        needed = len(xwins) * len(ywins)
        if needed > int(max_crops):
            raise ValueError(
                f"Union mask needs {needed} macro crops at max_crop_side={max_side}, "
                f"but max_crops={max_crops}. Increase max_crops or max_crop_side. "
                "Nothing was silently discarded."
            )

        # Ownership splits inside overlap choose the lowest mask density.
        xcuts = []
        for i in range(len(xwins) - 1):
            xcuts.append(self._best_vertical_split(
                union, xwins[i], xwins[i+1], y1, y2
            ))

        ycuts = []
        for i in range(len(ywins) - 1):
            ycuts.append(self._best_horizontal_split(
                union, ywins[i], ywins[i+1], x1, x2
            ))

        crops = []
        crop_masks = []
        stitch = []

        gid = 0
        for yi, (wy1, wy2) in enumerate(ywins):
            own_y1 = y1 if yi == 0 else ycuts[yi - 1]
            own_y2 = y2 if yi == len(ywins) - 1 else ycuts[yi]

            for xi, (wx1, wx2) in enumerate(xwins):
                own_x1 = x1 if xi == 0 else xcuts[xi - 1]
                own_x2 = x2 if xi == len(xwins) - 1 else xcuts[xi]

                crop = src[:, wy1:wy2, wx1:wx2, :]

                local_mask = union[wy1:wy2, wx1:wx2].clone()

                # Partition stitch ownership. The image crop still contains
                # the full contextual overlap for Klein.
                ownership = torch.zeros_like(local_mask)
                lx1 = max(0, own_x1 - wx1)
                lx2 = min(wx2 - wx1, own_x2 - wx1)
                ly1 = max(0, own_y1 - wy1)
                ly2 = min(wy2 - wy1, own_y2 - wy1)
                if lx2 > lx1 and ly2 > ly1:
                    ownership[ly1:ly2, lx1:lx2] = 1.0

                local_mask = (local_mask * ownership).unsqueeze(0)

                crops.append(crop)
                crop_masks.append(local_mask)
                stitch.append({
                    "x": int(wx1),
                    "y": int(wy1),
                    "width": int(wx2 - wx1),
                    "height": int(wy2 - wy1),
                    "source_width": W,
                    "source_height": H,
                    "group_id": int(gid),
                    "members": ["union"],
                    "noop": False,
                })
                gid += 1

        info = (
            f"Union area={area}px | bbox={x2-x1}x{y2-y1} | "
            f"macro crops={len(crops)} | max_crop_side={max_side} | overlap={overlap}. "
            "No individual SAM masks and no detected regions are dropped."
        )
        return (crops, crop_masks, stitch, info)


class DOGMAHarmonizedStitchCrops:
    """
    Stitch edited patches while reducing the 'pasted-on' look:
    - aligns patch RGB statistics to the matching source crop using unmasked pixels;
    - restores a small amount of source high-frequency texture/grain;
    - composites only through the supplied feathered semantic mask.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_image": ("IMAGE",),
                "patches": ("IMAGE",),
                "masks": ("MASK",),
                "stitch": ("DOGMA_STITCH",),
                "color_match_strength": ("FLOAT", {
                    "default": 0.75, "min": 0.0, "max": 1.0, "step": 0.01
                }),
                "source_texture_strength": ("FLOAT", {
                    "default": 0.18, "min": 0.0, "max": 1.0, "step": 0.01
                }),
                "edit_mix": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    INPUT_IS_LIST = True
    FUNCTION = "stitch"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _scalar(x, default):
        if isinstance(x, list):
            if not x:
                return default
            x = x[0]
        try:
            return float(x)
        except Exception:
            return default

    def stitch(self, base_image, patches, masks, stitch,
               color_match_strength, source_texture_strength, edit_mix):

        if not base_image:
            raise ValueError("DOGMA Harmonized Stitch received no base image.")

        result = base_image[0].clone()[..., :3]
        cm = self._scalar(color_match_strength, 0.75)
        tex = self._scalar(source_texture_strength, 0.18)
        mix = self._scalar(edit_mix, 1.0)

        count = min(len(patches), len(masks), len(stitch))

        for i in range(count):
            patch = patches[i]
            mask = masks[i]
            meta = stitch[i]

            if patch is None or mask is None or meta is None or meta.get("noop", False):
                continue

            if patch.ndim == 3:
                patch = patch.unsqueeze(0)
            if mask.ndim == 2:
                mask = mask.unsqueeze(0)

            x = int(meta["x"])
            y = int(meta["y"])
            w = int(meta["width"])
            h = int(meta["height"])

            if patch.shape[1] != h or patch.shape[2] != w:
                patch = F.interpolate(
                    patch[..., :3].movedim(-1, 1),
                    size=(h, w),
                    mode="bicubic",
                    align_corners=False,
                    antialias=True
                ).movedim(1, -1)
            else:
                patch = patch[..., :3]

            if mask.shape[-2:] != (h, w):
                mask = F.interpolate(
                    mask.unsqueeze(1).float(),
                    size=(h, w),
                    mode="bilinear",
                    align_corners=False
                ).squeeze(1)

            region = result[:, y:y+h, x:x+w, :]
            rh, rw = region.shape[1], region.shape[2]
            patch = patch[:, :rh, :rw, :].float().clamp(0, 1)
            mask = mask[:, :rh, :rw].float().clamp(0, 1)
            base = region.float().clamp(0, 1)

            # Match color/exposure using pixels that will NOT be replaced.
            outside = (mask < 0.03)
            if cm > 0 and int(outside.sum().item()) >= 512:
                base_flat = base[0][outside[0]]
                patch_flat = patch[0][outside[0]]

                bmean = base_flat.mean(dim=0)
                pmean = patch_flat.mean(dim=0)
                bstd = base_flat.std(dim=0).clamp(min=0.015)
                pstd = patch_flat.std(dim=0).clamp(min=0.015)

                matched = (
                    (patch - pmean.view(1,1,1,3))
                    * (bstd / pstd).view(1,1,1,3)
                    + bmean.view(1,1,1,3)
                ).clamp(0, 1)

                patch = patch * (1.0 - cm) + matched * cm

            # Put a little original photographic microtexture/grain back
            # without restoring the whole old geometry.
            if tex > 0:
                bchw = base.movedim(-1, 1)
                blur = F.avg_pool2d(
                    F.pad(bchw, (2,2,2,2), mode="reflect"),
                    kernel_size=5,
                    stride=1
                )
                high = (bchw - blur).movedim(1, -1)
                patch = (patch + high * tex).clamp(0, 1)

            alpha = (mask * mix).clamp(0, 1).unsqueeze(-1)
            result[:, y:y+rh, x:x+rw, :] = (
                patch * alpha + base * (1.0 - alpha)
            )

        return (result,)


def _dogma_v9_short_policy(self, category, target):
    c = str(category or "").lower()
    target = re.sub(r"\s+", " ", str(target or "").strip()).rstrip(".")
    if not target:
        target = "the requested setting"

    vehicles = ("car","cars","vehicle","vehicles","automobile","automobiles",
                "traffic","bus","buses","truck","trucks","van","vans",
                "motorcycle","motorcycles","bicycle","bicycles")
    people = ("person","people","pedestrian","pedestrians","human","humans",
              "crowd","crowds")
    architecture = ("building","buildings","architecture","facade","facades",
                    "façade","façades","house","houses","tower","towers",
                    "storefront","storefronts")
    roads = ("road","roads","street","streets","sidewalk","sidewalks",
             "pavement","pavements","curb","curbs","asphalt",
             "crosswalk","crosswalks")
    street_objects = ("traffic light","traffic lights","street light","street lights",
                      "street lamp","street lamps","sign","signs","traffic sign",
                      "traffic signs","pole","poles","bollard","bollards",
                      "bench","benches","street furniture")
    vegetation = ("tree","trees","vegetation","grass","bush","bushes","shrub",
                  "shrubs","plants","foliage")
    sky = ("sky","cloud","clouds")

    if any(k in c for k in vehicles):
        return (
            "car:300,bus:80,truck:80,van:80,motorcycle:80,bicycle:80",
            f"Repair the masked vehicles as coherent, realistic vehicles appropriate to {target}. "
            "Fix malformed or fused vehicle geometry and replace clearly anachronistic vehicles. "
            "Preserve count, position, direction, approximate size and color. Do not add vehicles."
        )
    if any(k in c for k in people):
        return (
            "person:250,pedestrian:250",
            f"Repair the masked people as realistic people appropriate to {target}. "
            "Fix malformed anatomy and silhouettes. Preserve count, pose, position, scale and clothing colors. "
            "Do not add or remove people."
        )
    if any(k in c for k in architecture):
        return (
            "building:100,facade:100",
            f"Repair the masked architecture as faithful architecture appropriate to {target}. "
            "Fix malformed façade edges, windows, balconies and structural details. "
            "Preserve building identity. Do not modernize or invent readable text."
        )
    if any(k in c for k in roads):
        return (
            "road:40,sidewalk:80,curb:80,crosswalk:50",
            f"Repair the masked road and sidewalk geometry as appropriate to {target}. "
            "Preserve layout, curbs, perspective and existing markings. Do not add vehicles, signs or text."
        )
    if any(k in c for k in street_objects):
        return (
            "traffic light:80,street lamp:100,traffic sign:100,pole:120,bollard:80,bench:50",
            f"Repair the masked street objects as realistic street objects appropriate to {target}. "
            "Preserve count, position, function and silhouette. Do not add objects or invent readable text."
        )
    if any(k in c for k in vegetation):
        return (
            "tree:150,bush:150,grass:50,vegetation:150",
            f"Repair only malformed masked vegetation so it looks natural and appropriate to {target}. "
            "Preserve layout and density."
        )
    if any(k in c for k in sky):
        return (
            "sky:20,cloud:80",
            f"Repair only visible masked defects in the sky appropriate to {target}. "
            "Preserve lighting, haze and cloud placement."
        )
    if c in ("none","__none__","unused","n/a",""):
        return ("nonexistent_placeholder_object_xyz:1", "Preserve the reference image unchanged.")

    simple = re.sub(r"[^a-zA-Z0-9 \-_/]", "", str(category)).strip() or "object"
    return (
        f"{simple}:150",
        f"Repair the masked {simple} so it is coherent and appropriate to {target}. "
        f"Preserve count, identity, position, scale and orientation. Do not add new {simple}."
    )


# v9 deliberately overrides the old verbose policy.
DOGMAScenePlanSlots._policy = _dogma_v9_short_policy



class DOGMASemanticMacroCropsV10:
    """
    Collapse a semantic category to one union mask, group only at the REGION
    level, and emit a few resized crops. No per-instance crop/render loop.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "masks": ("MASK",),
                "group_radius": ("INT", {"default": 480, "min": 0, "max": 2048, "step": 16}),
                "context_px": ("INT", {"default": 192, "min": 0, "max": 2048, "step": 16}),
                "max_source_side": ("INT", {"default": 3600, "min": 512, "max": 8192, "step": 16}),
                "target_long_side": ("INT", {"default": 1344, "min": 512, "max": 2048, "step": 32}),
                "max_crops": ("INT", {"default": 6, "min": 1, "max": 24, "step": 1}),
                "mask_threshold": ("FLOAT", {"default": 0.5, "min": 0.01, "max": 0.99, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "DOGMA_STITCH", "STRING")
    RETURN_NAMES = ("crops", "crop_masks", "stitch", "info")
    OUTPUT_IS_LIST = (True, True, True, False)
    FUNCTION = "make_crops"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _components(binary):
        arr = binary.astype("uint8", copy=False)
        h, w = arr.shape
        seen = np.zeros_like(arr, dtype=np.uint8)
        comps = []
        for y in range(h):
            for x in range(w):
                if arr[y, x] == 0 or seen[y, x]:
                    continue
                stack = [(y, x)]
                seen[y, x] = 1
                minx = maxx = x
                miny = maxy = y
                count = 0
                while stack:
                    cy, cx = stack.pop()
                    count += 1
                    if cx < minx: minx = cx
                    if cx > maxx: maxx = cx
                    if cy < miny: miny = cy
                    if cy > maxy: maxy = cy
                    for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                        if 0 <= ny < h and 0 <= nx < w and arr[ny,nx] and not seen[ny,nx]:
                            seen[ny,nx] = 1
                            stack.append((ny,nx))
                comps.append((minx, miny, maxx+1, maxy+1, count))
        return comps

    @staticmethod
    def _resize_image(image, nh, nw):
        chw = image.movedim(-1, 1)
        out = F.interpolate(chw, size=(nh, nw), mode="bicubic",
                            align_corners=False, antialias=True)
        return out.movedim(1, -1).clamp(0, 1)

    @staticmethod
    def _resize_mask(mask, nh, nw):
        return F.interpolate(mask.unsqueeze(1).float(), size=(nh, nw),
                             mode="bilinear", align_corners=False).squeeze(1).clamp(0, 1)

    @staticmethod
    def _target_size(h, w, long_side):
        scale = float(long_side) / float(max(h, w))
        nh = max(16, int(round((h * scale) / 16.0)) * 16)
        nw = max(16, int(round((w * scale) / 16.0)) * 16)
        return nh, nw

    def make_crops(self, image, masks, group_radius, context_px,
                   max_source_side, target_long_side, max_crops, mask_threshold):
        if image.ndim != 4 or image.shape[0] < 1:
            raise ValueError("DOGMA Semantic Macro Crops expects IMAGE [B,H,W,C].")
        src = image[0:1, ..., :3]
        H, W = int(src.shape[1]), int(src.shape[2])

        if masks.ndim == 2:
            masks = masks.unsqueeze(0)
        masks = masks.float()
        if masks.shape[-2:] != (H, W):
            masks = F.interpolate(masks.unsqueeze(1), size=(H, W),
                                  mode="bilinear", align_corners=False).squeeze(1)

        union = masks.max(dim=0).values.clamp(0, 1)
        hard = union > float(mask_threshold)

        if not torch.any(hard):
            side = min(H, W, 1024)
            y = max(0, (H - side)//2)
            x = max(0, (W - side)//2)
            crop = src[:, y:y+side, x:x+side, :]
            nh, nw = self._target_size(side, side, min(target_long_side, side))
            crop = self._resize_image(crop, nh, nw)
            z = torch.zeros((1, nh, nw), dtype=torch.float32, device=union.device)
            meta = {
                "x": int(x), "y": int(y), "width": int(side), "height": int(side),
                "source_width": int(W), "source_height": int(H),
                "noop": True, "group_id": -1
            }
            return ([crop], [z], [meta], "No active semantic mask: safe no-op.")

        # Region grouping happens on a small mask only, so thousands of
        # individual SAM detections never become thousands of crops.
        preview_long = 512
        scale = min(1.0, preview_long / float(max(H, W)))
        ph = max(32, int(round(H * scale)))
        pw = max(32, int(round(W * scale)))
        small = F.interpolate(union[None,None], size=(ph,pw),
                              mode="bilinear", align_corners=False)[0,0]
        small = (small > float(mask_threshold)).float()

        rad = int(round(float(group_radius) * scale))
        if rad > 0:
            k = rad * 2 + 1
            small = F.max_pool2d(small[None,None], kernel_size=k,
                                 stride=1, padding=rad)[0,0]

        comps = self._components((small > 0.5).cpu().numpy())
        comps.sort(key=lambda b: b[4], reverse=True)

        # Map coarse components to source-space bounding regions.
        regions = []
        sx = W / float(pw)
        sy = H / float(ph)
        for x1s, y1s, x2s, y2s, _ in comps:
            x1 = max(0, int(math.floor(x1s * sx)) - int(context_px))
            y1 = max(0, int(math.floor(y1s * sy)) - int(context_px))
            x2 = min(W, int(math.ceil(x2s * sx)) + int(context_px))
            y2 = min(H, int(math.ceil(y2s * sy)) + int(context_px))
            if x2 > x1 and y2 > y1:
                regions.append((x1,y1,x2,y2))

        # Merge the closest regions until there are at most max_crops before
        # oversize splitting. This is still REGION-level, never per-object.
        def bbox_gap(a,b):
            ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
            dx=max(0, max(ax1,bx1)-min(ax2,bx2))
            dy=max(0, max(ay1,by1)-min(ay2,by2))
            return dx*dx+dy*dy

        while len(regions) > int(max_crops):
            best = None
            for i in range(len(regions)):
                for j in range(i+1,len(regions)):
                    g = bbox_gap(regions[i], regions[j])
                    if best is None or g < best[0]:
                        best = (g,i,j)
            _,i,j=best
            a=regions[i]; b=regions[j]
            merged=(min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))
            regions=[r for k,r in enumerate(regions) if k not in (i,j)] + [merged]

        # Split only if a region is too large. Ownership windows do not
        # overlap; crops get context, so the same semantic pixels are not
        # edited twice.
        ownership_regions = []
        mss = int(max_source_side)
        inner = max(512, mss - 2*int(context_px))
        for rx1,ry1,rx2,ry2 in regions:
            xs=[]
            x=rx1
            while x < rx2:
                xe=min(rx2, x+inner)
                xs.append((x,xe))
                if xe>=rx2: break
                x=xe
            ys=[]
            y=ry1
            while y < ry2:
                ye=min(ry2, y+inner)
                ys.append((y,ye))
                if ye>=ry2: break
                y=ye
            for oy1,oy2 in ys:
                for ox1,ox2 in xs:
                    ownership_regions.append((ox1,oy1,ox2,oy2))

        if len(ownership_regions) > int(max_crops):
            raise ValueError(
                f"Semantic union needs {len(ownership_regions)} macro crops with max_source_side={max_source_side}, "
                f"but max_crops={max_crops}. Increase max_source_side or max_crops. No region was discarded."
            )

        crops=[]; crop_masks=[]; stitch=[]
        gid=0
        for ox1,oy1,ox2,oy2 in ownership_regions:
            cx1=max(0, ox1-int(context_px))
            cy1=max(0, oy1-int(context_px))
            cx2=min(W, ox2+int(context_px))
            cy2=min(H, oy2+int(context_px))

            # Align source crop to 16 px where possible.
            cx1=(cx1//16)*16
            cy1=(cy1//16)*16
            cx2=min(W, int(math.ceil(cx2/16.0))*16)
            cy2=min(H, int(math.ceil(cy2/16.0))*16)
            if cx2 <= cx1 or cy2 <= cy1:
                continue

            crop=src[:,cy1:cy2,cx1:cx2,:]
            own_mask=torch.zeros_like(union)
            own_mask[oy1:oy2,ox1:ox2]=union[oy1:oy2,ox1:ox2]
            local=own_mask[cy1:cy2,cx1:cx2][None]

            nh,nw=self._target_size(crop.shape[1],crop.shape[2],int(target_long_side))
            crop_r=self._resize_image(crop,nh,nw)
            mask_r=self._resize_mask(local,nh,nw)

            crops.append(crop_r)
            crop_masks.append(mask_r)
            stitch.append({
                "x":int(cx1),"y":int(cy1),
                "width":int(cx2-cx1),"height":int(cy2-cy1),
                "source_width":int(W),"source_height":int(H),
                "group_id":int(gid),"noop":False,
            })
            gid += 1

        info=(
            f"ONE semantic union mask -> {len(crops)} macro crop(s). "
            f"Source max side {max_source_side}px, model crop long side {target_long_side}px, "
            f"group radius {group_radius}px, context {context_px}px. No per-instance crops."
        )
        return (crops,crop_masks,stitch,info)


class DOGMAExactMaskedStitchV10:
    """
    Pure geometric stitch. No color matching, no texture synthesis, no global
    correction. Only pixels allowed by the final semantic mask are copied.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_image": ("IMAGE",),
                "patches": ("IMAGE",),
                "masks": ("MASK",),
                "stitch": ("DOGMA_STITCH",),
                "strength": ("FLOAT", {"default":1.0,"min":0.0,"max":1.0,"step":0.01}),
            }
        }
    RETURN_TYPES=("IMAGE",)
    RETURN_NAMES=("image",)
    INPUT_IS_LIST=True
    FUNCTION="stitch"
    CATEGORY="DOGMA/Semantic Detailer"

    def stitch(self, base_image, patches, masks, stitch, strength):
        if not base_image:
            raise ValueError("DOGMA Exact Masked Stitch received no base image.")
        result=base_image[0].clone()[...,:3]
        s=float(strength[0] if isinstance(strength,list) else strength)
        count=min(len(patches),len(masks),len(stitch))
        for i in range(count):
            meta=stitch[i]
            if meta is None or meta.get("noop",False):
                continue
            patch=patches[i]
            mask=masks[i]
            if patch.ndim==3: patch=patch.unsqueeze(0)
            if mask.ndim==2: mask=mask.unsqueeze(0)
            x=int(meta["x"]); y=int(meta["y"])
            w=int(meta["width"]); h=int(meta["height"])
            p=F.interpolate(patch[...,:3].movedim(-1,1),size=(h,w),
                            mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(mask.unsqueeze(1).float(),size=(h,w),
                            mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            region=result[:,y:y+h,x:x+w,:]
            rh,rw=region.shape[1],region.shape[2]
            alpha=(m[:,:rh,:rw]*s).unsqueeze(-1)
            result[:,y:y+rh,x:x+rw,:]=p[:,:rh,:rw,:]*alpha+region*(1.0-alpha)
        return (result,)


class DOGMAAfterMasksVRAMCleanup:
    """
    Explicit stage barrier: all six SAM masks must exist before this runs.
    Then SAM/Qwen/upscaler models can be unloaded before Klein inpainting.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mask_1": ("MASK",),
                "mask_2": ("MASK",),
                "mask_3": ("MASK",),
                "mask_4": ("MASK",),
                "mask_5": ("MASK",),
                "mask_6": ("MASK",),
                "unload_models": ("BOOLEAN", {"default": True}),
            }
        }
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","status")
    FUNCTION="cleanup"
    CATEGORY="DOGMA/Semantic Detailer"

    def cleanup(self,image,mask_1,mask_2,mask_3,mask_4,mask_5,mask_6,unload_models):
        import gc
        import comfy.model_management as mm
        if unload_models:
            try:
                mm.unload_all_models()
            except Exception:
                # Older/newer Comfy builds may not expose this exactly;
                # soft cache cleanup still helps and does not break the run.
                pass
        gc.collect()
        try:
            mm.soft_empty_cache()
        except Exception:
            pass
        return (image, "SAM stage complete. Model/cache cleanup executed before Klein stage.")


def _dogma_v10_final_state_policy(self, category, target):
    c = str(category or "").lower()
    target = re.sub(r"\s+", " ", str(target or "").strip()).rstrip(".")
    if not target:
        target = "the intended setting"

    if any(k in c for k in ("car","vehicle","automobile","traffic","bus","truck","van","motorcycle","bicycle")):
        return (
            "car:300,bus:80,truck:80,van:80,motorcycle:80,bicycle:80",
            f"Varied realistic vehicles appropriate to {target}. Keep the same visible vehicles, positions, directions, "
            "traffic density, approximate sizes and existing individual colors. Correct malformed or fused geometry and "
            "clearly anachronistic vehicle designs. Preserve color diversity. Do not add or remove vehicles."
        )
    if any(k in c for k in ("person","people","pedestrian","human","crowd")):
        return (
            "person:250,pedestrian:250",
            f"Realistic people appropriate to {target}. Keep the same people, poses, positions, scale and approximate clothing colors. "
            "Correct malformed anatomy and silhouettes. Do not add or remove people."
        )
    if any(k in c for k in ("building","architecture","facade","façade","house","tower","storefront")):
        return (
            "building:100,facade:100",
            f"Faithful architecture appropriate to {target}. Keep the same buildings and identity. Correct malformed façade edges, "
            "windows, balconies and structural geometry. Do not modernize, redesign, copy signage or invent readable text."
        )
    if any(k in c for k in ("road","street","sidewalk","pavement","curb","asphalt","crosswalk")):
        return (
            "road:40,sidewalk:80,curb:80,crosswalk:50",
            f"The same road and sidewalk surfaces appropriate to {target}, with coherent geometry and markings. "
            "Preserve layout, color, texture and perspective. Do not add vehicles, signs, text or new road features."
        )
    if any(k in c for k in ("traffic light","street light","street lamp","sign","pole","bollard","bench","street furniture")):
        return (
            "traffic light:80,street lamp:100,traffic sign:100,pole:120,bollard:80,bench:50",
            f"The same street objects appropriate to {target}. Preserve count, position, function, silhouette and approximate colors. "
            "Correct only malformed geometry. Do not add objects or invent readable text."
        )
    if any(k in c for k in ("tree","vegetation","grass","bush","shrub","plant","foliage")):
        return (
            "tree:150,bush:150,grass:50,vegetation:150",
            f"Natural vegetation appropriate to {target}. Preserve layout, density and color. Correct only malformed local geometry."
        )
    if any(k in c for k in ("sky","cloud")):
        return (
            "sky:20,cloud:80",
            f"The same sky appropriate to {target}. Preserve lighting, haze, color and cloud placement; correct only local artifacts."
        )
    if c in ("none","__none__","unused","n/a",""):
        return ("nonexistent_placeholder_object_xyz:1", "Preserve the reference image unchanged.")

    simple=re.sub(r"[^a-zA-Z0-9 \-_/]","",str(category)).strip() or "object"
    return (
        f"{simple}:150",
        f"The same {simple} appropriate to {target}. Preserve identity, count, position, scale, orientation and color. "
        f"Correct malformed geometry only. Do not add new {simple}."
    )

DOGMAScenePlanSlots._policy = _dogma_v10_final_state_policy


# =========================
# DOGMA v11 policy/settings
# =========================

def _dogma_v11_family(category):
    c = re.sub(r"\s+", " ", str(category or "").strip().lower())

    if c in ("", "none", "__none__", "unused", "n/a"):
        return "none"

    if (
        "roadway pedestrian" in c or "roadway pedestrians" in c
        or "pedestrian in road" in c or "pedestrians in road" in c
        or "person in road" in c or "people in road" in c
        or "traffic lane pedestrian" in c
    ):
        return "roadway_people"

    if "sidewalk pedestrian" in c or "sidewalk pedestrians" in c or "person on sidewalk" in c or "people on sidewalk" in c:
        return "sidewalk_people"

    signage_terms = (
        "signage", "billboard", "billboards", "advertising sign", "advertising signs",
        "rooftop sign", "rooftop signs", "building sign", "building signs",
        "large lettering", "large letters", "shop sign", "shop signs", "store sign", "store signs"
    )
    if any(k in c for k in signage_terms):
        return "signage"

    street_terms = (
        "traffic light", "traffic lights", "street light", "street lights",
        "street lamp", "street lamps", "pole", "poles", "bollard", "bollards",
        "bench", "benches", "street furniture"
    )
    if any(k in c for k in street_terms):
        return "street_objects"

    vehicle_terms = (
        "car", "cars", "vehicle", "vehicles", "automobile", "automobiles",
        "bus", "buses", "truck", "trucks", "van", "vans",
        "motorcycle", "motorcycles", "bicycle", "bicycles"
    )
    if any(k in c for k in vehicle_terms):
        return "vehicles"

    people_terms = ("person", "people", "pedestrian", "pedestrians", "human", "humans", "crowd", "crowds")
    if any(k in c for k in people_terms):
        return "people"

    architecture_terms = (
        "building", "buildings", "architecture", "facade", "facades", "façade", "façades",
        "house", "houses", "tower", "towers", "storefront", "storefronts"
    )
    if any(k in c for k in architecture_terms):
        return "architecture"

    vegetation_terms = (
        "vegetation", "grass", "lawn", "tree", "trees", "bush", "bushes",
        "shrub", "shrubs", "plants", "foliage"
    )
    if any(k in c for k in vegetation_terms):
        return "vegetation"

    road_terms = (
        "road", "roads", "street", "streets", "sidewalk", "sidewalks",
        "pavement", "pavements", "curb", "curbs", "asphalt", "crosswalk", "crosswalks"
    )
    if any(k in c for k in road_terms):
        return "road"

    if "sky" in c or "cloud" in c:
        return "sky"

    if "water" in c or "river" in c or "sea" in c or "lake" in c:
        return "water"

    if "animal" in c or "dog" in c or "cat" in c or "horse" in c or "bird" in c:
        return "animals"

    return "other"


def _dogma_v11_policy(self, category, target):
    c = re.sub(r"\s+", " ", str(category or "").strip())
    family = _dogma_v11_family(c)
    target = re.sub(r"\s+", " ", str(target or "").strip()).rstrip(".")
    if not target:
        target = "the requested setting"

    if family == "none":
        return ("nonexistent_placeholder_object_xyz:1", "Preserve the reference image unchanged.")

    if family == "vehicles":
        return (
            "car:500,automobile:500,parked car:500,distant car:500,tiny car:500,"
            "van:140,bus:120,truck:120,motorcycle:100,bicycle:100",
            f"Repair only the masked vehicles so they are coherent, realistic vehicles appropriate to {target}. "
            "Fix malformed bodies, fused cars, impossible wheels, windows and perspective, and correct clearly anachronistic vehicles. "
            "Preserve the exact traffic density, vehicle count, positions, directions, approximate sizes and EACH vehicle's existing approximate color. "
            "Keep natural color variety; do not turn the fleet white or duplicate one car design. Do not add vehicles."
        )

    if family == "roadway_people":
        return (
            "person standing in road:180,pedestrian in roadway:180,person in traffic lane:180",
            f"Remove only the masked people who are standing in active traffic lanes. "
            f"Reconstruct the road surface underneath consistently with {target}, preserving existing lane markings, lighting, perspective and texture. "
            "Do not add people, vehicles, signs or new road markings."
        )

    if family in ("sidewalk_people", "people"):
        sam = (
            "pedestrian on sidewalk:260,person on sidewalk:260"
            if family == "sidewalk_people"
            else "person:260,pedestrian:260"
        )
        return (
            sam,
            f"Repair only the masked people so they are anatomically coherent, realistic and appropriate to {target}. "
            "Preserve person count, pose, position, scale, direction and approximate clothing colors. "
            "Keep pedestrians on the sidewalk where they already are. Do not add people."
        )

    if family == "signage":
        return (
            "billboard:160,advertising sign:160,rooftop sign:160,building sign:160,"
            "large lettering:160,shop sign:160,store sign:160",
            f"Repair only the masked signs, billboards and large lettering so they are structurally coherent and appropriate to {target}. "
            "Preserve the exact existing wording, logo identity, placement, letter count, layout and colors visible in the reference. "
            "Improve malformed letter shapes and sign geometry without inventing, translating or replacing text."
        )

    if family == "architecture":
        return (
            "building:120,facade:120",
            f"Refine only malformed masked architectural details so the buildings remain faithful to {target}. "
            "Preserve exact building identity, façade materials, window layout, colors, exposure, sunlight direction and shadow pattern. "
            "Repair malformed edges, windows, balconies and structural details without redesigning, relighting or recoloring the building. "
            "Do not alter signs or readable text."
        )

    if family == "vegetation":
        return (
            "grass:140,lawn:140,tree:140,bush:140,shrub:140,vegetation:140",
            f"Refine only malformed masked vegetation while preserving the exact vegetation TYPE and occupied area in the reference. "
            f"Grass and lawn must remain grass or lawn; trees remain trees; bushes remain bushes. Keep the scene appropriate to {target}. "
            "Preserve layout, density, lighting and shadows. Do not turn open lawn into trees, bushes, flowers or a garden."
        )

    if family == "road":
        return (
            "road:60,street:60,asphalt:60,sidewalk:100,curb:100,crosswalk:80",
            f"Refine only malformed masked road, sidewalk, curb and marking details so they remain consistent with {target}. "
            "Preserve the exact road layout, asphalt color, perspective, lane markings and lighting. "
            "Do not alter, blur, add or remove vehicles, pedestrians, signs or street furniture."
        )

    if family == "street_objects":
        return (
            "traffic light:120,street lamp:140,pole:160,bollard:100,bench:80,street furniture:140",
            f"Repair only the masked street objects so they are coherent and appropriate to {target}. "
            "Preserve count, exact position, function, silhouette, lighting and colors. "
            "Do not add objects or alter nearby vehicles, people, signs or buildings."
        )

    if family == "sky":
        return (
            "sky:40,cloud:100",
            "Refine only obvious masked defects in the sky. Preserve the exact lighting, haze, color gradient and cloud placement."
        )

    if family == "water":
        return (
            "water:120",
            "Refine only obvious masked water defects. Preserve the exact shoreline, reflections, lighting, color and wave direction."
        )

    if family == "animals":
        return (
            "animal:180",
            f"Repair only the masked animals so they are anatomically coherent and appropriate to {target}. "
            "Preserve count, species, pose, position, scale and colors. Do not add animals."
        )

    simple = re.sub(r"[^a-zA-Z0-9 \-_/]", "", c).strip() or "object"
    return (
        f"{simple}:180",
        f"Repair only the masked {simple} so it is coherent and appropriate to {target}. "
        f"Preserve count, identity, position, scale, orientation, lighting and colors. Do not add new {simple}."
    )


def _dogma_v11_build(self, planner_text, global_target):
    target = re.sub(r"\s+", " ", str(global_target or "").strip())
    raw_lines = str(planner_text or "").replace(",", "\n").splitlines()

    cats = []
    seen = set()
    for line in raw_lines:
        c = _clean_category(line)
        if not c:
            continue
        key = c.lower()
        if key not in seen:
            seen.add(key)
            cats.append(c)

    # Coarse/background passes first; small/delicate objects last.
    # This means a later car/person/sign pass can repair any tiny accidental
    # surface spill from architecture/vegetation/road.
    priority = {
        "architecture": 10,
        "vegetation": 20,
        "road": 30,
        "sky": 30,
        "water": 30,
        "street_objects": 40,
        "signage": 50,
        "roadway_people": 60,
        "animals": 65,
        "vehicles": 70,
        "people": 80,
        "sidewalk_people": 80,
        "other": 55,
        "none": 999,
    }
    cats.sort(key=lambda x: priority.get(_dogma_v11_family(x), 55))
    cats = cats[:6]

    while len(cats) < 6:
        cats.append("__none__")

    outputs = []
    preview = []
    for i, cat in enumerate(cats, 1):
        sam, edit = _dogma_v11_policy(self, cat, target)
        outputs.extend([cat, sam, edit])
        preview.append(
            f"SLOT {i}\n"
            f"family: {_dogma_v11_family(cat)}\n"
            f"category: {cat}\n"
            f"SAM: {sam}\n"
            f"KLEIN: {edit}"
        )

    return ("\n\n".join(preview), *outputs)


# Patch old 6-slot planner in place so old workflows remain loadable.
DOGMAScenePlanSlots._policy = _dogma_v11_policy
DOGMAScenePlanSlots.build = _dogma_v11_build


class DOGMACategorySettingsV11:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "category": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = (
        "FLOAT", "INT", "INT", "INT", "INT", "INT", "FLOAT", "STRING"
    )
    RETURN_NAMES = (
        "sam_threshold",
        "group_radius",
        "context_px",
        "max_source_side",
        "target_long_side",
        "max_crops",
        "denoise",
        "summary",
    )
    FUNCTION = "settings"
    CATEGORY = "DOGMA/Semantic Detailer"

    def settings(self, category):
        family = _dogma_v11_family(category)

        table = {
            # threshold, group_radius, context, max source, model long side, crops, denoise
            "vehicles":        (0.14, 320, 160, 2400, 1536, 8, 1.00),
            "signage":         (0.20, 300, 160, 2200, 1536, 8, 0.65),
            "roadway_people":  (0.18, 260, 128, 1700, 1536, 8, 1.00),
            "sidewalk_people": (0.20, 260, 128, 1700, 1536, 8, 0.80),
            "people":          (0.20, 260, 128, 1700, 1536, 8, 0.80),
            "street_objects":  (0.24, 360, 144, 2200, 1536, 8, 0.70),
            "architecture":    (0.34, 720, 128, 2800, 1344, 6, 0.35),
            "vegetation":      (0.30, 680, 128, 2600, 1280, 6, 0.25),
            "road":            (0.34, 800, 128, 2800, 1152, 6, 0.25),
            "sky":             (0.40, 900, 64, 3000, 1024, 4, 0.20),
            "water":           (0.35, 800, 96, 2800, 1152, 4, 0.30),
            "animals":         (0.20, 300, 128, 1800, 1536, 8, 0.85),
            "other":           (0.28, 420, 144, 2200, 1344, 6, 0.65),
            "none":            (0.50, 480, 128, 1800, 1024, 1, 0.00),
        }

        values = table.get(family, table["other"])
        threshold, radius, context, max_source, target_side, max_crops, denoise = values
        summary = (
            f"{family}: SAM threshold={threshold:.2f}, group_radius={radius}, "
            f"source≤{max_source}, model≤{target_side}, max_crops={max_crops}, denoise={denoise:.2f}"
        )
        return (
            float(threshold),
            int(radius),
            int(context),
            int(max_source),
            int(target_side),
            int(max_crops),
            float(denoise),
            summary,
        )


class DOGMAPrepareSAMInputV11_1:
    """
    VRAM-safe SAM preparation stage.

    - Waits until the high-resolution working master exists, so the upscaler
      stage is definitely finished.
    - Unloads Qwen/upscaler/other currently loaded models before SAM.
    - Uses the ORIGINAL source image for semantic segmentation.
    - Downscales only if needed, preserving aspect ratio.
    - The resulting lower-resolution SAM mask is later resized to the high-res
      working master by DOGMASemanticMacroCropsV10.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_image": ("IMAGE",),
                "working_master_dependency": ("IMAGE",),
                "max_side": ("INT", {
                    "default": 2560,
                    "min": 1024,
                    "max": 4096,
                    "step": 64,
                }),
                "multiple": ("INT", {
                    "default": 16,
                    "min": 8,
                    "max": 64,
                    "step": 8,
                }),
                "unload_models": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("sam_image", "info")
    FUNCTION = "prepare"
    CATEGORY = "DOGMA/Semantic Detailer"

    def prepare(self, source_image, working_master_dependency,
                max_side, multiple, unload_models):

        import gc
        import comfy.model_management as mm

        # The dependency input is intentionally unused pixel-wise.
        # Its presence forces this node to execute only after the 2x master
        # has already been produced.
        _ = working_master_dependency

        if unload_models:
            try:
                mm.unload_all_models()
            except Exception:
                pass
            gc.collect()
            try:
                mm.soft_empty_cache()
            except Exception:
                pass

        if source_image.ndim != 4 or source_image.shape[0] < 1:
            raise ValueError(
                "DOGMA Prepare SAM Input expects IMAGE [B,H,W,C]."
            )

        image = source_image[..., :3]
        h = int(image.shape[1])
        w = int(image.shape[2])
        longest = max(h, w)

        max_side = int(max_side)
        multiple = max(1, int(multiple))

        if longest <= max_side:
            out = image
            nw, nh = w, h
        else:
            scale = float(max_side) / float(longest)
            nw = max(
                multiple,
                int(round((w * scale) / multiple)) * multiple
            )
            nh = max(
                multiple,
                int(round((h * scale) / multiple)) * multiple
            )

            # Prevent rounding from exceeding max_side.
            if max(nw, nh) > max_side:
                if nw >= nh:
                    nw = max(multiple, (max_side // multiple) * multiple)
                    nh = max(
                        multiple,
                        int(round((h * (nw / w)) / multiple)) * multiple
                    )
                else:
                    nh = max(multiple, (max_side // multiple) * multiple)
                    nw = max(
                        multiple,
                        int(round((w * (nh / h)) / multiple)) * multiple
                    )

            chw = image.movedim(-1, 1)
            out = F.interpolate(
                chw,
                size=(nh, nw),
                mode="bicubic",
                align_corners=False,
                antialias=True,
            ).movedim(1, -1).clamp(0, 1)

        info = (
            f"SAM analysis image: {w}x{h} -> {nw}x{nh}. "
            f"Max side={max_side}. Models/cache unloaded before SAM={bool(unload_models)}. "
            "SAM does NOT see the 2x working master; masks are rescaled later."
        )

        return (out, info)



class DOGMACategorySettingsV12:
    """
    v12 controls semantic detection/crop scale and FINAL pixel blend strength.
    The diffusion schedule itself stays full 4-step (denoise=1.0) for every
    active Klein masked-inpaint pass.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"category": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = (
        "FLOAT", "INT", "INT", "INT", "INT", "INT", "FLOAT", "STRING", "FLOAT"
    )
    RETURN_NAMES = (
        "sam_threshold", "group_radius", "context_px", "max_source_side",
        "target_long_side", "max_crops", "denoise", "summary", "stitch_strength"
    )
    FUNCTION="settings"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings(self, category):
        family=_dogma_v11_family(category)
        # threshold, radius, context, source max, model max, crops, denoise, stitch alpha
        table={
            "vehicles":        (0.14,320,160,2400,1536,8,1.00,1.00),
            "signage":         (0.20,300,160,2200,1536,8,1.00,0.95),
            "roadway_people":  (0.18,260,128,1700,1536,8,1.00,1.00),
            "sidewalk_people": (0.20,260,128,1700,1536,8,1.00,1.00),
            "people":          (0.20,260,128,1700,1536,8,1.00,1.00),
            "street_objects":  (0.24,360,144,2200,1536,8,1.00,0.90),
            "architecture":    (0.34,720,128,2800,1344,6,1.00,0.55),
            "vegetation":      (0.30,680,128,2600,1280,6,1.00,0.50),
            "road":            (0.34,800,128,2800,1152,6,1.00,0.40),
            "sky":             (0.40,900,64,3000,1024,4,1.00,0.35),
            "water":           (0.35,800,96,2800,1152,4,1.00,0.50),
            "animals":         (0.20,300,128,1800,1536,8,1.00,1.00),
            "other":           (0.28,420,144,2200,1344,6,1.00,0.75),
            "none":            (0.50,480,128,1800,1024,1,1.00,0.00),
        }
        vals=table.get(family,table['other'])
        threshold,radius,context,max_source,target_side,max_crops,denoise,stitch=vals
        summary=(
            f"{family}: SAM={threshold:.2f}, source≤{max_source}, model≤{target_side}, "
            f"Klein full 4-step denoise={denoise:.2f}, final stitch alpha={stitch:.2f}"
        )
        return (float(threshold),int(radius),int(context),int(max_source),int(target_side),
                int(max_crops),float(denoise),summary,float(stitch))


class DOGMASAMMaskCheckpointV12:
    """
    Moves a completed SAM category mask to CPU, then explicitly unloads models
    and empties caches. Its token output is used to serialize the next SAM call.
    This prevents VRAM accumulation across six SAM3 passes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mask": ("MASK",),
            "unload_models": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES=("MASK","STRING")
    RETURN_NAMES=("mask","token")
    FUNCTION="checkpoint"
    CATEGORY="DOGMA/Semantic Detailer"

    def checkpoint(self, mask, unload_models):
        import gc
        import comfy.model_management as mm
        cpu_mask=mask.detach().float().cpu().contiguous()
        del mask
        if unload_models:
            try:
                mm.unload_all_models()
            except Exception:
                pass
        gc.collect()
        try:
            mm.soft_empty_cache()
        except Exception:
            pass
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        return (cpu_mask, "SAM mask cached on CPU; models/cache + CUDA cache unloaded before next SAM category.")


# =========================
# DOGMA v13 robustness / protection / stronger conservative repair
# =========================

class DOGMACategorySettingsV13:
    """
    Full 4-step Klein masked-inpaint stays unchanged.
    v13 changes only semantic threshold, crop scale and final blend strength.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"category": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = (
        "FLOAT", "INT", "INT", "INT", "INT", "INT", "FLOAT", "STRING", "FLOAT"
    )
    RETURN_NAMES = (
        "sam_threshold", "group_radius", "context_px", "max_source_side",
        "target_long_side", "max_crops", "denoise", "summary", "stitch_strength"
    )
    FUNCTION = "settings"
    CATEGORY = "DOGMA/Semantic Detailer"

    def settings(self, category):
        family = _dogma_v11_family(category)
        # threshold, grouping, context, source crop, model side, desired crops,
        # denoise (always full), final alpha.
        table = {
            "vehicles":        (0.13, 360, 160, 2700, 1536, 10, 1.00, 1.00),
            "signage":         (0.18, 340, 160, 2600, 1536, 10, 1.00, 1.00),
            "roadway_people":  (0.16, 340, 144, 2400, 1536, 10, 1.00, 1.00),
            "sidewalk_people": (0.18, 340, 144, 2400, 1536, 10, 1.00, 1.00),
            "people":          (0.18, 340, 144, 2400, 1536, 10, 1.00, 1.00),
            "street_objects":  (0.22, 440, 160, 2700, 1536, 10, 1.00, 0.95),
            # Architecture was too close to the source in v12. Still masked
            # and identity-preserving, but now allowed to visibly fix defects.
            "architecture":    (0.28, 820, 160, 3200, 1536, 8, 1.00, 0.82),
            "vegetation":      (0.28, 820, 144, 3000, 1344, 8, 1.00, 0.55),
            "road":            (0.32, 900, 128, 3200, 1280, 8, 1.00, 0.35),
            "sky":             (0.40, 960,  96, 3400, 1024, 6, 1.00, 0.35),
            "water":           (0.34, 900, 112, 3200, 1280, 6, 1.00, 0.50),
            "animals":         (0.18, 360, 144, 2400, 1536, 10, 1.00, 1.00),
            "other":           (0.26, 500, 160, 2700, 1344, 8, 1.00, 0.80),
            "none":            (0.50, 480, 128, 1800, 1024, 1, 1.00, 0.00),
        }
        vals = table.get(family, table["other"])
        threshold, radius, context, max_source, target_side, max_crops, denoise, stitch = vals
        summary = (
            f"{family}: SAM={threshold:.2f}, requested source≤{max_source}, "
            f"model≤{target_side}, desired crops≤{max_crops}, "
            f"Klein full 4-step denoise=1.00, final alpha={stitch:.2f}"
        )
        return (
            float(threshold), int(radius), int(context), int(max_source),
            int(target_side), int(max_crops), float(denoise), summary,
            float(stitch)
        )


class DOGMAProtectedMasksV13:
    """
    Receives the six finished semantic masks and prevents broad surface passes
    (road / vegetation / architecture / sky) from touching higher-value
    foreground objects such as vehicles, people, signage and street furniture.
    This is category-aware and works regardless of which slot contains which
    semantic class.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {}
        for i in range(1, 7):
            req[f"mask_{i}"] = ("MASK",)
            req[f"category_{i}"] = ("STRING", {"forceInput": True})
        req["protect_radius"] = (
            "INT",
            {"default": 14, "min": 0, "max": 128, "step": 1}
        )
        return {"required": req}

    RETURN_TYPES = ("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES = (
        "mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","summary"
    )
    FUNCTION = "protect"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _union(mask):
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        mask = mask.float()
        if mask.shape[0] > 1:
            mask = mask.max(dim=0, keepdim=True).values
        return mask.clamp(0, 1)

    @staticmethod
    def _dilate(mask, radius):
        if radius <= 0:
            return mask
        k = radius * 2 + 1
        return F.max_pool2d(
            mask.unsqueeze(1), kernel_size=k, stride=1, padding=radius
        ).squeeze(1)

    def protect(
        self,
        mask_1, category_1,
        mask_2, category_2,
        mask_3, category_3,
        mask_4, category_4,
        mask_5, category_5,
        mask_6, category_6,
        protect_radius,
    ):
        masks = [
            self._union(mask_1), self._union(mask_2), self._union(mask_3),
            self._union(mask_4), self._union(mask_5), self._union(mask_6),
        ]
        cats = [category_1, category_2, category_3, category_4, category_5, category_6]
        fams = [_dogma_v11_family(c) for c in cats]

        # Normalize shape defensively using the semantic masks themselves.
        # DOGMAProtectedMasksV13 has no reference_image input.
        H = max(int(m.shape[-2]) for m in masks)
        W = max(int(m.shape[-1]) for m in masks)
        norm = []
        for m in masks:
            if m.shape[-2:] != (H, W):
                m = F.interpolate(
                    m.unsqueeze(1), size=(H, W),
                    mode="bilinear", align_corners=False
                ).squeeze(1)
            norm.append(m.clamp(0, 1))
        masks = norm

        protect_for = {
            "road": {
                "vehicles","roadway_people","sidewalk_people","people",
                "signage","street_objects","animals"
            },
            "vegetation": {
                "vehicles","roadway_people","sidewalk_people","people",
                "signage","street_objects","architecture","animals"
            },
            "architecture": {
                "vehicles","roadway_people","sidewalk_people","people",
                "signage","street_objects","animals"
            },
            "sky": {
                "architecture","signage","street_objects","vehicles","people",
                "sidewalk_people","roadway_people"
            },
            "water": {
                "vehicles","people","sidewalk_people","roadway_people","animals"
            },
        }

        outputs = []
        report = []
        radius = int(protect_radius)

        for i, (mask, family) in enumerate(zip(masks, fams)):
            blocked_fams = protect_for.get(family, set())
            blockers = []
            for j, other_family in enumerate(fams):
                if i != j and other_family in blocked_fams:
                    blockers.append(masks[j])

            if blockers:
                protection = torch.stack(blockers, dim=0).max(dim=0).values
                protection = self._dilate(protection, radius).clamp(0, 1)
                out = (mask * (1.0 - protection)).clamp(0, 1)
                report.append(
                    f"slot {i+1} {family}: protected from "
                    + ", ".join(sorted(set(
                        fams[j] for j in range(6)
                        if j != i and fams[j] in blocked_fams
                    )))
                )
            else:
                out = mask
                report.append(f"slot {i+1} {family}: no protection subtraction")

            outputs.append(out)

        return (*outputs, " | ".join(report))


# Keep a handle to the proven v10 macro crop implementation, then wrap it with
# automatic overflow handling. v12 stopped with a ValueError when a sparse
# semantic union happened to need more windows than max_crops.
_DOGMA_V13_BASE_MAKE_CROPS = DOGMASemanticMacroCropsV10.make_crops

def _dogma_v13_robust_make_crops(
    self, image, masks, group_radius, context_px,
    max_source_side, target_long_side, max_crops, mask_threshold
):
    requested_mss = int(max_source_side)
    requested_crops = int(max_crops)
    effective_mss = requested_mss
    effective_crops = requested_crops
    image_long = int(max(image.shape[1], image.shape[2]))
    adjustments = []

    # First prefer slightly larger source windows rather than exploding the
    # number of Klein renders. Model input resolution remains target_long_side,
    # so this does not increase diffusion resolution/VRAM.
    for _ in range(5):
        try:
            result = _DOGMA_V13_BASE_MAKE_CROPS(
                self, image, masks, group_radius, context_px,
                effective_mss, target_long_side, effective_crops, mask_threshold
            )
            crops, crop_masks, stitch, info = result
            if adjustments:
                info += (
                    " | v13 AUTO-FIT: " + "; ".join(adjustments)
                    + f" | final source≤{effective_mss}, crops≤{effective_crops}"
                )
            return (crops, crop_masks, stitch, info)
        except ValueError as e:
            msg = str(e)
            m = re.search(r"needs\s+(\d+)\s+macro crops", msg)
            if not m:
                raise
            needed = int(m.group(1))

            # Grow source coverage by ~25%; crop is later resized to the same
            # Klein target size, so this is much cheaper than adding many runs.
            if effective_mss < image_long:
                new_mss = min(
                    image_long,
                    int(math.ceil((effective_mss * 1.25) / 16.0) * 16)
                )
                if new_mss > effective_mss:
                    adjustments.append(
                        f"{needed} windows -> source {effective_mss}→{new_mss}"
                    )
                    effective_mss = new_mss
                    continue

            # Last resort: permit the actual required count, capped safely.
            if needed <= 16 and needed > effective_crops:
                adjustments.append(
                    f"allow crops {effective_crops}→{needed}"
                )
                effective_crops = needed
                continue

            raise ValueError(
                msg + " v13 auto-fit could not reduce this category below "
                "16 macro crops. Increase target grouping or inspect the mask."
            )

    raise RuntimeError("DOGMA v13 macro-crop auto-fit exhausted unexpectedly.")

DOGMASemanticMacroCropsV10.make_crops = _dogma_v13_robust_make_crops


def _dogma_v13_policy(self, category, target):
    family = _dogma_v11_family(category)
    if family == "architecture":
        target = re.sub(r"\s+", " ", str(target or "").strip()).rstrip(".")
        if not target:
            target = "the requested setting"
        return (
            "building:160,facade:160,building windows:180,balcony:120",
            f"Actively repair visibly malformed AI-generated architectural details inside the mask while keeping the SAME buildings "
            f"faithful to {target}. Correct broken or repetitive windows, warped façade lines, balconies, edges and structural geometry. "
            "Do not merely copy malformed details. Preserve building identity, materials, overall proportions, façade colors, exposure, "
            "sunlight direction and shadow pattern. Do not redesign or relight the building and do not alter signs or readable text."
        )
    return _dogma_v11_policy(self, category, target)

DOGMAScenePlanSlots._policy = _dogma_v13_policy



# =========================
# DOGMA v14 — GLOBAL BASE REFINER + SAFE LOCAL OBJECT REPAIRS
# =========================

class DOGMAGlobalRefineMaskV14:
    """
    Builds a full-frame refinement mask while protecting any detected signage/text.
    This lets the global visual-restoration pass change the photograph everywhere
    except the original sign/text pixels, which remain exact source pixels.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"reference_image": ("IMAGE",)}
        for i in range(1, 7):
            req[f"mask_{i}"] = ("MASK",)
            req[f"category_{i}"] = ("STRING", {"forceInput": True})
        req["protect_radius"] = ("INT", {
            "default": 20, "min": 0, "max": 128, "step": 1
        })
        return {"required": req}

    RETURN_TYPES = ("MASK", "MASK", "STRING")
    RETURN_NAMES = ("refine_mask", "protected_text_mask", "summary")
    FUNCTION = "build"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _union(mask):
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        mask = mask.detach().float().cpu()
        if mask.shape[0] > 1:
            mask = mask.max(dim=0, keepdim=True).values
        return mask.clamp(0, 1)

    @staticmethod
    def _dilate(mask, radius):
        radius = int(radius)
        if radius <= 0:
            return mask
        k = radius * 2 + 1
        return F.max_pool2d(
            mask.unsqueeze(1), kernel_size=k, stride=1, padding=radius
        ).squeeze(1)

    def build(
        self,
        reference_image,
        mask_1, category_1,
        mask_2, category_2,
        mask_3, category_3,
        mask_4, category_4,
        mask_5, category_5,
        mask_6, category_6,
        protect_radius,
    ):
        masks = [
            self._union(mask_1), self._union(mask_2), self._union(mask_3),
            self._union(mask_4), self._union(mask_5), self._union(mask_6),
        ]
        cats = [
            category_1, category_2, category_3,
            category_4, category_5, category_6,
        ]

        H = max(int(m.shape[-2]) for m in masks)
        W = max(int(m.shape[-1]) for m in masks)
        norm = []
        for m in masks:
            if m.shape[-2:] != (H, W):
                m = F.interpolate(
                    m.unsqueeze(1), size=(H, W),
                    mode="bilinear", align_corners=False
                ).squeeze(1)
            norm.append(m.clamp(0, 1))
        masks = norm

        protected = torch.zeros_like(masks[0])
        used = []
        for m, c in zip(masks, cats):
            fam = _dogma_v11_family(c)
            if fam == "signage":
                protected = torch.maximum(protected, m)
                used.append(str(c))

        protected = self._dilate(protected, int(protect_radius)).clamp(0, 1)
        refine = (1.0 - protected).clamp(0, 1)

        if used:
            summary = (
                "GLOBAL REFINER: protected original signage/text pixels from categories: "
                + ", ".join(used)
                + f". Protection radius={int(protect_radius)}px at SAM resolution."
            )
        else:
            summary = (
                "GLOBAL REFINER: no signage category detected; full frame is eligible "
                "for the global restoration pass."
            )
        return (refine, protected, summary)


class DOGMALocalRepairMasksV14:
    """
    Keeps local diffusion only for discrete objects.
    Broad surfaces and readable text are handled by the global refiner / exact
    source preservation instead of category-by-category regeneration.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {}
        for i in range(1, 7):
            req[f"mask_{i}"] = ("MASK",)
            req[f"category_{i}"] = ("STRING", {"forceInput": True})
        return {"required": req}

    RETURN_TYPES = ("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES = (
        "mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","summary"
    )
    FUNCTION = "gate"
    CATEGORY = "DOGMA/Semantic Detailer"

    @staticmethod
    def _one(mask):
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        mask = mask.detach().float().cpu()
        if mask.shape[0] > 1:
            mask = mask.max(dim=0, keepdim=True).values
        return mask.clamp(0, 1)

    def gate(
        self,
        mask_1, category_1,
        mask_2, category_2,
        mask_3, category_3,
        mask_4, category_4,
        mask_5, category_5,
        mask_6, category_6,
    ):
        masks = [
            self._one(mask_1), self._one(mask_2), self._one(mask_3),
            self._one(mask_4), self._one(mask_5), self._one(mask_6),
        ]
        cats = [
            category_1, category_2, category_3,
            category_4, category_5, category_6,
        ]

        active_families = {
            "vehicles", "roadway_people", "sidewalk_people", "people",
            "street_objects", "animals", "other"
        }

        out = []
        active = []
        skipped = []
        for m, c in zip(masks, cats):
            fam = _dogma_v11_family(c)
            if fam in active_families:
                out.append(m)
                active.append(f"{c} [{fam}]")
            else:
                out.append(torch.zeros_like(m))
                skipped.append(f"{c} [{fam}]")

        summary = (
            "LOCAL KLEIN ACTIVE: "
            + (", ".join(active) if active else "none")
            + "\nGLOBAL/PRESERVE ONLY: "
            + (", ".join(skipped) if skipped else "none")
        )
        return (*out, summary)


class DOGMAResizeToReferenceScaleV14:
    """
    Resizes an image to an exact multiple of another image's dimensions.
    Used after the 4x pixel upscaler so the final working master is exactly
    2x the original source, regardless of the global refiner input size.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "reference": ("IMAGE",),
            "scale": ("FLOAT", {
                "default": 2.0, "min": 0.25, "max": 8.0, "step": 0.05
            }),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "info")
    FUNCTION = "resize"
    CATEGORY = "DOGMA/Semantic Detailer"

    def resize(self, image, reference, scale):
        h = int(reference.shape[1])
        w = int(reference.shape[2])
        th = max(16, int(round(h * float(scale))))
        tw = max(16, int(round(w * float(scale))))
        # Keep Flux-friendly multiples while staying very close to exact x2.
        th = max(16, int(round(th / 16.0)) * 16)
        tw = max(16, int(round(tw / 16.0)) * 16)

        x = image[..., :3].movedim(-1, 1)
        y = F.interpolate(
            x, size=(th, tw), mode="bicubic",
            align_corners=False, antialias=True
        ).movedim(1, -1).clamp(0, 1)
        return (y, f"Working master resized to {tw}x{th} from reference {w}x{h} at scale {float(scale):.2f}.")


class DOGMAImageVRAMCleanupV14:
    """
    Generic image pass-through with an explicit model/cache unload barrier.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "unload_models": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "status")
    FUNCTION = "cleanup"
    CATEGORY = "DOGMA/Semantic Detailer"

    def cleanup(self, image, unload_models):
        import gc
        import comfy.model_management as mm
        if unload_models:
            try:
                mm.unload_all_models()
            except Exception:
                pass
        gc.collect()
        try:
            mm.soft_empty_cache()
        except Exception:
            pass
        return (
            image,
            "Model/cache cleanup executed before the next heavy stage."
        )


def _dogma_v14_policy(self, category, target):
    family = _dogma_v11_family(category)
    target = re.sub(r"\s+", " ", str(target or "").strip()).rstrip(".")
    if not target:
        target = "the intended historical setting"

    if family == "signage":
        return (
            "text sign:30,billboard:20,rooftop sign:20,building sign:20,"
            "shop sign:20,traffic sign:20",
            "PRESERVE EXACT SOURCE PIXELS. Signage is protected from generative editing "
            "because exact wording must not be hallucinated."
        )

    if family == "vehicles":
        return (
            "car:180,bus:15,truck:15,van:15,motorcycle:8,bicycle:8",
            f"Reconstruct only the masked vehicles as crisp, coherent, realistic vehicles appropriate to {target}. "
            "Fix fused bodies, melted geometry, impossible wheels, windows and perspective, and replace clearly "
            "anachronistic designs. Preserve the exact visible vehicle count, traffic density, positions, directions, "
            "approximate dimensions and EACH vehicle's individual approximate color. Keep natural color variety. "
            "Do not add vehicles and do not turn the traffic fleet white."
        )

    if family == "roadway_people":
        return (
            "person in roadway:60,pedestrian in traffic lane:60",
            f"Remove only the masked people who are clearly standing inside active traffic lanes. "
            f"Reconstruct the exposed road surface consistently with {target}. Preserve nearby cars, lane markings, "
            "curbs, lighting and perspective exactly. Do not remove people who are on sidewalks or safe pedestrian areas."
        )

    if family in ("sidewalk_people", "people"):
        sam = (
            "pedestrian on sidewalk:60,person on sidewalk:60"
            if family == "sidewalk_people"
            else "person:120"
        )
        return (
            sam,
            f"Reconstruct only the masked people as crisp, anatomically coherent, realistic pedestrians appropriate to {target}. "
            "Preserve count, pose, position, scale, direction and approximate clothing colors. Keep people on the sidewalk "
            "where they already are. Do not add or remove unrelated people."
        )

    if family == "street_objects":
        return (
            "traffic light:20,street lamp:25,pole:30,bollard:20,bench:15,street furniture:25",
            f"Reconstruct only the masked street objects as crisp, coherent objects appropriate to {target}. "
            "Preserve count, exact position, function, silhouette, lighting and approximate colors. "
            "Do not alter adjacent buildings, vehicles, pedestrians or readable signs."
        )

    if family == "animals":
        return (
            "animal:40,dog:20,cat:20,horse:20,bird:20",
            f"Reconstruct only the masked animals as anatomically coherent and appropriate to {target}. "
            "Preserve count, species, pose, position, scale and colors."
        )

    if family in ("architecture","vegetation","road","sky","water"):
        sam_map = {
            "architecture":"building:100,facade:100",
            "vegetation":"grass:120,lawn:120,tree:120,bush:120,vegetation:120",
            "road":"road:60,street:60,asphalt:60,sidewalk:80,curb:80",
            "sky":"sky:30,cloud:80",
            "water":"water:100",
        }
        return (
            sam_map[family],
            "Handled by the GLOBAL BASE restoration pass. Local generative edit disabled."
        )

    if family == "none":
        return (
            "nonexistent_placeholder_object_xyz:1",
            "Preserve the reference image unchanged."
        )

    simple = re.sub(r"[^a-zA-Z0-9 \-_/]", "", str(category)).strip() or "object"
    return (
        f"{simple}:220",
        f"Reconstruct only the masked {simple} so it is crisp, coherent and appropriate to {target}. "
        f"Preserve count, identity, position, scale, orientation and approximate color. Do not add unrelated objects."
    )


def _dogma_v14_build(self, planner_text, global_target):
    target = re.sub(r"\s+", " ", str(global_target or "").strip())

    # Always reserve slot 1 for signage protection. An empty signage SAM mask is
    # harmless on images without text, while this guarantees exact-text protection
    # on images that do contain signs.
    cats = ["signage"]
    seen = {"signage"}

    raw_lines = str(planner_text or "").replace(",", "\n").splitlines()
    for line in raw_lines:
        c = _clean_category(line)
        if not c:
            continue
        fam = _dogma_v11_family(c)

        # Broad surfaces are globally restored; they should not consume local slots.
        if fam in {"architecture","vegetation","road","sky","water","signage","none"}:
            continue

        key = c.lower()
        if key not in seen:
            seen.add(key)
            cats.append(c)

    priority = {
        "street_objects": 20,
        "roadway_people": 30,
        "animals": 40,
        "vehicles": 50,
        "people": 60,
        "sidewalk_people": 60,
        "other": 45,
        "none": 999,
    }
    tail = cats[1:]
    tail.sort(key=lambda x: priority.get(_dogma_v11_family(x), 45))
    cats = ["signage"] + tail[:5]

    while len(cats) < 6:
        cats.append("__none__")

    outputs = []
    preview = []
    for i, cat in enumerate(cats, 1):
        sam, edit = _dogma_v14_policy(self, cat, target)
        outputs.extend([cat, sam, edit])
        fam = _dogma_v11_family(cat)
        role = (
            "PROTECT ONLY" if fam == "signage"
            else "LOCAL REPAIR" if fam in {
                "vehicles","roadway_people","sidewalk_people","people",
                "street_objects","animals","other"
            }
            else "GLOBAL/NO-OP"
        )
        preview.append(
            f"SLOT {i}\n"
            f"role: {role}\n"
            f"family: {fam}\n"
            f"category: {cat}\n"
            f"SAM: {sam}\n"
            f"KLEIN: {edit}"
        )

    return ("\n\n".join(preview), *outputs)


# v14 policy: global BASE pass handles broad visual restoration; local distilled
# passes only repair discrete objects. Signage is always protected.
DOGMAScenePlanSlots._policy = _dogma_v14_policy
DOGMAScenePlanSlots.build = _dogma_v14_build



def _dogma_v14_settings(self, category):
    family = _dogma_v11_family(category)
    table = {
        "vehicles":        (0.13, 320, 176, 2400, 1536, 10, 1.00, 1.00),
        "roadway_people":  (0.15, 300, 144, 2100, 1536, 10, 1.00, 1.00),
        "sidewalk_people": (0.17, 300, 144, 2100, 1536, 10, 1.00, 1.00),
        "people":          (0.17, 300, 144, 2100, 1536, 10, 1.00, 1.00),
        "street_objects":  (0.20, 360, 160, 2200, 1408, 10, 1.00, 0.95),
        "animals":         (0.17, 320, 144, 2100, 1536, 10, 1.00, 1.00),
        "other":           (0.22, 420, 160, 2200, 1344, 8, 1.00, 0.90),
        # Protection/global-only categories intentionally become cheap no-op
        # local branches. Their SAM masks still exist for global protection.
        "signage":         (0.16, 300, 96, 1000, 512, 2, 1.00, 0.00),
        "architecture":    (0.30, 500, 96, 1000, 512, 2, 1.00, 0.00),
        "vegetation":      (0.30, 500, 96, 1000, 512, 2, 1.00, 0.00),
        "road":            (0.32, 500, 96, 1000, 512, 2, 1.00, 0.00),
        "sky":             (0.40, 500, 64, 1000, 512, 2, 1.00, 0.00),
        "water":           (0.34, 500, 64, 1000, 512, 2, 1.00, 0.00),
        "none":            (0.50, 300, 64, 768, 512, 1, 1.00, 0.00),
    }
    vals = table.get(family, table["other"])
    threshold, radius, context, max_source, target_side, max_crops, denoise, stitch = vals
    role = "LOCAL OBJECT REPAIR" if stitch > 0 else "GLOBAL/PRESERVE ONLY — local branch no-op"
    summary = (
        f"{family}: {role}; SAM={threshold:.2f}, source≤{max_source}, "
        f"model≤{target_side}, crops≤{max_crops}, local stitch alpha={stitch:.2f}"
    )
    return (
        float(threshold), int(radius), int(context), int(max_source),
        int(target_side), int(max_crops), float(denoise), summary,
        float(stitch)
    )

DOGMACategorySettingsV13.settings = _dogma_v14_settings



class DOGMAResizeMaskToImageV15:
    """Resize/union a semantic mask to exactly match a target IMAGE canvas."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mask": ("MASK",),
            "image": ("IMAGE",),
        }}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "resize"
    CATEGORY = "DOGMA/Semantic Detailer"

    def resize(self, mask, image):
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        mask = mask.detach().float()
        if mask.shape[0] > 1:
            mask = mask.max(dim=0, keepdim=True).values
        h = int(image.shape[1])
        w = int(image.shape[2])
        if tuple(mask.shape[-2:]) != (h, w):
            mask = F.interpolate(
                mask.unsqueeze(1), size=(h, w),
                mode="bilinear", align_corners=False
            ).squeeze(1)
        return (mask.clamp(0, 1),)
# ============================================================================
# DOGMA v16 — Semantic Divide & Conquer
# ============================================================================

def _dogma_v16_clean_category(line):
    s = str(line or "").strip()
    s = re.sub(r"^\s*[-*•]+\s*", "", s)
    s = re.sub(r"^\s*\d+\s*[\).:\-]\s*", "", s)
    s = s.strip().strip("`").strip()
    for sep in (" — ", " -> ", " => ", ": "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    s = re.sub(r"\s+", " ", s)
    return s[:64].strip()


def _dogma_v16_family(category):
    c = re.sub(r"\s+", " ", str(category or "").lower().strip())
    if c in ("", "none", "__none__", "unused", "n/a"):
        return "none"
    if any(k in c for k in ("vehicle", "car", "automobile", "bus", "truck", "van", "motorcycle", "bicycle", "traffic", "train", "tram", "subway", "railcar", "aircraft", "airplane", "aeroplane", "helicopter", "boat", "ship", "vessel")):
        return "vehicles"
    if any(k in c for k in ("person", "people", "pedestrian", "human", "crowd", "face", "portrait", "child", "man", "woman")):
        return "people"
    if any(k in c for k in ("architecture", "building", "facade", "façade", "house", "skyscraper", "high-rise", "high rise", "highrise", "tower", "tower block", "office block", "office building", "apartment block", "apartment building", "storefront", "bridge", "monument", "temple", "church", "cathedral", "castle", "cabin", "wall", "room", "interior", "ceiling", "door", "window")):
        return "architecture"
    if any(k in c for k in ("road", "street", "sidewalk", "pavement", "curb", "asphalt", "crosswalk", "ground", "floor", "path", "track", "terrain")):
        return "road"
    if any(k in c for k in ("vegetation", "tree", "grass", "bush", "shrub", "plant", "foliage", "lawn", "garden", "flower", "forest", "crop", "field")):
        return "vegetation"
    if any(k in c for k in ("street furniture", "traffic light", "street light", "streetlamp", "street lamp", "lamp post", "lamppost", "lamp", "pole", "bollard", "bench", "hydrant", "bus stop", "shelter")):
        return "street_objects"
    if any(k in c for k in ("animal", "dog", "cat", "horse", "bird", "fish", "wildlife", "insect")):
        return "animals"
    if any(k in c for k in ("furniture", "chair", "table", "sofa", "cabinet", "bed", "desk", "shelf", "wardrobe")):
        return "furniture"
    if any(k in c for k in ("clothing", "clothes", "garment", "dress", "shirt", "jacket", "coat", "shoe", "hat")):
        return "clothing"
    if any(k in c for k in ("machine", "machinery", "equipment", "tool", "appliance", "computer", "phone", "camera", "electronics", "instrument")):
        return "machinery"
    if any(k in c for k in ("food", "meal", "fruit", "vegetable", "dish", "bread", "cake", "drink", "beverage")):
        return "food"
    if any(k in c for k in ("water", "river", "lake", "sea", "ocean", "pool", "waterfall")):
        return "water"
    if any(k in c for k in ("sky", "cloud", "clouds")):
        return "sky"
    if any(k in c for k in ("product", "object", "device", "package", "bottle", "container", "sculpture", "statue", "toy", "book")):
        return "product"
    return "other"


def _dogma_v16_sam_policy(category):
    c = re.sub(r"\s+", " ", str(category or "").lower().strip())
    fam = _dogma_v16_family(c)
    if fam == "vehicles":
        return "car:140,bus:12,truck:12,van:12,motorcycle:8,bicycle:8,train:8,tram:8,boat:8,aircraft:6", 0.16
    if fam == "people":
        return "person:100", 0.18
    if fam == "architecture":
        # Preserve useful specificity when the planner supplied a basic object class.
        # Broad fallback is used ONLY when the category itself is broad.
        specific = [
            ("cathedral", "cathedral:30"), ("church", "church:30"), ("temple", "temple:30"),
            ("castle", "castle:30"), ("bridge", "bridge:30"), ("skyscraper", "skyscraper:30"),
            ("high rise", "high rise building:30"), ("high-rise", "high rise building:30"),
            ("tower", "tower:30"), ("house", "house:30"), ("cabin", "cabin:30"),
            ("storefront", "storefront:30"), ("monument", "monument:30"),
            ("door", "door:35"), ("window", "window:60"), ("wall", "wall:25"),
            ("room", "room:20"), ("interior", "interior:20"),
        ]
        for key,prompt in specific:
            if key in c:
                return prompt, 0.25
        return "building:24,facade:12", 0.29
    if fam == "road":
        if "floor" in c: return "floor:30", 0.28
        if "pavement" in c: return "pavement:30", 0.28
        if "sidewalk" in c: return "sidewalk:30", 0.28
        if "curb" in c: return "curb:24", 0.27
        if "crosswalk" in c: return "crosswalk:24", 0.27
        if "track" in c or "rail" in c: return "railway track:24", 0.27
        if "terrain" in c or "ground" in c: return "ground:24", 0.30
        return "road:24,sidewalk:12,curb:10,crosswalk:8", 0.29
    if fam == "vegetation":
        if "tree" in c: return "tree:35", 0.24
        if "grass" in c or "lawn" in c: return "grass:30,lawn:20", 0.25
        if "flower" in c: return "flower:30", 0.23
        if "bush" in c or "shrub" in c: return "bush:30,shrub:20", 0.24
        return "vegetation:30,tree:18,grass:18,bush:12", 0.27
    if fam == "street_objects":
        if "lamp" in c: return "street lamp:32,lamppost:24", 0.20
        if "traffic light" in c: return "traffic light:30", 0.20
        if "bench" in c: return "bench:24", 0.20
        if "bollard" in c: return "bollard:24", 0.20
        if "shelter" in c or "bus stop" in c: return "bus shelter:24,bus stop:18", 0.22
        return "street furniture:24,street lamp:18,pole:18,bollard:12,bench:10", 0.23
    if fam == "animals":
        # Exact class if useful, broad animal fallback otherwise.
        for key in ("dog","cat","horse","bird","fish","insect"):
            if key in c: return f"{key}:30", 0.18
        return "animal:30", 0.19
    if fam == "furniture":
        for key in ("chair","table","sofa","cabinet","bed","desk","shelf","wardrobe"):
            if key in c: return f"{key}:30", 0.21
        return "furniture:30", 0.23
    if fam == "clothing":
        return "clothing:30,garment:18", 0.22
    if fam == "machinery":
        simple=re.sub(r"[^a-z0-9 _\-/]","",c).strip()
        return (f"{simple}:30" if simple not in ("machinery","equipment","machine") else "machinery:30,equipment:20"), 0.22
    if fam == "food":
        return "food:30", 0.22
    if fam == "water":
        return "water:24", 0.29
    if fam == "sky":
        return "cloud:24" if "cloud" in c else "sky:12,cloud:18", 0.32
    if fam == "none":
        return "nonexistent_placeholder_object_xyz:1", 0.50
    # Unknown categories stay useful: use the exact simple noun phrase, not an "other" super-category.
    simple = re.sub(r"[^a-zA-Z0-9 _\-/]", "", str(category or "object")).strip() or "object"
    return f"{simple}:30", 0.24


class DOGMASemanticPlanV16:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"planner_text": ("STRING", {"forceInput": True, "multiline": True})}}

    RETURN_TYPES = ("STRING",) + tuple(x for _ in range(5) for x in ("STRING", "STRING", "FLOAT"))
    RETURN_NAMES = ("plan_preview",) + tuple(
        x for i in range(1, 6) for x in (f"category_{i}", f"sam_prompt_{i}", f"sam_threshold_{i}")
    )
    FUNCTION = "build"
    CATEGORY = "DOGMA/Semantic Detailer"

    def build(self, planner_text):
        forbidden = (
            "deformed object", "malformed object", "artifact", "artifacts", "detail", "details",
            "scene", "background", "foreground", "image quality", "blur", "noise", "restoration",
            "signage", "text", "letter", "billboard", "logo",
        )
        lines = str(planner_text or "").replace(",", "\n").splitlines()
        cats, seen = [], set()
        for line in lines:
            c = _dogma_v16_clean_category(line)
            if not c:
                continue
            low = c.lower()
            if any(k in low for k in forbidden):
                continue
            if low in seen:
                continue
            seen.add(low)
            cats.append(c)
            if len(cats) >= 5:
                break
        while len(cats) < 5:
            cats.append("none")

        outputs, preview = [], []
        for i, cat in enumerate(cats, 1):
            sam, threshold = _dogma_v16_sam_policy(cat)
            outputs.extend([cat, sam, float(threshold)])
            preview.append(f"SLOT {i}: {cat}\nSAM: {sam}\nthreshold: {threshold:.2f}")
        return ("\n\n".join(preview), *outputs)


class DOGMARestorationBriefV16:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "brief": ("STRING", {"multiline": True, "default": "Preserve the source image faithfully."})
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("brief",)
    FUNCTION = "emit"
    CATEGORY = "DOGMA/Semantic Detailer"

    def emit(self, brief):
        return (str(brief),)


def _dogma_v16_mask_from_image(image):
    if image.ndim == 3:
        image = image.unsqueeze(0)
    x = image.float()
    if x.shape[-1] >= 3:
        mask = x[..., :3].mean(dim=-1)
    else:
        mask = x[..., 0]
    if mask.shape[0] > 1:
        mask = mask.max(dim=0, keepdim=True).values
    return mask.clamp(0, 1)


def _dogma_v16_dilate(mask, radius):
    radius = int(radius)
    if radius <= 0:
        return mask
    kernel = radius * 2 + 1
    return F.max_pool2d(
        mask.unsqueeze(1), kernel_size=kernel, stride=1, padding=radius
    ).squeeze(1)


def _dogma_v16_edit_policy(category):
    fam = _dogma_v16_family(category)
    if fam == "vehicles":
        return (
            "VEHICLES: reconstruct malformed, melted or fused existing vehicles into coherent vehicles. "
            "Preserve the same vehicle count, exact positions, directions, approximate sizes and each vehicle's approximate individual colour. "
            "Keep period/style plausibility from the project brief. Do not add vehicles or standardise all cars to one colour."
        )
    if fam == "people":
        return (
            "PEOPLE: repair malformed anatomy, silhouettes, faces and clothing only where already present. "
            "Preserve person count, poses, positions, scale, direction and approximate clothing colours. "
            "Do not add or remove people unless the project brief explicitly requires it."
        )
    if fam == "architecture":
        return (
            "ARCHITECTURE: actively reconstruct smeared windows, facade edges, balconies and structural geometry while preserving the exact building identity, footprint, perspective, lighting and existing colours. "
            "Do not redesign buildings and do not invent signage or readable text."
        )
    if fam == "road":
        return (
            "ROAD/GROUND: repair muddy or malformed road, pavement, curb and marking geometry while preserving the exact layout, lanes, perspective, surface colour and existing markings. "
            "Do not create vehicles, people, signs or new road features."
        )
    if fam == "vegetation":
        return (
            "VEGETATION: resolve existing vegetation into natural detail while preserving its exact footprint, type and density. "
            "Grass/lawn must remain grass/lawn; do not turn lawns into forests, gardens or new shrubs."
        )
    if fam == "street_objects":
        return (
            "STREET OBJECTS: repair existing lamps, poles, traffic lights, bollards, benches and similar objects. "
            "Preserve count, position, function, silhouette and approximate colours. Do not add new street furniture or readable text."
        )
    if fam == "animals":
        return (
            "ANIMALS: repair only existing animals into anatomically coherent forms. Preserve count, species/type, pose, position, scale and colour. Do not add animals."
        )
    if fam == "furniture":
        return (
            "FURNITURE: repair only existing furniture geometry and material detail. Preserve count, identity, position, proportions, orientation and colour. Do not add or redesign furniture."
        )
    if fam == "clothing":
        return (
            "CLOTHING: repair only existing garment structure and fabric detail while preserving wearer, garment type, colour, cut and position. Do not invent accessories."
        )
    if fam == "machinery":
        return (
            "MACHINERY/EQUIPMENT: repair only existing mechanical forms, edges and components. Preserve identity, count, position, proportions and colour. Do not invent new parts."
        )
    if fam == "food":
        return (
            "FOOD: repair only existing food shapes, surfaces and texture while preserving item count, type, arrangement and colour. Do not add ingredients or dishes."
        )
    if fam == "water":
        return (
            "WATER: repair only local water-surface artifacts while preserving shoreline, reflections, colour, lighting and wave structure. Do not create objects in the water."
        )
    if fam == "sky":
        return (
            "SKY: repair only local sky/cloud artifacts while preserving lighting, haze, colour and cloud placement. Do not invent dramatic weather."
        )
    if fam == "none":
        return ""
    c = re.sub(r"\s+", " ", str(category)).strip()
    return (
        f"{c.upper()}: repair only the existing {c}. Preserve count, identity, position, scale, orientation and colour. "
        f"Do not add new {c} or unrelated content."
    )


class DOGMATileSemanticComposerV16:
    @classmethod
    def INPUT_TYPES(cls):
        req = {
            "tile": ("IMAGE",),
            "sign_mask_tile": ("IMAGE",),
        }
        for i in range(1, 6):
            req[f"mask_tile_{i}"] = ("IMAGE",)
            req[f"category_{i}"] = ("STRING", {"forceInput": True})
        req.update(
            {
                "restoration_brief": ("STRING", {"forceInput": True, "multiline": True}),
                "mask_threshold": ("FLOAT", {"default": 0.45, "min": 0.05, "max": 0.95, "step": 0.01}),
                "min_coverage": ("FLOAT", {"default": 0.0005, "min": 0.0, "max": 0.20, "step": 0.0005}),
                "noise_grow": ("INT", {"default": 14, "min": 0, "max": 128, "step": 1}),
                "composite_grow": ("INT", {"default": 2, "min": 0, "max": 64, "step": 1}),
                "sign_protect_radius": ("INT", {"default": 12, "min": 0, "max": 128, "step": 1}),
            }
        )
        return {"required": req}

    RETURN_TYPES = ("MASK", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("noise_mask", "composite_mask", "tile_prompt", "info")
    FUNCTION = "compose"
    CATEGORY = "DOGMA/Semantic Detailer"

    def compose(
        self,
        tile,
        sign_mask_tile,
        mask_tile_1,
        category_1,
        mask_tile_2,
        category_2,
        mask_tile_3,
        category_3,
        mask_tile_4,
        category_4,
        mask_tile_5,
        category_5,
        restoration_brief,
        mask_threshold,
        min_coverage,
        noise_grow,
        composite_grow,
        sign_protect_radius,
    ):
        h, w = int(tile.shape[1]), int(tile.shape[2])

        sign = _dogma_v16_mask_from_image(sign_mask_tile)
        if sign.shape[-2:] != (h, w):
            sign = F.interpolate(
                sign.unsqueeze(1), size=(h, w), mode="bilinear", align_corners=False
            ).squeeze(1)
        sign = (sign > float(mask_threshold)).float()
        sign = _dogma_v16_dilate(sign, int(sign_protect_radius)).clamp(0, 1)

        pairs = [
            (mask_tile_1, category_1),
            (mask_tile_2, category_2),
            (mask_tile_3, category_3),
            (mask_tile_4, category_4),
            (mask_tile_5, category_5),
        ]
        selected, hard, coverage_report = [], [], []

        for image, category in pairs:
            fam = _dogma_v16_family(category)
            if fam == "none":
                continue
            mask = _dogma_v16_mask_from_image(image)
            if mask.shape[-2:] != (h, w):
                mask = F.interpolate(
                    mask.unsqueeze(1), size=(h, w), mode="bilinear", align_corners=False
                ).squeeze(1)
            mask = (mask > float(mask_threshold)).float()
            coverage = float(mask.mean().item())
            coverage_report.append(f"{category}={coverage * 100:.1f}%")
            if coverage < float(min_coverage):
                continue

            # Discrete-object masks that cover most of a tile are likely detector failures.
            if fam in (
                "vehicles", "people", "street_objects", "animals", "furniture",
                "clothing", "machinery", "food", "product", "other",
            ) and coverage > 0.60:
                coverage_report[-1] += " [SKIPPED: implausibly broad]"
                continue

            selected.append((str(category), fam, mask))
            hard.append(mask)

        if hard:
            base = torch.stack(hard, dim=0).max(dim=0).values.clamp(0, 1)
        else:
            base = torch.zeros((1, h, w), dtype=torch.float32, device=tile.device)

        # Broad semantic regions recreate the successful large-block behavior.
        # Readable text/signage remains excluded from both masks.
        noise = _dogma_v16_dilate(base, int(noise_grow)).clamp(0, 1) * (1.0 - sign)
        composite = _dogma_v16_dilate(base, int(composite_grow)).clamp(0, 1) * (1.0 - sign)

        policies = [_dogma_v16_edit_policy(category) for category, _, _ in selected]
        policies = [policy for policy in policies if policy]
        active = ", ".join(category for category, _, _ in selected) if selected else "none"
        brief = re.sub(r"\s+", " ", str(restoration_brief or "").strip())

        prompt = (
            "MASKED RESTORATION OF THIS EXACT LARGE OVERLAPPING SOURCE TILE. "
            "The entire tile reference is spatial and photographic ground truth. Generate only inside the supplied mask; preserve unmasked content exactly. "
            "Do not create, copy, rewrite or alter readable text, logos or signage; those pixels are protected. "
            "Do not invent content in ambiguous areas. Preserve object count, positions, camera geometry, perspective, lighting direction and local colour continuity. "
            f"PROJECT BRIEF: {brief} "
        )
        if policies:
            prompt += " ACTIVE REPAIR POLICIES: " + " ".join(policies)
        else:
            prompt += " No valid semantic repair area is present in this tile; preserve it unchanged."

        info = (
            f"active: {active} | raw semantic coverage={float(base.mean().item()) * 100:.1f}% | "
            f"noise mask={float(noise.mean().item()) * 100:.1f}% | "
            f"final mask={float(composite.mean().item()) * 100:.1f}% | "
            f"sign protected={float(sign.mean().item()) * 100:.1f}% | detections: "
            + ("; ".join(coverage_report) if coverage_report else "none")
        )
        return (noise.float(), composite.float(), prompt, info)


class DOGMASemanticOverviewV16:
    @classmethod
    def INPUT_TYPES(cls):
        req = {"sign_mask": ("MASK",)}
        for i in range(1, 6):
            req[f"mask_{i}"] = ("MASK",)
            req[f"category_{i}"] = ("STRING", {"forceInput": True})
        return {"required": req}

    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("repair_union_image", "sign_image", "info")
    FUNCTION = "overview"
    CATEGORY = "DOGMA/Semantic Detailer"

    def overview(
        self,
        sign_mask,
        mask_1,
        category_1,
        mask_2,
        category_2,
        mask_3,
        category_3,
        mask_4,
        category_4,
        mask_5,
        category_5,
    ):
        masks = [mask_1, mask_2, mask_3, mask_4, mask_5]
        cats = [category_1, category_2, category_3, category_4, category_5]
        h = max(int(m.shape[-2]) for m in masks + [sign_mask])
        w = max(int(m.shape[-1]) for m in masks + [sign_mask])

        def norm(mask):
            if mask.ndim == 2:
                mask = mask.unsqueeze(0)
            mask = mask.float()
            if mask.shape[0] > 1:
                mask = mask.max(dim=0, keepdim=True).values
            if mask.shape[-2:] != (h, w):
                mask = F.interpolate(
                    mask.unsqueeze(1), size=(h, w), mode="bilinear", align_corners=False
                ).squeeze(1)
            return mask.clamp(0, 1)

        sign = norm(sign_mask)
        active, info = [], []
        for mask, category in zip(masks, cats):
            normalized = norm(mask)
            if _dogma_v16_family(category) != "none":
                active.append(normalized)
            info.append(f"{category}: {float((normalized > 0.5).float().mean().item()) * 100:.1f}%")

        union = torch.stack(active, dim=0).max(dim=0).values if active else torch.zeros_like(sign)
        union = (union * (1.0 - (sign > 0.5).float())).clamp(0, 1)
        union_image = union.unsqueeze(-1).repeat(1, 1, 1, 3)
        sign_image = sign.unsqueeze(-1).repeat(1, 1, 1, 3)
        return (
            union_image,
            sign_image,
            " | ".join(info) + f" | sign: {float((sign > 0.5).float().mean().item()) * 100:.1f}%",
        )


# ============================================================================
# DOGMA COMPLEX v21 — Global conservative restoration -> SAM -> macro edits
# ============================================================================

def _dogma_v21_family(category):
    c = str(category or "").lower().strip()
    if c in ("", "none", "__none__", "unused", "n/a"):
        return "none"
    if any(k in c for k in ("signage","sign","lettering","billboard","advertising","logo","text","marquee")):
        return "signage"
    if any(k in c for k in ("traffic light","street light","street lamp","lamp post","lamppost","bollard","bench","hydrant","street furniture","pole")):
        return "street_objects"
    if any(k in c for k in ("roadway pedestrian","pedestrian in road","person in road","person in traffic","people in road","roadway people")):
        return "roadway_people"
    if any(k in c for k in ("person","people","pedestrian","human","crowd","face")):
        return "people"
    if any(k in c for k in ("vehicle","car","automobile","bus","truck","van","motorcycle","bicycle")):
        return "vehicles"
    if any(k in c for k in ("architecture","building","facade","façade","house","tower","storefront","wall")):
        return "architecture"
    if any(k in c for k in ("road","street","sidewalk","pavement","curb","asphalt","crosswalk","ground","floor")):
        return "road"
    if any(k in c for k in ("vegetation","tree","grass","bush","shrub","plant","foliage","lawn","garden")):
        return "vegetation"
    if any(k in c for k in ("animal","dog","cat","horse","bird")):
        return "animals"
    if any(k in c for k in ("furniture","chair","table","sofa","cabinet","bed","desk")):
        return "furniture"
    if any(k in c for k in ("clothing","clothes","garment","dress","shirt","jacket","coat","shoe")):
        return "clothing"
    if any(k in c for k in ("machine","machinery","equipment","tool","appliance")):
        return "machinery"
    if any(k in c for k in ("food","meal","fruit","vegetable","dish")):
        return "food"
    if any(k in c for k in ("water","river","lake","sea","ocean","pool")):
        return "water"
    if any(k in c for k in ("sky","cloud")):
        return "sky"
    if any(k in c for k in ("product","device","package","bottle")):
        return "product"
    return "other"


def _dogma_v21_sam_policy(category):
    fam = _dogma_v21_family(category)
    table = {
        "architecture": ("building:40,facade:40", 0.28),
        "road": ("road:24,sidewalk:28,curb:18,crosswalk:14", 0.28),
        "vegetation": ("grass:24,tree:28,bush:22,vegetation:28,lawn:20", 0.26),
        "sky": ("sky:12,cloud:18", 0.32),
        "water": ("water:18", 0.30),
        "vehicles": ("car:180,bus:16,truck:16,van:16,motorcycle:10,bicycle:10", 0.14),
        "street_objects": ("traffic light:14,street lamp:18,pole:20,bollard:12,bench:10,street furniture:18", 0.22),
        "roadway_people": ("person:120", 0.17),
        "people": ("person:120", 0.18),
        "signage": ("text sign:28,billboard:22,rooftop sign:18,building sign:22,shop sign:20,traffic sign:20", 0.20),
        "animals": ("animal:28,dog:14,cat:14,horse:10,bird:10", 0.18),
        "furniture": ("chair:22,table:22,sofa:12,cabinet:12,furniture:26", 0.22),
        "clothing": ("clothing:30,garment:20", 0.22),
        "machinery": ("machinery:25,equipment:25,machine:20", 0.22),
        "food": ("food:30", 0.22),
        "product": ("product:30,device:20,package:20,bottle:20", 0.22),
        "none": ("nonexistent_placeholder_object_xyz:1", 0.90),
    }
    if fam in table:
        return table[fam]
    simple = re.sub(r"[^a-zA-Z0-9 _\-/]", "", str(category or "object")).strip() or "object"
    return f"{simple}:28", 0.24


class DOGMASemanticPlanV21:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"planner_text":("STRING",{"forceInput":True,"multiline":True})}}

    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","FLOAT"))
    RETURN_NAMES=("plan_preview",)+tuple(
        x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"sam_threshold_{i}")
    )
    FUNCTION="build"
    CATEGORY="DOGMA/Semantic Detailer"

    def build(self,planner_text):
        forbidden=(
            "deformed object","malformed object","artifact","artifacts","detail","details",
            "scene","background","foreground","image quality","blur","noise","restoration"
        )
        raw=str(planner_text or "").replace(",", "\n").splitlines()
        found=[]
        seen_fam=set()
        for line in raw:
            c=_dogma_v16_clean_category(line)
            if not c:
                continue
            low=c.lower()
            if any(k==low or low.startswith(k+":") for k in forbidden):
                continue
            fam=_dogma_v21_family(c)
            if fam=="none" or fam in seen_fam:
                continue
            seen_fam.add(fam)
            found.append((fam,c))
        priority={
            "architecture":10,"road":20,"vegetation":30,"sky":35,"water":36,
            "vehicles":50,"street_objects":60,"animals":62,"furniture":62,
            "machinery":62,"product":62,"food":62,"clothing":64,
            "roadway_people":70,"people":75,"other":80,"signage":100,
        }
        found.sort(key=lambda fc: priority.get(fc[0],80))
        found=found[:6]
        while len(found)<6:
            found.append(("none","none"))
        out=[]; preview=[]
        for idx,(fam,cat) in enumerate(found,1):
            sam,thr=_dogma_v21_sam_policy(cat)
            out.extend([cat,sam,float(thr)])
            preview.append(
                f"SLOT {idx}: {cat} [{fam}]\nSAM: {sam}\nthreshold: {thr:.2f}"
            )
        return ("\n\n".join(preview),*out)


def _dogma_v21_edit_policy(category, brief):
    fam=_dogma_v21_family(category)
    b=str(brief or "").strip()
    common=(
        "Work only inside the supplied semantic mask. The CURRENT MASTER crop is the spatial and photographic truth. "
        "The ORIGINAL same-position reference is identity evidence: preserve real positions, count, proportions, colours and scene content. "
        "Do not copy unrelated content from the reference and do not add new objects. "
    )
    policies={
        "architecture":(
            "ARCHITECTURE: actively rebuild smeared windows, facade edges, balconies, roof lines and structural geometry. "
            "Keep the exact building identity, footprint, perspective, materials, existing colour relationships, lighting and era. "
            "Do not modernize, redesign or invent signage."
        ),
        "road":(
            "ROAD/GROUND: repair muddy asphalt, pavement, curbs, lane/crosswalk markings and broken surface geometry. "
            "Preserve exact road layout, perspective, markings, surface colour and traffic organization. "
            "Do not add vehicles, people, signs or new road features."
        ),
        "vegetation":(
            "VEGETATION: improve existing natural detail and continuity while preserving exact footprint, type and density. "
            "Grass/lawn must remain grass/lawn. Do not turn lawn into bushes, trees, flowers, forest or garden."
        ),
        "sky":(
            "SKY: repair only real local sky/cloud artifacts while preserving lighting, haze, colour, cloud placement and atmospheric depth. "
            "Do not invent dramatic weather."
        ),
        "water":(
            "WATER: repair only existing water surface artifacts while preserving shoreline, reflections, colour, lighting and wave structure."
        ),
        "vehicles":(
            "VEHICLES: reconstruct malformed, melted, fused or unreadable existing vehicles into coherent vehicles appropriate to the project era. "
            "Preserve approximate vehicle count, exact traffic positions, directions, perspective scale and EACH vehicle's approximate individual colour. "
            "Very small distant vehicles must remain small and atmospheric but should read as coherent vehicles rather than blobs. "
            "Do not standardize all cars to one model or colour and do not populate empty road/grass/sidewalk areas."
        ),
        "street_objects":(
            "STREET OBJECTS: repair existing lamps, poles, traffic lights, bollards, benches and similar objects. "
            "Preserve count, exact position, function, silhouette and approximate colour. Do not add furniture or transfer signage."
        ),
        "roadway_people":(
            "ROADWAY PEOPLE: preserve legitimate crossing pedestrians, but remove clearly implausible isolated people standing in active vehicle lanes "
            "when the source does not support a real crossing situation; reconstruct the underlying road naturally. "
            "Repair malformed anatomy for people that should remain."
        ),
        "people":(
            "PEOPLE: repair malformed anatomy, silhouettes, faces and clothing only where people already exist. "
            "Preserve legitimate person count, poses, positions, scale, direction and approximate clothing colours. "
            "Do not create crowds or extra pedestrians."
        ),
        "signage":(
            "SIGNAGE / LETTERING: preserve the SAME existing sign, panel, graphic layout and visible glyph shapes in the SAME location. "
            "Improve photographic definition, edges, material and local legibility only to the extent supported by the original reference. "
            "If characters are unreadable or ambiguous in the original, KEEP THEM semantically unreadable/ambiguous: do not infer, complete, translate, replace or invent words. "
            "Never copy a word, logo or sign from another part of the image."
        ),
        "animals":(
            "ANIMALS: repair only existing animals. Preserve species/type, count, pose, position, scale and colour. Do not add animals."
        ),
        "furniture":(
            "FURNITURE: repair existing furniture geometry/material detail while preserving identity, count, position, proportions, orientation and colour."
        ),
        "machinery":(
            "MACHINERY/EQUIPMENT: repair only existing mechanical forms and components. Preserve identity, count, position, proportions and colour."
        ),
        "clothing":(
            "CLOTHING: repair only existing garment structure/fabric detail while preserving wearer, garment type, colour, cut and position."
        ),
        "food":(
            "FOOD: repair only existing food shapes/surfaces while preserving item count, type, arrangement and colour."
        ),
        "product":(
            "PRODUCT/OBJECT: repair only the existing object while preserving identity, count, position, proportions, orientation, labels and colour."
        ),
        "none":"Preserve the current master unchanged.",
    }
    p=policies.get(fam, f"{str(category).upper()}: repair only this existing category in place. Preserve identity, count, position, scale, orientation and colour.")
    return common+p+(" "+b if b else "")


class DOGMACategorySettingsV21:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "restoration_brief":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("INT","INT","INT","INT","INT","FLOAT","STRING","STRING")
    RETURN_NAMES=("group_radius","context_px","max_source_side","target_long_side","max_crops","stitch_strength","edit_prompt","summary")
    FUNCTION="settings"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings(self,category,restoration_brief):
        fam=_dogma_v21_family(category)
        # region grouping, context, source bbox advisory, MODEL max long side <= 2000, crop cap, final alpha
        table={
            "architecture":(900,192,3800,1920,6,0.88),
            "road":(1050,192,4000,1792,6,0.68),
            "vegetation":(950,192,3800,1792,6,0.72),
            "sky":(1200,128,4400,1536,4,0.55),
            "water":(1000,160,4000,1664,4,0.65),
            "vehicles":(560,208,3400,1920,8,1.00),
            "street_objects":(520,192,3000,1920,8,0.95),
            "roadway_people":(460,192,2800,1920,8,1.00),
            "people":(460,192,2800,1920,8,1.00),
            "signage":(440,192,2800,1920,8,0.78),
            "animals":(460,192,2800,1920,8,1.00),
            "furniture":(520,192,3000,1920,8,0.95),
            "machinery":(520,192,3000,1920,8,0.95),
            "clothing":(420,160,2400,1920,8,0.95),
            "food":(420,160,2400,1920,8,0.95),
            "product":(480,176,2800,1920,8,0.95),
            "other":(560,192,3200,1792,8,0.88),
            "none":(480,128,1800,1024,1,0.00),
        }
        vals=table.get(fam,table["other"])
        prompt=_dogma_v21_edit_policy(category,restoration_brief)
        radius,context,max_source,target,crops,alpha=vals
        summary=(
            f"{fam}: region grouping={radius}px, context={context}px, source advisory≤{max_source}px, "
            f"Klein crop long side≤{target}px (hard max <2000), macro crops≤{crops}, stitch alpha={alpha:.2f}"
        )
        return int(radius),int(context),int(max_source),int(target),int(crops),float(alpha),prompt,summary


class DOGMAProtectedMasksV21:
    @classmethod
    def INPUT_TYPES(cls):
        req={}
        for i in range(1,7):
            req[f"mask_{i}"]=("MASK",)
            req[f"category_{i}"]=("STRING",{"forceInput":True})
        req["protect_radius"]=("INT",{"default":12,"min":0,"max":96,"step":1})
        return {"required":req}
    RETURN_TYPES=("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","summary")
    FUNCTION="protect"
    CATEGORY="DOGMA/Semantic Detailer"

    def protect(self,mask_1,category_1,mask_2,category_2,mask_3,category_3,
                mask_4,category_4,mask_5,category_5,mask_6,category_6,protect_radius):
        raw=[mask_1,mask_2,mask_3,mask_4,mask_5,mask_6]
        cats=[category_1,category_2,category_3,category_4,category_5,category_6]
        fams=[_dogma_v21_family(c) for c in cats]
        H=max(int(m.shape[-2]) for m in raw)
        W=max(int(m.shape[-1]) for m in raw)
        masks=[]
        for m in raw:
            if m.ndim==2: m=m.unsqueeze(0)
            m=m.float()
            if m.shape[0]>1: m=m.max(dim=0,keepdim=True).values
            if m.shape[-2:]!=(H,W):
                m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            masks.append(m.clamp(0,1))
        blockers_for={
            "architecture":{"vehicles","people","roadway_people","signage","street_objects","animals"},
            "road":{"vehicles","people","roadway_people","signage","street_objects","animals"},
            "vegetation":{"vehicles","people","roadway_people","signage","street_objects","architecture","animals"},
            "sky":{"architecture","vehicles","people","roadway_people","signage","street_objects"},
            "water":{"vehicles","people","roadway_people","animals"},
        }
        r=int(protect_radius)
        outs=[]; report=[]
        for i,(m,fam) in enumerate(zip(masks,fams)):
            bfs=blockers_for.get(fam,set())
            blockers=[masks[j] for j,f in enumerate(fams) if j!=i and f in bfs]
            if blockers:
                p=torch.stack(blockers,dim=0).max(dim=0).values
                if r>0:
                    p=F.max_pool2d(p.unsqueeze(1),kernel_size=2*r+1,stride=1,padding=r).squeeze(1)
                out=(m*(1-p.clamp(0,1))).clamp(0,1)
                report.append(f"slot {i+1} {fam}: protected from {', '.join(sorted(bfs.intersection(set(fams))))}")
            else:
                out=m
                report.append(f"slot {i+1} {fam}: unchanged")
            outs.append(out)
        return (*outs,"\n".join(report))


class DOGMASemanticMacroCropsV21:
    """
    Few large semantic REGION crops from the current master, plus an aligned
    ORIGINAL-source reference crop for each region. Current crop and original
    reference are always the exact same spatial location after resizing source
    to master coordinates. Model long side is hard-capped at 2000.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "reference_image":("IMAGE",),
            "masks":("MASK",),
            "group_radius":("INT",{"default":560,"min":0,"max":2400,"step":16}),
            "context_px":("INT",{"default":192,"min":0,"max":2048,"step":16}),
            "max_source_side":("INT",{"default":3400,"min":512,"max":8192,"step":16}),
            "target_long_side":("INT",{"default":1920,"min":512,"max":2000,"step":16}),
            "max_crops":("INT",{"default":8,"min":1,"max":20,"step":1}),
            "mask_threshold":("FLOAT",{"default":0.5,"min":0.01,"max":0.99,"step":0.01}),
        }}
    RETURN_TYPES=("IMAGE","IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","reference_crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,True,False)
    FUNCTION="make_crops"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _components(binary):
        arr=binary.astype("uint8",copy=False)
        h,w=arr.shape
        seen=np.zeros_like(arr,dtype=np.uint8)
        comps=[]
        for y in range(h):
            for x in range(w):
                if arr[y,x]==0 or seen[y,x]: continue
                stack=[(y,x)]; seen[y,x]=1
                minx=maxx=x; miny=maxy=y; count=0
                while stack:
                    cy,cx=stack.pop(); count+=1
                    minx=min(minx,cx); maxx=max(maxx,cx)
                    miny=min(miny,cy); maxy=max(maxy,cy)
                    for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                        if 0<=ny<h and 0<=nx<w and arr[ny,nx] and not seen[ny,nx]:
                            seen[ny,nx]=1; stack.append((ny,nx))
                comps.append((minx,miny,maxx+1,maxy+1,count))
        return comps

    @staticmethod
    def _resize_image(image,nh,nw):
        return F.interpolate(
            image.movedim(-1,1),size=(nh,nw),mode="bicubic",
            align_corners=False,antialias=True
        ).movedim(1,-1).clamp(0,1)

    @staticmethod
    def _resize_mask(mask,nh,nw):
        return F.interpolate(
            mask.unsqueeze(1).float(),size=(nh,nw),
            mode="bilinear",align_corners=False
        ).squeeze(1).clamp(0,1)

    @staticmethod
    def _target_size(h,w,long_side):
        long_side=min(2000,int(long_side))
        scale=min(1.0,float(long_side)/float(max(h,w)))
        # Do not upsample a crop that is already smaller than target.
        nh=max(16,int(round((h*scale)/16.0))*16)
        nw=max(16,int(round((w*scale)/16.0))*16)
        return nh,nw

    @staticmethod
    def _gap(a,b):
        ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
        dx=max(0,max(ax1,bx1)-min(ax2,bx2))
        dy=max(0,max(ay1,by1)-min(ay2,by2))
        return dx*dx+dy*dy

    def make_crops(self,image,reference_image,masks,group_radius,context_px,
                   max_source_side,target_long_side,max_crops,mask_threshold):
        if image.ndim!=4 or image.shape[0]<1:
            raise ValueError("DOGMA v21 Macro Crops expects IMAGE [B,H,W,C].")
        src=image[0:1,...,:3]
        H,W=int(src.shape[1]),int(src.shape[2])

        ref=reference_image[0:1,...,:3]
        if ref.shape[1]!=H or ref.shape[2]!=W:
            ref=self._resize_image(ref,H,W)

        if masks.ndim==2: masks=masks.unsqueeze(0)
        masks=masks.float()
        if masks.shape[-2:]!=(H,W):
            masks=F.interpolate(masks.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
        union=masks.max(dim=0).values.clamp(0,1)
        hard=union>float(mask_threshold)

        if not torch.any(hard):
            side=min(H,W,1024)
            x=max(0,(W-side)//2); y=max(0,(H-side)//2)
            cur=src[:,y:y+side,x:x+side,:]
            old=ref[:,y:y+side,x:x+side,:]
            nh,nw=self._target_size(side,side,min(int(target_long_side),side))
            cur=self._resize_image(cur,nh,nw); old=self._resize_image(old,nh,nw)
            z=torch.zeros((1,nh,nw),dtype=torch.float32,device=union.device)
            meta={"x":int(x),"y":int(y),"width":int(side),"height":int(side),
                  "source_width":W,"source_height":H,"noop":True,"group_id":-1}
            return ([cur],[old],[z],[meta],"No active semantic mask: safe no-op.")

        preview_long=640
        sc=min(1.0,preview_long/float(max(H,W)))
        ph=max(32,int(round(H*sc))); pw=max(32,int(round(W*sc)))
        small=F.interpolate(union[None,None],size=(ph,pw),mode="bilinear",align_corners=False)[0,0]
        small=(small>float(mask_threshold)).float()
        rad=int(round(float(group_radius)*sc))
        if rad>0:
            small=F.max_pool2d(small[None,None],kernel_size=2*rad+1,stride=1,padding=rad)[0,0]
        comps=self._components((small>0.5).cpu().numpy())
        comps.sort(key=lambda b:b[4],reverse=True)

        sx=W/float(pw); sy=H/float(ph)
        regions=[]
        for x1s,y1s,x2s,y2s,_ in comps:
            x1=max(0,int(math.floor(x1s*sx))-int(context_px))
            y1=max(0,int(math.floor(y1s*sy))-int(context_px))
            x2=min(W,int(math.ceil(x2s*sx))+int(context_px))
            y2=min(H,int(math.ceil(y2s*sy))+int(context_px))
            if x2>x1 and y2>y1: regions.append((x1,y1,x2,y2))

        # Merge nearest semantic regions until count is manageable.
        while len(regions)>int(max_crops):
            best=None
            for i in range(len(regions)):
                for j in range(i+1,len(regions)):
                    g=self._gap(regions[i],regions[j])
                    if best is None or g<best[0]: best=(g,i,j)
            _,i,j=best
            a=regions[i]; b=regions[j]
            merged=(min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))
            regions=[r for k,r in enumerate(regions) if k not in (i,j)]+[merged]

        # Very large regions are split only along their long axis, preserving
        # large context. If that creates too many regions, nearest pieces are
        # merged again. Model input is always resized to <=2000 long side.
        split=[]
        limit=max(1024,int(max_source_side))
        for r in regions:
            x1,y1,x2,y2=r; w=x2-x1; h=y2-y1
            if max(w,h)<=limit:
                split.append(r); continue
            if w>=h:
                n=max(2,int(math.ceil(w/float(limit))))
                step=w/float(n)
                for k in range(n):
                    ax1=int(round(x1+k*step)); ax2=int(round(x1+(k+1)*step))
                    split.append((ax1,y1,ax2,y2))
            else:
                n=max(2,int(math.ceil(h/float(limit))))
                step=h/float(n)
                for k in range(n):
                    ay1=int(round(y1+k*step)); ay2=int(round(y1+(k+1)*step))
                    split.append((x1,ay1,x2,ay2))
        regions=split
        while len(regions)>int(max_crops):
            best=None
            for i in range(len(regions)):
                for j in range(i+1,len(regions)):
                    g=self._gap(regions[i],regions[j])
                    if best is None or g<best[0]: best=(g,i,j)
            _,i,j=best
            a=regions[i]; b=regions[j]
            merged=(min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))
            regions=[r for k,r in enumerate(regions) if k not in (i,j)]+[merged]

        crops=[]; refs=[]; crop_masks=[]; stitch=[]
        for gid,(rx1,ry1,rx2,ry2) in enumerate(regions):
            # Add one more context ring around grouped semantic region.
            cx1=max(0,rx1-int(context_px)); cy1=max(0,ry1-int(context_px))
            cx2=min(W,rx2+int(context_px)); cy2=min(H,ry2+int(context_px))
            cx1=(cx1//16)*16; cy1=(cy1//16)*16
            cx2=min(W,int(math.ceil(cx2/16.0))*16); cy2=min(H,int(math.ceil(cy2/16.0))*16)
            if cx2<=cx1 or cy2<=cy1: continue

            cur=src[:,cy1:cy2,cx1:cx2,:]
            old=ref[:,cy1:cy2,cx1:cx2,:]
            # Region ownership prevents the same semantic pixels being edited
            # twice when neighbouring macro crops overlap for context.
            own=torch.zeros_like(union)
            own[ry1:ry2,rx1:rx2]=union[ry1:ry2,rx1:rx2]
            local=own[cy1:cy2,cx1:cx2][None]
            nh,nw=self._target_size(cur.shape[1],cur.shape[2],int(target_long_side))
            cur_r=self._resize_image(cur,nh,nw)
            old_r=self._resize_image(old,nh,nw)
            mask_r=self._resize_mask(local,nh,nw)
            crops.append(cur_r); refs.append(old_r); crop_masks.append(mask_r)
            stitch.append({
                "x":int(cx1),"y":int(cy1),"width":int(cx2-cx1),"height":int(cy2-cy1),
                "source_width":W,"source_height":H,"group_id":int(gid),"noop":False
            })

        return (
            crops,refs,crop_masks,stitch,
            f"v21 semantic union -> {len(crops)} LARGE region crop(s); current+original aligned references; "
            f"model long side≤{min(2000,int(target_long_side))}px; no per-instance crops."
        )



class DOGMATileCoherenceBlendV22:
    """
    Preserve low-frequency source appearance and suppress generative drift in
    flat regions / tile borders, while keeping generated high-frequency detail
    where the source actually contains structure.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),
            "source":("IMAGE",),
            "lowfreq_strength":("FLOAT",{"default":0.92,"min":0.0,"max":1.0,"step":0.01}),
            "lowpass_divisor":("INT",{"default":24,"min":8,"max":64,"step":1}),
            "flat_alpha":("FLOAT",{"default":0.08,"min":0.0,"max":1.0,"step":0.01}),
            "detail_low":("FLOAT",{"default":0.006,"min":0.0,"max":0.1,"step":0.001}),
            "detail_high":("FLOAT",{"default":0.035,"min":0.001,"max":0.2,"step":0.001}),
            "edge_fade":("INT",{"default":256,"min":0,"max":768,"step":16}),
            "edge_floor":("FLOAT",{"default":0.05,"min":0.0,"max":1.0,"step":0.01}),
        }}

    RETURN_TYPES=("IMAGE","MASK","STRING")
    RETURN_NAMES=("image","generation_weight","info")
    FUNCTION="blend"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _resize(img,h,w):
        return F.interpolate(
            img.movedim(-1,1),size=(h,w),
            mode="bicubic",align_corners=False,antialias=True
        ).movedim(1,-1).clamp(0,1)

    def blend(self,generated,source,lowfreq_strength,lowpass_divisor,
              flat_alpha,detail_low,detail_high,edge_fade,edge_floor):
        g=generated[...,:3].float()
        s=source[...,:3].float()

        if s.shape[1:3] != g.shape[1:3]:
            s=self._resize(s,int(g.shape[1]),int(g.shape[2]))
        if s.shape[0] != g.shape[0]:
            if s.shape[0]==1:
                s=s.repeat(g.shape[0],1,1,1)
            else:
                s=s[:g.shape[0]]

        B,H,W,C=g.shape
        div=max(8,int(lowpass_divisor))
        lh=max(8,int(round(H/float(div))))
        lw=max(8,int(round(W/float(div))))

        def lowpass(x,h,w):
            y=F.interpolate(x.movedim(-1,1),size=(h,w),mode="area")
            y=F.interpolate(
                y,size=(H,W),mode="bicubic",
                align_corners=False,antialias=True
            )
            return y.movedim(1,-1)

        gl=lowpass(g,lh,lw)
        sl=lowpass(s,lh,lw)
        locked=(g + float(lowfreq_strength)*(sl-gl)).clamp(0,1)

        dh=max(8,int(round(H/8.0)))
        dw=max(8,int(round(W/8.0)))
        ss=lowpass(s,dh,dw)
        detail=(s-ss).abs().mean(dim=-1)
        lo=float(detail_low)
        hi=max(lo+1e-6,float(detail_high))
        gate=((detail-lo)/(hi-lo)).clamp(0,1)

        gate=F.max_pool2d(gate.unsqueeze(1),kernel_size=31,stride=1,padding=15)
        gate=F.avg_pool2d(gate,kernel_size=31,stride=1,padding=15).squeeze(1).clamp(0,1)

        alpha=float(flat_alpha)+(1.0-float(flat_alpha))*gate

        fade=max(0,int(edge_fade))
        if fade>0:
            yy=torch.arange(H,device=g.device,dtype=g.dtype)
            xx=torch.arange(W,device=g.device,dtype=g.dtype)
            dy=torch.minimum(yy,torch.flip(yy,[0]))
            dx=torch.minimum(xx,torch.flip(xx,[0]))
            dist=torch.minimum(dy[:,None],dx[None,:])
            e=(dist/float(max(1,fade))).clamp(0,1)
            e=e*e*(3.0-2.0*e)
            e=float(edge_floor)+(1.0-float(edge_floor))*e
            alpha=alpha*e.unsqueeze(0)

        alpha=alpha.clamp(0,1)
        out=(s*(1.0-alpha.unsqueeze(-1)) + locked*alpha.unsqueeze(-1)).clamp(0,1)

        return (
            out,
            alpha,
            f"v22 coherence lock | lowfreq={float(lowfreq_strength):.2f} | "
            f"flat alpha={float(flat_alpha):.2f} | edge fade={fade}px | "
            f"mean generated weight={float(alpha.mean().item()):.3f}"
        )


class DOGMACategorySettingsV22(DOGMACategorySettingsV21):
    """
    v22 semantic edits are anchored to the CURRENT MASTER, never the original.
    Broad-surface strengths are intentionally conservative. Sky and signage are
    protection-only categories: detected for mask protection, but not regenerated.
    """
    FUNCTION="settings_v22"

    def settings_v22(self,category,restoration_brief):
        radius,context,max_source,target,crops,alpha,prompt,summary = super().settings(
            category,restoration_brief
        )
        fam=_dogma_v21_family(category)

        alpha_overrides={
            "architecture":0.70,
            "road":0.60,
            "vegetation":0.55,
            "sky":0.00,
            "water":0.45,
            "vehicles":1.00,
            "street_objects":0.90,
            "roadway_people":1.00,
            "people":1.00,
            "signage":0.00,
            "animals":0.95,
            "furniture":0.90,
            "machinery":0.90,
            "clothing":0.90,
            "food":0.90,
            "product":0.90,
            "other":0.80,
            "none":0.00,
        }
        alpha=float(alpha_overrides.get(fam,alpha))

        prompt=prompt.replace(
            "The ORIGINAL same-position reference is identity evidence: preserve real positions, count, proportions, colours and scene content. "
            "Do not copy unrelated content from the reference and do not add new objects. ",
            "The ReferenceLatent is the SAME CURRENT MASTER crop. Use it to anchor identity, positions, count, proportions, colours, lighting and photographic continuity. "
            "Do not revert to an older/lower-quality source appearance and do not add new objects. "
        )

        if fam=="sky":
            prompt=(
                "SKY IS PROTECTED IN v22. Preserve the current global-master sky exactly; "
                "do not regenerate clouds, haze, colour or exposure."
            )
        elif fam=="signage":
            prompt=(
                "SIGNAGE IS PROTECTED IN v22. Preserve the current global-master sign/lettering pixels exactly. "
                "Do not rewrite, infer, complete or regenerate text."
            )

        summary=(
            f"v22 {fam}: grouping={radius}px, context={context}px, model long side≤{target}px, "
            f"macro crops≤{crops}, stitch alpha={alpha:.2f}; CURRENT MASTER is ReferenceLatent; "
            f"{'PROTECTION ONLY' if alpha==0.0 else 'semantic repair enabled'}"
        )
        return int(radius),int(context),int(max_source),int(target),int(crops),float(alpha),prompt,summary



class DOGMAReflectPadV23:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "pad":("INT",{"default":256,"min":0,"max":1024,"step":16}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="pad"
    CATEGORY="DOGMA/Semantic Detailer"

    def pad(self,image,pad):
        p=max(0,int(pad))
        if p<=0:
            return (image,"v23 pad disabled")
        x=image.float()
        h,w=int(x.shape[1]),int(x.shape[2])
        # Reflection is preferred for restoration context. Fall back to
        # replication only when a very small image cannot support reflection.
        mode="reflect" if p < h and p < w else "replicate"
        y=F.pad(x.movedim(-1,1),(p,p,p,p),mode=mode).movedim(1,-1)
        return (y.clamp(0,1),f"v23 {mode} context pad: {p}px each side | {w}x{h} -> {int(y.shape[2])}x{int(y.shape[1])}")


class DOGMACenterCropToReferenceScaleV23:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "reference":("IMAGE",),
            "scale":("FLOAT",{"default":2.0,"min":1.0,"max":8.0,"step":0.05}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="crop"
    CATEGORY="DOGMA/Semantic Detailer"

    def crop(self,image,reference,scale):
        x=image.float()
        rh,rw=int(reference.shape[1]),int(reference.shape[2])
        th=max(1,int(round(rh*float(scale))))
        tw=max(1,int(round(rw*float(scale))))
        h,w=int(x.shape[1]),int(x.shape[2])
        if h < th or w < tw:
            y=F.interpolate(
                x.movedim(-1,1),size=(th,tw),
                mode="bicubic",align_corners=False,antialias=True
            ).movedim(1,-1).clamp(0,1)
            return (y,f"v23 fallback resize to exact {tw}x{th}")
        y0=max(0,(h-th)//2); x0=max(0,(w-tw)//2)
        y=x[:,y0:y0+th,x0:x0+tw,:]
        return (y.clamp(0,1),f"v23 center crop padded master: ({x0},{y0}) -> exact {tw}x{th}")


class DOGMAFixedSemanticPlanV23:
    """
    Deterministic restoration plan. Broad surfaces are support/protection only;
    generative semantic passes are reserved for discrete objects where SAM is
    reliable enough to be useful.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{}}

    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","FLOAT"))
    RETURN_NAMES=("plan_preview",)+tuple(
        x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"sam_threshold_{i}")
    )
    FUNCTION="build"
    CATEGORY="DOGMA/Semantic Detailer"

    def build(self):
        plan=[
            ("road support","road:80,street:80,asphalt:80,traffic lane:60,intersection:40,roadway:60",0.12),
            ("vehicles","car:220,automobile:220,bus:20,truck:20,van:20,motorcycle:12,bicycle:12",0.12),
            ("roadway people","person:180,pedestrian:180,human:180",0.14),
            ("people","person:180,pedestrian:180,human:180",0.16),
            ("street furniture","traffic light:20,street lamp:28,pole:32,bollard:18,bench:16,street furniture:28",0.18),
            ("signage","text sign:36,billboard:30,rooftop sign:24,building sign:30,shop sign:28,traffic sign:28",0.18),
        ]
        preview=[]; out=[]
        for i,(cat,prompt,thr) in enumerate(plan,1):
            fam=_dogma_v21_family(cat)
            preview.append(f"SLOT {i}: {cat} [{fam}]\nSAM: {prompt}\nthreshold: {thr:.2f}")
            out.extend([cat,prompt,float(thr)])
        return ("\n\n".join(preview),*out)


class DOGMAProtectedMasksV23:
    """
    v23 mask logic:
    - road is SUPPORT ONLY;
    - roadway people = detected people intersected with a generously dilated road;
    - ordinary people have roadway people removed;
    - discrete object masks remain union masks.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req={}
        for i in range(1,7):
            req[f"mask_{i}"]=("MASK",)
            req[f"category_{i}"]=("STRING",{"forceInput":True})
        req["protect_radius"]=("INT",{"default":24,"min":0,"max":128,"step":1})
        return {"required":req}
    RETURN_TYPES=("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","summary")
    FUNCTION="protect_v23"
    CATEGORY="DOGMA/Semantic Detailer"

    def protect_v23(self,mask_1,category_1,mask_2,category_2,mask_3,category_3,
                    mask_4,category_4,mask_5,category_5,mask_6,category_6,protect_radius):
        raw=[mask_1,mask_2,mask_3,mask_4,mask_5,mask_6]
        cats=[category_1,category_2,category_3,category_4,category_5,category_6]
        fams=[_dogma_v21_family(c) for c in cats]
        H=max(int(m.shape[-2]) for m in raw)
        W=max(int(m.shape[-1]) for m in raw)
        masks=[]
        for m in raw:
            if m.ndim==2: m=m.unsqueeze(0)
            m=m.float()
            if m.shape[0]>1: m=m.max(dim=0,keepdim=True).values
            if m.shape[-2:]!=(H,W):
                m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            masks.append(m.clamp(0,1))

        def union_for(family):
            xs=[masks[i] for i,f in enumerate(fams) if f==family]
            return torch.stack(xs,dim=0).max(dim=0).values if xs else torch.zeros_like(masks[0])

        road=union_for("road")
        r=max(0,int(protect_radius))
        if r>0:
            road_wide=F.max_pool2d(road.unsqueeze(1),kernel_size=2*r+1,stride=1,padding=r).squeeze(1)
        else:
            road_wide=road

        # Both person SAM passes see people. Spatially separate road users from
        # ordinary pedestrians by intersecting one copy with the road support mask.
        roadway_raw=union_for("roadway_people")
        roadway=(roadway_raw*road_wide.clamp(0,1)).clamp(0,1)
        road_person_block=roadway
        if r>0:
            rr=max(3,r//3)
            road_person_block=F.max_pool2d(
                road_person_block.unsqueeze(1),
                kernel_size=2*rr+1,stride=1,padding=rr
            ).squeeze(1).clamp(0,1)

        outs=[]; report=[]
        for i,(m,fam) in enumerate(zip(masks,fams)):
            if fam=="roadway_people":
                out=roadway
                report.append(f"slot {i+1}: roadway people = PERSON ∩ dilated ROAD support")
            elif fam=="people":
                out=(m*(1.0-road_person_block)).clamp(0,1)
                report.append(f"slot {i+1}: ordinary people exclude roadway-person region")
            else:
                out=m
                report.append(f"slot {i+1}: {fam} union unchanged")
            outs.append(out)
        return (*outs,"\n".join(report))


class DOGMACategorySettingsV23:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "restoration_brief":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("INT","INT","INT","INT","INT","FLOAT","STRING","STRING")
    RETURN_NAMES=("group_radius","context_px","max_source_side","target_long_side","max_crops","stitch_strength","edit_prompt","summary")
    FUNCTION="settings_v23"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings_v23(self,category,restoration_brief):
        fam=_dogma_v21_family(category)
        table={
            "road":(1000,224,4200,1792,4,0.0),
            "architecture":(1000,224,4200,1792,4,0.0),
            "vegetation":(1000,224,4200,1792,4,0.0),
            "sky":(1200,160,4400,1536,2,0.0),
            "water":(1000,192,4200,1792,4,0.0),
            "vehicles":(720,272,3800,1984,6,1.00),
            "roadway_people":(520,272,3200,1984,6,1.00),
            "people":(520,256,3200,1984,6,0.98),
            "street_objects":(600,240,3400,1984,6,0.95),
            "signage":(520,224,3200,1920,6,0.0),
            "animals":(520,240,3200,1984,6,0.98),
            "furniture":(600,240,3400,1984,6,0.95),
            "machinery":(600,240,3400,1984,6,0.95),
            "other":(600,240,3400,1920,6,0.90),
            "none":(480,128,1800,1024,1,0.0),
        }
        radius,context,max_source,target,crops,alpha=table.get(fam,table["other"])
        brief=str(restoration_brief or "").strip()
        common=(
            "FULL-NOISE LOCAL RECONSTRUCTION, but ONLY the supplied semantic mask will be stitched back. "
            "The CURRENT MASTER crop is also the ReferenceLatent and is the sole spatial/photographic truth. "
            "Preserve exact camera geometry, local lighting, haze, object positions and surrounding context. "
            "Do not add objects outside the detected category and do not copy content from another location. "
        )
        policies={
            "road":"ROAD SUPPORT MASK ONLY. Do not regenerate road in v23.",
            "architecture":"ARCHITECTURE IS GLOBAL-PASS ONLY IN v23. Do not regenerate it here.",
            "vegetation":"VEGETATION IS GLOBAL-PASS ONLY IN v23. Do not regenerate it here.",
            "sky":"SKY IS GLOBAL-PASS ONLY IN v23. Do not regenerate it here.",
            "water":"WATER IS GLOBAL-PASS ONLY IN v23. Do not regenerate it here.",
            "vehicles":(
                "VEHICLES: genuinely reconstruct every masked vehicle rather than merely smoothing it. "
                "Separate fused/melted cars, repair body geometry, windows, wheels and perspective while preserving each vehicle's exact approximate position, "
                "direction, scale, traffic density and individual colour. Keep small distant vehicles small and atmospheric but make them coherent. "
                "Use period-plausible Italian/European vehicles for Milan circa 1972–1978. Do not create vehicles in empty road, lawn or sidewalk."
            ),
            "roadway_people":(
                "ROADWAY PEOPLE CLEANUP: these masks are people overlapping detected roadway. "
                "If a masked person is isolated in an active traffic lane and is not clearly on a marked crosswalk or legitimate crossing path, REMOVE the person completely "
                "and reconstruct clean continuous asphalt/markings underneath. Do NOT add a replacement person, shadow, dirt skid, stain or object. "
                "If the person is clearly a legitimate crossing pedestrian, repair anatomy and silhouette while preserving the crossing action."
            ),
            "people":(
                "PEOPLE: reconstruct ONLY the masked legitimate non-roadway pedestrians already present. "
                "Repair black blobs, malformed anatomy, duplicated limbs and melted silhouettes. Preserve count, pose, position, scale, direction and approximate clothing colour. "
                "Never create an extra person or crowd."
            ),
            "street_objects":(
                "STREET OBJECTS: reconstruct only existing lamps, poles, traffic lights, bollards, railings and street furniture. "
                "Preserve exact position, count, silhouette, function and approximate colour. Do not add signs or people."
            ),
            "signage":"SIGNAGE IS PROTECTED IN v23. Preserve the global-master signage exactly; do not regenerate or infer text.",
        }
        p=policies.get(fam,(
            f"{str(category).upper()}: reconstruct only existing masked instances in place; preserve identity, count, position, scale, orientation and colour."
        ))
        prompt=common+p+(" "+brief if brief else "")
        summary=(
            f"v23 {fam}: grouping={radius}px, context={context}px, model long side≤{target}px, "
            f"macro crops≤{crops}, stitch alpha={alpha:.2f}; "
            f"{'SUPPORT/PROTECTION ONLY' if alpha==0.0 else 'FULL-NOISE ReferenceLatent reconstruction'}"
        )
        return int(radius),int(context),int(max_source),int(target),int(crops),float(alpha),prompt,summary




class DOGMATileCoherenceBlendFastV231:
    """
    Fast v23.1 replacement for the v22 coherence lock.

    The visual purpose is unchanged: keep source low-frequency colour / haze /
    exposure while retaining generated structural detail and suppressing edits in
    flat areas and near tile borders.

    Performance difference: all analysis happens on a tiny proxy.  Delta RGB +
    structure gate are packed together and upsampled to full resolution ONCE.
    This avoids the old node's multiple full-resolution bicubic/antialiased
    resizes and 31x31 full-resolution pooling passes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),
            "source":("IMAGE",),
            "lowfreq_strength":("FLOAT",{"default":0.92,"min":0.0,"max":1.0,"step":0.01}),
            "lowpass_divisor":("INT",{"default":24,"min":8,"max":64,"step":1}),
            "flat_alpha":("FLOAT",{"default":0.03,"min":0.0,"max":1.0,"step":0.01}),
            "detail_low":("FLOAT",{"default":0.006,"min":0.0,"max":0.1,"step":0.001}),
            "detail_high":("FLOAT",{"default":0.035,"min":0.001,"max":0.2,"step":0.001}),
            "edge_fade":("INT",{"default":192,"min":0,"max":768,"step":16}),
            "edge_floor":("FLOAT",{"default":0.30,"min":0.0,"max":1.0,"step":0.01}),
        }}

    RETURN_TYPES=("IMAGE","MASK","STRING")
    RETURN_NAMES=("image","generation_weight","info")
    FUNCTION="blend_fast"
    CATEGORY="DOGMA/Semantic Detailer"

    def blend_fast(self,generated,source,lowfreq_strength,lowpass_divisor,
                   flat_alpha,detail_low,detail_high,edge_fade,edge_floor):
        with torch.no_grad():
            g=generated[...,:3].float()
            s=source[...,:3].float()

            B,H,W,C=g.shape
            if s.shape[1:3] != (H,W):
                s=F.interpolate(
                    s.movedim(-1,1),size=(H,W),mode="bilinear",align_corners=False
                ).movedim(1,-1).clamp(0,1)
            if s.shape[0] != B:
                if s.shape[0] == 1:
                    s=s.expand(B,-1,-1,-1)
                else:
                    s=s[:B]

            # Tiny analysis proxy. For a 1536 tile and divisor=24 this is 96x96.
            # 96 minimum keeps the flat/structured classification spatially useful
            # without doing expensive full-resolution filtering.
            div=max(8,int(lowpass_divisor))
            ph=min(H,max(96,int(round(H/float(div)))))
            pw=min(W,max(96,int(round(W/float(div)))))

            gc=F.interpolate(g.movedim(-1,1),size=(ph,pw),mode="area")
            sc=F.interpolate(s.movedim(-1,1),size=(ph,pw),mode="area")

            # Low-frequency correction is simply source minus generated on proxy.
            delta=sc-gc

            # Cheap structural gate entirely on proxy. Local residual is enough to
            # distinguish sky/asphalt/fog from architecture/vehicles/vegetation.
            local_mean=F.avg_pool2d(sc,kernel_size=3,stride=1,padding=1)
            detail=(sc-local_mean).abs().mean(dim=1,keepdim=True)
            lo=float(detail_low)
            hi=max(lo+1e-6,float(detail_high))
            gate=((detail-lo)/(hi-lo)).clamp(0,1)
            gate=F.max_pool2d(gate,kernel_size=3,stride=1,padding=1)

            # Pack RGB correction + 1-channel gate and perform ONE full-res resize.
            packed=torch.cat([delta,gate],dim=1)
            up=F.interpolate(packed,size=(H,W),mode="bilinear",align_corners=False)
            correction=up[:,:3].movedim(1,-1)
            gate_full=up[:,3].clamp(0,1)

            locked=(g + float(lowfreq_strength)*correction).clamp(0,1)
            alpha=float(flat_alpha)+(1.0-float(flat_alpha))*gate_full

            fade=max(0,int(edge_fade))
            if fade>0:
                yy=torch.arange(H,device=g.device,dtype=g.dtype)
                xx=torch.arange(W,device=g.device,dtype=g.dtype)
                dy=torch.minimum(yy,(H-1)-yy)
                dx=torch.minimum(xx,(W-1)-xx)
                ey=(dy/float(max(1,fade))).clamp(0,1)
                ex=(dx/float(max(1,fade))).clamp(0,1)
                e=torch.minimum(ey[:,None],ex[None,:])
                e=e*e*(3.0-2.0*e)
                e=float(edge_floor)+(1.0-float(edge_floor))*e
                alpha=alpha*e.unsqueeze(0)

            alpha=alpha.clamp(0,1)
            out=(s*(1.0-alpha.unsqueeze(-1)) + locked*alpha.unsqueeze(-1)).clamp(0,1)

            return (
                out,
                alpha,
                f"v23.1 FAST coherence | proxy={pw}x{ph} | lowfreq={float(lowfreq_strength):.2f} | "
                f"flat alpha={float(flat_alpha):.2f} | edge fade={fade}px | "
                f"mean generated weight={float(alpha.mean().item()):.3f}"
            )



class DOGMAGlobalLowFreqLockFastV24:
    """
    One whole-frame low-frequency correction AFTER Steudio Combine Tiles.
    It never blends source high-frequency pixels back into the generated master:
    generated detail is preserved everywhere while source colour/exposure/haze
    are restored only at very low spatial frequencies.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),
            "source":("IMAGE",),
            "strength":("FLOAT",{"default":0.92,"min":0.0,"max":1.0,"step":0.01}),
            "proxy_divisor":("INT",{"default":32,"min":8,"max":96,"step":1}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="lock"
    CATEGORY="DOGMA/Semantic Detailer"

    def lock(self,generated,source,strength,proxy_divisor):
        with torch.no_grad():
            g=generated[...,:3].float()
            s=source[...,:3].float()
            B,H,W,C=g.shape
            if s.shape[1:3]!=(H,W):
                s=F.interpolate(
                    s.movedim(-1,1),size=(H,W),mode="bilinear",align_corners=False
                ).movedim(1,-1).clamp(0,1)
            if s.shape[0]!=B:
                s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]

            div=max(8,int(proxy_divisor))
            ph=min(H,max(64,int(round(H/float(div)))))
            pw=min(W,max(64,int(round(W/float(div)))))
            gp=F.interpolate(g.movedim(-1,1),size=(ph,pw),mode="area")
            sp=F.interpolate(s.movedim(-1,1),size=(ph,pw),mode="area")
            delta=sp-gp
            corr=F.interpolate(delta,size=(H,W),mode="bilinear",align_corners=False).movedim(1,-1)
            out=(g+float(strength)*corr).clamp(0,1)
            return (
                out,
                f"v24 whole-frame low-frequency lock | proxy={pw}x{ph} | strength={float(strength):.2f} | "
                "generated high-frequency detail preserved everywhere"
            )


class DOGMAAdaptiveSemanticPlanV24:
    """
    Convert Qwen's four scene-specific discrete repair targets into six serial
    SAM slots:
      1 conditional road support (only for roadway-people reasoning)
      2-5 adaptive repair categories
      6 signage/text protection
    Broad surfaces are rejected from local generative repair.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"planner_text":("STRING",{"forceInput":True,"multiline":True})}}

    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","FLOAT"))
    RETURN_NAMES=("plan_preview",)+tuple(
        x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"sam_threshold_{i}")
    )
    FUNCTION="build"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _norm(c):
        s=_clean_category(c).lower()
        if not s or s in ("none","unused","n/a","__none__"):
            return "__none__"
        if ("roadway" in s or "traffic lane" in s or "in road" in s) and any(k in s for k in ("person","people","pedestrian","human")):
            return "roadway people"
        if any(k in s for k in ("car","cars","vehicle","vehicles","automobile","automobiles","traffic vehicles","bus","buses","truck","trucks","van","vans","motorcycle","motorcycles")):
            return "vehicles"
        if any(k in s for k in ("person","people","pedestrian","pedestrians","human","humans","crowd","crowds")):
            return "people"
        if any(k in s for k in ("street furniture","street object","street objects","traffic light","street light","street lamp","lamp post","lamppost","bollard","railing")):
            return "street furniture"
        if any(k in s for k in ("face","faces","facial")):
            return "faces"
        if any(k in s for k in ("hand","hands","finger","fingers")):
            return "hands"
        if any(k in s for k in ("animal","animals","dog","dogs","cat","cats","horse","horses","bird","birds")):
            return "animals"
        if any(k in s for k in ("furniture","chair","chairs","table","tables","sofa","couch","bed","beds")):
            return "furniture"
        if any(k in s for k in ("machine","machinery","equipment","appliance","appliances","tool","tools")):
            return "machinery"
        if any(k in s for k in ("clothing","clothes","garment","garments","jacket","dress","shirt","coat")):
            return "clothing"
        # Reject broad surfaces and protected text categories from local generation.
        broad=("road","street","asphalt","sidewalk","pavement","grass","vegetation","tree","trees","bush","architecture",
               "building","buildings","facade","façade","sky","cloud","water","wall","floor","background","landscape")
        protected=("sign","signage","text","letter","letters","logo","billboard","advertising")
        if any(k in s for k in broad) or any(k in s for k in protected):
            return "__none__"
        return re.sub(r"[^a-z0-9 _\-/]","",s).strip() or "__none__"

    @staticmethod
    def _sam(cat):
        c=str(cat).lower()
        if c in ("","__none__","none"):
            return "nonexistent_placeholder_object_xyz:1",0.50
        if c=="road support":
            return "road:80,street:80,asphalt:80,traffic lane:60,intersection:40,roadway:60",0.13
        if c=="signage":
            return "text sign:36,billboard:30,rooftop sign:24,building sign:30,shop sign:28,traffic sign:28",0.18
        if c=="vehicles":
            return "car:220,automobile:220,bus:24,truck:24,van:24,motorcycle:16,bicycle:12",0.13
        if c in ("people","roadway people"):
            return "person:180,pedestrian:180,human:180",0.14
        if c=="street furniture":
            return "traffic light:28,street lamp:40,pole:44,bollard:24,bench:20,railing:24,street furniture:36",0.17
        if c=="faces":
            return "face:180,human face:180",0.16
        if c=="hands":
            return "hand:180,human hand:180",0.17
        if c=="animals":
            return "animal:120,dog:80,cat:80,horse:50,bird:50",0.16
        if c=="furniture":
            return "furniture:120,chair:100,table:80,sofa:60,couch:60,bed:50",0.17
        if c=="machinery":
            return "machinery:100,machine:100,equipment:100,tool:80,appliance:80",0.17
        if c=="clothing":
            return "clothing:120,jacket:80,shirt:80,dress:60,coat:60",0.18
        simple=re.sub(r"[^a-z0-9 _\-/]","",c).strip() or "object"
        return f"{simple}:120",0.18

    def build(self,planner_text):
        lines=str(planner_text or "").replace("\r","\n").splitlines()
        cats=[]; seen=set()
        for line in lines:
            c=self._norm(line)
            if c=="__none__":
                continue
            if c not in seen:
                cats.append(c); seen.add(c)
            if len(cats)>=4: break
        while len(cats)<4:
            cats.append("__none__")

        needs_road=any(c=="roadway people" for c in cats)
        slots=[("road support" if needs_road else "__none__")]+cats+["signage"]
        preview=[]; out=[]
        for i,c in enumerate(slots,1):
            p,t=self._sam(c)
            preview.append(f"SLOT {i}: {c}\nSAM: {p}\nthreshold: {t:.2f}")
            out.extend([c,p,float(t)])
        return ("\n\n".join(preview),*out)


class DOGMAProtectedMasksV24:
    """
    Adaptive protection logic:
    - conditional ROAD support is never generated;
    - 'roadway people' = detected people intersected with road support;
    - ordinary people exclude roadway people;
    - signage/text is protection-only and is subtracted from all repair masks.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req={}
        for i in range(1,7):
            req[f"mask_{i}"]=("MASK",)
            req[f"category_{i}"]=("STRING",{"forceInput":True})
        req["protect_radius"]=("INT",{"default":20,"min":0,"max":96,"step":1})
        return {"required":req}
    RETURN_TYPES=("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","summary")
    FUNCTION="protect"
    CATEGORY="DOGMA/Semantic Detailer"

    def protect(self,mask_1,category_1,mask_2,category_2,mask_3,category_3,
                mask_4,category_4,mask_5,category_5,mask_6,category_6,protect_radius):
        raw=[mask_1,mask_2,mask_3,mask_4,mask_5,mask_6]
        cats=[category_1,category_2,category_3,category_4,category_5,category_6]
        fams=[_dogma_v21_family(c) for c in cats]
        H=max(int(m.shape[-2]) for m in raw); W=max(int(m.shape[-1]) for m in raw)
        masks=[]
        for m in raw:
            if m.ndim==2: m=m.unsqueeze(0)
            m=m.float()
            if m.shape[0]>1: m=m.max(dim=0,keepdim=True).values
            if m.shape[-2:]!=(H,W):
                m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            masks.append(m.clamp(0,1))

        def union_for(fam):
            xs=[masks[i] for i,f in enumerate(fams) if f==fam]
            return torch.stack(xs,dim=0).max(dim=0).values if xs else torch.zeros_like(masks[0])

        road=union_for("road")
        signage=union_for("signage")
        r=max(0,int(protect_radius))
        if r>0:
            road_wide=F.max_pool2d(road.unsqueeze(1),kernel_size=2*r+1,stride=1,padding=r).squeeze(1)
            sr=max(3,r//2)
            sign_block=F.max_pool2d(signage.unsqueeze(1),kernel_size=2*sr+1,stride=1,padding=sr).squeeze(1)
        else:
            road_wide=road; sign_block=signage

        roadway_raw=union_for("roadway_people")
        roadway=(roadway_raw*road_wide.clamp(0,1)).clamp(0,1)
        road_block=roadway
        if r>0:
            rr=max(3,r//3)
            road_block=F.max_pool2d(roadway.unsqueeze(1),kernel_size=2*rr+1,stride=1,padding=rr).squeeze(1).clamp(0,1)

        outs=[]; report=[]
        for i,(m,fam,cat) in enumerate(zip(masks,fams,cats)):
            if fam=="road":
                out=m
                report.append(f"slot {i+1}: road SUPPORT ONLY")
            elif fam=="signage":
                out=m
                report.append(f"slot {i+1}: signage PROTECTION ONLY")
            elif fam=="roadway_people":
                out=roadway
                out=(out*(1.0-sign_block)).clamp(0,1)
                report.append(f"slot {i+1}: roadway people = PERSON ∩ ROAD, text protected")
            elif fam=="people":
                out=(m*(1.0-road_block)*(1.0-sign_block)).clamp(0,1)
                report.append(f"slot {i+1}: people exclude roadway-person + text regions")
            elif fam=="none":
                out=torch.zeros_like(m)
                report.append(f"slot {i+1}: none")
            else:
                out=(m*(1.0-sign_block)).clamp(0,1)
                report.append(f"slot {i+1}: {cat}, text protected")
            outs.append(out)
        return (*outs,"\n".join(report))


class DOGMACategorySettingsV24:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "restoration_brief":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("INT","INT","INT","INT","INT","FLOAT","STRING","STRING")
    RETURN_NAMES=("group_radius","context_px","max_source_side","target_long_side","max_crops","stitch_strength","edit_prompt","summary")
    FUNCTION="settings"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings(self,category,restoration_brief):
        c=str(category or "").strip().lower()
        fam=_dogma_v21_family(c)
        # Smaller source groups than v23: still contextual, but avoid shrinking
        # enormous areas into one 2K crop.
        table={
            "vehicles":(340,192,2500,1792,8,0.90),
            "roadway_people":(280,208,2200,1792,8,1.00),
            "people":(300,192,2300,1792,8,0.88),
            "street_objects":(320,192,2400,1792,8,0.88),
            "animals":(300,192,2300,1792,8,0.90),
            "furniture":(320,192,2400,1792,8,0.88),
            "machinery":(320,192,2400,1792,8,0.90),
            "clothing":(260,160,2200,1664,8,0.84),
            "signage":(320,160,2200,1664,6,0.0),
            "road":(800,160,3200,1664,4,0.0),
            "architecture":(800,160,3200,1664,4,0.0),
            "vegetation":(800,160,3200,1664,4,0.0),
            "sky":(800,160,3200,1664,2,0.0),
            "water":(800,160,3200,1664,2,0.0),
            "none":(240,128,1800,1280,1,0.0),
        }
        radius,context,max_source,target,crops,alpha=table.get(fam,(300,192,2300,1792,8,0.86))
        if "face" in c:
            radius,context,max_source,target,crops,alpha=(220,160,2000,1664,8,0.86)
        elif "hand" in c:
            radius,context,max_source,target,crops,alpha=(200,160,1900,1664,8,0.88)

        brief=str(restoration_brief or "").strip()
        common=(
            "TRUE MASKED LOCAL INPAINT of the CURRENT MASTER. The CURRENT MASTER crop is also the ReferenceLatent "
            "and is the spatial, photographic and identity ground truth. Only the supplied inpaint mask may change; "
            "everything outside it must remain the same. Reconstruct real coherent detail rather than smoothing blur. "
            "Preserve local perspective, lighting, haze, scale, object positions and surrounding context. "
            "Never add extra instances or copy content from elsewhere. "
        )
        if fam=="vehicles":
            policy=(
                "VEHICLES: repair malformed/fused existing vehicles into coherent individual vehicles while preserving approximate count, "
                "position, direction, scale and individual colour. Keep distant vehicles distant. Do not create vehicles in empty space."
            )
        elif fam=="roadway_people":
            policy=(
                "ROADWAY PEOPLE: the planner identified people implausibly located in active vehicle lanes. "
                "If the masked figure is not clearly on a legitimate crossing path, remove it completely and reconstruct the underlying road "
                "from surrounding evidence. Do not add a replacement person, shadow, stain or object. If clearly crossing legitimately, repair anatomy only."
            )
        elif fam=="people":
            policy=(
                "PEOPLE: repair only the already-detected people. Correct black blobs, fused anatomy, duplicated limbs and malformed silhouettes. "
                "Preserve count, pose, position, scale, direction and approximate clothing colour. Never add people."
            )
        elif fam=="street_objects":
            policy=(
                "STREET OBJECTS: repair only existing lamps, poles, traffic lights, railings, bollards or similar detected objects. "
                "Preserve count, position, function and silhouette. Do not add signage or people."
            )
        elif "face" in c:
            policy="FACES: repair only detected existing faces; preserve identity, pose, expression, age and lighting. Do not create extra faces."
        elif "hand" in c:
            policy="HANDS: repair only detected existing hands; preserve pose and interaction. Correct anatomy without adding extra fingers, hands or objects."
        elif fam=="animals":
            policy="ANIMALS: repair only existing detected animals; preserve species, count, pose, position and colour. Do not add animals."
        elif fam=="furniture":
            policy="FURNITURE: repair only existing detected furniture; preserve count, placement, dimensions, material and function."
        elif fam=="machinery":
            policy="MACHINERY/EQUIPMENT: repair only existing detected objects; preserve function, count, position, scale and design language."
        elif fam in ("road","architecture","vegetation","sky","water","signage","none"):
            policy="PROTECTION/SUPPORT ONLY. Do not perform a generative local edit for this category."
        else:
            policy=f"{c.upper()}: repair only the existing masked instances; preserve identity, count, position, scale, orientation and colour."

        prompt=common+policy+(" "+brief if brief else "")
        summary=(
            f"v24 {fam}: group={radius}px context={context}px source≤{max_source}px model≤{target}px "
            f"crops≤{crops} stitch={alpha:.2f} | "
            f"{'support/protection only' if alpha==0.0 else 'TRUE masked ReferenceLatent inpaint'}"
        )
        return int(radius),int(context),int(max_source),int(target),int(crops),float(alpha),prompt,summary




class DOGMATileBatchToListV25:
    """Split a D&C IMAGE batch into a real Comfy mapped IMAGE list, one tile per item."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"images":("IMAGE",)}}
    RETURN_TYPES=("IMAGE",)
    RETURN_NAMES=("tiles",)
    OUTPUT_IS_LIST=(True,)
    FUNCTION="split"
    CATEGORY="DOGMA/Semantic Detailer"

    def split(self,images):
        if images.ndim!=4 or images.shape[0]<1:
            raise ValueError("DOGMA v25 expected IMAGE batch [B,H,W,C].")
        return ([images[i:i+1] for i in range(int(images.shape[0]))],)


class DOGMAImageListToBatchV25:
    """Reassemble a mapped IMAGE list in original order for Steudio Combine Tiles."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"images":("IMAGE",)}}
    RETURN_TYPES=("IMAGE",)
    RETURN_NAMES=("batch",)
    INPUT_IS_LIST=True
    FUNCTION="batch"
    CATEGORY="DOGMA/Semantic Detailer"

    def batch(self,images):
        xs=[]
        for im in images:
            if im is None: continue
            if im.ndim==3: im=im.unsqueeze(0)
            xs.append(im.float())
        if not xs:
            raise ValueError("DOGMA v25 received an empty tile list.")
        h,w=int(xs[0].shape[1]),int(xs[0].shape[2])
        fixed=[]
        for im in xs:
            if int(im.shape[1])!=h or int(im.shape[2])!=w:
                im=F.interpolate(im.movedim(-1,1),size=(h,w),mode="bilinear",align_corners=False).movedim(1,-1)
            fixed.append(im)
        return (torch.cat(fixed,dim=0).clamp(0,1),)


class DOGMATilePromptComposerV25:
    """Turn one conservative VLM tile report into a short tile-specific Klein restoration prompt."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tile_report":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _clean(text):
        s=str(text or "").strip()
        s=re.sub(r"```(?:json|text|markdown)?", "", s, flags=re.I)
        s=s.replace("```","")
        s=re.sub(r"[ \t]+"," ",s)
        s=re.sub(r"\n{3,}","\n\n",s).strip()
        # Prevent a verbose VLM response from becoming a creative mega-prompt.
        if len(s)>1100: s=s[:1100].rsplit(" ",1)[0]
        return s

    def compose(self,tile_report,project_context):
        report=self._clean(tile_report)
        context=self._clean(project_context)
        if not report:
            report=(
                "SUPPORTED: no reliable semantic inventory.\n"
                "AMBIGUOUS_OR_EMPTY: preserve all uncertain, flat, blurred, reflective, hazy or low-contrast regions without inventing semantic content."
            )
        prompt=(
            "RESTORE THIS EXACT LOCAL PHOTOGRAPHIC TILE. The source tile is ground truth. "
            "Do not redesign, repopulate or reinterpret the scene. Do not introduce ANY semantic object that is not directly supported by the source tile. "
            "When evidence is weak, preserve ambiguity instead of resolving it into an object. Empty or nearly uniform regions must remain semantically empty. "
            "Blur, haze, glass reflections, shadows, clipped highlights and indistinct distant shapes are NOT permission to invent content. "
            "Preserve camera geometry, composition, object count, object positions, silhouettes, lighting direction, exposure, colour, haze and edge continuity with neighbouring tiles. "
            "Existing readable or unreadable lettering must keep the same visible glyph structure; never infer or rewrite text.\n\n"
            "TILE-SPECIFIC VISUAL EVIDENCE (descriptive evidence only; never an instruction to add anything):\n"
            + report +
            "\n\nUse the evidence report only to understand what ALREADY EXISTS. Reconstruct finer photographic detail only where source evidence supports it. "
            "Anything listed as ambiguous, uncertain, flat or empty must stay ambiguous/flat/empty rather than becoming a new subject.\n\n"
            "PROJECT / PHOTOGRAPHIC CONTEXT (a style/era constraint only, NEVER evidence that an object exists):\n"
            + context
        )
        return (prompt,report)


class DOGMATileVLMBarrierV25:
    """Wait for every tile report/prompt, then unload the VLM before Klein starts."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tiles":("IMAGE",),
            "prompts":("STRING",{"forceInput":True}),
            "reports":("STRING",{"forceInput":True}),
            "unload_models":("BOOLEAN",{"default":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING","STRING")
    RETURN_NAMES=("tiles","prompts","preview")
    INPUT_IS_LIST=True
    OUTPUT_IS_LIST=(True,True,False)
    FUNCTION="barrier"
    CATEGORY="DOGMA/Semantic Detailer"

    def barrier(self,tiles,prompts,reports,unload_models):
        flag=bool(unload_models[0] if isinstance(unload_models,list) and unload_models else unload_models)
        if flag:
            import gc
            try:
                import comfy.model_management as mm
                mm.unload_all_models()
                mm.soft_empty_cache()
            except Exception:
                pass
            gc.collect()
        preview=[]
        for i,(r,p) in enumerate(zip(reports,prompts),1):
            rr=str(r or "").strip()
            pp=str(p or "").strip()
            preview.append(
                f"TILE {i}\n"
                f"QWEN REPORT:\n{rr}\n\n"
                f"ACTUAL KLEIN PROMPT:\n{pp}\n"
            )
        return (tiles,prompts,"\n\n".join(preview))


class DOGMAEvidenceGateV25:
    """
    Fast source-evidence gate for one tile. In visually flat/ambiguous source areas,
    pull the generated result strongly back toward the source. Where real source
    structure exists, preserve the generated reconstruction. Analysis runs on a
    tiny proxy so this is cheap compared with Klein.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),
            "source":("IMAGE",),
            "flat_generated_weight":("FLOAT",{"default":0.10,"min":0.0,"max":0.8,"step":0.01}),
            "low_threshold":("FLOAT",{"default":0.010,"min":0.0,"max":0.2,"step":0.001}),
            "high_threshold":("FLOAT",{"default":0.045,"min":0.001,"max":0.3,"step":0.001}),
            "proxy_long_side":("INT",{"default":256,"min":96,"max":512,"step":32}),
            "support_grow":("INT",{"default":5,"min":0,"max":16,"step":1}),
        }}
    RETURN_TYPES=("IMAGE","MASK","STRING")
    RETURN_NAMES=("image","evidence_weight","info")
    FUNCTION="gate"
    CATEGORY="DOGMA/Semantic Detailer"

    def gate(self,generated,source,flat_generated_weight,low_threshold,high_threshold,proxy_long_side,support_grow):
        with torch.no_grad():
            g=generated[...,:3].float()
            s=source[...,:3].float()
            B,H,W,C=g.shape
            if s.shape[1:3]!=(H,W):
                s=F.interpolate(s.movedim(-1,1),size=(H,W),mode="bilinear",align_corners=False).movedim(1,-1)
            if s.shape[0]!=B:
                s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]

            long=max(H,W); target=max(96,int(proxy_long_side))
            scale=min(1.0,target/float(long))
            ph=max(32,int(round(H*scale))); pw=max(32,int(round(W*scale)))
            sp=F.interpolate(s.movedim(-1,1),size=(ph,pw),mode="area")
            lum=(0.2126*sp[:,0:1]+0.7152*sp[:,1:2]+0.0722*sp[:,2:3])

            # Local gradients + local deviation: real edges/textures score high;
            # uniform sky/glass/fog/shadow fields score low.
            dx=F.pad((lum[:,:,:,1:]-lum[:,:,:,:-1]).abs(),(0,1,0,0))
            dy=F.pad((lum[:,:,1:,:]-lum[:,:,:-1,:]).abs(),(0,0,0,1))
            mean=F.avg_pool2d(lum,kernel_size=7,stride=1,padding=3)
            dev=(lum-mean).abs()
            evidence=torch.maximum(torch.maximum(dx,dy),dev*1.5)

            lo=float(low_threshold); hi=max(lo+1e-6,float(high_threshold))
            gate=((evidence-lo)/(hi-lo)).clamp(0,1)
            grow=max(0,int(support_grow))
            if grow>0:
                k=2*grow+1
                gate=F.max_pool2d(gate,kernel_size=k,stride=1,padding=grow)
            gate=F.avg_pool2d(gate,kernel_size=5,stride=1,padding=2).clamp(0,1)
            gate=F.interpolate(gate,size=(H,W),mode="bilinear",align_corners=False).squeeze(1)

            floor=float(flat_generated_weight)
            alpha=(floor+(1.0-floor)*gate).clamp(0,1)
            out=(s*(1.0-alpha.unsqueeze(-1))+g*alpha.unsqueeze(-1)).clamp(0,1)
            return (
                out,
                alpha,
                f"v25 evidence gate | proxy={pw}x{ph} | flat generated={floor:.2f} | mean generated weight={float(alpha.mean().item()):.3f}"
            )




class DOGMASectorPlanV26:
    """Three non-destructive sector categories in old 6-slot-compatible layout."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"planner_text":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","FLOAT"))
    RETURN_NAMES=("plan_preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"sam_threshold_{i}"))
    FUNCTION="build"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _norm(line):
        s=str(line or "").strip().lower()
        s=re.sub(r"^[\s\-\*\d\.)]+","",s)
        if not s or s in ("none","unused","n/a","__none__"): return "__none__"
        if any(k in s for k in ("sign","signage","billboard","advert","poster","lettering","text")): return "signage"
        if any(k in s for k in ("car","vehicle","automobile","bus","truck","van","motorcycle","bicycle")): return "vehicles"
        if any(k in s for k in ("face","facial")): return "faces"
        if any(k in s for k in ("hand","finger")): return "hands"
        if any(k in s for k in ("person","people","pedestrian","human","crowd")): return "people"
        if any(k in s for k in ("street furniture","traffic light","street light","street lamp","lamp post","lamppost","bollard","railing","pole")): return "street furniture"
        if any(k in s for k in ("window","door","balcony","storefront","architectural detail","facade detail","façade detail")): return "architectural details"
        if any(k in s for k in ("animal","dog","cat","horse","bird")): return "animals"
        if any(k in s for k in ("furniture","chair","table","sofa","couch","bed")): return "furniture"
        if any(k in s for k in ("machine","machinery","equipment","appliance","tool")): return "machinery"
        if any(k in s for k in ("clothing","clothes","garment","jacket","dress","shirt","coat")): return "clothing"
        if any(k in s for k in ("product","package","bottle","container")): return "products"
        broad=("road","asphalt","pavement","sidewalk","grass","vegetation","tree","sky","cloud","water","wall","floor","background","haze","fog","building","architecture")
        if any(k in s for k in broad): return "__none__"
        return re.sub(r"[^a-z0-9 _\-/]","",s).strip() or "__none__"

    @staticmethod
    def _sam(c):
        if c in ("","__none__","none"): return "nonexistent_placeholder_object_xyz:1",0.50
        if c=="vehicles": return "car:220,automobile:220,bus:30,truck:30,van:30,motorcycle:20,bicycle:16",0.13
        if c=="people": return "person:220,pedestrian:220,human:220",0.14
        if c=="signage": return "billboard:60,advertising sign:60,shop sign:60,poster:60,traffic sign:40,rooftop sign:40,signboard:60",0.16
        if c=="street furniture": return "street lamp:60,traffic light:40,pole:80,bollard:40,railing:60,bench:40,street furniture:60",0.16
        if c=="architectural details": return "window:220,door:120,balcony:120,storefront:100,architectural detail:160",0.16
        if c=="faces": return "face:220,human face:220",0.16
        if c=="hands": return "hand:220,human hand:220",0.17
        if c=="animals": return "animal:160,dog:100,cat:100,horse:70,bird:70",0.16
        if c=="furniture": return "furniture:160,chair:120,table:100,sofa:80,couch:80,bed:70",0.17
        if c=="machinery": return "machine:140,machinery:140,equipment:140,tool:100,appliance:100",0.17
        if c=="clothing": return "clothing:160,jacket:100,shirt:100,dress:80,coat:80",0.18
        if c=="products": return "product:160,bottle:100,package:100,container:100",0.18
        return f"{c}:160",0.18

    def build(self,planner_text):
        cats=[]; seen=set()
        for line in str(planner_text or "").replace("\r","\n").splitlines():
            c=self._norm(line)
            if c=="__none__" or c in seen: continue
            cats.append(c); seen.add(c)
            if len(cats)>=3: break
        while len(cats)<3: cats.append("__none__")
        # Preserve old wiring: slot1 unused, slots2-4 sectors, slots5-6 unused.
        slots=["__none__",cats[0],cats[1],cats[2],"__none__","__none__"]
        preview=[]; out=[]
        for i,c in enumerate(slots,1):
            p,t=self._sam(c)
            preview.append(f"SLOT {i}: {c}\nSAM: {p}\nthreshold={t:.2f}")
            out.extend([c,p,float(t)])
        return ("\n\n".join(preview),*out)


class DOGMASectorMasksV26:
    """Normalize three masks only. No deletion logic and no cross-category erasure."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "mask_1":("MASK",),"category_1":("STRING",{"forceInput":True}),
            "mask_2":("MASK",),"category_2":("STRING",{"forceInput":True}),
            "mask_3":("MASK",),"category_3":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","summary")
    FUNCTION="prepare"
    CATEGORY="DOGMA/Semantic Detailer"

    def prepare(self,mask_1,category_1,mask_2,category_2,mask_3,category_3):
        raw=[mask_1,mask_2,mask_3]; cats=[str(category_1),str(category_2),str(category_3)]
        H=max(int(m.shape[-2]) for m in raw); W=max(int(m.shape[-1]) for m in raw)
        outs=[]; report=[]
        for i,(m,c) in enumerate(zip(raw,cats),1):
            if m.ndim==2: m=m.unsqueeze(0)
            m=m.float()
            if m.shape[0]>1: m=m.max(dim=0,keepdim=True).values
            if m.shape[-2:]!=(H,W):
                m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            if not c.strip() or c.strip().lower() in ("none","__none__","unused"):
                m=torch.zeros_like(m)
            m=m.clamp(0,1)
            cov=float((m>0.5).float().mean().item())*100.0
            outs.append(m); report.append(f"sector {i}: {c} | mask coverage {cov:.2f}% | preserve all existing instances")
        return (*outs,"\n".join(report))


class DOGMASectorSettingsV26:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"category":("STRING",{"forceInput":True}),"restoration_brief":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("INT","INT","INT","INT","INT","FLOAT","STRING","STRING")
    RETURN_NAMES=("group_radius","context_px","max_source_side","target_long_side","max_crops","stitch_strength","vlm_request","summary")
    FUNCTION="settings"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings(self,category,restoration_brief):
        c=str(category or "").strip().lower()
        # Group nearby instances, but force several sectors rather than one whole-category crop.
        table={
            "vehicles":(220,224,3200,2560,4,0.96),
            "people":(180,208,3000,2400,4,0.95),
            "signage":(160,192,2800,2304,4,0.95),
            "street furniture":(180,208,3000,2400,4,0.93),
            "architectural details":(260,256,3400,2560,4,0.92),
            "faces":(140,192,2200,2048,4,0.94),
            "hands":(120,192,1900,1792,4,0.94),
            "animals":(180,208,2800,2304,4,0.95),
            "furniture":(220,224,3200,2560,4,0.94),
            "machinery":(220,224,3200,2560,4,0.95),
            "clothing":(160,192,2600,2200,4,0.92),
            "products":(160,192,2600,2200,4,0.94),
            "__none__":(160,128,1800,1536,1,0.0),
            "none":(160,128,1800,1536,1,0.0),
        }
        radius,context,maxsrc,target,crops,alpha=table.get(c,(190,208,3000,2400,4,0.93))
        historical=(
            "Historical context: the intended scene is Milan, Italy in the 1970s. Use this context only to make ALREADY VISIBLE objects historically plausible "
            "(vehicle design, clothing, materials, street furniture, typography and advertising style). The context is never evidence that a new object should exist. "
        )
        universal=(
            "Inspect this GROUPED crop of the current restored master. The target category is '"+c+"'. "
            "Write ONE concise 50-80 word natural-language editing instruction for FLUX.2 Klein. Describe the actual existing target instances visible in this crop and the specific remaining defects worth improving. "
            "State both the refinement and the visual facts that remain unchanged: instance count, positions, scale, pose/direction, occlusion, surrounding geometry, lighting and colour. Every existing instance remains present. "
            "Use positive preservation language. The instruction must improve detail beyond a generic HD/upscale request. "
        )
        if c=="vehicles":
            specific=("Focus on vehicle geometry: coherent body panels, windows, wheels, lights, perspective, separation between touching vehicles and period-correct 1970s Italian/European design cues. Retain each vehicle's existing colour, position and direction.")
        elif c=="people":
            specific=("Focus on anatomy, silhouettes, faces when visible, clothing and clean separation from railings, poles, cars and architecture. Retain EVERY visible person in the same position and pose; the instruction must not remove or add people.")
        elif c=="signage":
            specific=("Inspect each existing sign face. When wording is confidently readable, include that exact wording in quotation marks and ask Klein to render it cleanly. When wording is genuinely unreadable, ask for a plausible 1970s Milan/Italian advertising design confined to the EXISTING sign face, preserving its frame, size, position and perspective.")
        elif c=="street furniture":
            specific=("Focus on existing lamps, poles, traffic lights, railings, bollards and similar objects: clean geometry, attachment points, materials and period-correct design while preserving each object's position and count.")
        elif c=="architectural details":
            specific=("Focus only on existing windows, doors, balconies, storefronts and facade details inside the mask: regular perspective, believable frames, glazing, masonry and 1970s-consistent materials while preserving the building identity and layout.")
        elif c=="faces":
            specific=("Focus on existing visible faces only: coherent eyes, nose, mouth, skin texture and perspective while preserving identity, expression, head pose, age and lighting.")
        elif c=="hands":
            specific=("Focus on existing hands only: anatomically coherent fingers, grip and contact with nearby objects while preserving pose and interaction.")
        else:
            specific=("Refine the existing masked objects with coherent geometry, material texture and period-appropriate detail while preserving identity, count, position and relationships to nearby objects.")
        req=universal+historical+specific+" Output only the final Klein editing instruction, with no analysis or headings."
        summary=f"v26 {c}: grouped sectors≤{crops}, context={context}px, source region≤{maxsrc}px, model≤{target}px and ≤3.6MP, stitch={alpha:.2f}; local VLM writes the actual edit prompt"
        return int(radius),int(context),int(maxsrc),int(target),int(crops),float(alpha),req,summary


class DOGMASectorCropsV26(DOGMASemanticMacroCropsV21):
    """V21 spatial grouping with native-resolution preservation up to ~3.6MP / 2560px."""
    @classmethod
    def INPUT_TYPES(cls):
        d=super().INPUT_TYPES()
        d["required"]["group_radius"]=("INT",{"default":200,"min":0,"max":1200,"step":16})
        d["required"]["context_px"]=("INT",{"default":208,"min":0,"max":1024,"step":16})
        d["required"]["max_source_side"]=("INT",{"default":3200,"min":768,"max":8192,"step":16})
        d["required"]["target_long_side"]=("INT",{"default":2560,"min":768,"max":2560,"step":16})
        d["required"]["max_crops"]=("INT",{"default":4,"min":1,"max":8,"step":1})
        return d

    @staticmethod
    def _target_size(h,w,long_side):
        long_side=min(2560,max(768,int(long_side)))
        scale=min(1.0,float(long_side)/float(max(h,w)))
        max_pixels=3_600_000.0
        area=float(h*w)*scale*scale
        if area>max_pixels:
            scale*=math.sqrt(max_pixels/area)
        nh=max(16,int(math.floor((h*scale)/16.0))*16)
        nw=max(16,int(math.floor((w*scale)/16.0))*16)
        return nh,nw

    def make_crops(self,*args,**kwargs):
        out=super().make_crops(*args,**kwargs)
        crops,refs,masks,stitch,info=out
        sizes=[]
        for c in crops:
            sizes.append(f"{int(c.shape[2])}x{int(c.shape[1])}")
        return crops,refs,masks,stitch,("v26 GROUPED sectors / high-res: "+", ".join(sizes)+" | native detail preserved when within 3.6MP; "+str(info))


class DOGMALocalPromptV26:
    """Clean local VLM output and hard-lock non-destructive instance preservation."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"category":("STRING",{"forceInput":True}),"vlm_instruction":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","info")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    def compose(self,category,vlm_instruction):
        c=str(category or "object").strip().lower()
        s=str(vlm_instruction or "").strip()
        s=re.sub(r"```(?:text|markdown|json)?","",s,flags=re.I).replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        # Never let a VLM-generated local prompt authorize destructive cleanup.
        sentences=re.split(r"(?<=[.!?])\s+",s)
        safe=[]
        danger=re.compile(r"\b(remove|delete|erase|eliminate|discard|take away|replace all people|remove people|remove vehicles)\b",re.I)
        for sent in sentences:
            if sent and not danger.search(sent): safe.append(sent)
        s=" ".join(safe).strip()
        if len(s)>1100: s=s[:1100].rsplit(" ",1)[0]
        if not s:
            s=f"Refine the existing masked {c} with coherent geometry and natural photographic detail while preserving every instance, position, scale, colour, pose and occlusion in the current master."
        if c=="signage":
            lock=(" Keep the number, frame, location, size and perspective of all existing signs unchanged. Changes to unreadable graphic content remain strictly inside the existing sign faces. Maintain the current master's lighting, colour and surrounding geometry.")
        elif c=="people":
            lock=(" Every currently visible person remains present in the same position, scale and pose. Keep each body cleanly separated from railings, vehicles, poles and architecture. Maintain the current master's lighting, colour and surrounding geometry.")
        elif c=="vehicles":
            lock=(" Every currently visible vehicle remains present with the same position, direction, scale and approximate colour. Maintain the current master's lighting, road geometry and surrounding objects.")
        else:
            lock=(" Keep the number and placement of all existing masked instances unchanged. Maintain the current master's lighting, colour, geometry and surrounding objects.")
        prompt=(s+lock).strip()
        return prompt,f"v26 local Klein prompt for {c}: {len(prompt)} chars; destructive VLM sentences filtered"


class DOGMALocalVLMBarrierV26:
    """Collect all group-specific Qwen prompts for one sector, unload VLM, then release aligned lists to Klein."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "crops":("IMAGE",),"reference_crops":("IMAGE",),"crop_masks":("MASK",),"stitch":("DOGMA_STITCH",),
            "prompts":("STRING",{"forceInput":True}),"unload_models":("BOOLEAN",{"default":True}),
        }}
    RETURN_TYPES=("IMAGE","IMAGE","MASK","DOGMA_STITCH","STRING","STRING")
    RETURN_NAMES=("crops","reference_crops","crop_masks","stitch","prompts","preview")
    INPUT_IS_LIST=True
    OUTPUT_IS_LIST=(True,True,True,True,True,False)
    FUNCTION="barrier"
    CATEGORY="DOGMA/Semantic Detailer"

    def barrier(self,crops,reference_crops,crop_masks,stitch,prompts,unload_models):
        flag=bool(unload_models[0] if isinstance(unload_models,list) and unload_models else unload_models)
        if flag:
            import gc
            try:
                import comfy.model_management as mm
                mm.unload_all_models(); mm.soft_empty_cache()
            except Exception:
                pass
            gc.collect()
        n=min(len(crops),len(reference_crops),len(crop_masks),len(stitch),len(prompts))
        crops=crops[:n]; reference_crops=reference_crops[:n]; crop_masks=crop_masks[:n]; stitch=stitch[:n]; prompts=prompts[:n]
        preview=[]
        for i,p in enumerate(prompts,1): preview.append(f"GROUP {i}\n{str(p).strip()}\n")
        return crops,reference_crops,crop_masks,stitch,prompts,"\n".join(preview)




class DOGMASectorPlanV261(DOGMASectorPlanV26):
    """v26.1: text/signage is never a generative local sector."""
    @staticmethod
    def _norm(line):
        s=str(line or "").strip().lower()
        # Any text-bearing category is protected by refusing to route it to local generation.
        text_terms=(
            "sign", "signage", "billboard", "advert", "advertisement", "poster", "lettering", "text",
            "logo", "rooftop lettering", "building name", "shop name", "store name", "license plate", "typography"
        )
        if any(k in s for k in text_terms):
            return "__none__"
        return DOGMASectorPlanV26._norm(line)

    @staticmethod
    def _sam(c):
        # Architectural repair intentionally excludes storefronts because storefront masks
        # frequently contain shop lettering/signage.
        if c=="architectural details":
            return "window:220,door:120,balcony:120,architectural detail:160",0.16
        return DOGMASectorPlanV26._sam(c)


class DOGMASectorSettingsV261(DOGMASectorSettingsV26):
    """v26.1: same high-res sector logic, with an absolute text-identity lock."""
    FUNCTION="settings"
    def settings(self,category,restoration_brief):
        radius,context,maxsrc,target,crops,alpha,req,summary=super().settings(category,restoration_brief)
        c=str(category or "").strip().lower()
        text_lock=(
            " ABSOLUTE TEXT IDENTITY LOCK: all visible lettering, glyphs, numbers, logos, building names, rooftop letters, "
            "shop signs, posters, advertisements and license-plate characters inside or near this crop are fixed visual identity. "
            "Do not rewrite, rename, respell, replace, complete, infer or invent any text. Do not change the visible glyph sequence. "
            "If text is blurry or unreadable, preserve that same blurry/ambiguous glyph structure. The target category is NOT text."
        )
        req=str(req)+text_lock
        summary=str(summary)+" | v26.1 TEXTSAFE: all text/signage locked"
        return radius,context,maxsrc,target,crops,alpha,req,summary


class DOGMALocalPromptV261(DOGMALocalPromptV26):
    """v26.1: aggressively remove any VLM sentence that could rewrite identity text."""
    FUNCTION="compose"
    def compose(self,category,vlm_instruction):
        c=str(category or "object").strip().lower()
        s=str(vlm_instruction or "").strip()
        s=re.sub(r"```(?:text|markdown|json)?","",s,flags=re.I).replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        sentences=re.split(r"(?<=[.!?])\s+",s)
        safe=[]
        destructive=re.compile(
            r"\b(remove|delete|erase|eliminate|discard|take away|replace|rewrite|rename|respell|re-spell|"
            r"correct spelling|correct the text|change (?:the )?(?:text|wording|letters|lettering|logo)|"
            r"invent|generate (?:new )?(?:text|words|wording|letters|lettering|logo)|"
            r"create (?:new )?(?:text|words|wording|letters|lettering|logo)|substitute)\b",re.I
        )
        for sent in sentences:
            if sent and not destructive.search(sent):
                safe.append(sent)
        s=" ".join(safe).strip()
        if len(s)>1100:
            s=s[:1100].rsplit(" ",1)[0]
        if not s:
            s=(f"Refine the existing masked {c} with coherent geometry and natural photographic detail while preserving every instance, "
               "position, scale, colour, pose and occlusion in the current master.")
        # Global hard lock, regardless of category.
        lock=(
            " Preserve all existing visible text as fixed identity: same glyph shapes, same character sequence, same wording, same logo, "
            "same placement, same size and same perspective. Blurry or unreadable text remains blurry/ambiguous rather than becoming different words. "
            "Do not alter text-bearing pixels except incidental photographic continuity at the feather edge."
        )
        if c=="people":
            lock += " Every currently visible person remains present in the same position, scale and pose."
        elif c=="vehicles":
            lock += " Every currently visible vehicle remains present with the same position, direction, scale and approximate colour."
        else:
            lock += " Keep the number and placement of all existing masked target instances unchanged."
        prompt=(s+lock).strip()
        return prompt,f"v26.1 TEXTSAFE local Klein prompt for {c}: {len(prompt)} chars; text rewrite/destructive instructions filtered"



# =========================
# DOGMA v27 — OBJECT-CENTRIC LOCAL REFINEMENT
# =========================

class DOGMASectorPlanV27(DOGMASectorPlanV261):
    """
    v27 keeps the v26.1 text-safe planner, but SAM instance caps are intentionally
    finite because local refinement only keeps a handful of complete object groups.
    """
    @staticmethod
    def _sam(c):
        if c in ("","__none__","none"):
            return "nonexistent_placeholder_object_xyz:1",0.50
        if c=="vehicles":
            return "car:80,automobile:80,bus:12,truck:16,van:24,motorcycle:16,bicycle:16",0.13
        if c=="people":
            return "person:100,pedestrian:100,human:100",0.14
        if c=="street furniture":
            return "street lamp:40,traffic light:32,pole:60,bollard:32,railing:40,bench:32,street furniture:40",0.16
        if c=="architectural details":
            return "window:120,door:80,balcony:80,architectural detail:100",0.16
        if c=="faces":
            return "face:100,human face:100",0.16
        if c=="hands":
            return "hand:100,human hand:100",0.17
        if c=="animals":
            return "animal:80,dog:60,cat:60,horse:40,bird:40",0.16
        if c=="furniture":
            return "furniture:80,chair:80,table:60,sofa:40,couch:40,bed:40",0.17
        if c=="machinery":
            return "machine:80,machinery:80,equipment:80,tool:60,appliance:60",0.17
        if c=="clothing":
            return "clothing:100,jacket:60,shirt:60,dress:50,coat:50",0.18
        if c=="products":
            return "product:100,bottle:60,package:60,container:60",0.18
        return f"{c}:80",0.18


class DOGMAObjectSettingsV27:
    """
    Settings for OBJECT-CENTRIC SAM refinement.
    group_radius is a proximity threshold only; it never causes giant region merging.
    max_source_side is a resize ceiling, NEVER a split threshold.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "restoration_brief":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("INT","INT","INT","INT","INT","FLOAT","STRING","STRING")
    RETURN_NAMES=("group_radius","context_px","max_source_side","target_long_side","max_crops","stitch_strength","vlm_request","summary")
    FUNCTION="settings"
    CATEGORY="DOGMA/Semantic Detailer"

    def settings(self,category,restoration_brief):
        c=str(category or "").strip().lower()
        # proximity gap, context, crop ceiling, target long side, max groups, stitch
        table={
            "vehicles":(96,176,4096,3072,8,0.96),
            "people":(72,152,3584,2560,8,0.96),
            "street furniture":(80,152,3584,2560,7,0.94),
            "architectural details":(96,208,4096,3072,6,0.94),
            "faces":(48,112,2304,2048,8,0.96),
            "hands":(40,104,2048,1792,8,0.96),
            "animals":(72,152,3328,2560,7,0.96),
            "furniture":(96,176,4096,3072,7,0.95),
            "machinery":(96,176,4096,3072,7,0.95),
            "clothing":(64,136,3072,2304,8,0.94),
            "products":(64,136,3072,2304,8,0.95),
            "__none__":(48,96,1536,1536,1,0.0),
            "none":(48,96,1536,1536,1,0.0),
        }
        gap,context,maxsrc,target,maxcrops,alpha=table.get(c,(80,160,3584,2560,7,0.95))

        historical=(
            "Historical context: Milan, Italy, 1970s. Use this ONLY to refine an object that is already visibly present: "
            "period-correct design, materials, clothing, typography style and manufacturing details. "
            "It is never permission to create a new object. "
        )
        universal=(
            "Inspect this OBJECT-CENTRIC crop from an already restored master. The crop contains one complete target object "
            "or a very small cluster of directly adjacent target objects; it is NOT a scene tile. "
            "Write one concise FLUX.2 Klein editing instruction describing exactly what is visibly present and what specific defects remain. "
            "Preserve every target instance, silhouette, position, scale, direction or pose, occlusion, approximate colour, surrounding geometry, "
            "lighting and contact shadows. Improve the target beyond the global restoration without redesigning the scene. "
            "All text and logos visible anywhere in the crop are fixed visual identity and must remain unchanged. "
        )
        if c=="vehicles":
            specific=(
                "Refine only the existing vehicle or tiny adjacent vehicle cluster: coherent body panels, wheel geometry, glazing, lights, "
                "trim, perspective and clean separation where vehicles touch. Preserve model family cues supported by the image; do not clone, "
                "replace, add or remove vehicles."
            )
        elif c=="people":
            specific=(
                "Refine only the existing complete person or tiny adjacent group: anatomy, face only where genuinely visible, clothing, hands, "
                "limbs and clean separation from railings, poles, vehicles and architecture. Preserve every person and pose; never remove or add anyone."
            )
        elif c=="street furniture":
            specific=(
                "Refine only the existing complete lamp, traffic light, pole, railing, bollard, bench or related street object: geometry, joints, "
                "materials and mounting points. Keep exact placement and count."
            )
        elif c=="architectural details":
            specific=(
                "Refine only the existing complete window, door, balcony or non-text architectural detail inside the mask: perspective, frames, "
                "glazing, masonry and structural consistency. Preserve building identity and all lettering."
            )
        elif c=="faces":
            specific=(
                "Refine only existing visible faces supported by the pixels: coherent eyes, nose, mouth, skin and perspective while preserving "
                "identity, expression, age, head pose and lighting. Do not invent facial detail where the face is too small or occluded."
            )
        elif c=="hands":
            specific=(
                "Refine only existing visible hands: anatomically coherent fingers, grip and contact with nearby objects while preserving gesture, pose and occlusion."
            )
        else:
            specific=(
                "Refine only the existing masked target object(s): coherent geometry, materials and period-appropriate detail while preserving "
                "identity, count, position and relationships to nearby objects."
            )
        text_lock=(
            " ABSOLUTE TEXT IDENTITY LOCK: do not rewrite, rename, respell, complete, infer or invent lettering, numbers, logos, building names, "
            "shop signs, posters, advertisements or license-plate characters. Blurry or unreadable glyphs stay the same blurry/ambiguous glyphs."
        )
        req=universal+historical+specific+text_lock+" Output only the final editing instruction, no analysis or headings."
        summary=(
            f"v27 {c}: OBJECT-CENTRIC / no local tiling; proximity≤{gap}px; context={context}px; "
            f"whole crop never split; model long side≤{target}px, ≤3.8MP; groups≤{maxcrops}; stitch={alpha:.2f}; "
            "Base 9B local img2img is intended downstream."
        )
        return int(gap),int(context),int(maxsrc),int(target),int(maxcrops),float(alpha),req,summary


class DOGMAObjectClusterCropsV27:
    """
    Convert INDIVIDUAL SAM masks into complete-object crops.
    - Deduplicates overlapping SAM detections.
    - Keeps each object whole.
    - Groups only a tiny number of directly adjacent objects.
    - NEVER splits a crop into tiles.
    - If a crop is too large, the whole crop is downscaled as one image.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "reference_image":("IMAGE",),
            "masks":("MASK",),
            "category":("STRING",{"forceInput":True}),
            "group_radius":("INT",{"default":80,"min":0,"max":512,"step":8}),
            "context_px":("INT",{"default":160,"min":0,"max":768,"step":8}),
            "max_source_side":("INT",{"default":4096,"min":768,"max":8192,"step":16}),
            "target_long_side":("INT",{"default":3072,"min":768,"max":4096,"step":16}),
            "max_crops":("INT",{"default":8,"min":1,"max":16,"step":1}),
            "mask_threshold":("FLOAT",{"default":0.50,"min":0.01,"max":0.99,"step":0.01}),
        }}
    RETURN_TYPES=("IMAGE","IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","reference_crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,True,False)
    FUNCTION="make_crops"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _resize_image(image,nh,nw):
        return F.interpolate(
            image.movedim(-1,1),size=(nh,nw),mode="bicubic",
            align_corners=False,antialias=True
        ).movedim(1,-1).clamp(0,1)

    @staticmethod
    def _resize_mask(mask,nh,nw):
        if mask.ndim==2: mask=mask.unsqueeze(0)
        return F.interpolate(
            mask.unsqueeze(1).float(),size=(nh,nw),
            mode="bilinear",align_corners=False
        ).squeeze(1).clamp(0,1)

    @staticmethod
    def _bbox_gap(a,b):
        ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
        dx=max(0,max(ax1,bx1)-min(ax2,bx2))
        dy=max(0,max(ay1,by1)-min(ay2,by2))
        return math.sqrt(float(dx*dx+dy*dy))

    @staticmethod
    def _bbox_iou(a,b):
        ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
        ix1=max(ax1,bx1); iy1=max(ay1,by1); ix2=min(ax2,bx2); iy2=min(ay2,by2)
        iw=max(0,ix2-ix1); ih=max(0,iy2-iy1)
        inter=float(iw*ih)
        if inter<=0: return 0.0
        aa=float(max(0,ax2-ax1)*max(0,ay2-ay1))
        bb=float(max(0,bx2-bx1)*max(0,by2-by1))
        return inter/max(1.0,aa+bb-inter)

    @staticmethod
    def _target_size(h,w,long_side):
        long_side=max(768,min(4096,int(long_side)))
        scale=min(1.0,long_side/float(max(h,w)))
        max_pixels=3_800_000.0
        area=float(h*w)*scale*scale
        if area>max_pixels:
            scale*=math.sqrt(max_pixels/area)
        nh=max(16,int(math.floor((h*scale)/16.0))*16)
        nw=max(16,int(math.floor((w*scale)/16.0))*16)
        return nh,nw

    @staticmethod
    def _max_objects(category):
        c=str(category or "").strip().lower()
        if c=="vehicles": return 3
        if c=="people": return 2
        if c in ("faces","hands"): return 2
        if c=="architectural details": return 2
        if c=="street furniture": return 2
        return 2

    def make_crops(self,image,reference_image,masks,category,group_radius,context_px,
                   max_source_side,target_long_side,max_crops,mask_threshold):
        if image.ndim!=4 or image.shape[0]<1:
            raise ValueError("DOGMA v27 Object Crops expects IMAGE [B,H,W,C].")
        src=image[0:1,...,:3].float()
        H,W=int(src.shape[1]),int(src.shape[2])

        ref=reference_image[0:1,...,:3].float()
        if ref.shape[1]!=H or ref.shape[2]!=W:
            ref=self._resize_image(ref,H,W)

        if masks.ndim==2: masks=masks.unsqueeze(0)
        masks=masks.detach().float().cpu()
        N=int(masks.shape[0]); MH=int(masks.shape[-2]); MW=int(masks.shape[-1])
        threshold=float(mask_threshold)

        detections=[]
        sx=W/float(MW); sy=H/float(MH)
        # Work on SAM resolution first; never expand an entire mask stack to master resolution.
        for i in range(N):
            m=masks[i]
            hard=m>threshold
            count=int(hard.sum().item())
            if count<6:
                continue
            ys,xs=torch.where(hard)
            x1s=int(xs.min().item()); x2s=int(xs.max().item())+1
            y1s=int(ys.min().item()); y2s=int(ys.max().item())+1
            # Reject pathological masks that cover most of the frame for a discrete category.
            frac=count/float(max(1,MH*MW))
            if frac>0.55:
                continue
            x1=max(0,int(math.floor(x1s*sx))); y1=max(0,int(math.floor(y1s*sy)))
            x2=min(W,int(math.ceil(x2s*sx))); y2=min(H,int(math.ceil(y2s*sy)))
            if x2-x1<4 or y2-y1<4:
                continue
            detections.append({
                "idx":i,"bbox":(x1,y1,x2,y2),
                "area":float(count)*sx*sy,
                "sam_bbox":(x1s,y1s,x2s,y2s)
            })

        if not detections:
            side=min(H,W,768)
            x=max(0,(W-side)//2); y=max(0,(H-side)//2)
            cur=src[:,y:y+side,x:x+side,:]
            old=ref[:,y:y+side,x:x+side,:]
            z=torch.zeros((1,cur.shape[1],cur.shape[2]),dtype=torch.float32)
            meta={"x":x,"y":y,"width":side,"height":side,
                  "source_width":W,"source_height":H,"noop":True,"group_id":-1}
            return ([cur],[old],[z],[meta],"v27: no valid individual object detections; safe no-op.")

        # Deduplicate synonyms such as car/automobile or person/human.
        detections.sort(key=lambda d:d["area"],reverse=True)
        unique=[]
        for d in detections:
            duplicate=False
            for u in unique:
                if self._bbox_iou(d["bbox"],u["bbox"])>=0.72:
                    duplicate=True; break
            if not duplicate:
                unique.append(d)
        detections=unique

        # Greedy tiny clusters only. Never merge merely to satisfy max_crops.
        max_obj=self._max_objects(category)
        gap=float(group_radius)
        remaining=list(range(len(detections)))
        groups=[]
        while remaining:
            seed=remaining.pop(0)
            members=[seed]
            ub=detections[seed]["bbox"]
            while len(members)<max_obj and remaining:
                best=None
                for ridx,j in enumerate(remaining):
                    g=self._bbox_gap(ub,detections[j]["bbox"])
                    if g<=gap and (best is None or g<best[0]):
                        best=(g,ridx,j)
                if best is None: break
                _,ridx,j=best
                remaining.pop(ridx)
                members.append(j)
                b=detections[j]["bbox"]
                ub=(min(ub[0],b[0]),min(ub[1],b[1]),max(ub[2],b[2]),max(ub[3],b[3]))
            groups.append((members,ub))

        # If there are too many groups, keep the most visually significant groups.
        # Crucially, do NOT merge distant objects into one giant crop.
        groups.sort(key=lambda gb:sum(detections[i]["area"] for i in gb[0]),reverse=True)
        groups=groups[:max(1,int(max_crops))]
        # Stable visual order after selection.
        groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))

        crops=[]; refs=[]; crop_masks=[]; stitch=[]
        info_lines=[]
        for gid,(members,ub) in enumerate(groups):
            x1,y1,x2,y2=ub
            # Context around the WHOLE object/group.
            cx1=max(0,x1-int(context_px)); cy1=max(0,y1-int(context_px))
            cx2=min(W,x2+int(context_px)); cy2=min(H,y2+int(context_px))
            cx1=(cx1//16)*16; cy1=(cy1//16)*16
            cx2=min(W,int(math.ceil(cx2/16.0))*16); cy2=min(H,int(math.ceil(cy2/16.0))*16)
            if cx2<=cx1 or cy2<=cy1:
                continue

            cur=src[:,cy1:cy2,cx1:cx2,:]
            old=ref[:,cy1:cy2,cx1:cx2,:]
            ch,cw=int(cur.shape[1]),int(cur.shape[2])

            # Reconstruct only the selected object masks into this crop.
            local=torch.zeros((1,ch,cw),dtype=torch.float32)
            for di in members:
                m=masks[detections[di]["idx"]]
                # Convert full-res crop rectangle back to SAM coordinates and resize that slice.
                lx1=max(0,int(math.floor(cx1/float(W)*MW)))
                ly1=max(0,int(math.floor(cy1/float(H)*MH)))
                lx2=min(MW,int(math.ceil(cx2/float(W)*MW)))
                ly2=min(MH,int(math.ceil(cy2/float(H)*MH)))
                sub=m[ly1:ly2,lx1:lx2]
                if sub.numel()==0:
                    continue
                sub=F.interpolate(sub[None,None],size=(ch,cw),mode="bilinear",align_corners=False)[0,0]
                local=torch.maximum(local,sub[None].cpu())
            local=local.clamp(0,1)

            # WHOLE crop resize only. Never split into tiles.
            nh,nw=self._target_size(ch,cw,int(target_long_side))
            # max_source_side is an additional conservative resize ceiling, not a split trigger.
            ceiling=max(768,int(max_source_side))
            if max(ch,cw)>ceiling:
                factor=ceiling/float(max(ch,cw))
                ch2=max(16,int(math.floor(ch*factor/16.0))*16)
                cw2=max(16,int(math.floor(cw*factor/16.0))*16)
                nh=min(nh,ch2); nw=min(nw,cw2)
            cur_r=self._resize_image(cur,nh,nw)
            old_r=self._resize_image(old,nh,nw)
            mask_r=self._resize_mask(local,nh,nw)

            crops.append(cur_r); refs.append(old_r); crop_masks.append(mask_r)
            stitch.append({
                "x":int(cx1),"y":int(cy1),"width":int(cx2-cx1),"height":int(cy2-cy1),
                "source_width":W,"source_height":H,"group_id":int(gid),"noop":False,
                "members":len(members),"object_centric":True
            })
            info_lines.append(
                f"group {gid+1}: {len(members)} object(s), source {cw}x{ch} -> model {nw}x{nh}; NEVER split"
            )

        if not crops:
            side=min(H,W,768)
            x=max(0,(W-side)//2); y=max(0,(H-side)//2)
            cur=src[:,y:y+side,x:x+side,:]
            old=ref[:,y:y+side,x:x+side,:]
            z=torch.zeros((1,cur.shape[1],cur.shape[2]),dtype=torch.float32)
            meta={"x":x,"y":y,"width":side,"height":side,
                  "source_width":W,"source_height":H,"noop":True,"group_id":-1}
            return ([cur],[old],[z],[meta],"v27: detections existed but no valid object crop survived; safe no-op.")

        return (
            crops,refs,crop_masks,stitch,
            "v27 OBJECT-CENTRIC SAM: individual masks -> dedupe -> max "
            f"{max_obj} adjacent object(s)/crop; no giant-region merge; no crop splitting. "
            + " | ".join(info_lines)
        )



# =========================
# DOGMA v31 — MASK-HEAVY SAM + SINGLE 4B AUDIT / BASE 0.35
# =========================

class DOGMAAuditSectorPlanV31:
    """
    One Qwen3-VL audit drives both category choice and fallback defect boxes.
    The first 19 outputs intentionally mirror the old v26/v27 6-slot layout
    (real sectors are slots 2-4) so the existing workflow wiring stays stable.
    Extra outputs provide per-sector fallback masks and defect hints.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "planner_text":("STRING",{"forceInput":True,"multiline":True}),
            "mask_reference":("IMAGE",),
        }}

    RETURN_TYPES = (
        ("STRING",) +
        tuple(x for _ in range(6) for x in ("STRING","STRING","FLOAT")) +
        ("MASK","STRING","MASK","STRING","MASK","STRING")
    )
    RETURN_NAMES = (
        ("plan_preview",) +
        tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"sam_threshold_{i}")) +
        ("audit_masks_2","audit_hints_2","audit_masks_3","audit_hints_3","audit_masks_4","audit_hints_4")
    )
    FUNCTION="build"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _norm(s):
        s=str(s or "").strip().lower()
        s=re.sub(r"^[\s\-\*\d\.)]+","",s)
        if not s or s in ("none","unused","n/a","__none__"):
            return "__none__"
        if any(k in s for k in ("car","vehicle","automobile","bus","coach","truck","van","motorcycle","bicycle","scooter")):
            return "vehicles"
        if any(k in s for k in ("person","people","pedestrian","human","crowd","figure","silhouette")):
            return "people"
        if any(k in s for k in ("window","door","balcony","facade","façade","building","architecture","architectural")):
            return "architectural details"
        if any(k in s for k in ("street furniture","traffic light","street light","street lamp","lamp post","lamppost","bollard","railing","guardrail","pole","bench")):
            return "street furniture"
        if any(k in s for k in ("face","facial")):
            return "faces"
        if any(k in s for k in ("hand","finger")):
            return "hands"
        if any(k in s for k in ("animal","dog","cat","horse","bird")):
            return "animals"
        if any(k in s for k in ("furniture","chair","table","sofa","couch","bed")):
            return "furniture"
        if any(k in s for k in ("machine","machinery","equipment","appliance","tool")):
            return "machinery"
        if any(k in s for k in ("clothing","clothes","garment","jacket","dress","shirt","coat")):
            return "clothing"
        if any(k in s for k in ("product","package","bottle","container")):
            return "products"
        # text/signage deliberately never enters the local generative path.
        if any(k in s for k in ("sign","signage","billboard","advert","poster","lettering","text","logo","license plate","typography")):
            return "__none__"
        # broad surfaces are not local sectors.
        if any(k in s for k in ("road","asphalt","pavement","sidewalk","grass","vegetation","tree","sky","cloud","water","wall","floor","background","haze","fog")):
            return "__none__"
        return "__none__"

    @staticmethod
    def _sam(c):
        # Recall-biased prompts. Qwen defect boxes are only a fallback; SAM still
        # provides the actual object masks whenever it can.
        if c=="vehicles":
            return "car:120,automobile:120,vehicle:120,bus:24,coach:20,truck:24,van:32,motorcycle:20,bicycle:20,scooter:16",0.11
        if c=="people":
            return "person:140,pedestrian:140,human:140,human figure:120,human silhouette:120,crowd:60",0.11
        if c=="architectural details":
            return "window:160,door:120,balcony:120,facade:100,building detail:120,architectural detail:140",0.14
        if c=="street furniture":
            return "street lamp:70,traffic light:50,pole:90,bollard:50,railing:90,guardrail:60,bench:40,street furniture:70",0.14
        if c=="faces":
            return "face:120,human face:120",0.14
        if c=="hands":
            return "hand:120,human hand:120",0.15
        if c=="animals":
            return "animal:100,dog:80,cat:80,horse:60,bird:60",0.14
        if c=="furniture":
            return "furniture:100,chair:100,table:80,sofa:60,couch:60,bed:50",0.15
        if c=="machinery":
            return "machine:100,machinery:100,equipment:100,tool:80,appliance:80",0.15
        if c=="clothing":
            return "clothing:120,jacket:80,shirt:80,dress:60,coat:60",0.16
        if c=="products":
            return "product:100,bottle:80,package:80,container:80",0.16
        return "nonexistent_placeholder_object_xyz:1",0.50

    @staticmethod
    def _empty_mask(h,w):
        return torch.zeros((1,h,w),dtype=torch.float32)

    def build(self,planner_text,mask_reference):
        if mask_reference.ndim!=4 or mask_reference.shape[0]<1:
            raise ValueError("DOGMA v31 audit plan expects IMAGE [B,H,W,C] for mask_reference.")
        H=int(mask_reference.shape[1]); W=int(mask_reference.shape[2])
        text=str(planner_text or "").replace("\r","\n")

        targets=[]
        defects=[]
        # TARGET|people
        # DEFECT|people|x1|y1|x2|y2|priority|short hint
        for raw in text.splitlines():
            line=raw.strip().strip("`")
            if not line:
                continue
            parts=[p.strip() for p in line.split("|")]
            tag=parts[0].upper() if parts else ""
            if tag=="TARGET" and len(parts)>=2:
                c=self._norm(parts[1])
                if c!="__none__" and c not in targets:
                    targets.append(c)
            elif tag=="DEFECT" and len(parts)>=8:
                c=self._norm(parts[1])
                if c=="__none__":
                    continue
                try:
                    x1=max(0,min(1000,int(round(float(parts[2])))))
                    y1=max(0,min(1000,int(round(float(parts[3])))))
                    x2=max(0,min(1000,int(round(float(parts[4])))))
                    y2=max(0,min(1000,int(round(float(parts[5])))))
                    pr=max(1,min(5,int(round(float(parts[6])))))
                except Exception:
                    continue
                if x2<=x1 or y2<=y1:
                    continue
                hint=" | ".join(parts[7:]).strip()
                defects.append((c,x1,y1,x2,y2,pr,hint))

        # If TARGET lines were malformed/missing, infer top categories from defects.
        if len(targets)<3:
            scores={}
            for c,_,_,_,_,pr,_ in defects:
                scores[c]=scores.get(c,0.0)+float(pr)
            for c,_ in sorted(scores.items(),key=lambda kv:(-kv[1],kv[0])):
                if c not in targets:
                    targets.append(c)
                if len(targets)>=3:
                    break
        targets=targets[:3]
        while len(targets)<3:
            targets.append("__none__")

        masks_by_cat={}
        hints_by_cat={}
        for c,x1,y1,x2,y2,pr,hint in defects:
            if c not in targets:
                continue
            # normalized 0..1000 -> mask_reference coordinates.
            ax1=max(0,min(W-1,int(math.floor(x1/1000.0*W))))
            ay1=max(0,min(H-1,int(math.floor(y1/1000.0*H))))
            ax2=max(ax1+1,min(W,int(math.ceil(x2/1000.0*W))))
            ay2=max(ay1+1,min(H,int(math.ceil(y2/1000.0*H))))
            # Tiny proportional safety ring. This is NOT the later large local
            # edit expansion; it just ensures the defect interaction is inside.
            pad=max(4,int(round(0.012*max(ax2-ax1,ay2-ay1))))
            ax1=max(0,ax1-pad); ay1=max(0,ay1-pad)
            ax2=min(W,ax2+pad); ay2=min(H,ay2+pad)
            m=torch.zeros((1,H,W),dtype=torch.float32)
            m[:,ay1:ay2,ax1:ax2]=1.0
            masks_by_cat.setdefault(c,[]).append(m)
            if hint:
                hints_by_cat.setdefault(c,[]).append(f"P{pr}: {hint}")

        slots=["__none__",targets[0],targets[1],targets[2],"__none__","__none__"]
        out=[]
        preview=[]
        for i,c in enumerate(slots,1):
            p,t=self._sam(c)
            preview.append(f"SLOT {i}: {c}\nSAM: {p}\nthreshold={t:.2f}")
            out.extend([c,p,float(t)])

        extras=[]
        for c in targets:
            mm=masks_by_cat.get(c,[])
            if mm:
                m=torch.cat(mm,dim=0)
            else:
                m=self._empty_mask(H,W)
            hints="; ".join(hints_by_cat.get(c,[]))[:1200]
            extras.extend([m,hints])

        defect_summary=[]
        for c,x1,y1,x2,y2,pr,hint in defects:
            if c in targets:
                defect_summary.append(f"{c} P{pr} [{x1},{y1},{x2},{y2}] {hint}")
        preview_text="\n\n".join(preview)
        if defect_summary:
            preview_text += "\n\nQWEN FALLBACK DEFECT BOXES:\n" + "\n".join(defect_summary)
        else:
            preview_text += "\n\nQWEN FALLBACK DEFECT BOXES: none"

        return (preview_text,*out,*extras)


class DOGMAMergeSamAuditV31:
    """
    Merge normal SAM instance masks with Qwen defect boxes.
    - SAM remains primary.
    - If a Qwen box overlaps SAM, enlarge the SAM-supported region into the
      interaction area instead of replacing it with a raw rectangle.
    - If SAM completely misses a malformed object, the Qwen box survives as
      a fallback object mask.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "sam_masks":("MASK",),
            "audit_masks":("MASK",),
            "expand_px":("INT",{"default":22,"min":0,"max":96,"step":2}),
        }}
    RETURN_TYPES=("MASK","STRING")
    RETURN_NAMES=("merged_masks","info")
    FUNCTION="merge"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _resize_stack(m,h,w):
        if m.ndim==2: m=m.unsqueeze(0)
        if tuple(m.shape[-2:])==(h,w):
            return m.float()
        return F.interpolate(m.unsqueeze(1).float(),size=(h,w),mode="nearest").squeeze(1)

    def merge(self,sam_masks,audit_masks,expand_px):
        if sam_masks.ndim==2: sam_masks=sam_masks.unsqueeze(0)
        sam=sam_masks.detach().float().cpu().contiguous()
        H,W=int(sam.shape[-2]),int(sam.shape[-1])
        aud=self._resize_stack(audit_masks.detach().float().cpu(),H,W).clamp(0,1)

        # Filter truly empty SAM masks.
        sam_list=[]
        for i in range(int(sam.shape[0])):
            if int((sam[i]>0.5).sum().item())>=4:
                sam_list.append(sam[i:i+1])
        if not sam_list:
            sam_list=[torch.zeros((1,H,W),dtype=torch.float32)]
        sam_nonempty=[m for m in sam_list if int((m>0.5).sum().item())>=4]
        union=torch.zeros((1,H,W),dtype=torch.float32)
        for m in sam_nonempty:
            union=torch.maximum(union,m)

        out=list(sam_nonempty)
        added_overlap=0; added_fallback=0
        radius=max(0,int(expand_px))
        k=2*radius+1 if radius>0 else 1

        for i in range(int(aud.shape[0])):
            a=(aud[i:i+1]>0.5).float()
            area=float(a.sum().item())
            if area<4:
                continue
            overlap=((a>0.5)&(union>0.5)).float()
            ov=float(overlap.sum().item())/max(1.0,area)

            if ov>=0.02 and union.sum()>0:
                seed=union*a
                if radius>0 and seed.sum()>0:
                    expanded=F.max_pool2d(seed.unsqueeze(1),kernel_size=k,stride=1,padding=radius).squeeze(1)
                else:
                    expanded=seed
                # Allow expansion through the Qwen-described interaction box,
                # plus a tiny ring, but not across the scene.
                cap=a
                if radius>0:
                    cap=F.max_pool2d(a.unsqueeze(1),kernel_size=min(k,25),stride=1,padding=min(radius,12)).squeeze(1)
                aug=(expanded*cap).clamp(0,1)
                if aug.sum()>0:
                    out.append(aug)
                    added_overlap+=1
            else:
                # SAM missed it: preserve the whole Qwen defect box as fallback.
                out.append(a)
                added_fallback+=1

        if not out:
            out=[torch.zeros((1,H,W),dtype=torch.float32)]
        merged=torch.cat(out,dim=0).contiguous()
        return merged,(
            f"v31 SAM+AUDIT masks: SAM instances={len(sam_nonempty)}, "
            f"overlap expansions={added_overlap}, Qwen-only fallbacks={added_fallback}, "
            f"total mask stack={int(merged.shape[0])}"
        )


class DOGMAActiveLocalPromptV31:
    """
    One active category prompt replaces the expensive per-object Qwen calls.
    The full-frame 4B audit supplies defect hints; Klein itself sees each local crop.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "audit_hints":("STRING",{"forceInput":True,"multiline":True}),
            "restoration_brief":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","info")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    def compose(self,category,audit_hints,restoration_brief):
        c=str(category or "").strip().lower()
        hints=re.sub(r"\s+"," ",str(audit_hints or "")).strip()
        hist=(
            "Use Milan, Italy, 1970s only as a plausibility constraint for an object that is already visible. "
            "Do not change the object's identity merely to make it more period-like. "
        )
        common=(
            "SECOND-PASS LOCAL REPAIR. Inspect the masked existing object(s) in this crop and make VISIBLE structural corrections where defects remain. "
            "This is not a generic upscale/sharpen pass. Reconstruct malformed, fused, melted, duplicated or internally inconsistent geometry supported by the pixels. "
            "Keep the same existing instance count, positions, scale, pose/direction, approximate colours, occlusion order, camera perspective, lighting and contact shadows. "
            "Do not add or remove subjects. "
        )
        if c=="vehicles":
            specific=(
                "Actively repair broken vehicle geometry: fused neighboring cars, impossible body panels, malformed wheels/tires, broken windows, lights, trim, rooflines and perspective. "
                "Separate touching vehicles cleanly when the source supports separate vehicles, while preserving each vehicle's footprint, direction and approximate colour. "
            )
        elif c=="people":
            specific=(
                "Actively repair malformed people: fused bodies, impossible limbs, melted silhouettes, duplicated anatomy, and bodies merged into railings, poles, vehicles or architecture. "
                "Reconstruct each EXISTING person as a coherent human figure in the same pose and place, with clothing and visible anatomy consistent with the image. "
            )
        elif c=="architectural details":
            specific=(
                "Actively repair local architectural defects: warped or duplicated windows, inconsistent frames, broken balcony geometry, malformed doors, impossible facade edges and repetitive structures. "
                "Preserve the building identity, layout, materials and perspective. "
            )
        elif c=="street furniture":
            specific=(
                "Actively repair existing railings, poles, lamps, traffic lights, bollards and similar objects: straighten impossible geometry, restore joints, spacing, attachment points and coherent materials. "
            )
        elif c=="faces":
            specific=(
                "Repair only clearly visible existing facial structure that is malformed: coherent eyes, nose, mouth, head geometry and skin detail, preserving identity, expression, age, pose and lighting. "
            )
        elif c=="hands":
            specific=(
                "Repair existing malformed hands and fingers, grip and contact geometry while preserving the original gesture, pose and interaction with nearby objects. "
            )
        else:
            specific=(
                "Actively repair the existing masked target object(s), correcting visibly malformed geometry and material detail while preserving identity and scene relationships. "
            )
        text_lock=(
            "TEXT LOCK: all visible lettering, numbers, logos, building names, signs, advertisements and license-plate glyphs are fixed identity. "
            "Do not rewrite, complete, respell or invent text; unreadable glyphs remain ambiguous. "
        )
        hint_clause=""
        if hints:
            hint_clause=(
                "Full-frame audit noticed possible defects in this category: "+hints+
                ". Apply a listed defect only if it is actually visible in THIS crop; otherwise ignore it. "
            )
        prompt=(common+specific+hint_clause+hist+text_lock).strip()
        return prompt,f"v31 ACTIVE {c} prompt | audit hints={'yes' if hints else 'no'} | Base9B 20-step CFG4 denoise0.35"




class DOGMAObjectSettingsV31(DOGMAObjectSettingsV27):
    """v31: fewer, denser compact groups to reduce Base-9B calls without returning to giant macro crops."""
    FUNCTION="settings"
    def settings(self,category,restoration_brief):
        c=str(category or "").strip().lower()
        table={
            "vehicles":(120,192,4096,3072,5,0.96),
            "people":(96,176,3584,2560,5,0.96),
            "street furniture":(112,176,3584,2560,5,0.94),
            "architectural details":(120,224,4096,3072,4,0.94),
            "faces":(64,128,2304,2048,5,0.96),
            "hands":(56,120,2048,1792,5,0.96),
            "animals":(96,176,3328,2560,5,0.96),
            "furniture":(120,192,4096,3072,5,0.95),
            "machinery":(120,192,4096,3072,5,0.95),
            "clothing":(80,152,3072,2304,5,0.94),
            "products":(80,152,3072,2304,5,0.95),
            "__none__":(48,96,1536,1536,1,0.0),
            "none":(48,96,1536,1536,1,0.0),
        }
        gap,context,maxsrc,target,maxcrops,alpha=table.get(c,(104,176,3584,2560,5,0.95))
        # The old vlm_request output is retained for socket compatibility but no
        # per-object VLM is used in v31.
        req="v31 uses one full-frame 4B audit; no per-object VLM call."
        summary=(
            f"v31 {c}: compact grouped objects / no local tiling; proximity≤{gap}px; context={context}px; "
            f"whole crop never split; model long side≤{target}px, ≤3.8MP; groups≤{maxcrops}; stitch={alpha:.2f}; "
            "Base9B 20-step CFG4 denoise0.35."
        )
        return int(gap),int(context),int(maxsrc),int(target),int(maxcrops),float(alpha),req,summary


class DOGMAObjectClusterCropsV31(DOGMAObjectClusterCropsV27):
    """v31 compact grouping: several truly adjacent instances, never a scene-sized macro region."""
    @staticmethod
    def _max_objects(category):
        c=str(category or "").strip().lower()
        if c=="vehicles": return 4
        if c=="people": return 3
        if c=="architectural details": return 3
        if c=="street furniture": return 3
        if c in ("faces","hands"): return 3
        return 3




# =========================
# DOGMA v34 — DUAL SEMANTIC / SHORT PROMPTS / SAFE STITCH
# =========================

class DOGMATilePromptComposerV34A:
    """Short, front-loaded prompt for the first semantic tiled restoration pass."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tile_report":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _clean(s, limit=320):
        s=str(s or "").replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        if len(s)>limit:
            s=s[:limit].rsplit(" ",1)[0]
        return s

    @staticmethod
    def _field(report, key):
        for line in str(report or "").splitlines():
            if line.strip().upper().startswith(key+":"):
                return line.split(":",1)[1].strip()
        return ""

    def compose(self,tile_report,project_context):
        report=self._clean(tile_report,420)
        focus=self._clean(self._field(tile_report,"FOCUS"),180)
        protect=self._clean(self._field(tile_report,"PROTECT"),160)
        if not focus or focus.lower() in ("none","n/a"):
            focus="existing visible objects, edges and materials"
        if not protect:
            protect="true blur, smooth sky or haze, and existing text/logos"
        context=self._clean(project_context,120)
        # Klein is highly sensitive to the first words. Put the exact action and subjects first.
        prompt=(
            f"RESTORE {focus.upper()}. "
            "Reconstruct only these existing elements with coherent geometry and natural photographic detail. "
            "Keep exact count, position, scale, direction, pose, occlusion and focus. "
            f"PROTECT {protect}; leave those regions unchanged. "
            "No new or missing objects. Keep all existing text/logo glyphs unchanged."
        )
        if context:
            prompt += " Style context only where visibly supported: " + context
        return (prompt,report)


class DOGMATilePromptComposerV34B:
    """Short, front-loaded quality-control prompt for the shifted second tiled pass."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tile_report":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _clean(s,limit=320):
        s=str(s or "").replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        if len(s)>limit:
            s=s[:limit].rsplit(" ",1)[0]
        return s

    @staticmethod
    def _field(report,key):
        for line in str(report or "").splitlines():
            if line.strip().upper().startswith(key+":"):
                return line.split(":",1)[1].strip()
        return ""

    def compose(self,tile_report,project_context):
        report=self._clean(tile_report,420)
        fix=self._clean(self._field(tile_report,"FIX"),190)
        keep=self._clean(self._field(tile_report,"KEEP"),160)
        if not keep:
            keep="correct objects, true optical blur, smooth sky/haze and all text/logos"
        if not fix or fix.lower() in ("none","nothing","no visible defect","n/a"):
            prompt=(
                "PRESERVE THIS TILE. Keep the current restored master unchanged except for obvious tile-edge continuity. "
                f"KEEP {keep}. No new or missing objects. Do not rewrite text."
            )
        else:
            prompt=(
                f"FIX {fix.upper()}. "
                "Correct only these existing defects; restore coherent geometry and consistent local focus/detail. "
                "Keep exact object count, position, scale, direction, pose and occlusion. "
                f"KEEP {keep} unchanged. No new or missing objects. Do not rewrite text."
            )
        return (prompt,report)


class DOGMATileSecondPassGateV34:
    """If the second-pass VLM says there is nothing to fix, keep the source tile exactly."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),
            "source":("IMAGE",),
            "prompt":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="gate"
    CATEGORY="DOGMA/Semantic Detailer"

    def gate(self,generated,source,prompt):
        p=str(prompt or "").strip().upper()
        if p.startswith("PRESERVE THIS TILE"):
            return (source, "v34 pass-B gate: VLM requested no repair; exact source tile kept")
        return (generated, "v34 pass-B gate: semantic repair active")


class DOGMAShiftPadV34:
    """Reflect-pad a restored master so the second D&C grid is shifted by half a stride."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "shift_x":("INT",{"default":384,"min":0,"max":1024,"step":16}),
            "shift_y":("INT",{"default":384,"min":0,"max":1024,"step":16}),
        }}
    RETURN_TYPES=("IMAGE","DOGMA_SHIFT_META","STRING")
    RETURN_NAMES=("image","meta","info")
    FUNCTION="pad"
    CATEGORY="DOGMA/Semantic Detailer"

    def pad(self,image,shift_x,shift_y):
        x=max(0,int(shift_x)); y=max(0,int(shift_y))
        B,H,W,C=image.shape
        if x==0 and y==0:
            meta={"pad_x":0,"pad_y":0,"orig_w":int(W),"orig_h":int(H)}
            return (image,meta,"v34 shifted grid: no pad")
        chw=image[...,:3].movedim(-1,1)
        # reflect requires pad smaller than the corresponding dimension
        x=min(x,max(0,W-1)); y=min(y,max(0,H-1))
        out=F.pad(chw,(x,x,y,y),mode="reflect").movedim(1,-1).clamp(0,1)
        meta={"pad_x":int(x),"pad_y":int(y),"orig_w":int(W),"orig_h":int(H)}
        return (out,meta,f"v34 shifted grid pad: x={x}, y={y}, {W}x{H} -> {out.shape[2]}x{out.shape[1]}")


class DOGMAUnshiftCropV34:
    """Remove scaled reflect padding after the shifted 1.5x tiled pass."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "meta":("DOGMA_SHIFT_META",),
            "scale":("FLOAT",{"default":1.5,"min":1.0,"max":4.0,"step":0.05}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="crop"
    CATEGORY="DOGMA/Semantic Detailer"

    def crop(self,image,meta,scale):
        s=float(scale)
        px=int(round(int(meta.get("pad_x",0))*s)); py=int(round(int(meta.get("pad_y",0))*s))
        tw=max(1,int(round(int(meta.get("orig_w",image.shape[2]))*s)))
        th=max(1,int(round(int(meta.get("orig_h",image.shape[1]))*s)))
        H,W=int(image.shape[1]),int(image.shape[2])
        x1=max(0,min(px,W-1)); y1=max(0,min(py,H-1))
        x2=min(W,x1+tw); y2=min(H,y1+th)
        out=image[:,y1:y2,x1:x2,:]
        if out.shape[1]!=th or out.shape[2]!=tw:
            out=F.interpolate(out.movedim(-1,1),size=(th,tw),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
        return (out,f"v34 unshift crop: {W}x{H} -> {tw}x{th} at ({x1},{y1})")


class DOGMAFastDualMaskV34:
    """GPU-friendly threshold+dilate plus an opaque-core feathered stitch mask."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "mask":("MASK",),
            "threshold":("FLOAT",{"default":0.50,"min":0.01,"max":0.99,"step":0.01}),
            "generation_grow":("INT",{"default":12,"min":0,"max":96,"step":1}),
            "stitch_grow":("INT",{"default":2,"min":0,"max":48,"step":1}),
            "stitch_feather":("INT",{"default":8,"min":0,"max":48,"step":1}),
        }}
    RETURN_TYPES=("MASK","MASK","STRING")
    RETURN_NAMES=("generation_mask","stitch_mask","info")
    FUNCTION="make"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _dilate(x,r):
        r=max(0,int(r))
        if r==0: return x
        return F.max_pool2d(x.unsqueeze(1),kernel_size=2*r+1,stride=1,padding=r).squeeze(1)

    @staticmethod
    def _outward_feather(core,r):
        r=max(0,int(r))
        if r==0: return core
        x=core.unsqueeze(1)
        k=2*r+1
        # Two cheap separable-ish smoothing passes. The max keeps the semantic core exactly opaque.
        blur=F.avg_pool2d(x,kernel_size=k,stride=1,padding=r)
        blur=F.avg_pool2d(blur,kernel_size=k,stride=1,padding=r)
        return torch.maximum(core,blur.squeeze(1).clamp(0,1))

    def make(self,mask,threshold,generation_grow,stitch_grow,stitch_feather):
        with torch.no_grad():
            m=mask.float()
            if m.ndim==2: m=m.unsqueeze(0)
            # The old VLM mask processor was a major CPU bottleneck. Prefer CUDA when available.
            if torch.cuda.is_available() and m.device.type!="cuda":
                m=m.cuda(non_blocking=True)
            core=(m>=float(threshold)).float()
            gen=self._dilate(core,int(generation_grow)).clamp(0,1)
            stitch_core=self._dilate(core,int(stitch_grow)).clamp(0,1)
            stitch=self._outward_feather(stitch_core,int(stitch_feather)).clamp(0,1)
            return (gen,stitch,
                    f"v34 fast masks | gen +{int(generation_grow)} hard | stitch +{int(stitch_grow)} feather {int(stitch_feather)} | opaque core")


class DOGMASafeMaskedStitchV34:
    """Opaque-core stitch with context color alignment; feather never makes the object itself transparent."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "base_image":("IMAGE",),
            "patches":("IMAGE",),
            "masks":("MASK",),
            "stitch":("DOGMA_STITCH",),
            "strength":("FLOAT",{"default":1.0,"min":0.0,"max":1.0,"step":0.01}),
        }}
    RETURN_TYPES=("IMAGE",)
    RETURN_NAMES=("image",)
    INPUT_IS_LIST=True
    FUNCTION="stitch"
    CATEGORY="DOGMA/Semantic Detailer"

    def stitch(self,base_image,patches,masks,stitch,strength):
        if not base_image:
            raise ValueError("DOGMA Safe Masked Stitch v34 received no base image")
        result=base_image[0].clone()[...,:3].float()
        s=float(strength[0] if isinstance(strength,list) else strength)
        count=min(len(patches),len(masks),len(stitch))
        for i in range(count):
            meta=stitch[i]
            if meta is None or meta.get("noop",False):
                continue
            patch=patches[i]
            mask=masks[i]
            if patch.ndim==3: patch=patch.unsqueeze(0)
            if mask.ndim==2: mask=mask.unsqueeze(0)
            x=int(meta["x"]); y=int(meta["y"]); w=int(meta["width"]); h=int(meta["height"])
            p=F.interpolate(patch[...,:3].movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(mask.unsqueeze(1).float(),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            region=result[:,y:y+h,x:x+w,:]
            rh,rw=region.shape[1],region.shape[2]
            p=p[:,:rh,:rw,:]; m=m[:,:rh,:rw]
            region=region[:,:rh,:rw,:]

            # Align only a tiny DC color offset from the untouched crop context.
            context=(m<0.02).float().unsqueeze(-1)
            denom=context.sum(dim=(1,2),keepdim=True)
            if float(denom.max().item())>64.0:
                delta=((p-region)*context).sum(dim=(1,2),keepdim=True)/denom.clamp_min(1.0)
                delta=delta.clamp(-0.05,0.05)
                p=(p-delta).clamp(0,1)

            # Critical v34 rule: semantic core is 100% edited patch. Strength affects feather only.
            core=(m>=0.999).float()
            feather=(m-core).clamp(0,1)
            alpha=(core+feather*s).clamp(0,1).unsqueeze(-1)
            result[:,y:y+rh,x:x+rw,:]=p*alpha+region*(1.0-alpha)
        return (result.clamp(0,1),)


class DOGMAObjectSettingsV34(DOGMAObjectSettingsV27):
    """v27 object geometry, but drastically shorter Qwen requests and full-strength safe stitch."""
    FUNCTION="settings"
    def settings(self,category,restoration_brief):
        gap,context,maxsrc,target,maxcrops,_alpha,_old_req,_summary=super().settings(category,restoration_brief)
        c=str(category or "object").strip().lower()
        label=re.sub(r"[^A-Z0-9 ]","",c.upper()) or "OBJECTS"
        req=(
            f"Inspect only the existing {c} in this crop. Return ONE line, max 18 words, starting exactly 'FIX {label}:'. "
            "Name the visible geometry/anatomy/material defect to repair. If none, write 'none'. Preserve count and position. Never request text changes."
        )
        summary=(
            f"v34 {c}: v27 whole-object crop; Base 9B 20-step CFG4 denoise 0.35; short front-loaded prompt; "
            f"groups≤{maxcrops}; stitch core opaque."
        )
        return int(gap),int(context),int(maxsrc),int(target),int(maxcrops),1.0,req,summary


class DOGMALocalPromptV34:
    """Turn the crop VLM answer into a very short Klein prompt whose first words state the exact repair target."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "category":("STRING",{"forceInput":True}),
            "vlm_instruction":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","info")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    def compose(self,category,vlm_instruction):
        c=str(category or "objects").strip().lower()
        label=re.sub(r"[^A-Z0-9 ]","",c.upper()) or "OBJECTS"
        s=str(vlm_instruction or "").replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        # Hard-filter destructive/text-rewrite verbs.
        if re.search(r"\b(remove|delete|erase|replace|rewrite|rename|respell|invent|add new|create new)\b",s,re.I):
            s=""
        none = (not s) or bool(re.search(r"\bnone\b|no visible defect|no repair",s,re.I))
        if none:
            prompt=f"PRESERVE {label}. No visible target defect; keep the existing masked {c} unchanged. Keep all text/logos unchanged."
            return prompt,f"v34 local prompt for {c}: preserve/no-op"
        # Keep only the first concise clause from Qwen; Klein responds better to a short imperative.
        s=s.split("\n",1)[0].strip()
        if len(s)>150: s=s[:150].rsplit(" ",1)[0]
        # Remove an existing prefix so we can guarantee the exact first words.
        s=re.sub(rf"^FIX\s+{re.escape(label)}\s*:\s*","",s,flags=re.I).strip(" .:-")
        if not s:
            s="repair visible geometry and restore coherent photographic detail"
        prompt=(
            f"FIX {label}: {s}. "
            f"Reconstruct only the existing masked {c}; keep count, position, scale, direction/pose, color and occlusion. "
            "Keep all text/logos unchanged."
        )
        if len(prompt)>310: prompt=prompt[:310].rsplit(" ",1)[0]
        return prompt,f"v34 short local prompt for {c}: {len(prompt)} chars"


class DOGMALocalResultGateV34:
    """A crop that Qwen explicitly says to preserve cannot leak VAE/Klein changes into the stitch."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "edited":("IMAGE",),
            "original":("IMAGE",),
            "prompt":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="gate"
    CATEGORY="DOGMA/Semantic Detailer"

    def gate(self,edited,original,prompt):
        if str(prompt or "").strip().upper().startswith("PRESERVE "):
            return (original,"v34 local gate: exact original crop kept")
        return (edited,"v34 local gate: edited crop kept")




# =========================
# DOGMA v35 — COHERENT GLOBAL / SAFE LOCAL 0.35
# =========================

def _dogma_v35_coords(dac):
    W=int(dac['upscaled_width']); H=int(dac['upscaled_height'])
    tw=int(dac['tile_width']); th=int(dac['tile_height'])
    ox=int(dac['overlap_x']); oy=int(dac['overlap_y'])
    gx=int(dac['grid_x']); gy=int(dac['grid_y']); order=int(dac.get('tile_order',1))
    tiles=[]
    for row in range(gy):
        y=row*(th-oy)
        if row==gy-1: y=H-th
        for col in range(gx):
            x=col*(tw-ox)
            if col==gx-1: x=W-tw
            tiles.append((int(x),int(y)))
    if order==1 and len(tiles)>1:
        spiral=[]; visited=set(); x=gx//2; y=gy//2; dx,dy=1,0; layer=1
        while len(spiral)<len(tiles):
            for _ in range(2):
                for _ in range(layer):
                    if 0<=x<gx and 0<=y<gy and (x,y) not in visited:
                        idx=y*gx+x
                        if idx<len(tiles): spiral.append(tiles[idx]); visited.add((x,y))
                    x+=dx; y+=dy
                dx,dy=-dy,dx
            layer+=1
        spiral.reverse(); tiles=spiral
    return tiles


class DOGMAAlignedDacPrepareV35:
    """2x working canvas whose tile origins/strides are multiples of 16, so Flux2 latent grids line up across overlaps."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'image':('IMAGE',),
            'tile_size':('INT',{'default':1536,'min':512,'max':4096,'step':16}),
            'target_scale':('FLOAT',{'default':2.0,'min':1.0,'max':4.0,'step':0.05}),
            'overlap_fraction':('FLOAT',{'default':0.50,'min':0.10,'max':0.75,'step':0.01}),
            'alignment':('INT',{'default':16,'min':8,'max':64,'step':8}),
            'tile_order':(['spiral','linear'],{'default':'spiral'}),
        }}
    RETURN_TYPES=('IMAGE','DAC_DATA','STRING')
    RETURN_NAMES=('IMAGE','dac_data','ui')
    FUNCTION='prepare'
    CATEGORY='DOGMA/Semantic Detailer'

    @staticmethod
    def _axis(target,tile,desired_stride,align):
        if target<=tile:
            return tile,1,0
        grid=max(2,int(math.ceil((target-tile)/float(desired_stride)))+1)
        ideal=(target-tile)/float(grid-1)
        stride=max(align,int(round(ideal/align))*align)
        stride=min(tile-align,stride)
        work=tile+(grid-1)*stride
        overlap=tile-stride
        return int(work),int(grid),int(overlap)

    def prepare(self,image,tile_size,target_scale,overlap_fraction,alignment,tile_order):
        import comfy.utils
        B,H,W,C=image.shape
        tile=max(16,(int(tile_size)//16)*16)
        align=max(8,int(alignment)); align=max(16,(align//16)*16)
        target_w=max(16,int(round(W*float(target_scale)/16.0))*16)
        target_h=max(16,int(round(H*float(target_scale)/16.0))*16)
        desired=max(align,int(round(tile*(1.0-float(overlap_fraction))/align))*align)
        work_w,gx,ox=self._axis(target_w,tile,desired,align)
        work_h,gy,oy=self._axis(target_h,tile,desired,align)
        # Both working dimensions and every stride are latent-aligned by construction.
        samples=image[...,:3].movedim(-1,1)
        work=comfy.utils.common_upscale(samples,work_w,work_h,'lanczos','disabled').movedim(1,-1).clamp(0,1)
        dac={
            'upscaled_width':work_w,'upscaled_height':work_h,
            'tile_width':tile,'tile_height':tile,
            'overlap_x':ox,'overlap_y':oy,'grid_x':gx,'grid_y':gy,
            'tile_order':1 if str(tile_order)=='spiral' else 0,
        }
        sx=tile-ox; sy=tile-oy
        info=(f'v35 latent-aligned D&C | source {W}x{H} | target≈{target_w}x{target_h} | '
              f'working {work_w}x{work_h} | grid {gx}x{gy} | tile {tile} | '
              f'stride {sx}x{sy} (both /16) | overlap {ox}x{oy} | {tile_order}')
        return (work,dac,info)


class _DOGMAGlobalNoiseFieldV35:
    def __init__(self,seed,global_w,global_h):
        self.seed=int(seed); self.global_w=int(global_w); self.global_h=int(global_h); self.cache={}
    def tensor(self,channels):
        channels=int(channels)
        if channels not in self.cache:
            g=torch.Generator(device='cpu'); g.manual_seed(self.seed)
            self.cache[channels]=torch.randn((1,channels,self.global_h//16,self.global_w//16),generator=g,dtype=torch.float32,device='cpu')
        return self.cache[channels]


class _DOGMASpatialNoiseV35:
    def __init__(self,field,x,y):
        self.field=field; self.x=int(x); self.y=int(y); self.seed=field.seed
    def generate_noise(self,input_latent):
        latent=input_latent['samples']
        B,C,H,W=latent.shape
        x0=self.x//16; y0=self.y//16
        base=self.field.tensor(C)
        crop=base[:,:,y0:y0+H,x0:x0+W]
        if crop.shape[-2:]!=(H,W):
            # Defensive fallback; aligned v35 geometry should never need this.
            ph=max(0,H-crop.shape[-2]); pw=max(0,W-crop.shape[-1])
            crop=F.pad(crop,(0,pw,0,ph),mode='replicate')[:,:,:H,:W]
        if B>1: crop=crop.expand(B,-1,-1,-1)
        return crop.to(device=latent.device,dtype=latent.dtype,non_blocking=True).contiguous()


class DOGMAAlignedTileNoiseV35:
    """One global Flux2 noise field, cropped at each tile's global latent coordinate."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'dac_data':('DAC_DATA',),'seed':('INT',{'default':1976,'min':0,'max':0xffffffffffffffff})}}
    RETURN_TYPES=('NOISE','STRING')
    RETURN_NAMES=('noise','info')
    OUTPUT_IS_LIST=(True,False)
    FUNCTION='make'
    CATEGORY='DOGMA/Semantic Detailer'
    def make(self,dac_data,seed):
        field=_DOGMAGlobalNoiseFieldV35(seed,dac_data['upscaled_width'],dac_data['upscaled_height'])
        coords=_dogma_v35_coords(dac_data)
        noises=[_DOGMASpatialNoiseV35(field,x,y) for x,y in coords]
        info=(f'v35 global aligned noise seed={int(seed)} | {len(noises)} tiles | '
              f'global latent {dac_data["upscaled_width"]//16}x{dac_data["upscaled_height"]//16}')
        return (noises,info)


class DOGMACenterWeightedCombineV35:
    """Normalized center-weighted blend. Most of an overlap is decided by the tile whose center is closer, not a broad Gaussian average."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'images':('IMAGE',),'dac_data':('DAC_DATA',),
            'center_power':('FLOAT',{'default':3.0,'min':1.0,'max':8.0,'step':0.25}),
        }}
    RETURN_TYPES=('IMAGE','STRING')
    RETURN_NAMES=('image','info')
    INPUT_IS_LIST=True
    FUNCTION='combine'
    CATEGORY='DOGMA/Semantic Detailer'

    @staticmethod
    def _ramp(n,device,dtype):
        if n<=1: return torch.ones((max(1,n),),device=device,dtype=dtype)
        t=torch.linspace(0.0,1.0,n,device=device,dtype=dtype)
        return 0.5-0.5*torch.cos(math.pi*t)

    def combine(self,images,dac_data,center_power):
        if isinstance(dac_data,list): dac_data=dac_data[0]
        p=float(center_power[0] if isinstance(center_power,list) else center_power)
        if not images: raise ValueError('DOGMA v35 combine received no tiles')
        coords=_dogma_v35_coords(dac_data)
        W=int(dac_data['upscaled_width']); H=int(dac_data['upscaled_height'])
        ox=int(dac_data['overlap_x']); oy=int(dac_data['overlap_y'])
        first=images[0]; device=first.device; dtype=first.dtype
        canvas=torch.zeros((1,H,W,3),device=device,dtype=torch.float32)
        weights=torch.zeros((1,H,W,1),device=device,dtype=torch.float32)
        for i,(x,y) in enumerate(coords[:len(images)]):
            tile=images[i]
            if tile.ndim==3: tile=tile.unsqueeze(0)
            tile=tile[...,:3].to(device=device,dtype=torch.float32)
            th,tw=tile.shape[1],tile.shape[2]
            wx=torch.ones((tw,),device=device,dtype=torch.float32)
            wy=torch.ones((th,),device=device,dtype=torch.float32)
            if x>0 and ox>0:
                n=min(ox,tw); wx[:n]=self._ramp(n,device,torch.float32)
            if x+tw<W and ox>0:
                n=min(ox,tw); wx[-n:]=torch.flip(self._ramp(n,device,torch.float32),dims=[0])
            if y>0 and oy>0:
                n=min(oy,th); wy[:n]=self._ramp(n,device,torch.float32)
            if y+th<H and oy>0:
                n=min(oy,th); wy[-n:]=torch.flip(self._ramp(n,device,torch.float32),dims=[0])
            w=(wy[:,None]*wx[None,:]).clamp_min(1e-5).pow(p).unsqueeze(0).unsqueeze(-1)
            rh=min(th,H-y); rw=min(tw,W-x)
            canvas[:,y:y+rh,x:x+rw,:]+=tile[:,:rh,:rw,:]*w[:,:rh,:rw,:]
            weights[:,y:y+rh,x:x+rw,:]+=w[:,:rh,:rw,:]
        out=(canvas/weights.clamp_min(1e-6)).clamp(0,1).to(dtype=dtype)
        return (out,f'v35 center-weighted normalized combine | power={p:.2f} | tiles={min(len(images),len(coords))}')


class DOGMAObjectSettingsV35(DOGMAObjectSettingsV31):
    """v31 whole-object geometry + a deliberately tiny defect request for per-crop Qwen."""
    FUNCTION='settings'
    def settings(self,category,restoration_brief):
        gap,context,maxsrc,target,maxcrops,_alpha,_req,_summary=super().settings(category,restoration_brief)
        c=str(category or 'objects').strip().lower()
        label=re.sub(r'[^a-z0-9 ]','',c) or 'objects'
        req=(f'Inspect only the existing {label}. Output exactly: DEFECT: followed by at most 14 words naming the single clearest visible defect. '
             'If no clear defect, output DEFECT: none. Do not describe the scene. Do not add/remove objects or change text.')
        summary=(f'v35 {c}: v31 compact whole-object crops; Base9B 20-step CFG4 denoise0.35; '
                 f'Qwen defect-only ≤14 words; groups≤{maxcrops}; exact-core stitch.')
        return int(gap),int(context),int(maxsrc),int(target),int(maxcrops),1.0,req,summary


class DOGMAObjectClusterCropsV35(DOGMAObjectClusterCropsV31):
    pass


class DOGMALocalPromptV35:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'category':('STRING',{'forceInput':True}),'vlm_instruction':('STRING',{'forceInput':True,'multiline':True})}}
    RETURN_TYPES=('STRING','STRING')
    RETURN_NAMES=('prompt','info')
    FUNCTION='compose'
    CATEGORY='DOGMA/Semantic Detailer'
    def compose(self,category,vlm_instruction):
        c=str(category or 'objects').strip().lower(); label=re.sub(r'[^A-Z0-9 ]','',c.upper()) or 'OBJECTS'
        s=str(vlm_instruction or '').replace('```',''); s=re.sub(r'\s+',' ',s).strip()
        s=re.sub(r'^DEFECT\s*:\s*','',s,flags=re.I).strip(' .')
        if len(s)>120: s=s[:120].rsplit(' ',1)[0]
        bad=bool(re.search(r'\b(remove|delete|erase|add|create|invent|replace|rewrite|rename|respell)\b',s,re.I))
        none=(not s) or bad or bool(re.search(r'\bnone\b|no clear defect|no visible defect',s,re.I))
        if none:
            return (f'PRESERVE {label}.',f'v35 {c}: no clear defect -> exact crop preserve')
        prompt=(f'FIX {label}: {s}. Preserve exact count, position, identity, orientation, occlusion and true focus. '
                'Change only the masked target; keep text/logos unchanged.')
        return (prompt,f'v35 {c}: front-loaded prompt {len(prompt)} chars')


class DOGMAFastDualMaskV35:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'mask':('MASK',),'category':('STRING',{'forceInput':True}),'threshold':('FLOAT',{'default':0.50,'min':0.01,'max':0.99,'step':0.01})}}
    RETURN_TYPES=('MASK','MASK','STRING')
    RETURN_NAMES=('generation_mask','stitch_mask','info')
    FUNCTION='make'
    CATEGORY='DOGMA/Semantic Detailer'
    @staticmethod
    def _dilate(x,r):
        if r<=0: return x
        return F.max_pool2d(x.unsqueeze(1),kernel_size=2*r+1,stride=1,padding=r).squeeze(1)
    @staticmethod
    def _outward(core,r):
        if r<=0: return core
        x=core.unsqueeze(1); k=2*r+1
        blur=F.avg_pool2d(x,kernel_size=k,stride=1,padding=r)
        blur=F.avg_pool2d(blur,kernel_size=k,stride=1,padding=r)
        return torch.maximum(core,blur.squeeze(1).clamp(0,1))
    def make(self,mask,category,threshold):
        c=str(category or '').strip().lower()
        table={
            'vehicles':(24,3,8),'people':(28,3,8),'street furniture':(20,2,7),
            'architectural details':(16,2,6),'faces':(12,1,5),'hands':(12,1,5),
            'animals':(22,3,8),'furniture':(18,2,7),'machinery':(20,2,7),
            'clothing':(14,2,6),'products':(14,2,6),
        }
        gg,sg,sf=table.get(c,(20,2,7))
        with torch.no_grad():
            m=mask.float()
            if m.ndim==2: m=m.unsqueeze(0)
            if torch.cuda.is_available() and m.device.type!='cuda': m=m.cuda(non_blocking=True)
            core=(m>=float(threshold)).float()
            gen_core=self._dilate(core,gg).clamp(0,1)
            gen=self._outward(gen_core,2).clamp(0,1)
            stitch_core=self._dilate(core,sg).clamp(0,1)
            stitch=self._outward(stitch_core,sf).clamp(0,1)
        return (gen,stitch,f'v35 {c} masks | generation +{gg}/feather2 | stitch +{sg}/feather{sf} | opaque core')


class DOGMALocalResultGateV35:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'edited':('IMAGE',),'original':('IMAGE',),'prompt':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('IMAGE','STRING')
    RETURN_NAMES=('image','info')
    FUNCTION='gate'
    CATEGORY='DOGMA/Semantic Detailer'
    def gate(self,edited,original,prompt):
        if str(prompt or '').strip().upper().startswith('PRESERVE '):
            return (original,'v35 exact preserve: Klein result discarded')
        return (edited,'v35 repair active')


class DOGMAExactCoreStitchV35:
    """No color matching, no transparency in the semantic core, no generated pixels outside the outward feather."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'base_image':('IMAGE',),'patches':('IMAGE',),'masks':('MASK',),'stitch':('DOGMA_STITCH',),
            'strength':('FLOAT',{'default':1.0,'min':0.0,'max':1.0,'step':0.01}),
        }}
    RETURN_TYPES=('IMAGE',); RETURN_NAMES=('image',); INPUT_IS_LIST=True
    FUNCTION='stitch'; CATEGORY='DOGMA/Semantic Detailer'
    def stitch(self,base_image,patches,masks,stitch,strength):
        if not base_image: raise ValueError('DOGMA v35 stitch received no base image')
        result=base_image[0].clone()[...,:3].float()
        s=float(strength[0] if isinstance(strength,list) else strength)
        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if meta is None or meta.get('noop',False): continue
            patch=patches[i]; mask=masks[i]
            if patch.ndim==3: patch=patch.unsqueeze(0)
            if mask.ndim==2: mask=mask.unsqueeze(0)
            target_device=result.device
            patch=patch.to(target_device,non_blocking=(target_device.type=='cuda'))
            mask=mask.to(target_device,dtype=torch.float32,non_blocking=(target_device.type=='cuda'))
            x=int(meta['x']); y=int(meta['y']); w=int(meta['width']); h=int(meta['height'])
            p=F.interpolate(patch[...,:3].movedim(-1,1),size=(h,w),mode='bicubic',align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(mask.unsqueeze(1).float(),size=(h,w),mode='bilinear',align_corners=False).squeeze(1).clamp(0,1)
            region=result[:,y:y+h,x:x+w,:]; rh,rw=region.shape[1],region.shape[2]
            p=p[:,:rh,:rw,:]; m=m[:,:rh,:rw]; region=region[:,:rh,:rw,:]
            core=(m>=0.999).float(); feather=(m-core).clamp(0,1)
            alpha=(core+feather*s).clamp(0,1).unsqueeze(-1)
            result[:,y:y+rh,x:x+rw,:]=p*alpha+region*(1-alpha)
        return (result.clamp(0,1),)



# =========================
# DOGMA v35.1 — QUICK 2x2 TILE LAB + SHARED FULL-RUN CONTROLS
# =========================
class DOGMAGlobalTestControlsV351:
    @classmethod
    def INPUT_TYPES(cls):
        import comfy.samplers
        return {'required':{
            'sampler_name':(comfy.samplers.KSampler.SAMPLERS,{'default':'euler'}),
            'steps':('INT',{'default':4,'min':1,'max':50,'step':1}),
            'denoise':('FLOAT',{'default':1.0,'min':0.05,'max':1.0,'step':0.01}),
            'cfg':('FLOAT',{'default':1.0,'min':0.0,'max':10.0,'step':0.1}),
            'seed':('INT',{'default':1976,'min':0,'max':0xffffffffffffffff}),
            'center_power':('FLOAT',{'default':3.0,'min':1.0,'max':8.0,'step':0.25}),
        }}
    RETURN_TYPES=('SAMPLER','INT','FLOAT','FLOAT','INT','FLOAT','STRING')
    RETURN_NAMES=('sampler','steps','denoise','cfg','seed','center_power','info')
    FUNCTION='controls'; CATEGORY='DOGMA/Semantic Detailer'
    def controls(self,sampler_name,steps,denoise,cfg,seed,center_power):
        import comfy.samplers
        sampler=comfy.samplers.sampler_object(str(sampler_name))
        info=(f'GLOBAL TEST/FULL | sampler={sampler_name} | steps={int(steps)} | denoise={float(denoise):.2f} | '
              f'cfg={float(cfg):.2f} | seed={int(seed)} | center_power={float(center_power):.2f}')
        return (sampler,int(steps),float(denoise),float(cfg),int(seed),float(center_power),info)

class DOGMASelect2x2TestTilesV351:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'image':('IMAGE',),'dac_data':('DAC_DATA',),
            'block_x':('FLOAT',{'default':0.50,'min':0.0,'max':1.0,'step':0.05}),
            'block_y':('FLOAT',{'default':0.50,'min':0.0,'max':1.0,'step':0.05}),
        }}
    RETURN_TYPES=('IMAGE','DOGMA_TEST_DATA','IMAGE','STRING')
    RETURN_NAMES=('tiles','test_data','source_patch','info')
    OUTPUT_IS_LIST=(True,False,False,False)
    FUNCTION='select'; CATEGORY='DOGMA/Semantic Detailer'
    def select(self,image,dac_data,block_x,block_y):
        if isinstance(dac_data,list): dac_data=dac_data[0]
        B,H,W,C=image.shape
        tw=int(dac_data['tile_width']); th=int(dac_data['tile_height'])
        ox=int(dac_data['overlap_x']); oy=int(dac_data['overlap_y'])
        gx=int(dac_data['grid_x']); gy=int(dac_data['grid_y'])
        if gx<2 or gy<2: raise ValueError(f'2x2 test needs at least 2x2 grid, got {gx}x{gy}')
        sx=tw-ox; sy=th-oy
        c0=max(0,min(gx-2,int(round(float(block_x)*(gx-2)))))
        r0=max(0,min(gy-2,int(round(float(block_y)*(gy-2)))))
        coords=[]; tiles=[]
        for rr in (r0,r0+1):
            for cc in (c0,c0+1):
                x=cc*sx; y=rr*sy
                if cc==gx-1: x=W-tw
                if rr==gy-1: y=H-th
                x=int(x); y=int(y); coords.append((x,y)); tiles.append(image[:,y:y+th,x:x+tw,:])
        x0=min(x for x,y in coords); y0=min(y for x,y in coords)
        x1=max(x+tw for x,y in coords); y1=max(y+th for x,y in coords)
        patch=image[:,y0:y1,x0:x1,:]
        td={'coords':coords,'global_w':int(W),'global_h':int(H),'tile_width':tw,'tile_height':th,
            'overlap_x':ox,'overlap_y':oy,'patch_x':x0,'patch_y':y0,'patch_w':x1-x0,'patch_h':y1-y0,
            'grid_x':gx,'grid_y':gy,'block_col':c0,'block_row':r0}
        info=f'2x2 block row={r0}/{gy-2}, col={c0}/{gx-2} | coords={coords} | patch={x1-x0}x{y1-y0}'
        return (tiles,td,patch,info)

class DOGMAAlignedTestTileNoiseV351:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'test_data':('DOGMA_TEST_DATA',),'seed':('INT',{'default':1976,'min':0,'max':0xffffffffffffffff})}}
    RETURN_TYPES=('NOISE','STRING'); RETURN_NAMES=('noise','info')
    OUTPUT_IS_LIST=(True,False); FUNCTION='make'; CATEGORY='DOGMA/Semantic Detailer'
    def make(self,test_data,seed):
        if isinstance(test_data,list): test_data=test_data[0]
        field=_DOGMAGlobalNoiseFieldV35(seed,test_data['global_w'],test_data['global_h'])
        noises=[_DOGMASpatialNoiseV35(field,x,y) for x,y in test_data['coords']]
        return (noises,f'v35.1 aligned noise seed={int(seed)} / 4 tiles')

class DOGMACombine2x2TestTilesV351:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'images':('IMAGE',),'test_data':('DOGMA_TEST_DATA',),
                            'center_power':('FLOAT',{'default':3.0,'min':1.0,'max':8.0,'step':0.25})}}
    RETURN_TYPES=('IMAGE','STRING'); RETURN_NAMES=('image','info')
    INPUT_IS_LIST=True; FUNCTION='combine'; CATEGORY='DOGMA/Semantic Detailer'
    @staticmethod
    def _ramp(n,device):
        if n<=1: return torch.ones((max(1,n),),device=device,dtype=torch.float32)
        t=torch.linspace(0.0,1.0,n,device=device,dtype=torch.float32)
        return 0.5-0.5*torch.cos(math.pi*t)
    def combine(self,images,test_data,center_power):
        td=test_data[0] if isinstance(test_data,list) else test_data
        p=float(center_power[0] if isinstance(center_power,list) else center_power)
        if not images: raise ValueError('v35.1 test combine got no tiles')
        px=int(td['patch_x']); py=int(td['patch_y']); W=int(td['patch_w']); H=int(td['patch_h'])
        ox=int(td['overlap_x']); oy=int(td['overlap_y'])
        device=images[0].device; dtype=images[0].dtype
        canvas=torch.zeros((1,H,W,3),device=device,dtype=torch.float32)
        weights=torch.zeros((1,H,W,1),device=device,dtype=torch.float32)
        for i,(gx,gy) in enumerate(td['coords'][:len(images)]):
            tile=images[i]
            if tile.ndim==3: tile=tile.unsqueeze(0)
            tile=tile[...,:3].to(device=device,dtype=torch.float32)
            y=int(gy)-py; x=int(gx)-px; th,tw=tile.shape[1:3]
            wx=torch.ones((tw,),device=device,dtype=torch.float32)
            wy=torch.ones((th,),device=device,dtype=torch.float32)
            if x>0 and ox>0:
                n=min(ox,tw); wx[:n]=self._ramp(n,device)
            if x+tw<W and ox>0:
                n=min(ox,tw); wx[-n:]=torch.flip(self._ramp(n,device),dims=[0])
            if y>0 and oy>0:
                n=min(oy,th); wy[:n]=self._ramp(n,device)
            if y+th<H and oy>0:
                n=min(oy,th); wy[-n:]=torch.flip(self._ramp(n,device),dims=[0])
            w=(wy[:,None]*wx[None,:]).clamp_min(1e-5).pow(p).unsqueeze(0).unsqueeze(-1)
            canvas[:,y:y+th,x:x+tw,:]+=tile*w
            weights[:,y:y+th,x:x+tw,:]+=w
        out=(canvas/weights.clamp_min(1e-6)).clamp(0,1).to(dtype=dtype)
        return (out,f'2x2 combine power={p:.2f} / {W}x{H}')

class DOGMALatentByDenoiseV351:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'source_latent':('LATENT',),'empty_latent':('LATENT',),
                            'denoise':('FLOAT',{'default':1.0,'min':0.05,'max':1.0,'step':0.01})}}
    RETURN_TYPES=('LATENT','STRING'); RETURN_NAMES=('latent','info')
    FUNCTION='select'; CATEGORY='DOGMA/Semantic Detailer'
    def select(self,source_latent,empty_latent,denoise):
        d=float(denoise)
        if d>=0.999: return (empty_latent,'denoise 1.00: original v35 empty-latent full-noise')
        return (source_latent,f'denoise {d:.2f}: true source-latent img2img')




# =========================
# DOGMA v35.3 — ONE MASTER RUN-MODE SWITCH
# Front-end extension uses this single boolean to group-mute TEST vs FULL outputs.
# =========================
class DOGMARunModeMasterV353:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "full_run":("BOOLEAN",{"default":False,"label_on":"FULL RUN","label_off":"2x2 TEST"})
        }}
    RETURN_TYPES=("STRING",)
    RETURN_NAMES=("mode",)
    FUNCTION="mode"
    CATEGORY="DOGMA/Run Control"
    def mode(self,full_run):
        return ("FULL WORKFLOW" if bool(full_run) else "2x2 TILE TEST",)



# =========================
# DOGMA v35.4 — FOUR LOCAL SECTORS + DEVICE-SAFE MASKED INPAINT
# =========================
class DOGMASectorPlanV354(DOGMASectorPlanV27):
    """Same conservative v27 normalization/SAM prompts, but routes FOUR real sectors in slots 2..5."""
    FUNCTION="build"
    def build(self,planner_text):
        cats=[]; seen=set()
        for line in str(planner_text or "").replace("\r","\n").splitlines():
            c=self._norm(line)
            if c=="__none__" or c in seen:
                continue
            cats.append(c); seen.add(c)
            if len(cats)>=4:
                break
        while len(cats)<4:
            cats.append("__none__")
        slots=["__none__",cats[0],cats[1],cats[2],cats[3],"__none__"]
        preview=[]; out=[]
        for i,c in enumerate(slots,1):
            p,t=self._sam(c)
            preview.append(f"SLOT {i}: {c}\nSAM: {p}\nthreshold={t:.2f}")
            out.extend([c,p,float(t)])
        return ("\n\n".join(preview),*out)


class DOGMASectorMasks4V354:
    @classmethod
    def INPUT_TYPES(cls):
        req={}
        for i in range(1,5):
            req[f"mask_{i}"]=("MASK",)
            req[f"category_{i}"]=("STRING",{"forceInput":True})
        return {"required":req}
    RETURN_TYPES=("MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","mask_4","summary")
    FUNCTION="prepare"
    CATEGORY="DOGMA/Semantic Detailer"
    def prepare(self,mask_1,category_1,mask_2,category_2,mask_3,category_3,mask_4,category_4):
        raw=[mask_1,mask_2,mask_3,mask_4]
        cats=[str(category_1),str(category_2),str(category_3),str(category_4)]
        H=max(int(m.shape[-2]) for m in raw); W=max(int(m.shape[-1]) for m in raw)
        outs=[]; report=[]
        for i,(m,c) in enumerate(zip(raw,cats),1):
            if m.ndim==2: m=m.unsqueeze(0)
            m=m.float()
            if m.shape[0]>1: m=m.max(dim=0,keepdim=True).values
            if m.shape[-2:]!=(H,W):
                m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            if not c.strip() or c.strip().lower() in ("none","__none__","unused"):
                m=torch.zeros_like(m)
            m=m.clamp(0,1)
            cov=float((m>0.5).float().mean().item())*100.0
            outs.append(m)
            report.append(f"sector {i}: {c} | mask coverage {cov:.2f}%")
        return (*outs,"\n".join(report))


class DOGMAMaskMatchImageDeviceV354:
    """Hard runtime guard: InpaintModelConditioning receives mask on the exact same device as its crop pixels."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"mask":("MASK",)}}
    RETURN_TYPES=("MASK","STRING")
    RETURN_NAMES=("mask","info")
    FUNCTION="align"
    CATEGORY="DOGMA/Semantic Detailer"
    def align(self,image,mask):
        target=image.device
        out=mask.to(device=target,dtype=torch.float32,non_blocking=(target.type=="cuda"))
        return (out,f"mask device {mask.device} -> {target}")



# =========================
# DOGMA v36 — CLEAN SAFE GLOBAL + POSITIVE-STATE LOCAL
# =========================

class DOGMATilePromptComposerV36:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tile_report":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _terms(report,key):
        text=str(report or "").replace("\n"," ")
        m=re.search(rf"\b{key}\s*:\s*(.*?)(?=\b(?:SUPPORTED|PROTECT|AMBIGUOUS_OR_EMPTY)\s*:|$)",text,re.I)
        if not m: return []
        raw=re.split(r"[;,]",m.group(1))
        seen=set(); out=[]
        for x in raw:
            x=re.sub(r"\s+"," ",x).strip(" .:-").lower()
            if not x or x in seen: continue
            # Never condition Klein with text-bearing identity classes.
            if any(k in x for k in ("letter","text","logo","license plate","advert","billboard","signage")):
                continue
            seen.add(x); out.append(x)
        return out

    def compose(self,tile_report,project_context):
        supported=self._terms(tile_report,"SUPPORTED")[:12]
        protect=(self._terms(tile_report,"PROTECT")+self._terms(tile_report,"AMBIGUOUS_OR_EMPTY"))[:10]
        # Reflection/blur/haze/sky belong in protection, not restoration targets.
        move=[]
        for x in list(supported):
            if any(k in x for k in ("reflection","reflected","blur","haze","sky","shadow","fog","glare")):
                move.append(x); supported.remove(x)
        for x in move:
            if x not in protect: protect.append(x)
        if not protect:
            protect=["true blur","reflections","haze","sky","shadows","unreadable text","distant indistinct forms"]

        if supported:
            lead="RESTORE ONLY EXISTING " + "; ".join(supported[:10]).upper() + ". "
            body=("Use the source tile as exact geometric ground truth. Increase photographic detail only on those already-visible targets. "
                  "Keep exact object count, positions, silhouettes, perspective, occlusions, lighting and colour relationships. ")
        else:
            lead="PRESERVE THIS TILE. "
            body="No high-confidence restoration target is required. Keep source geometry and semantics unchanged. "

        prompt=(lead+body+
                "PROTECT "+ "; ".join(protect[:10]) + ". "
                "Never create a new object, never resolve an uncertain shape into a named object, and never rewrite text or logos. "
                "Preserve edge continuity with neighbouring tiles.")
        clean=("SUPPORTED: "+("; ".join(supported) if supported else "none")+
               "\nPROTECT: "+("; ".join(protect) if protect else "none"))
        return (prompt,clean)


class DOGMAEvidenceGateV36:
    """v25 source-evidence gate plus a veto for strong NEW edges/structures not supported by source pixels."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "generated":("IMAGE",),"source":("IMAGE",),
            "flat_generated_weight":("FLOAT",{"default":0.06,"min":0.0,"max":0.8,"step":0.01}),
            "low_threshold":("FLOAT",{"default":0.009,"min":0.0,"max":0.2,"step":0.001}),
            "high_threshold":("FLOAT",{"default":0.040,"min":0.001,"max":0.3,"step":0.001}),
            "proxy_long_side":("INT",{"default":384,"min":96,"max":768,"step":32}),
            "support_grow":("INT",{"default":4,"min":0,"max":16,"step":1}),
        }}
    RETURN_TYPES=("IMAGE","MASK","STRING")
    RETURN_NAMES=("image","evidence_weight","info")
    FUNCTION="gate"
    CATEGORY="DOGMA/Semantic Detailer"

    @staticmethod
    def _grad(lum):
        dx=F.pad((lum[:,:,:,1:]-lum[:,:,:,:-1]).abs(),(0,1,0,0))
        dy=F.pad((lum[:,:,1:,:]-lum[:,:,:-1,:]).abs(),(0,0,0,1))
        return torch.maximum(dx,dy)

    def gate(self,generated,source,flat_generated_weight,low_threshold,high_threshold,proxy_long_side,support_grow):
        with torch.no_grad():
            g=generated[...,:3].float()
            device=g.device
            s=source[...,:3].float().to(device)
            B,H,W,C=g.shape
            if s.shape[1:3]!=(H,W):
                s=F.interpolate(s.movedim(-1,1),size=(H,W),mode="bilinear",align_corners=False).movedim(1,-1)
            if s.shape[0]!=B:
                s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]

            target=max(96,int(proxy_long_side))
            scale=min(1.0,target/float(max(H,W)))
            ph=max(32,int(round(H*scale))); pw=max(32,int(round(W*scale)))
            sp=F.interpolate(s.movedim(-1,1),size=(ph,pw),mode="area")
            gp=F.interpolate(g.movedim(-1,1),size=(ph,pw),mode="area")
            sl=0.2126*sp[:,0:1]+0.7152*sp[:,1:2]+0.0722*sp[:,2:3]
            gl=0.2126*gp[:,0:1]+0.7152*gp[:,1:2]+0.0722*gp[:,2:3]

            sg=self._grad(sl)
            gg=self._grad(gl)
            mean=F.avg_pool2d(sl,7,1,3)
            dev=(sl-mean).abs()
            evidence=torch.maximum(sg,dev*1.5)

            lo=float(low_threshold); hi=max(lo+1e-6,float(high_threshold))
            support=((evidence-lo)/(hi-lo)).clamp(0,1)
            grow=max(0,int(support_grow))
            if grow:
                support=F.max_pool2d(support,2*grow+1,1,grow)
            support=F.avg_pool2d(support,5,1,2).clamp(0,1)

            # A generated edge much stronger than any source edge is suspicious,
            # especially in low-support regions (classic invented bus/person/tree).
            novelty=((gg - sg*2.2 - 0.012)/0.060).clamp(0,1)
            novelty=F.avg_pool2d(novelty,5,1,2).clamp(0,1)
            diff=(gp-sp).abs().mean(dim=1,keepdim=True)
            flat_change=((diff-0.035)/0.12).clamp(0,1)
            veto=torch.maximum(novelty,flat_change)*(1.0-support).pow(1.35)

            floor=float(flat_generated_weight)
            alpha=(floor+(1-floor)*support)*(1.0-0.97*veto)
            alpha=alpha.clamp(0,1)
            alpha=F.interpolate(alpha,size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            out=(s*(1-alpha.unsqueeze(-1))+g*alpha.unsqueeze(-1)).clamp(0,1)
            return (out,alpha,
                    f"v36 evidence+novelty gate | proxy={pw}x{ph} | generated mean={float(alpha.mean()):.3f} | veto mean={float(veto.mean()):.3f}")


class DOGMASectorPlanV36(DOGMASectorPlanV354):
    """Four present categories; stronger SAM recall for small vehicles/people."""
    @staticmethod
    def _sam(c):
        if c in ("","__none__","none"):
            return "nonexistent_placeholder_object_xyz:1",0.50
        if c=="vehicles":
            return "car:400,automobile:320,parked car:260,vehicle:220,bus:120,truck:140,van:140,motorcycle:80,bicycle:80",0.08
        if c=="people":
            return "person:320,pedestrian:280,human:220,standing person:160,walking person:160",0.10
        if c=="street furniture":
            return "street lamp:100,traffic light:100,pole:140,bollard:80,railing:100,bench:80,street furniture:120",0.12
        if c=="architectural details":
            return "window:260,door:160,balcony:180,facade detail:180,architectural detail:220",0.12
        if c=="faces":
            return "face:180,human face:180",0.13
        if c=="hands":
            return "hand:180,human hand:180",0.14
        if c=="animals":
            return "animal:160,dog:120,cat:120,horse:100,bird:80",0.12
        if c=="furniture":
            return "furniture:160,chair:140,table:120,sofa:100,couch:100,bed:100",0.13
        if c=="machinery":
            return "machine:160,machinery:160,equipment:140,tool:100,appliance:100",0.13
        if c=="clothing":
            return "clothing:180,jacket:120,shirt:100,dress:100,coat:120",0.14
        if c=="products":
            return "product:160,bottle:120,package:120,container:120",0.14
        return f"{c}:160",0.13


class DOGMAObjectSettingsV36(DOGMAObjectSettingsV31):
    FUNCTION="settings"
    def settings(self,category,restoration_brief):
        gap,context,maxsrc,target,maxcrops,_alpha,_req,_summary=super().settings(category,restoration_brief)
        c=str(category or "objects").strip().lower()
        label=re.sub(r"[^a-z0-9 ]","",c) or "objects"
        req=(
            f"Inspect only the existing {label} in this crop. Decide whether a clearly impossible restoration/AI geometry issue needs correction. "
            "If no correction is clearly needed, output exactly: STATE: preserve. "
            "If correction is needed, output exactly: STATE: followed by at most 16 words describing ONLY the correct positive FINAL appearance. "
            "Use positive geometry/material words such as intact, continuous, aligned, coherent, natural, correctly proportioned. "
            "NEVER use these words: damage, damaged, broken, malformed, fused, destroyed, wrong, missing, bent, tilted. "
            "Preserve count, identity, pose/orientation, supported real wear/dirt/paint and all text/logos."
        )
        summary=(f"v36 {c}: stronger SAM recall; whole-object crop; Qwen positive final-state only; "
                 f"Klein Distilled 4-step CFG1 denoise0.35; safety-gated edit; groups≤{maxcrops}.")
        return int(gap),int(context),int(maxsrc),int(target),int(maxcrops),1.0,req,summary


class DOGMALocalPromptV36:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"category":("STRING",{"forceInput":True}),
                            "vlm_instruction":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","info")
    FUNCTION="compose"
    CATEGORY="DOGMA/Semantic Detailer"

    def compose(self,category,vlm_instruction):
        c=str(category or "objects").strip().lower()
        label=re.sub(r"[^A-Z0-9 ]","",c.upper()) or "OBJECTS"
        s=str(vlm_instruction or "").replace("```","")
        s=re.sub(r"\s+"," ",s).strip()
        s=re.sub(r"^STATE\s*:\s*","",s,flags=re.I).strip(" .")
        forbidden=r"\b(damage|damaged|broken|malformed|fused|destroyed|wrong|missing|bent|tilted|remove|delete|erase|add|create|invent|replace|rewrite)\b"
        preserve=(not s) or bool(re.search(r"\bpreserve\b|\bnone\b|no correction",s,re.I))
        if re.search(forbidden,s,re.I):
            preserve=True
        if preserve:
            return (f"PRESERVE {label}.",f"v36 {c}: preserve / unsafe-negative wording rejected")
        if len(s)>150: s=s[:150].rsplit(" ",1)[0]
        prompt=(f"RESTORE EXISTING {label} TO THIS POSITIVE TARGET STATE: {s}. "
                "Keep exact count, identity, position, scale, orientation, occlusion and true focus. "
                "Preserve supported real wear, dirt, paint, text and logos. Change only the masked target.")
        return (prompt,f"v36 {c}: positive-state prompt {len(prompt)} chars")


class DOGMALocalSafetyGateV36:
    """Exact preserve for no-op; otherwise cap local edit strength according to actual pixel deviation."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"edited":("IMAGE",),"original":("IMAGE",),"prompt":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="gate"
    CATEGORY="DOGMA/Semantic Detailer"

    def gate(self,edited,original,prompt):
        p=str(prompt or "").strip().upper()
        if p.startswith("PRESERVE "):
            return (original,"v36 safety: exact original crop kept")
        e=edited[...,:3].float()
        o=original[...,:3].float().to(e.device)
        if o.shape[1:3]!=e.shape[1:3]:
            o=F.interpolate(o.movedim(-1,1),size=e.shape[1:3],mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
        if o.shape[0]!=e.shape[0]:
            o=o[:1].expand(e.shape[0],-1,-1,-1) if o.shape[0]==1 else o[:e.shape[0]]
        delta=(e-o).abs().mean(dim=(1,2,3))
        out=[]
        alphas=[]
        for i,d in enumerate(delta):
            dv=float(d.item())
            # Never allow a local crop to become a wholesale reinterpretation.
            a=min(0.72, 0.095/max(dv,1e-6))
            a=max(0.20,a)
            out.append((o[i:i+1]*(1-a)+e[i:i+1]*a).clamp(0,1))
            alphas.append(a)
        return (torch.cat(out,0),f"v36 safety: mean deltas={[round(float(x),4) for x in delta]} | edit alpha={[round(x,3) for x in alphas]}")



# =========================
# DOGMA v37 — FIXED CATEGORY REFINEMENT / NO LOCAL QWEN
# =========================
class DOGMAFixedCategoriesV37:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{}}
    RETURN_TYPES=("STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING")
    RETURN_NAMES=("category_1","sam_prompt_1","category_2","sam_prompt_2","category_3","sam_prompt_3","category_4","sam_prompt_4","category_5","sam_prompt_5","category_6","sam_prompt_6","summary")
    FUNCTION="plan"; CATEGORY="DOGMA/Semantic Detailer"
    def plan(self):
        vals=[
          ("vehicles","car:500,automobile:400,vehicle:350,parked car:300,bus:180,truck:180,van:180,motorcycle:100,bicycle:100"),
          ("people","person:420,pedestrian:380,human:320,standing person:220,walking person:220"),
          ("architecture","building:380,facade:380,window:340,door:220,balcony:260,architectural detail:280"),
          ("vegetation","grass:450,lawn:450,vegetation:380,tree:260,bush:240,shrub:240,foliage:240"),
          ("street_objects","street lamp:200,traffic light:200,pole:240,railing:200,bollard:160,bench:140,street furniture:220"),
          ("road_ground","road:480,street:450,asphalt:450,pavement:340,sidewalk:340,curb:260,ground:320"),
        ]
        out=[]
        for c,p in vals: out.extend([c,p])
        return (*out,"\n".join(f"{i+1}. {c}" for i,(c,_) in enumerate(vals)))

class DOGMASAMInputResizeV37:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"max_side":("INT",{"default":2560,"min":1024,"max":4096,"step":64})}}
    RETURN_TYPES=("IMAGE","STRING"); RETURN_NAMES=("image","info")
    FUNCTION="resize"; CATEGORY="DOGMA/Semantic Detailer"
    def resize(self,image,max_side):
        h,w=image.shape[1:3]; mx=max(h,w)
        if mx<=int(max_side): return (image,f"SAM source kept {w}x{h}")
        sc=float(max_side)/mx
        nh=max(16,int(round(h*sc/16))*16); nw=max(16,int(round(w*sc/16))*16)
        out=F.interpolate(image[...,:3].movedim(-1,1),size=(nh,nw),mode="bilinear",align_corners=False,antialias=True).movedim(1,-1)
        return (out,f"SAM source {w}x{h} -> {nw}x{nh}")

class DOGMAFixedCategoryPromptV37:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"family":(["vehicles","people","architecture","vegetation","street_objects","road_ground"],)}}
    RETURN_TYPES=("STRING","STRING"); RETURN_NAMES=("prompt","info")
    FUNCTION="compose"; CATEGORY="DOGMA/Semantic Detailer"
    def compose(self,family):
        P={
        "vehicles":"REFINE THE EXISTING VEHICLES ONLY. Preserve exact vehicle count, identity, position, direction, scale, silhouette, supported paint colour, wear, dirt and occlusion. Improve only coherent existing body panels, windows, lights, wheels and perspective. Do not redesign, modernize, add or remove vehicles. Preserve plate text.",
        "people":"REFINE THE EXISTING PEOPLE ONLY. Preserve exact person count, positions, poses, scale, direction, clothing colours and occlusions. Improve natural existing silhouettes, limbs, faces and clothing structure. Do not add, remove, reposition or beautify people.",
        "architecture":"REFINE THE EXISTING ARCHITECTURE ONLY. Preserve exact building identity, footprint, perspective, proportions, facade colours and lighting. Improve existing windows, doors, balconies, facade edges and repetitive structural detail without redesigning anything. Preserve all text and signs.",
        "vegetation":"REFINE THE EXISTING VEGETATION ONLY. Preserve exact footprint, density, height, type and lighting of grass, lawns, trees, bushes and foliage. Improve natural fine texture without creating new plants, shrubs, flowers or trees. A lawn must remain the same lawn.",
        "street_objects":"REFINE THE EXISTING STREET OBJECTS ONLY. Preserve exact count, position, function, silhouette, colour and orientation of lamps, traffic lights, poles, railings, bollards, benches and similar objects. Improve coherent geometry only. Do not add objects or rewrite text.",
        "road_ground":"REFINE THE EXISTING ROAD AND GROUND ONLY. Preserve exact road layout, lane geometry, sidewalks, curbs, markings, surface colour, lighting and wear. Improve continuity and photographic surface detail only. Do not create vehicles, people, objects or new markings."
        }
        return (P[family],f"v37 fixed prompt: {family}")

class DOGMACategoryGroupedCropsV37:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"mask":("MASK",),
            "family":(["vehicles","people","architecture","vegetation","street_objects","road_ground"],),
            "max_groups":("INT",{"default":8,"min":1,"max":16}),
            "context_px":("INT",{"default":160,"min":32,"max":512,"step":16}),
            "target_long_side":("INT",{"default":1792,"min":768,"max":3072,"step":64})}}
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="build"; CATEGORY="DOGMA/Semantic Detailer"
    def build(self,image,mask,family,max_groups,context_px,target_long_side):
        if mask.ndim==2: mask=mask.unsqueeze(0)
        if mask.shape[0]>1: mask=mask.max(dim=0,keepdim=True).values
        H,W=image.shape[1:3]
        m=mask.float().to(image.device)
        if m.shape[-2:]!=(H,W):
            m=F.interpolate(m.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
        # Slight grow so the full object, not only its center, gets edited.
        m=F.max_pool2d(m.unsqueeze(1),kernel_size=17,stride=1,padding=8).squeeze(1).clamp(0,1)
        # Coarse occupancy components: fast even on 8K.
        cell=128
        gh=(H+cell-1)//cell; gw=(W+cell-1)//cell
        occ=F.adaptive_max_pool2d(m.unsqueeze(1),(gh,gw))[0,0].detach().cpu()
        active=(occ>0.20)
        seen=torch.zeros_like(active,dtype=torch.bool)
        groups=[]
        for yy in range(gh):
            for xx in range(gw):
                if not bool(active[yy,xx]) or bool(seen[yy,xx]): continue
                stack=[(yy,xx)];seen[yy,xx]=True;cells=[]
                while stack:
                    y,x=stack.pop();cells.append((y,x))
                    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=y+dy,x+dx
                        if 0<=ny<gh and 0<=nx<gw and bool(active[ny,nx]) and not bool(seen[ny,nx]):
                            seen[ny,nx]=True;stack.append((ny,nx))
                ys=[q[0] for q in cells];xs=[q[1] for q in cells]
                groups.append([min(xs)*cell,min(ys)*cell,min(W,(max(xs)+1)*cell),min(H,(max(ys)+1)*cell),len(cells)])
        groups.sort(key=lambda q:q[4],reverse=True)
        # For giant broad surfaces, split bounding regions into model-sized chunks.
        expanded=[]
        target=int(target_long_side)
        ctx=int(context_px)
        for x1,y1,x2,y2,_ in groups:
            x1=max(0,x1-ctx);y1=max(0,y1-ctx);x2=min(W,x2+ctx);y2=min(H,y2+ctx)
            bw=x2-x1;bh=y2-y1
            if family in ("architecture","vegetation","road_ground") and max(bw,bh)>target*1.35:
                stride=int(target*0.80)
                for yy in range(y1,y2,max(256,stride)):
                    for xx in range(x1,x2,max(256,stride)):
                        ex=min(x2,xx+target);ey=min(y2,yy+target)
                        if float(m[:,yy:ey,xx:ex].mean().item())>0.01:
                            expanded.append([xx,yy,ex,ey,1])
            else: expanded.append([x1,y1,x2,y2,1])
        expanded=expanded[:int(max_groups)]
        if not expanded:
            return ([image[:,:64,:64,:]],[torch.zeros((1,64,64),device=image.device)],[{"x":0,"y":0,"width":64,"height":64,"empty":True}],f"{family}: no selected regions")
        crops=[];masks=[];meta=[]
        for x1,y1,x2,y2,_ in expanded:
            c=image[:,y1:y2,x1:x2,:]; cm=m[:,y1:y2,x1:x2]
            h,w=c.shape[1:3]
            if max(h,w)>target:
                sc=target/float(max(h,w));nh=max(64,int(round(h*sc/16))*16);nw=max(64,int(round(w*sc/16))*16)
                c=F.interpolate(c.movedim(-1,1),size=(nh,nw),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
                cm=F.interpolate(cm.unsqueeze(1),size=(nh,nw),mode="bilinear",align_corners=False).squeeze(1)
            crops.append(c);masks.append(cm.clamp(0,1));meta.append({"x":x1,"y":y1,"width":x2-x1,"height":y2-y1,"family":family})
        return (crops,masks,meta,f"{family}: {len(crops)} grouped/category crops")

class DOGMAConservativeBlendV37:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"edited":("IMAGE",),"original":("IMAGE",),"max_alpha":("FLOAT",{"default":0.55,"min":0.0,"max":1.0,"step":0.05})}}
    RETURN_TYPES=("IMAGE","STRING"); RETURN_NAMES=("image","info")
    INPUT_IS_LIST=True; OUTPUT_IS_LIST=(True,False)
    FUNCTION="blend"; CATEGORY="DOGMA/Semantic Detailer"
    def blend(self,edited,original,max_alpha):
        out=[];notes=[]
        for i,e in enumerate(edited):
            o=original[min(i,len(original)-1)]
            if e.ndim==3:e=e.unsqueeze(0)
            if o.ndim==3:o=o.unsqueeze(0)
            o=o.to(e.device)
            if o.shape[1:3]!=e.shape[1:3]:
                o=F.interpolate(o.movedim(-1,1),size=e.shape[1:3],mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
            delta=float((e[...,:3]-o[...,:3]).abs().mean().item())
            a=min(float(max_alpha),0.060/max(delta,1e-6)); a=max(0.18,a)
            out.append((o*(1-a)+e*a).clamp(0,1));notes.append(f"{i+1}:d={delta:.3f}/a={a:.2f}")
        return (out," | ".join(notes))

class DOGMAOpaqueMaskedStitchV37:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"base_image":("IMAGE",),"patches":("IMAGE",),"masks":("MASK",),"stitch":("DOGMA_STITCH",)}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info")
    INPUT_IS_LIST=True;FUNCTION="stitch";CATEGORY="DOGMA/Semantic Detailer"
    def stitch(self,base_image,patches,masks,stitch):
        result=(base_image[0] if isinstance(base_image,list) else base_image).clone()
        if result.ndim==3:result=result.unsqueeze(0)
        dev=result.device
        for i,meta in enumerate(stitch):
            if meta.get("empty"):continue
            p=patches[min(i,len(patches)-1)];m=masks[min(i,len(masks)-1)]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev);m=m.to(dev,dtype=torch.float32)
            x=int(meta["x"]);y=int(meta["y"]);w=int(meta["width"]);h=int(meta["height"])
            p=F.interpolate(p[...,:3].movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
            m=F.interpolate(m.unsqueeze(1),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            core=(m>0.58).float()
            feather=F.avg_pool2d(m.unsqueeze(1),17,1,8).squeeze(1).clamp(0,1)
            a=torch.maximum(core,feather*0.70).unsqueeze(-1)
            reg=result[:,y:y+h,x:x+w,:3]
            result[:,y:y+h,x:x+w,:3]=reg*(1-a)+p*a
        return (result,f"v37 stitched {len(stitch)} crops")



# =========================
# DOGMA v38 — QWEN SCENE INVENTORY ONLY
# =========================
class DOGMAInventoryResizeV38:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"max_side":("INT",{"default":1024,"min":512,"max":1536,"step":64})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info")
    FUNCTION="resize";CATEGORY="DOGMA/Semantic Detailer"
    def resize(self,image,max_side):
        h,w=image.shape[1:3];mx=max(h,w)
        if mx<=int(max_side): return (image,f"inventory view {w}x{h}")
        sc=float(max_side)/mx;nh=max(16,int(round(h*sc/16))*16);nw=max(16,int(round(w*sc/16))*16)
        out=F.interpolate(image[...,:3].movedim(-1,1),size=(nh,nw),mode="bilinear",align_corners=False,antialias=True).movedim(1,-1)
        return (out,f"inventory view {w}x{h}->{nw}x{nh}")

def _v38_parse_inventory(text):
    rows=[];seen=set()
    for raw in str(text or "").replace("```","").splitlines():
        raw=raw.strip()
        if not raw.upper().startswith("GROUP|"): continue
        parts=[p.strip() for p in raw.split("|")]
        if len(parts)<4: continue
        cat=re.sub(r"\s+"," ",parts[1]).strip().lower()
        sam=re.sub(r"\s+"," ",parts[2]).strip()
        kind=parts[3].strip().upper()
        if kind not in ("OBJECT","STRUCTURE","SURFACE"): kind="OBJECT"
        if not cat or cat in seen: continue
        if any(x in cat for x in ("text","logo","sign","license","brand","advert")): continue
        if re.search(r"\b(broken|damage|damaged|malformed|wrong|missing|blur|blurry)\b",cat,re.I): continue
        if not sam: sam=cat
        seen.add(cat);rows.append((cat,sam,kind))
        if len(rows)>=6: break
    while len(rows)<6:
        rows.append(("none","nonexistent_placeholder_object_xyz:1","OBJECT"))
    return rows[:6]

class DOGMASceneInventoryPlanV38:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING","STRING")
    RETURN_NAMES=("category_1","sam_prompt_1","category_2","sam_prompt_2","category_3","sam_prompt_3","category_4","sam_prompt_4","category_5","sam_prompt_5","category_6","sam_prompt_6","summary")
    FUNCTION="parse";CATEGORY="DOGMA/Semantic Detailer"
    def parse(self,inventory_text):
        rows=_v38_parse_inventory(inventory_text);out=[]
        for c,s,k in rows: out.extend([c,s])
        summary="\n".join(f"{i+1}. {c} [{k}] — SAM: {s}" for i,(c,s,k) in enumerate(rows))
        return (*out,summary)

class DOGMASceneInventoryKindsV38:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING","STRING","STRING","STRING","STRING")
    RETURN_NAMES=("kind_1","kind_2","kind_3","kind_4","kind_5","kind_6")
    FUNCTION="parse";CATEGORY="DOGMA/Semantic Detailer"
    def parse(self,inventory_text):
        return tuple(k for c,s,k in _v38_parse_inventory(inventory_text))

class DOGMAAdaptiveCategoryPromptV38:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("STRING","STRING");RETURN_NAMES=("prompt","info")
    FUNCTION="compose";CATEGORY="DOGMA/Semantic Detailer"
    def compose(self,category,kind):
        c=str(category or "none").strip()
        k=str(kind or "OBJECT").strip().upper()
        if c.lower()=="none":
            return ("PRESERVE IMAGE.","inactive inventory slot")
        if k=="SURFACE":
            p=(f"REFINE ONLY THE EXISTING {c.upper()} SURFACE. Preserve its exact footprint, boundaries, colour, lighting, wear, "
               "density and large-scale structure. Improve fine photographic texture only where already supported. "
               "Do not create new objects, markings, plants, structures or semantic content.")
        elif k=="STRUCTURE":
            p=(f"REFINE ONLY THE EXISTING {c.upper()}. Preserve exact identity, count, placement, proportions, perspective, colour, "
               "lighting and occlusion. Improve existing structural edges and repetitive detail without redesigning anything. "
               "Preserve all text, logos and signs.")
        else:
            p=(f"REFINE ONLY THE EXISTING {c.upper()}. Preserve exact count, identity, position, scale, orientation, silhouette, colour, "
               "pose and occlusion. Improve coherent existing detail only. Do not add, remove, replace, redesign or modernize anything. "
               "Preserve text and logos.")
        return (p,f"adaptive {k.lower()} prompt: {c}")

class DOGMAAdaptiveGroupedCropsV38(DOGMACategoryGroupedCropsV37):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"mask":("MASK",),
            "category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),
            "max_groups":("INT",{"default":8,"min":1,"max":16}),
            "context_px":("INT",{"default":160,"min":32,"max":512,"step":16}),
            "target_long_side":("INT",{"default":1792,"min":768,"max":3072,"step":64})}}
    FUNCTION="build"
    def build(self,image,mask,category,kind,max_groups,context_px,target_long_side):
        cat=str(category or "none").lower()
        if cat=="none":
            z=torch.zeros((1,image.shape[1],image.shape[2]),device=image.device)
            return super().build(image,z,"road_ground",1,32,768)
        k=str(kind or "OBJECT").upper()
        family="road_ground" if k=="SURFACE" else ("architecture" if k=="STRUCTURE" else "vehicles")
        return super().build(image,mask,family,max_groups,context_px,target_long_side)



class DOGMATilePromptComposerV381(DOGMATilePromptComposerV36):
    @staticmethod
    def _canonical(items):
        out=[]; seen=set()
        aliases={'car':'cars','automobile':'cars','vehicle':'cars','vehicles':'cars','cars':'cars','pedestrian':'people','person':'people','people':'people','building':'buildings','facade':'buildings','buildings':'buildings','window':'windows','windows':'windows','road':'road surface','street':'road surface','asphalt':'road surface','pavement':'road surface','grass':'grass','lawn':'grass','vegetation':'vegetation','traffic light':'traffic lights','streetlight':'street lights','street light':'street lights','sidewalk':'sidewalk','crosswalk':'crosswalk','balcony':'balconies','roof':'roofs'}
        banned={'traffic','traffic jam','city','urban scene','scene','metal','glass'}
        for x in items:
            x=re.sub(r'\s+',' ',str(x).strip().lower())
            if not x or x in banned: continue
            x=aliases.get(x,x)
            if x not in seen: seen.add(x); out.append(x)
        return out
    def compose(self,tile_report,project_context):
        supported=self._canonical(self._terms(tile_report,'SUPPORTED'))[:9]
        protect=self._canonical(self._terms(tile_report,'PROTECT')+self._terms(tile_report,'AMBIGUOUS_OR_EMPTY'))[:8]
        context=re.sub(r'\s+',' ',str(project_context or '')).strip()
        if context:
            parts=re.split(r'(?<=[.!?])\s+',context); context=' '.join(parts[:2])[:520].strip()
        else: context='Preserve the exact era, location and technology visible in the source; never modernize.'
        lead=(f'{context} REFINE ONLY ALREADY-VISIBLE '+('; '.join(supported).upper())+'. ') if supported else f'{context} PRESERVE THIS TILE. '
        prompt=(lead+'The source pixels are the ONLY authority for object existence. Preserve exact object count, positions, silhouettes, perspective, occlusions and large-scale geometry. '
                'Do NOT add another instance of any listed class. Do NOT turn blur, reflections, shadows, road texture or ambiguous shapes into vehicles, people, buildings or street objects. '
                'Improve only supported fine photographic detail inside already-visible forms. '+(('PROTECT '+'; '.join(protect)+'. ') if protect else '')+
                'Never rewrite text, logos or license plates. Preserve edge continuity with neighbouring tiles.')
        clean='SUPPORTED: '+('; '.join(supported) if supported else 'none')+'\nPROTECT: '+('; '.join(protect) if protect else 'none')
        return (prompt,clean)

class DOGMAEvidenceGateV381(DOGMAEvidenceGateV36):
    FUNCTION='gate'
    def gate(self,generated,source,flat_generated_weight,low_threshold,high_threshold,proxy_long_side,support_grow):
        with torch.no_grad():
            g=generated[...,:3].float(); s=source[...,:3].float().to(g.device); B,H,W,C=g.shape
            if s.shape[1:3]!=(H,W): s=F.interpolate(s.movedim(-1,1),size=(H,W),mode='bilinear',align_corners=False).movedim(1,-1)
            if s.shape[0]!=B: s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]
            target=max(128,int(proxy_long_side)); scale=min(1.0,target/float(max(H,W))); ph=max(48,int(round(H*scale))); pw=max(48,int(round(W*scale)))
            sp=F.interpolate(s.movedim(-1,1),size=(ph,pw),mode='area'); gp=F.interpolate(g.movedim(-1,1),size=(ph,pw),mode='area')
            sl=0.2126*sp[:,0:1]+0.7152*sp[:,1:2]+0.0722*sp[:,2:3]; gl=0.2126*gp[:,0:1]+0.7152*gp[:,1:2]+0.0722*gp[:,2:3]
            sg=self._grad(sl); gg=self._grad(gl); mean=F.avg_pool2d(sl,7,1,3); dev=(sl-mean).abs(); evidence=torch.maximum(sg,dev*1.5)
            lo=float(low_threshold); hi=max(lo+1e-6,float(high_threshold)); support=((evidence-lo)/(hi-lo)).clamp(0,1)
            grow=max(0,int(support_grow))
            if grow: support=F.max_pool2d(support,2*grow+1,1,grow)
            support=F.avg_pool2d(support,5,1,2).clamp(0,1)
            novelty=((gg-sg*2.0-0.010)/0.050).clamp(0,1); novelty=F.avg_pool2d(novelty,5,1,2).clamp(0,1)
            k=15; slow=F.avg_pool2d(sp,k,1,k//2); glow=F.avg_pool2d(gp,k,1,k//2)
            lowdiff=(glow-slow).abs().mean(dim=1,keepdim=True); structure=((lowdiff-0.022)/0.070).clamp(0,1); structure=F.avg_pool2d(structure,7,1,3).clamp(0,1)
            diff=(gp-sp).abs().mean(dim=1,keepdim=True); broad=((diff-0.035)/0.11).clamp(0,1); veto=torch.maximum(torch.maximum(novelty,broad*0.75),structure)
            floor=float(flat_generated_weight); alpha=floor+(1-floor)*support; alpha=alpha*(1.0-0.96*veto*(1.0-0.55*support)); hard=(structure>0.72)&(support<0.58)
            alpha=torch.where(hard,torch.zeros_like(alpha),alpha).clamp(0,1); alpha=F.interpolate(alpha,size=(H,W),mode='bilinear',align_corners=False).squeeze(1)
            out=(s*(1-alpha.unsqueeze(-1))+g*alpha.unsqueeze(-1)).clamp(0,1)
            return (out,alpha,f'v39 ghost-veto | proxy={pw}x{ph} | gen={float(alpha.mean()):.3f} | structure={float(structure.mean()):.3f}')

class DOGMAConservativeBlendV381(DOGMAConservativeBlendV37):
    FUNCTION='blend'
    def blend(self,edited,original,max_alpha):
        ma=max_alpha[0] if isinstance(max_alpha,(list,tuple)) else max_alpha; ma=float(ma)
        if not isinstance(edited,list): edited=[edited]
        if not isinstance(original,list): original=[original]
        out=[]; notes=[]
        for i,e in enumerate(edited):
            o=original[min(i,len(original)-1)]
            if e.ndim==3:e=e.unsqueeze(0)
            if o.ndim==3:o=o.unsqueeze(0)
            o=o.to(e.device)
            if o.shape[1:3]!=e.shape[1:3]: o=F.interpolate(o.movedim(-1,1),size=e.shape[1:3],mode='bicubic',align_corners=False,antialias=True).movedim(1,-1)
            delta=float((e[...,:3]-o[...,:3]).abs().mean().item()); em=float(e[...,:3].abs().mean().item()); om=float(o[...,:3].abs().mean().item())
            if (em<0.01 and om>0.03) or delta>0.24: a=0.0
            else: a=max(0.16,min(ma,0.060/max(delta,1e-6)))
            out.append((o*(1-a)+e*a).clamp(0,1)); notes.append(f'{i+1}:d={delta:.3f}/a={a:.2f}')
        return (out,' | '.join(notes))

class DOGMAAdaptiveGroupedCropsV381(DOGMAAdaptiveGroupedCropsV38):
    FUNCTION='build'
    def build(self,image,mask,category,kind,max_groups,context_px,target_long_side):
        crops,masks,stitch,info=super().build(image,mask,category,kind,max_groups,context_px,target_long_side)
        if 'no selected regions' in str(info).lower() or str(category).lower()=='none':
            h=max(64,(min(512,image.shape[1])//16)*16); w=max(64,(min(512,image.shape[2])//16)*16); crop=image[:,:h,:w,:]; z=torch.zeros((1,h,w),device=image.device,dtype=torch.float32)
            return ([crop],[z],[{'x':0,'y':0,'width':w,'height':h,'empty':True,'category':str(category)}],f'{category}: no selected regions — SAFE NO-OP')
        return (crops,masks,stitch,info)



# =========================
# DOGMA v39 — CLEAN REBUILD
# =========================
class DOGMAGlobalControlsV39:
    @classmethod
    def INPUT_TYPES(cls):
        import comfy.samplers
        return {"required":{
            "sampler_name":(comfy.samplers.KSampler.SAMPLERS,{"default":"euler"}),
            "steps":("INT",{"default":4,"min":1,"max":20,"step":1}),
            "denoise":("FLOAT",{"default":1.0,"min":0.10,"max":1.0,"step":0.05}),
            "cfg":("FLOAT",{"default":1.0,"min":0.0,"max":5.0,"step":0.1}),
            "mid_strength":("FLOAT",{"default":0.28,"min":0.0,"max":1.0,"step":0.02}),
            "detail_strength":("FLOAT",{"default":0.82,"min":0.0,"max":1.2,"step":0.02}),
        }}
    RETURN_TYPES=("SAMPLER","INT","FLOAT","FLOAT","FLOAT","FLOAT","STRING")
    RETURN_NAMES=("sampler","steps","denoise","cfg","mid_strength","detail_strength","info")
    FUNCTION="controls";CATEGORY="DOGMA/v39"
    def controls(self,sampler_name,steps,denoise,cfg,mid_strength,detail_strength):
        import comfy.samplers
        return (comfy.samplers.sampler_object(str(sampler_name)),int(steps),float(denoise),float(cfg),float(mid_strength),float(detail_strength),
                f"v39 global: {sampler_name} / {steps} step / denoise {denoise:.2f} / CFG {cfg:.1f} / detail {mid_strength:.2f}+{detail_strength:.2f}")

class DOGMATilePromptComposerV39:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"tile_report":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING");RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose";CATEGORY="DOGMA/v39"
    @staticmethod
    def _clean(s):
        s=re.sub(r"```(?:json|text|markdown)?","",str(s or ""),flags=re.I).replace("```","")
        return re.sub(r"\s+"," ",s).strip()[:900]
    def compose(self,tile_report,project_context):
        r=self._clean(tile_report); c=self._clean(project_context)
        if not r: r="VISIBLE: no reliable inventory. UNCERTAIN: preserve all ambiguity."
        p=(
            "RESTORE ONLY THE EXISTING CONTENT IN THIS EXACT TILE. PROJECT CONTEXT / PERIOD LOCK: "+c+"\n"
            "The source tile is geometric ground truth. The project context constrains the appearance of objects that already exist; it is NEVER permission to add an object. "
            "Preserve exact object count, positions, silhouettes, perspective, occlusions, lighting, exposure, haze and composition. Never modernize an existing object. "
            "Never convert blur, reflection, shadow, foliage texture, asphalt texture, haze or an indistinct shape into a new vehicle, person, building or other subject. "
            "Preserve visible text/logo glyph structure and never rewrite it.\n"
            "TILE INVENTORY: "+r+"\n"
            "Improve photographic micro-detail only on content already supported by the source. Uncertain regions must remain uncertain."
        )
        return (p,r)

class DOGMAGlobalTileDetailInjectV39:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"generated":("IMAGE",),"source":("IMAGE",),
            "mid_strength":("FLOAT",{"default":0.28,"min":0,"max":1,"step":0.02}),
            "detail_strength":("FLOAT",{"default":0.82,"min":0,"max":1.2,"step":0.02}),
            "drift_start":("FLOAT",{"default":0.035,"min":0,"max":0.3,"step":0.005}),
            "drift_end":("FLOAT",{"default":0.105,"min":0.01,"max":0.5,"step":0.005}),
            "support_floor":("FLOAT",{"default":0.24,"min":0,"max":1,"step":0.02})}}
    RETURN_TYPES=("IMAGE","MASK","STRING");RETURN_NAMES=("image","detail_weight","info")
    FUNCTION="inject";CATEGORY="DOGMA/v39"
    @staticmethod
    def _lp(x,div):
        h,w=x.shape[-2:];hh=max(8,round(h/div));ww=max(8,round(w/div))
        return F.interpolate(F.interpolate(x,size=(hh,ww),mode="area"),size=(h,w),mode="bilinear",align_corners=False)
    def inject(self,generated,source,mid_strength,detail_strength,drift_start,drift_end,support_floor):
        g=generated[...,:3].float();s=source[...,:3].float().to(g.device)
        if s.shape[1:3]!=g.shape[1:3]:s=F.interpolate(s.movedim(-1,1),size=g.shape[1:3],mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
        if s.shape[0]!=g.shape[0]:s=s[:1].expand(g.shape[0],-1,-1,-1)
        b=s.movedim(-1,1);p=g.movedim(-1,1)
        bl=self._lp(b,16);pl=self._lp(p,16);bs=self._lp(b,4);ps=self._lp(p,4)
        bmid=bs-bl;pmid=ps-pl;bhi=b-bs;phi=p-ps
        # large semantic drift = do not import generated structure.
        drift=(pl-bl).abs().mean(1,keepdim=True)
        ds=float(drift_start);de=max(ds+1e-5,float(drift_end));guard=(1-((drift-ds)/(de-ds)).clamp(0,1))
        # Source structure map. A floor allows genuine deblurring while flat areas stay conservative.
        lum=(0.2126*b[:,0:1]+0.7152*b[:,1:2]+0.0722*b[:,2:3])
        dx=F.pad((lum[:,:,:,1:]-lum[:,:,:,:-1]).abs(),(0,1,0,0));dy=F.pad((lum[:,:,1:,:]-lum[:,:,:-1,:]).abs(),(0,0,0,1))
        dev=(lum-F.avg_pool2d(lum,7,1,3)).abs();support=torch.maximum(torch.maximum(dx,dy),dev*1.4)
        support=(support/0.045).clamp(0,1);support=F.avg_pool2d(support,7,1,3)
        sf=float(support_floor);weight=(guard*(sf+(1-sf)*support)).clamp(0,1)
        mid=float(mid_strength);hi=float(detail_strength)
        cand=bl + bmid + (pmid-bmid)*(weight*mid) + bhi + (phi-bhi)*(weight*hi)
        out=cand.clamp(0,1).movedim(1,-1)
        return (out,weight.squeeze(1),f"v39 detail donor | mean weight={float(weight.mean()):.3f} | drift={float(drift.mean()):.4f}")

class DOGMASceneInventoryPlanV39:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(4) for x in ("STRING","STRING","STRING","FLOAT"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,5) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}"))
    FUNCTION="parse";CATEGORY="DOGMA/v39"
    def parse(self,inventory_text):
        rows=[];seen=set()
        for raw in str(inventory_text or "").replace("```","").splitlines():
            if not raw.strip().upper().startswith("GROUP|"):continue
            p=[x.strip() for x in raw.split("|")]
            if len(p)<4:continue
            c=re.sub(r"\s+"," ",p[1]).strip().lower();sam=p[2].strip();k=p[3].strip().upper()
            if not c or c in seen or any(z in c for z in ("text","logo","sign","brand","license plate")):continue
            if k not in ("OBJECT","STRUCTURE","SURFACE"):k="OBJECT"
            if not sam:sam=c
            thr=0.10 if k=="OBJECT" else (0.12 if k=="STRUCTURE" else 0.10)
            rows.append((c,sam,k,thr));seen.add(c)
            if len(rows)>=4:break
        while len(rows)<4:rows.append(("none","nonexistent_placeholder_object_xyz:1","OBJECT",0.50))
        out=[];prev=[]
        for i,(c,s,k,t) in enumerate(rows,1):out.extend([c,s,k,float(t)]);prev.append(f"GROUP {i}: {c} [{k}] | SAM={s} | threshold={t:.2f}")
        return ("\n".join(prev),*out)

class DOGMAMaskPreviewV39:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"mask":("MASK",)}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");FUNCTION="show";CATEGORY="DOGMA/v39"
    def show(self,mask):
        m=mask.float()
        if m.ndim==2:
            m=m.unsqueeze(0)
        # SAM is allowed to return an empty mask batch [0,H,W].
        # Preview must never crash on a valid "nothing found" result.
        if m.numel()==0 or (m.ndim>=1 and int(m.shape[0])==0):
            h=int(m.shape[-2]) if m.ndim>=2 and int(m.shape[-2])>0 else 256
            w=int(m.shape[-1]) if m.ndim>=1 and int(m.shape[-1])>0 else 256
            img=torch.zeros((1,h,w,3),dtype=torch.float32,device=m.device)
            return (img,f"empty mask batch=0 | coverage=0.00% | {w}x{h}")
        union=m.max(0,keepdim=True).values.clamp(0,1)
        img=union.unsqueeze(-1).repeat(1,1,1,3)
        return (img,f"mask batch={m.shape[0]} | union coverage={float((union>0.5).float().mean())*100:.2f}%")

class DOGMAAdaptiveSettingsV39:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("INT","INT","INT","FLOAT","FLOAT","FLOAT","FLOAT","STRING")
    RETURN_NAMES=("max_groups","context_px","target_long_side","mid_strength","detail_strength","drift_start","drift_end","info")
    FUNCTION="settings";CATEGORY="DOGMA/v39"
    def settings(self,category,kind):
        k=str(kind or "OBJECT").upper();c=str(category or "none")
        if c=="none":vals=(1,64,768,0.0,0.0,0.03,0.09)
        elif k=="SURFACE":vals=(6,160,2048,0.12,0.62,0.025,0.085)
        elif k=="STRUCTURE":vals=(6,208,2048,0.22,0.78,0.030,0.095)
        else:vals=(8,176,2048,0.28,0.88,0.035,0.105)
        return (*vals,f"{c} [{k}] | groups≤{vals[0]} | target≤{vals[2]} | mid/high={vals[3]:.2f}/{vals[4]:.2f}")

class DOGMAAdaptiveCropsV39:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"reference_image":("IMAGE",),"masks":("MASK",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),"max_groups":("INT",{"default":8,"min":1,"max":16}),"context_px":("INT",{"default":176,"min":0,"max":640}),"target_long_side":("INT",{"default":2048,"min":768,"max":3072})}}
    RETURN_TYPES=("IMAGE","IMAGE","MASK","DOGMA_STITCH","STRING");RETURN_NAMES=("crops","reference_crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,True,False);FUNCTION="make";CATEGORY="DOGMA/v39"
    @staticmethod
    def _resize_img(x,h,w):return F.interpolate(x.movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
    @staticmethod
    def _resize_mask(x,h,w):
        if x.ndim==2:x=x.unsqueeze(0)
        return F.interpolate(x.unsqueeze(1).float(),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
    def _noop(self,src,ref,cat):
        H,W=src.shape[1:3];side=min(768,H,W);x=max(0,(W-side)//2);y=max(0,(H-side)//2)
        c=src[:,y:y+side,x:x+side,:];r=ref[:,y:y+side,x:x+side,:];m=torch.zeros((1,side,side),dtype=torch.float32,device=c.device)
        return ([c],[r],[m],[{"x":x,"y":y,"width":side,"height":side,"noop":True}],f"{cat}: no valid mask — safe no-op")
    def make(self,image,reference_image,masks,category,kind,max_groups,context_px,target_long_side):
        src=image[:1,...,:3].float();ref=reference_image[:1,...,:3].float().to(src.device);H,W=src.shape[1:3]
        if ref.shape[1:3]!=(H,W):ref=self._resize_img(ref,H,W)
        cat=str(category or "none").strip().lower();k=str(kind or "OBJECT").upper()
        if cat=="none":return self._noop(src,ref,cat)
        if masks.ndim==2:masks=masks.unsqueeze(0)
        ms=masks.detach().float().cpu()
        # Empty SAM output [0,H,W] is a normal result for a category that is not found.
        # Do not reduce an empty tensor and do not send a fake generated crop downstream.
        if ms.numel()==0 or int(ms.shape[0])==0:
            return self._noop(src,ref,cat)
        if ms.ndim!=3:
            return self._noop(src,ref,cat)
        N,MH,MW=ms.shape
        # OBJECT: reuse proven v27 whole-object cropper.
        if k=="OBJECT":
            return DOGMAObjectClusterCropsV27().make_crops(src,ref,ms,cat,96,int(context_px),4096,int(target_long_side),int(max_groups),0.35)
        # STRUCTURE/SURFACE: union SAM, build a few broad macro crops, then inject detail only.
        union=ms.max(0,keepdim=True).values
        if float((union>0.35).float().mean())<0.0002:return self._noop(src,ref,cat)
        full=self._resize_mask(union,H,W).to(src.device)
        # Coarse occupied cells, connected components.
        cell=256;gh=max(1,math.ceil(H/cell));gw=max(1,math.ceil(W/cell));occ=F.adaptive_max_pool2d(full.unsqueeze(1),(gh,gw))[0,0].cpu()>0.25
        seen=torch.zeros_like(occ,dtype=torch.bool);boxes=[]
        for yy in range(gh):
            for xx in range(gw):
                if not bool(occ[yy,xx]) or bool(seen[yy,xx]):continue
                stack=[(yy,xx)];seen[yy,xx]=True;pts=[]
                while stack:
                    y,x=stack.pop();pts.append((y,x))
                    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=y+dy,x+dx
                        if 0<=ny<gh and 0<=nx<gw and bool(occ[ny,nx]) and not bool(seen[ny,nx]):seen[ny,nx]=True;stack.append((ny,nx))
                ys=[p[0] for p in pts];xs=[p[1] for p in pts];boxes.append((min(xs)*cell,min(ys)*cell,min(W,(max(xs)+1)*cell),min(H,(max(ys)+1)*cell),len(pts)))
        boxes.sort(key=lambda b:b[4],reverse=True)
        crops=[];refs=[];cms=[];meta=[];target=int(target_long_side);ctx=int(context_px)
        for bx in boxes:
            x1,y1,x2,y2,_=bx;x1=max(0,x1-ctx);y1=max(0,y1-ctx);x2=min(W,x2+ctx);y2=min(H,y2+ctx)
            # split only giant broad regions, with overlap, because the final compositor is detail-only.
            stride=max(512,int(target*0.75));wins=[]
            if max(x2-x1,y2-y1)>target*1.25:
                for yy in range(y1,y2,stride):
                    for xx in range(x1,x2,stride):wins.append((xx,yy,min(x2,xx+target),min(y2,yy+target)))
            else:wins=[(x1,y1,x2,y2)]
            for xx1,yy1,xx2,yy2 in wins:
                if len(crops)>=int(max_groups):break
                fm=full[:,yy1:yy2,xx1:xx2]
                if float(fm.mean())<0.005:continue
                c=src[:,yy1:yy2,xx1:xx2,:];r=ref[:,yy1:yy2,xx1:xx2,:];h,w=c.shape[1:3]
                if max(h,w)>target:
                    sc=target/float(max(h,w));nh=max(64,int(h*sc)//16*16);nw=max(64,int(w*sc)//16*16);c=self._resize_img(c,nh,nw);r=self._resize_img(r,nh,nw);fm=self._resize_mask(fm,nh,nw)
                crops.append(c);refs.append(r);cms.append(fm.clamp(0,1));meta.append({"x":xx1,"y":yy1,"width":xx2-xx1,"height":yy2-yy1,"noop":False})
            if len(crops)>=int(max_groups):break
        if not crops:return self._noop(src,ref,cat)
        return (crops,refs,cms,meta,f"{cat} [{k}]: {len(crops)} macro crop(s), detail-injection only")

class DOGMAAdaptivePromptV39:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING");RETURN_NAMES=("prompt","info");FUNCTION="compose";CATEGORY="DOGMA/v39"
    def compose(self,category,kind,project_context):
        c=str(category or "objects").strip();k=str(kind or "OBJECT").upper();ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()[:700]
        if c.lower()=="none":return ("PRESERVE IMAGE.","inactive group")
        if k=="SURFACE":body=f"REFINE ONLY THE EXISTING {c.upper()} SURFACE. Preserve exact footprint, boundaries, colour, lighting, density, wear and large-scale structure. Improve natural photographic texture only."
        elif k=="STRUCTURE":body=f"REFINE ONLY THE EXISTING {c.upper()}. Preserve exact identity, placement, proportions, perspective, materials, colour and lighting. Improve existing structural edges/repetition only; never redesign."
        else:body=f"REFINE ONLY THE EXISTING {c.upper()}. Preserve exact count, identity, position, scale, orientation, silhouette, colour, pose and occlusion. Improve coherent existing detail only."
        p=body+" PROJECT/PERIOD LOCK: "+ctx+" Do not add, remove, replace or modernize anything. Preserve all text/logo glyph structure."
        return (p,f"v39 {k.lower()} detail donor prompt: {c}")

class DOGMADetailBandStitchV39:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"base_image":("IMAGE",),"patches":("IMAGE",),"masks":("MASK",),"stitch":("DOGMA_STITCH",),"mid_strength":("FLOAT",{"default":0.28,"min":0,"max":1}),"detail_strength":("FLOAT",{"default":0.88,"min":0,"max":1.2}),"drift_start":("FLOAT",{"default":0.035,"min":0,"max":0.3}),"drift_end":("FLOAT",{"default":0.105,"min":0.01,"max":0.5})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");INPUT_IS_LIST=True;FUNCTION="stitch";CATEGORY="DOGMA/v39"
    @staticmethod
    def _lp(x,div):
        h,w=x.shape[-2:];hh=max(8,round(h/div));ww=max(8,round(w/div));return F.interpolate(F.interpolate(x,size=(hh,ww),mode="area"),size=(h,w),mode="bilinear",align_corners=False)
    def stitch(self,base_image,patches,masks,stitch,mid_strength,detail_strength,drift_start,drift_end):
        result=base_image[0].clone()[...,:3];dev=result.device
        mid=float(mid_strength[0] if isinstance(mid_strength,list) else mid_strength);hi=float(detail_strength[0] if isinstance(detail_strength,list) else detail_strength)
        ds=float(drift_start[0] if isinstance(drift_start,list) else drift_start);de=max(ds+1e-5,float(drift_end[0] if isinstance(drift_end,list) else drift_end))
        used=0
        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if not meta or meta.get("noop",False):continue
            p=patches[i];m=masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev);m=m.to(dev,dtype=torch.float32)
            x=int(meta['x']);y=int(meta['y']);w=int(meta['width']);h=int(meta['height']);b=result[:,y:y+h,x:x+w,:].movedim(-1,1).float()
            if b.shape[-2]<=0 or b.shape[-1]<=0:continue
            p=F.interpolate(p[...,:3].movedim(-1,1),size=b.shape[-2:],mode="bicubic",align_corners=False,antialias=True).clamp(0,1)
            m=F.interpolate(m.unsqueeze(1),size=b.shape[-2:],mode="bilinear",align_corners=False).clamp(0,1)
            bl=self._lp(b,16);pl=self._lp(p,16);bs=self._lp(b,4);ps=self._lp(p,4);bmid=bs-bl;pmid=ps-pl;bhi=b-bs;phi=p-ps
            drift=(pl-bl).abs().mean(1,keepdim=True);guard=(1-((drift-ds)/(de-ds)).clamp(0,1));guard=0.05+0.95*guard
            candidate=bl+(bmid*(1-mid)+pmid*mid)+(bhi*(1-hi)+phi*hi)
            alpha=(m*guard).clamp(0,1);merged=(candidate*alpha+b*(1-alpha)).clamp(0,1)
            result[:,y:y+h,x:x+w,:]=merged.movedim(1,-1);used+=1
        return (result,f"v39 multiband: {used} crop(s) injected; master low-frequency geometry retained")




# =========================
# DOGMA v39.2 — AUDITED CONTROLS
# =========================
class DOGMAControlsV392:
    @classmethod
    def INPUT_TYPES(cls):
        import comfy.samplers
        return {"required":{
            "sampler_name":(comfy.samplers.KSampler.SAMPLERS,{"default":"euler"}),
            "steps":("INT",{"default":4,"min":1,"max":20,"step":1}),
            "denoise":("FLOAT",{"default":1.0,"min":0.10,"max":1.0,"step":0.05}),
            "cfg":("FLOAT",{"default":1.0,"min":0.0,"max":5.0,"step":0.1}),
            "local_denoise":("FLOAT",{"default":0.25,"min":0.10,"max":0.50,"step":0.05}),
        }}
    RETURN_TYPES=("SAMPLER","INT","FLOAT","FLOAT","FLOAT","STRING")
    RETURN_NAMES=("sampler","steps","denoise","cfg","local_denoise","info")
    FUNCTION="controls"
    CATEGORY="DOGMA/v39"
    def controls(self,sampler_name,steps,denoise,cfg,local_denoise):
        import comfy.samplers
        sampler=comfy.samplers.sampler_object(str(sampler_name))
        return (
            sampler,int(steps),float(denoise),float(cfg),float(local_denoise),
            f"GLOBAL {sampler_name}/{int(steps)} step/denoise {float(denoise):.2f}/CFG {float(cfg):.1f} | "
            f"LOCAL denoise {float(local_denoise):.2f}"
        )



# =========================
# DOGMA v40 — TRUE LOCAL REFINEMENT
# =========================
def _v40_clean_category(text):
    s=re.sub(r"[^a-z0-9 /_-]+"," ",str(text or "").lower())
    return re.sub(r"\s+"," ",s).strip()
def _v40_canonical(cat):
    c=_v40_clean_category(cat)
    if re.search(r"\b(bus|buses|coach|coaches)\b",c): return "bus"
    if re.search(r"\b(truck|trucks|lorry|lorries)\b",c): return "trucks"
    if re.search(r"\b(car|cars|automobile|automobiles|vehicle|vehicles|sedan|sedans)\b",c): return "cars"
    if re.search(r"\b(person|people|pedestrian|pedestrians|human|humans|crowd)\b",c): return "people"
    if re.search(r"\b(building|buildings|architecture|facade|facades)\b",c): return "buildings"
    if re.search(r"\b(grass|lawn|lawns|vegetation|greenery)\b",c): return "grass"
    if re.search(r"\b(tree|trees|foliage|bush|bushes|shrub|shrubs)\b",c): return "trees"
    if re.search(r"\b(sky|cloud|clouds)\b",c): return "sky"
    if re.search(r"\b(road|roads|street|streets|asphalt|pavement|ground|sidewalk)\b",c): return "road"
    if re.search(r"\b(water|sea|ocean|lake|river)\b",c): return "water"
    if re.search(r"\b(mountain|mountains|hill|hills)\b",c): return "mountains"
    if re.search(r"\b(dog|dogs|cat|cats|animal|animals)\b",c): return "animals"
    if re.search(r"\b(furniture|chair|chairs|table|tables|sofa|couch)\b",c): return "furniture"
    return c[:48] if c else "none"
def _v40_family(cat):
    c=_v40_canonical(cat)
    if c in ("cars","bus","trucks"):return "vehicle"
    if c=="people":return "human"
    if c=="buildings":return "structure"
    if c in ("grass","trees"):return "vegetation"
    if c in ("sky","road","water","mountains"):return "surface"
    return c
def _v40_sam_prompt(cat,raw):
    c=_v40_canonical(cat)
    base={"cars":"car, automobile, sedan, hatchback, station wagon","bus":"bus, city bus, coach","trucks":"truck, lorry, van",
          "people":"person, pedestrian, human","buildings":"building, facade, window, balcony","grass":"grass, lawn, vegetation",
          "trees":"tree, bush, shrub, foliage","sky":"sky","road":"road, asphalt, street, pavement","water":"water",
          "mountains":"mountain, hill","animals":"animal, dog, cat","furniture":"furniture, chair, table, sofa"}
    return base.get(c,re.sub(r"\s+"," ",str(raw or c)).strip()[:180] or c)

class DOGMASceneInventoryPlanV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}"))
    FUNCTION="parse";CATEGORY="DOGMA/v40"
    def parse(self,inventory_text):
        rows=[];seen=set();famcnt={}
        for raw in str(inventory_text or "").replace("```","").splitlines():
            if not raw.strip().upper().startswith("GROUP|"):continue
            p=[x.strip() for x in raw.split("|")]
            if len(p)<4:continue
            c=_v40_canonical(p[1]);sam=p[2].strip();k=p[3].strip().upper()
            if c in ("","none") or any(z in c for z in ("text","logo","sign","brand","license")):continue
            if k not in ("OBJECT","STRUCTURE","SURFACE"):k="OBJECT"
            if c in seen:continue
            fam=_v40_family(c);cap=2 if fam=="vehicle" else 1
            if famcnt.get(fam,0)>=cap:continue
            seen.add(c);famcnt[fam]=famcnt.get(fam,0)+1
            if c=="buildings":k="STRUCTURE"
            elif c in ("sky","road","water","mountains","grass"):k="SURFACE"
            else:k="OBJECT"
            thr=0.055 if c in ("cars","bus","trucks","people") else (0.075 if k=="STRUCTURE" else 0.060)
            rows.append((c,_v40_sam_prompt(c,sam),k,thr))
            if len(rows)>=6:break
        while len(rows)<6:rows.append(("none","nonexistent_placeholder_object_xyz:1","OBJECT",0.50))
        out=[];prev=[]
        for i,(c,s,k,t) in enumerate(rows,1):
            out.extend([c,s,k,float(t)]);prev.append(f"GROUP {i}: {c} [{k}] | SAM: {s} | threshold={t:.3f}")
        return ("\n".join(prev),*out)

class DOGMAMaskVisualV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"image":("IMAGE",),"masks":("MASK",)}}
    RETURN_TYPES=("IMAGE","IMAGE","STRING");RETURN_NAMES=("overlay","mask_image","info")
    FUNCTION="show";CATEGORY="DOGMA/v40"
    def show(self,image,masks):
        src=image[:1,...,:3].float();H,W=src.shape[1:3];m=masks.float()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:union=torch.zeros((1,H,W),device=src.device);count=0
        else:
            union=m.max(0,keepdim=True).values.to(src.device)
            if union.shape[-2:]!=(H,W):union=F.interpolate(union.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
            union=union.clamp(0,1);count=int(m.shape[0])
        hard=(union>0.35).float();overlay=(src*(0.22+0.78*hard.unsqueeze(-1))).clamp(0,1);bw=union.unsqueeze(-1).repeat(1,1,1,3)
        return (overlay,bw,f"SAM masks={count} | union coverage={float(hard.mean())*100:.3f}% | bright area = selected")

class DOGMAAdaptiveCropsV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"image":("IMAGE",),"masks":("MASK",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING");RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False);FUNCTION="make";CATEGORY="DOGMA/v40"
    @staticmethod
    def _ri(x,h,w):return F.interpolate(x.movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
    @staticmethod
    def _rm(x,h,w):
        if x.ndim==2:x=x.unsqueeze(0)
        return F.interpolate(x.unsqueeze(1).float(),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
    @staticmethod
    def _iou(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b;ix1=max(ax1,bx1);iy1=max(ay1,by1);ix2=min(ax2,bx2);iy2=min(ay2,by2)
        inter=max(0,ix2-ix1)*max(0,iy2-iy1)
        if inter<=0:return 0.0
        aa=max(1,(ax2-ax1)*(ay2-ay1));bb=max(1,(bx2-bx1)*(by2-by1));return inter/float(aa+bb-inter)
    @staticmethod
    def _gap(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b;dx=max(0,max(ax1,bx1)-min(ax2,bx2));dy=max(0,max(ay1,by1)-min(ay2,by2))
        return math.sqrt(dx*dx+dy*dy)
    def _noop(self,src,cat):
        H,W=src.shape[1:3];side=min(256,H,W);x=max(0,(W-side)//2);y=max(0,(H-side)//2);c=src[:,y:y+side,x:x+side,:]
        z=torch.zeros((1,side,side),dtype=torch.float32,device=c.device)
        return ([c],[z],[{"x":x,"y":y,"width":side,"height":side,"noop":True}],f"{cat}: no valid segmentation — safe no-op")
    def _components(self,mask,threshold=0.30):
        hard=(mask>threshold).float();H,W=hard.shape
        if int(hard.sum())<6:return []
        step=max(1,int(math.ceil(max(H,W)/640.0)))
        sh=(F.max_pool2d(hard[None,None],step,step)[0,0]>0) if step>1 else (hard>0)
        hh,ww=sh.shape;seen=torch.zeros_like(sh,dtype=torch.bool);boxes=[]
        for yy in range(hh):
            for xx in range(ww):
                if not bool(sh[yy,xx]) or bool(seen[yy,xx]):continue
                stack=[(yy,xx)];seen[yy,xx]=True;pts=[]
                while stack:
                    y,x=stack.pop();pts.append((y,x))
                    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=y+dy,x+dx
                        if 0<=ny<hh and 0<=nx<ww and bool(sh[ny,nx]) and not bool(seen[ny,nx]):seen[ny,nx]=True;stack.append((ny,nx))
                if len(pts)<2:continue
                ys=[q[0] for q in pts];xs=[q[1] for q in pts];x1=max(0,min(xs)*step);y1=max(0,min(ys)*step);x2=min(W,(max(xs)+1)*step);y2=min(H,(max(ys)+1)*step)
                cnt=int(hard[y1:y2,x1:x2].sum())
                if cnt>=6:boxes.append((x1,y1,x2,y2,cnt))
        return boxes
    def make(self,image,masks,category,kind):
        src=image[:1,...,:3].float();H,W=src.shape[1:3];cat=_v40_canonical(category);k=str(kind or "OBJECT").upper()
        if cat=="none":return self._noop(src,cat)
        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return self._noop(src,cat)
        N,MH,MW=m.shape;sx=W/float(MW);sy=H/float(MH)
        if k in ("STRUCTURE","SURFACE"):
            union=m.max(0,keepdim=True).values
            if float((union>0.30).float().mean())<0.0001:return self._noop(src,cat)
            full=self._rm(union,H,W).to(src.device);target=1792;max_groups=6 if k=="STRUCTURE" else 5;hard=full[0]>0.25;ys,xs=torch.where(hard)
            if xs.numel()==0:return self._noop(src,cat)
            x1=max(0,int(xs.min())-128);y1=max(0,int(ys.min())-128);x2=min(W,int(xs.max())+129);y2=min(H,int(ys.max())+129);stride=int(target*0.78);wins=[]
            if max(x2-x1,y2-y1)>target*1.15:
                for yy in range(y1,y2,max(512,stride)):
                    for xx in range(x1,x2,max(512,stride)):
                        ex=min(x2,xx+target);ey=min(y2,yy+target)
                        if float(full[:,yy:ey,xx:ex].mean())>0.01:wins.append((xx,yy,ex,ey))
            else:wins=[(x1,y1,x2,y2)]
            crops=[];cms=[];meta=[]
            for xx1,yy1,xx2,yy2 in wins[:max_groups]:
                c=src[:,yy1:yy2,xx1:xx2,:];cm=full[:,yy1:yy2,xx1:xx2];h,w=c.shape[1:3]
                if max(h,w)>target:
                    sc=target/float(max(h,w));nh=max(64,int(h*sc)//16*16);nw=max(64,int(w*sc)//16*16);c=self._ri(c,nh,nw);cm=self._rm(cm,nh,nw)
                crops.append(c);cms.append(cm.clamp(0,1));meta.append({"x":xx1,"y":yy1,"width":xx2-xx1,"height":yy2-yy1,"noop":False})
            return (crops,cms,meta,f"{cat} [{k}]: {len(crops)} macro crop(s)") if crops else self._noop(src,cat)
        det=[]
        for mi in range(N):
            for x1s,y1s,x2s,y2s,count in self._components(m[mi],0.30):
                frac=count/float(max(1,MH*MW))
                if frac>0.45:continue
                box=(max(0,int(x1s*sx)),max(0,int(y1s*sy)),min(W,int(math.ceil(x2s*sx))),min(H,int(math.ceil(y2s*sy))))
                if box[2]-box[0]>=4 and box[3]-box[1]>=4:det.append({"mask_idx":mi,"sam_box":(x1s,y1s,x2s,y2s),"bbox":box,"area":count*sx*sy})
        if not det:return self._noop(src,cat)
        det.sort(key=lambda q:q["area"],reverse=True);uniq=[]
        for q in det:
            if not any(self._iou(q["bbox"],u["bbox"])>=0.68 for u in uniq):uniq.append(q)
        det=uniq
        if cat in ("cars","bus","trucks"):max_obj,max_groups,gap,ctx,target=4,10,120,128,1536
        elif cat=="people":max_obj,max_groups,gap,ctx,target=4,8,100,112,1536
        else:max_obj,max_groups,gap,ctx,target=3,8,110,128,1536
        rem=list(range(len(det)));groups=[]
        while rem:
            seed=rem.pop(0);members=[seed];ub=det[seed]["bbox"]
            while len(members)<max_obj and rem:
                best=None
                for ri,j in enumerate(rem):
                    g=self._gap(ub,det[j]["bbox"])
                    if g<=gap and (best is None or g<best[0]):best=(g,ri,j)
                if best is None:break
                _,ri,j=best;rem.pop(ri);members.append(j);b=det[j]["bbox"];ub=(min(ub[0],b[0]),min(ub[1],b[1]),max(ub[2],b[2]),max(ub[3],b[3]))
            groups.append((members,ub))
        groups.sort(key=lambda gb:sum(det[i]["area"] for i in gb[0]),reverse=True);groups=groups[:max_groups];groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))
        crops=[];cms=[];meta=[]
        for members,ub in groups:
            x1,y1,x2,y2=ub;cx1=max(0,x1-ctx);cy1=max(0,y1-ctx);cx2=min(W,x2+ctx);cy2=min(H,y2+ctx);c=src[:,cy1:cy2,cx1:cx2,:];ch,cw=c.shape[1:3];local=torch.zeros((1,ch,cw))
            for di in members:
                q=det[di];mi=q["mask_idx"];lx1=max(0,int(math.floor(cx1/W*MW)));ly1=max(0,int(math.floor(cy1/H*MH)));lx2=min(MW,int(math.ceil(cx2/W*MW)));ly2=min(MH,int(math.ceil(cy2/H*MH)));sub=m[mi,ly1:ly2,lx1:lx2].clone()
                if sub.numel()==0:continue
                bx1,by1,bx2,by2=q["sam_box"];yy=torch.arange(ly1,ly2)[:,None];xx=torch.arange(lx1,lx2)[None,:];sub=sub*((xx>=bx1)&(xx<bx2)&(yy>=by1)&(yy<by2)).float()
                sub=F.interpolate(sub[None,None],size=(ch,cw),mode="bilinear",align_corners=False)[0,0];local=torch.maximum(local,sub[None])
            if max(ch,cw)>target:
                sc=target/float(max(ch,cw));nh=max(64,int(ch*sc)//16*16);nw=max(64,int(cw*sc)//16*16);c=self._ri(c,nh,nw);local=self._rm(local,nh,nw)
            crops.append(c);cms.append(local.clamp(0,1));meta.append({"x":cx1,"y":cy1,"width":cx2-cx1,"height":cy2-cy1,"noop":False,"members":len(members)})
        return (crops,cms,meta,f"{cat} [OBJECT]: {len(det)} individual component(s) → {len(crops)} crop group(s), max {max_obj} objects/crop")

class DOGMALocalPromptV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING");RETURN_NAMES=("prompt","info");FUNCTION="compose";CATEGORY="DOGMA/v40"
    def compose(self,category,kind,project_context):
        c=_v40_canonical(category);k=str(kind or "OBJECT").upper()
        if c=="none":return ("PRESERVE IMAGE.","inactive group")
        ctx=re.sub(r"\s+"," ",str(project_context or "")).strip();shortctx=ctx.split(".")[0].strip()[:180]
        P={
        "cars":"1970s ITALIAN CARS. Refine the existing cars into clean, coherent period-correct Italian vehicles. Improve body panels, windows, lights, wheels and fine photographic detail. Keep their count, positions, colours and basic shapes. Do not add or remove cars.",
        "bus":"1970s ITALIAN CITY BUS. Refine the existing bus with coherent period-correct bodywork, windows, lights, wheels and fine photographic detail. Keep its position, scale, colour and silhouette. Do not add another bus.",
        "trucks":"1970s ITALIAN TRUCKS AND VANS. Refine the existing commercial vehicles with coherent period-correct bodywork, windows, wheels and fine detail. Keep count, position, colour and silhouette.",
        "people":"1970s MILAN PEDESTRIANS. Refine the existing people with natural anatomy, faces, limbs and period-correct everyday clothing. Keep the same people, positions, poses and scale.",
        "buildings":"1970s MILAN URBAN BUILDINGS. Refine the existing facades, windows, balconies, railings and architectural detail. Preserve the exact building geometry and identity; improve clarity and coherent repetition.",
        "grass":"URBAN GRASS AND LAWN. Improve the existing grass into natural fine photographic lawn texture with coherent density and lighting. Keep the exact lawn footprint; do not add plants or objects.",
        "trees":"URBAN TREES AND VEGETATION. Improve the existing foliage, branches and bushes with natural photographic texture. Keep the same vegetation footprint, scale and lighting.",
        "sky":"NATURAL HAZY URBAN SKY. Refine the existing sky into a smooth photographic atmospheric gradient with natural haze and filmic tonal detail. Do not add clouds or objects that are not already visible.",
        "road":"1970s MILAN ASPHALT AND STREET SURFACES. Refine the existing road texture, curbs and visible markings with coherent photographic detail. Keep the exact road geometry and markings.",
        "water":"NATURAL WATER SURFACE. Refine the existing water texture, reflections and tonal detail while preserving its exact boundary and lighting."}
        if c in P:p=P[c]
        elif k=="SURFACE":p=f"{c.upper()} SURFACE. Improve the existing surface with coherent natural photographic micro-detail while preserving its footprint, colour and lighting."
        elif k=="STRUCTURE":p=f"{shortctx}. REFINE THE EXISTING {c.upper()}. Improve coherent structural detail, edges and repetition while preserving the existing geometry and identity."
        else:p=f"{shortctx}. REFINE THE EXISTING {c.upper()}. Improve coherent photographic shape and detail while keeping count, position, scale and colour."
        return (p,f"v40 short prompt: {c} [{k}]")

class DOGMAMaskedLatentV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"latent":("LATENT",),"mask":("MASK",)}}
    RETURN_TYPES=("LATENT","STRING");RETURN_NAMES=("latent","info");FUNCTION="apply";CATEGORY="DOGMA/v40"
    def apply(self,latent,mask):
        out=latent.copy();m=mask
        if m.ndim==2:m=m.unsqueeze(0)
        m=m.float().clamp(0,1)
        # V53: expand slightly, then feather the actual diffusion/noise mask.
        # This prevents the hard local-diffusion boundary that produced visible cut lines.
        x=m.unsqueeze(1)
        x=F.max_pool2d(x,kernel_size=13,stride=1,padding=6)
        x=F.avg_pool2d(x,kernel_size=31,stride=1,padding=15)
        x=F.avg_pool2d(x,kernel_size=15,stride=1,padding=7).clamp(0,1)
        m=x.squeeze(1)
        out["noise_mask"]=m.reshape((-1,1,m.shape[-2],m.shape[-1]))
        return (out,f"V53 feathered noise mask coverage={float((m>0.10).float().mean())*100:.2f}%")

class DOGMAOpaqueLocalStitchV40:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"base_image":("IMAGE",),"patches":("IMAGE",),"masks":("MASK",),"stitch":("DOGMA_STITCH",)}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");INPUT_IS_LIST=True;FUNCTION="stitch";CATEGORY="DOGMA/v40"
    def stitch(self,base_image,patches,masks,stitch):
        base=base_image[0] if isinstance(base_image,list) else base_image;result=base.clone()[...,:3];dev=result.device;used=0
        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if not meta or meta.get("noop",False):continue
            p=patches[i];m=masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev)[...,:3].float();m=m.to(dev).float();x=int(meta["x"]);y=int(meta["y"]);w=int(meta["width"]);h=int(meta["height"])
            if w<=0 or h<=0:continue
            p=F.interpolate(p.movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(m.unsqueeze(1),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            core=(m>0.52).float();soft=F.avg_pool2d(m.unsqueeze(1),21,1,10).squeeze(1).clamp(0,1);alpha=torch.maximum(core,soft*0.72).unsqueeze(-1)
            reg=result[:,y:y+h,x:x+w,:];result[:,y:y+h,x:x+w,:]=(reg*(1-alpha)+p*alpha).clamp(0,1);used+=1
        return (result,f"v40 opaque local stitch: {used} edited crop(s)")



# =========================
# DOGMA v42 — HD RECOVERY / ROBUST SAM
# =========================
def _v42_compact_unique(text, limit=14):
    s=re.sub(r"```(?:json|text|markdown)?","",str(text or ""),flags=re.I).replace("```","")
    s=re.sub(r"\s+"," ",s).strip()
    # Collapse pathological repeated comma tokens while preserving order.
    parts=re.split(r"[,;]",s);out=[];seen=set()
    for p in parts:
        q=re.sub(r"\s+"," ",p).strip(" .:-\t\n").lower()
        if not q or q in seen:continue
        seen.add(q);out.append(q)
        if len(out)>=limit:break
    return ", ".join(out)

class DOGMATilePromptComposerV42:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"tile_report":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True}),"atmosphere_lock":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING");RETURN_NAMES=("prompt","clean_report");FUNCTION="compose";CATEGORY="DOGMA/v42"
    def compose(self,tile_report,project_context,atmosphere_lock):
        raw=str(tile_report or "");ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()[:520];atm=re.sub(r"\s+"," ",str(atmosphere_lock or "")).strip()[:260]
        vis="";prot=""
        for line in raw.replace("```","").splitlines():
            u=line.strip()
            if u.upper().startswith(("VISIBLE:","SUPPORTED:")):vis=u.split(":",1)[1]
            elif u.upper().startswith(("PROTECT:","AMBIGUOUS_OR_EMPTY:")):prot=u.split(":",1)[1]
        if not vis:vis=raw
        vis=_v42_compact_unique(vis,12);prot=_v42_compact_unique(prot,8)
        clean=f"VISIBLE: {vis or 'existing source content'} | PROTECT: {prot or 'none'}"
        p=(
            "RESTORE THIS EXACT TILE TO CLEAN, DEFINED HIGH-DEFINITION DETAIL. "
            f"VISIBLE HERE: {vis or 'existing source content'}. "
            f"GLOBAL ATMOSPHERE LOCK: {atm or 'preserve the source atmosphere, lighting and exposure exactly'}. "
            "Keep that atmosphere continuous across the entire tile: never locally dehaze fog/haze/smoke, never outline silhouettes, and never create bright, dark or coloured halos around objects. "
            "Remove synthetic grain, speckling, mushy AI texture and compression-like noise while reconstructing coherent fine detail only where the source supports it. "
            f"PROTECT AS SOFT/UNCERTAIN: {prot or 'none'}. "
            "Preserve exact geometry, object count, positions, silhouettes, perspective, occlusion, lighting and visible text/logo glyph shapes. Never add, remove or move a subject. "
            f"PROJECT/PERIOD LOCK: {ctx}"
        )
        return (p,clean)

class DOGMATileStatsLockV42:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"generated":("IMAGE",),"source":("IMAGE",),"strength":("FLOAT",{"default":0.55,"min":0.0,"max":1.0,"step":0.05}),"gain_limit":("FLOAT",{"default":0.10,"min":0.0,"max":0.30,"step":0.01}),"shift_limit":("FLOAT",{"default":0.05,"min":0.0,"max":0.20,"step":0.01})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");FUNCTION="lock";CATEGORY="DOGMA/v42"
    def lock(self,generated,source,strength,gain_limit,shift_limit):
        g=generated[...,:3].float();s=source[...,:3].float();B,H,W,C=g.shape
        if s.shape[1:3]!=(H,W):s=F.interpolate(s.movedim(-1,1),size=(H,W),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
        if s.shape[0]!=B:s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]
        # Pure per-tile affine statistics. NO spatial correction map => cannot paint halos/blobs.
        gm=g.mean(dim=(1,2),keepdim=True);sm=s.mean(dim=(1,2),keepdim=True)
        gs=g.std(dim=(1,2),keepdim=True).clamp_min(1e-4);ss=s.std(dim=(1,2),keepdim=True).clamp_min(1e-4)
        lim=max(0.0,float(gain_limit));gain=(ss/gs).clamp(1.0-lim,1.0+lim)
        sh=max(0.0,float(shift_limit));shift=(sm-gm*gain).clamp(-sh,sh)
        corr=(g*gain+shift).clamp(0,1);a=max(0.0,min(1.0,float(strength)));out=(g*(1-a)+corr*a).clamp(0,1)
        return (out,f"v42 non-spatial stats lock | strength={a:.2f} gain mean={float(gain.mean()):.4f} shift |mean|={float(shift.abs().mean()):.4f}")


class DOGMATileDetailMergeV56:
    """Source-anchored frequency merge for Phase 2 tiles.
    Source owns low-frequency geometry/lighting/color. Generated tile contributes
    controllable mid/high-frequency detail. This cannot create broad generated
    shadow blobs, color patches or halos because the generated low-frequency band is discarded.
    """
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"generated":("IMAGE",),"source":("IMAGE",),"mid_strength":("FLOAT",{"default":0.32,"min":0.0,"max":1.0,"step":0.02}),"detail_strength":("FLOAT",{"default":0.90,"min":0.0,"max":1.2,"step":0.02})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");FUNCTION="merge";CATEGORY="DOGMA/v56.4"
    @staticmethod
    def _lp(x,div):
        h,w=x.shape[-2:];hh=max(16,int(round(h/float(div))));ww=max(16,int(round(w/float(div))));return F.interpolate(F.interpolate(x,size=(hh,ww),mode="area"),size=(h,w),mode="bilinear",align_corners=False)
    def merge(self,generated,source,mid_strength,detail_strength):
        g=generated[...,:3].float();s=source[...,:3].float().to(g.device);B,H,W,C=g.shape
        if s.shape[1:3]!=(H,W):s=F.interpolate(s.movedim(-1,1),size=(H,W),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
        if s.shape[0]!=B:s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]
        gc=g.movedim(-1,1);sc=s.movedim(-1,1);glo=self._lp(gc,16);slo=self._lp(sc,16);g4=self._lp(gc,4);s4=self._lp(sc,4)
        gmid=g4-glo;smid=s4-slo;ghi=gc-g4;shi=sc-s4
        mid=max(0.0,min(1.0,float(mid_strength)));hi=max(0.0,min(1.2,float(detail_strength)))
        out=slo+(smid*(1-mid)+gmid*mid)+(shi*(1-hi)+ghi*hi)
        return (out.movedim(1,-1).clamp(0,1),f"v56.4 source low-frequency lock | generated mid={mid:.2f} high={hi:.2f} | broad lighting/color/geometry from source")

class DOGMATileEdgeAnchorV56:
    """Source-anchor only the OUTER tile border before Steudio Combine.
    With overlapping tiles, central generated content survives while border mismatches
    are forced toward the same source pixels, preventing hard color cuts/seams.
    """
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"generated":("IMAGE",),"source":("IMAGE",),"edge_width":("INT",{"default":192,"min":0,"max":512,"step":16}),"edge_generated_floor":("FLOAT",{"default":0.0,"min":0.0,"max":1.0,"step":0.05})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");FUNCTION="anchor";CATEGORY="DOGMA/v56.4"
    def anchor(self,generated,source,edge_width,edge_generated_floor):
        g=generated[...,:3].float();s=source[...,:3].float().to(g.device);B,H,W,C=g.shape
        if s.shape[1:3]!=(H,W):s=F.interpolate(s.movedim(-1,1),size=(H,W),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1)
        if s.shape[0]!=B:s=s[:1].expand(B,-1,-1,-1) if s.shape[0]==1 else s[:B]
        ew=max(0,int(edge_width));floor=max(0.0,min(1.0,float(edge_generated_floor)))
        if ew<=0:return (g,f"v56.4 tile edge anchor disabled | floor={floor:.2f}")
        yy=torch.arange(H,device=g.device,dtype=g.dtype).view(H,1);xx=torch.arange(W,device=g.device,dtype=g.dtype).view(1,W)
        d=torch.minimum(torch.minimum(xx,(W-1)-xx),torch.minimum(yy,(H-1)-yy));t=(d/float(max(1,ew))).clamp(0,1);t=t*t*(3.0-2.0*t);a=(floor+(1.0-floor)*t).view(1,H,W,1)
        out=(s*(1-a)+g*a).clamp(0,1)
        return (out,f"v56.4 source edge anchor | width={ew}px | generated floor at edge={floor:.2f} | center generated=1.00")

def _v42_cat(text):
    c=re.sub(r"[^a-z0-9 _/-]+"," ",str(text or "").lower());c=re.sub(r"\s+"," ",c).strip()
    specs=[
      ("bus",r"\b(bus|buses|coach|coaches)\b"),("trucks",r"\b(truck|trucks|lorry|lorries|van|vans)\b"),("cars",r"\b(car|cars|automobile|automobiles|sedan|sedans|hatchback|station wagon|vehicle|vehicles)\b"),
      ("people",r"\b(person|people|pedestrian|pedestrians|human|humans|crowd)\b"),("buildings",r"\b(building|buildings|architecture|facade|facades|balcony|balconies|window|windows)\b"),
      ("grass",r"\b(grass|lawn|lawns)\b"),("trees",r"\b(tree|trees|vegetation|foliage|bush|bushes|shrub|shrubs|plant|plants)\b"),("sky",r"\b(sky|cloud|clouds)\b"),
      ("road",r"\b(road|roads|street|streets|asphalt|pavement|sidewalk|ground)\b"),("water",r"\b(water|sea|ocean|lake|river)\b"),("animals",r"\b(animal|animals|dog|dogs|cat|cats|horse|horses|bird|birds)\b"),
      ("furniture",r"\b(furniture|chair|chairs|table|tables|sofa|couch|bed)\b"),("machinery",r"\b(machine|machines|machinery|equipment|tool|tools)\b"),("food",r"\b(food|dish|meal|fruit|vegetable|bread|cake)\b"),("products",r"\b(product|products|bottle|bottles|package|packages|box|boxes)\b"),("clothing",r"\b(clothing|clothes|garment|garments|shirt|dress|coat|jacket)\b")]
    for k,pat in specs:
        if re.search(pat,c):return k
    if c and c not in ("none","null","n/a","unknown"):return c[:40]
    return ""

def _v42_spec(cat,raw=""):
    c=_v42_cat(cat) or _v42_cat(raw) or "objects"
    table={
      "cars":("car, automobile, sedan, hatchback, station wagon","OBJECT",0.20),"bus":("bus, city bus, coach","OBJECT",0.20),"trucks":("truck, lorry, van","OBJECT",0.20),
      "people":("person, pedestrian, human","OBJECT",0.16),"buildings":("building, facade, balcony, window","STRUCTURE",0.22),"grass":("grass, lawn","SURFACE",0.18),"trees":("tree, bush, shrub, vegetation","OBJECT",0.18),
      "sky":("sky","SURFACE",0.18),"road":("road, asphalt, street, pavement","SURFACE",0.20),"water":("water","SURFACE",0.18),"animals":("animal, dog, cat, horse, bird","OBJECT",0.18),
      "furniture":("furniture, chair, table, sofa, bed","OBJECT",0.20),"machinery":("machine, machinery, equipment","OBJECT",0.20),"food":("food, dish, fruit, bread, cake","OBJECT",0.20),"products":("product, bottle, package, box","OBJECT",0.20),"clothing":("clothing, garment, coat, jacket, dress","OBJECT",0.18)}
    return c,*table.get(c,(re.sub(r"\s+"," ",str(raw or c)).strip()[:160] or c,"OBJECT",0.20))

class DOGMASceneInventoryPlanV42:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}"))
    FUNCTION="parse";CATEGORY="DOGMA/v42"
    def parse(self,inventory_text,project_context):
        txt=str(inventory_text or "").replace("```","");rows=[];seen=set();family_count={}
        def add(cat,raw="",origin="QWEN"):
            c,s,k,t=_v42_spec(cat,raw)
            if not c or c in seen:return
            fam="vehicle" if c in ("cars","bus","trucks") else ("vegetation" if c in ("grass","trees") else c)
            cap=2 if fam in ("vehicle","vegetation") else 1
            if family_count.get(fam,0)>=cap:return
            seen.add(c);family_count[fam]=family_count.get(fam,0)+1;rows.append((c,s,k,float(t),origin))
        # 1) Parse requested pipe format when Qwen obeys it.
        for raw in txt.splitlines():
            line=raw.strip()
            if not line:continue
            if "|" in line:
                p=[x.strip() for x in line.split("|")]
                if p and p[0].upper().startswith(("GROUP","CATEGORY")) and len(p)>=2:add(p[1],p[2] if len(p)>2 else p[1])
        # 2) Formatting-tolerant keyword scan across the ENTIRE Qwen response.
        scan_order=["people","cars","bus","trucks","buildings","grass","trees","sky","road","water","animals","furniture","machinery","food","products","clothing"]
        low=txt.lower()
        patterns={
          "people":r"\b(person|people|pedestrian|pedestrians|human|humans|crowd)\b","cars":r"\b(car|cars|automobile|automobiles|sedan|sedans|hatchback|vehicle|vehicles)\b","bus":r"\b(bus|buses|coach|coaches)\b","trucks":r"\b(truck|trucks|lorry|van|vans)\b",
          "buildings":r"\b(building|buildings|facade|facades|architecture|balcony|balconies|window|windows)\b","grass":r"\b(grass|lawn|lawns)\b","trees":r"\b(tree|trees|vegetation|foliage|bush|bushes|shrub|shrubs|plant|plants)\b","sky":r"\b(sky|cloud|clouds)\b",
          "road":r"\b(road|roads|street|streets|asphalt|pavement|sidewalk|ground)\b","water":r"\b(water|sea|ocean|lake|river)\b","animals":r"\b(animal|animals|dog|dogs|cat|cats|horse|bird)\b","furniture":r"\b(furniture|chair|chairs|table|tables|sofa|couch|bed)\b",
          "machinery":r"\b(machine|machinery|equipment|tool|tools)\b","food":r"\b(food|dish|meal|fruit|bread|cake)\b","products":r"\b(product|products|bottle|package|box)\b","clothing":r"\b(clothing|clothes|garment|shirt|dress|coat|jacket)\b"}
        for c in scan_order:
            if re.search(patterns[c],low):add(c,c)
        # 3) Urban/project fallback prevents catastrophic six-NONE plans. Absent classes simply yield empty SAM masks/no-op.
        ctx=str(project_context or "").lower();fallback=(['cars','people','buildings','grass','sky','road'] if any(x in ctx for x in ('milan','urban','city','street')) else ['people','animals','buildings','trees','sky','road'])
        for c in fallback:
            if len(rows)>=6:break
            add(c,c,"FALLBACK")
        # final generic fallback; still never NONE
        for c in ['furniture','products','machinery','water','clothing','food']:
            if len(rows)>=6:break
            add(c,c,"FALLBACK")
        rows=rows[:6]
        out=[];prev=[]
        for i,(c,s,k,t,o) in enumerate(rows,1):
            out.extend([c,s,k,t]);prev.append(f"GROUP {i}: {c} [{k}] | SAM: {s} | threshold={t:.2f} | {o}")
        return ("\n".join(prev),*out)

class DOGMALocalPromptV42:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),"project_context":("STRING",{"forceInput":True,"multiline":True}),"base_denoise":("FLOAT",{"forceInput":True})}}
    RETURN_TYPES=("STRING","STRING","FLOAT");RETURN_NAMES=("prompt","info","denoise");FUNCTION="compose";CATEGORY="DOGMA/v42"
    def compose(self,category,kind,project_context,base_denoise):
        c=_v42_cat(category) or str(category or "objects").strip().lower();base=max(0.15,min(0.55,float(base_denoise)))
        factor={"cars":1.0,"bus":1.0,"trucks":1.0,"people":0.95,"animals":0.95,"furniture":0.90,"products":0.90,"machinery":0.90,"clothing":0.85,"buildings":0.85,"grass":0.72,"trees":0.75,"road":0.62,"water":0.55,"sky":0.45}.get(c,0.85)
        den=max(0.15,min(0.55,base*factor));head={
          "cars":"1970s ITALIAN CARS","bus":"1970s ITALIAN CITY BUS","trucks":"1970s ITALIAN TRUCKS AND VANS","people":"1970s MILAN PEDESTRIANS","buildings":"1970s MILAN URBAN BUILDINGS",
          "grass":"URBAN GRASS AND LAWN","trees":"URBAN TREES AND VEGETATION","sky":"NATURAL HAZY URBAN SKY","road":"MILAN ASPHALT AND STREET SURFACES","water":"NATURAL WATER SURFACE","animals":"EXISTING ANIMALS","furniture":"EXISTING FURNITURE","machinery":"EXISTING MACHINERY","food":"EXISTING FOOD","products":"EXISTING PRODUCTS","clothing":"EXISTING CLOTHING"}.get(c,c.upper())
        if c in ("sky","water","grass","trees","road"):
            body="Refine only the selected existing region into clean, coherent photographic texture. Remove synthetic grain and AI mush while preserving its exact boundary, lighting, atmosphere and natural softness. Do not add objects."
        else:
            body="Refine only the selected existing instances into clean, coherent photographic detail. Repair mushy AI geometry and synthetic grain while keeping exact count, position, pose, scale, silhouette and colour. Do not add, remove or move an instance."
        p=f"{head} — CLEAN REFINEMENT. {body}"
        return (p,f"v42 local {c} | denoise={den:.3f}",float(den))



# =========================
# DOGMA v43 — REGION-SAFE LOCAL
# =========================
def _v43_canonical(text):
    c=_v42_cat(text)
    return c or re.sub(r"\s+"," ",str(text or "").strip().lower())[:40] or "none"

def _v43_spec(cat):
    c=_v43_canonical(cat)
    table={
      "cars":("car","OBJECT",0.07),"bus":("bus","OBJECT",0.08),"trucks":("truck","OBJECT",0.08),
      "people":("person","OBJECT",0.06),"animals":("animal","OBJECT",0.08),"furniture":("furniture","OBJECT",0.10),
      "machinery":("machine","OBJECT",0.10),"products":("product","OBJECT",0.10),"clothing":("clothing","OBJECT",0.09),"food":("food","OBJECT",0.10),
      "buildings":("building","STRUCTURE",0.10),"grass":("grass","SURFACE",0.08),"trees":("tree","OBJECT",0.08),
      "sky":("sky","SURFACE",0.08),"road":("road","SURFACE",0.09),"water":("water","SURFACE",0.08)
    }
    return (c,)+table.get(c,(c,"OBJECT",0.10))

class DOGMASceneInventoryPlanV43:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}"))
    FUNCTION="parse";CATEGORY="DOGMA/v43"
    def parse(self,inventory_text,project_context):
        txt=str(inventory_text or "").replace("```","");low=txt.lower();rows=[];seen=set();fam={}
        def add(raw,origin="QWEN"):
            c,s,k,t=_v43_spec(raw)
            if not c or c in ("none","unknown") or c in seen:return
            family="vehicle" if c in ("cars","bus","trucks") else ("vegetation" if c in ("grass","trees") else c)
            cap=3 if family=="vehicle" else (2 if family=="vegetation" else 1)
            if fam.get(family,0)>=cap:return
            seen.add(c);fam[family]=fam.get(family,0)+1;rows.append((c,s,k,float(t),origin))
        # explicit lines first
        for line in txt.splitlines():
            if "|" in line:
                p=[x.strip() for x in line.split("|")]
                if p and p[0].upper().startswith(("GROUP","CATEGORY")) and len(p)>=2:add(p[1])
        pats=[
          ("people",r"\b(person|people|pedestrian|pedestrians|human|humans|crowd)\b"),("cars",r"\b(car|cars|automobile|automobiles|sedan|sedans|hatchback|vehicle|vehicles)\b"),
          ("bus",r"\b(bus|buses|coach|coaches)\b"),("trucks",r"\b(truck|trucks|lorry|lorries|van|vans)\b"),("buildings",r"\b(building|buildings|facade|facades|architecture|balcony|balconies|window|windows)\b"),
          ("grass",r"\b(grass|lawn|lawns)\b"),("trees",r"\b(tree|trees|vegetation|foliage|bush|bushes|shrub|shrubs)\b"),("sky",r"\b(sky|cloud|clouds)\b"),
          ("road",r"\b(road|roads|street|streets|asphalt|pavement|sidewalk|ground)\b"),("water",r"\b(water|sea|ocean|lake|river)\b"),("animals",r"\b(animal|animals|dog|dogs|cat|cats|horse|bird)\b"),
          ("furniture",r"\b(furniture|chair|chairs|table|tables|sofa|couch|bed)\b"),("machinery",r"\b(machine|machinery|equipment|tool|tools)\b"),("products",r"\b(product|products|bottle|package|box)\b"),("clothing",r"\b(clothing|clothes|garment|shirt|dress|coat|jacket)\b"),("food",r"\b(food|dish|meal|fruit|bread|cake)\b")]
        for c,p in pats:
            if re.search(p,low):add(c)
        # General fallback only if Qwen returned too little. These rows no-op if SAM sees nothing.
        ctx=str(project_context or "").lower();fallback=['cars','people','buildings','grass','sky','road'] if any(x in ctx for x in ('milan','urban','city','street')) else ['people','buildings','trees','sky','animals','road']
        for c in fallback:
            if len(rows)>=6:break
            add(c,"FALLBACK")
        rows=rows[:6]
        while len(rows)<6:rows.append(("none","nonexistent_placeholder_object_xyz","OBJECT",0.50,"INACTIVE"))
        out=[];prev=[]
        for i,(c,s,k,t,o) in enumerate(rows,1):
            out.extend([c,s,k,t]);prev.append(f"GROUP {i}: {c} [{k}] | SAM='{s}' | threshold={t:.2f} | {o}")
        return ("\n".join(prev),*out)

class DOGMARegionCropsV43:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"image":("IMAGE",),"masks":("MASK",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING");RETURN_NAMES=("crops","crop_masks","stitch","info");OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="make";CATEGORY="DOGMA/v43"
    @staticmethod
    def _ri(x,h,w):return F.interpolate(x.movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
    @staticmethod
    def _rm(x,h,w):
        if x.ndim==2:x=x.unsqueeze(0)
        return F.interpolate(x.unsqueeze(1).float(),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
    @staticmethod
    def _iou(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b;ix1=max(ax1,bx1);iy1=max(ay1,by1);ix2=min(ax2,bx2);iy2=min(ay2,by2);inter=max(0,ix2-ix1)*max(0,iy2-iy1)
        if inter<=0:return 0.0
        aa=max(1,(ax2-ax1)*(ay2-ay1));bb=max(1,(bx2-bx1)*(by2-by1));return inter/float(aa+bb-inter)
    @staticmethod
    def _gap(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b;dx=max(0,max(ax1,bx1)-min(ax2,bx2));dy=max(0,max(ay1,by1)-min(ay2,by2));return math.sqrt(dx*dx+dy*dy)
    @staticmethod
    def _components(mask,threshold=0.28,max_dim=720):
        hard=(mask>threshold).float();H,W=hard.shape
        if int(hard.sum())<8:return []
        step=max(1,int(math.ceil(max(H,W)/float(max_dim))))
        sh=(F.max_pool2d(hard[None,None],step,step)[0,0]>0) if step>1 else (hard>0)
        hh,ww=sh.shape;seen=torch.zeros_like(sh,dtype=torch.bool);out=[]
        for yy in range(hh):
            for xx in range(ww):
                if not bool(sh[yy,xx]) or bool(seen[yy,xx]):continue
                stack=[(yy,xx)];seen[yy,xx]=True;pts=[]
                while stack:
                    y,x=stack.pop();pts.append((y,x))
                    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=y+dy,x+dx
                        if 0<=ny<hh and 0<=nx<ww and bool(sh[ny,nx]) and not bool(seen[ny,nx]):seen[ny,nx]=True;stack.append((ny,nx))
                if len(pts)<2:continue
                ys=[p[0] for p in pts];xs=[p[1] for p in pts];x1=max(0,min(xs)*step);y1=max(0,min(ys)*step);x2=min(W,(max(xs)+1)*step);y2=min(H,(max(ys)+1)*step);cnt=int(hard[y1:y2,x1:x2].sum())
                if cnt>=8:out.append((x1,y1,x2,y2,cnt))
        return out
    def _noop(self,src,cat):
        H,W=src.shape[1:3];side=min(256,H,W);x=max(0,(W-side)//2);y=max(0,(H-side)//2);c=src[:,y:y+side,x:x+side,:];z=torch.zeros((1,side,side),device=src.device)
        return ([c],[z],[{"x":x,"y":y,"width":side,"height":side,"noop":True}],f"{cat}: no valid SAM region — safe no-op")
    def make(self,image,masks,category,kind):
        src=image[:1,...,:3].float();H,W=src.shape[1:3];cat=_v43_canonical(category);k=str(kind or 'OBJECT').upper();m=masks.detach().float().cpu()
        if cat=='none':return self._noop(src,cat)
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return self._noop(src,cat)
        N,MH,MW=m.shape;sx=W/float(MW);sy=H/float(MH)
        union=m.max(0).values
        # SURFACE / STRUCTURE: connected semantic pieces ONLY. Never manufacture a grid.
        if k in ('SURFACE','STRUCTURE'):
            comps=self._components(union,0.24,720)
            if not comps:return self._noop(src,cat)
            comps=sorted(comps,key=lambda q:q[4],reverse=True)[:(2 if k=='SURFACE' else 4)]
            full=self._rm(union[None],H,W).to(src.device);crops=[];cms=[];meta=[];target=2048;ctx=112 if k=='SURFACE' else 144
            for x1s,y1s,x2s,y2s,cnt in comps:
                x1=max(0,int(x1s*sx)-ctx);y1=max(0,int(y1s*sy)-ctx);x2=min(W,int(math.ceil(x2s*sx))+ctx);y2=min(H,int(math.ceil(y2s*sy))+ctx)
                c=src[:,y1:y2,x1:x2,:];cm=full[:,y1:y2,x1:x2];h,w=c.shape[1:3]
                if max(h,w)>target:
                    sc=target/float(max(h,w));nh=max(64,int(h*sc)//16*16);nw=max(64,int(w*sc)//16*16);c=self._ri(c,nh,nw);cm=self._rm(cm,nh,nw)
                crops.append(c);cms.append(cm.clamp(0,1));meta.append({'x':x1,'y':y1,'width':x2-x1,'height':y2-y1,'noop':False,'kind':k})
            return (crops,cms,meta,f"{cat} [{k}]: {len(comps)} real connected region(s); NEVER grid-tiled")
        # OBJECT: explode every disconnected SAM component and retain many groups.
        det=[]
        for mi in range(N):
            for x1s,y1s,x2s,y2s,cnt in self._components(m[mi],0.26,720):
                box=(max(0,int(x1s*sx)),max(0,int(y1s*sy)),min(W,int(math.ceil(x2s*sx))),min(H,int(math.ceil(y2s*sy))))
                if box[2]-box[0]>=4 and box[3]-box[1]>=4:det.append({'mi':mi,'sbox':(x1s,y1s,x2s,y2s),'bbox':box,'area':cnt*sx*sy})
        if not det:return self._noop(src,cat)
        det.sort(key=lambda q:q['area'],reverse=True);uniq=[]
        for q in det:
            if not any(self._iou(q['bbox'],u['bbox'])>=0.72 for u in uniq):uniq.append(q)
        det=uniq
        if cat in ('cars','bus','trucks'):max_obj,max_groups,gap,ctx,target=4,20,140,128,1664
        elif cat=='people':max_obj,max_groups,gap,ctx,target=4,16,110,112,1536
        else:max_obj,max_groups,gap,ctx,target=3,12,120,128,1664
        rem=list(range(len(det)));groups=[]
        while rem:
            seed=rem.pop(0);members=[seed];ub=det[seed]['bbox']
            while len(members)<max_obj and rem:
                best=None
                for ri,j in enumerate(rem):
                    g=self._gap(ub,det[j]['bbox'])
                    if g<=gap and (best is None or g<best[0]):best=(g,ri,j)
                if best is None:break
                _,ri,j=best;rem.pop(ri);members.append(j);b=det[j]['bbox'];ub=(min(ub[0],b[0]),min(ub[1],b[1]),max(ub[2],b[2]),max(ub[3],b[3]))
            groups.append((members,ub))
        groups.sort(key=lambda gb:sum(det[i]['area'] for i in gb[0]),reverse=True);groups=groups[:max_groups];groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))
        crops=[];cms=[];meta=[]
        for members,ub in groups:
            x1,y1,x2,y2=ub;cx1=max(0,x1-ctx);cy1=max(0,y1-ctx);cx2=min(W,x2+ctx);cy2=min(H,y2+ctx);c=src[:,cy1:cy2,cx1:cx2,:];ch,cw=c.shape[1:3];local=torch.zeros((1,ch,cw))
            for di in members:
                q=det[di];mi=q['mi'];lx1=max(0,int(math.floor(cx1/W*MW)));ly1=max(0,int(math.floor(cy1/H*MH)));lx2=min(MW,int(math.ceil(cx2/W*MW)));ly2=min(MH,int(math.ceil(cy2/H*MH)));sub=m[mi,ly1:ly2,lx1:lx2].clone()
                if sub.numel()==0:continue
                bx1,by1,bx2,by2=q['sbox'];yy=torch.arange(ly1,ly2)[:,None];xx=torch.arange(lx1,lx2)[None,:];sub=sub*((xx>=bx1)&(xx<bx2)&(yy>=by1)&(yy<by2)).float();sub=F.interpolate(sub[None,None],size=(ch,cw),mode='bilinear',align_corners=False)[0,0];local=torch.maximum(local,sub[None])
            if max(ch,cw)>target:
                sc=target/float(max(ch,cw));nh=max(64,int(ch*sc)//16*16);nw=max(64,int(cw*sc)//16*16);c=self._ri(c,nh,nw);local=self._rm(local,nh,nw)
            crops.append(c);cms.append(local.clamp(0,1));meta.append({'x':cx1,'y':cy1,'width':cx2-cx1,'height':cy2-cy1,'noop':False,'kind':'OBJECT','members':len(members)})
        return (crops,cms,meta,f"{cat} [OBJECT]: {len(det)} detected component(s) -> {len(crops)} crop group(s), cap {max_groups}")

class DOGMALocalPromptV43:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),"project_context":("STRING",{"forceInput":True,"multiline":True}),"base_denoise":("FLOAT",{"forceInput":True})}}
    RETURN_TYPES=("STRING","STRING","FLOAT");RETURN_NAMES=("prompt","info","denoise");FUNCTION="compose";CATEGORY="DOGMA/v43"
    def compose(self,category,kind,project_context,base_denoise):
        c=_v43_canonical(category);k=str(kind or 'OBJECT').upper();base=max(.20,min(.45,float(base_denoise)))
        fixed={'cars':.35,'bus':.35,'trucks':.35,'people':.30,'animals':.30,'furniture':.32,'machinery':.32,'products':.30,'clothing':.28,'food':.28,'buildings':.27,'trees':.22,'grass':.20,'road':.16,'water':.14,'sky':.12}
        den=fixed.get(c,min(base,.30))
        heads={'cars':'1970s ITALIAN CARS','bus':'1970s ITALIAN CITY BUS','trucks':'1970s ITALIAN TRUCKS AND VANS','people':'1970s MILAN PEDESTRIANS','buildings':'1970s MILAN BUILDING DETAILS','grass':'URBAN GRASS','trees':'URBAN TREES AND VEGETATION','sky':'EXISTING SKY AND ATMOSPHERE','road':'EXISTING STREET AND ASPHALT','water':'EXISTING WATER','animals':'EXISTING ANIMALS'}
        h=heads.get(c,c.upper())
        if c=='sky':body='Clean only the selected existing sky/haze. Remove AI blotches and synthetic grain while preserving the exact colour, exposure, haze, cloud structure and softness. No new clouds, light sources or objects.'
        elif c in ('grass','trees'):body='Improve only the selected existing natural texture into coherent fine detail. Preserve exact colour, lighting, boundaries and vegetation layout. Do not add plants, paths or objects.'
        elif c in ('road','water'):body='Clean only the selected existing surface texture. Preserve exact geometry, markings/reflections, colour, exposure and lighting. Do not add or remove anything.'
        elif c=='buildings':body='Refine only the selected existing facade, windows, balconies and architectural micro-detail. Preserve exact geometry, window count, facade identity, lighting and colour.'
        else:body='Refine only the selected existing instances into clean coherent photographic detail. Preserve exact count, position, pose, scale, silhouette, colour and occlusion. Do not add, remove or move an instance.'
        p=f"{h}. {body}"
        return (p,f"v43.1 {c} [{k}] | Distilled9B CFG1 | denoise={den:.2f}",float(den))

class DOGMARegionStitchV43:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"base_image":("IMAGE",),"patches":("IMAGE",),"masks":("MASK",),"stitch":("DOGMA_STITCH",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");INPUT_IS_LIST=True;FUNCTION="stitch_regions";CATEGORY="DOGMA/v53"
    def stitch_regions(self,base_image,patches,masks,stitch,category,kind):
        base=base_image[0] if isinstance(base_image,list) else base_image;result=base.clone()[...,:3];dev=result.device;cat=_v43_canonical(category[0] if isinstance(category,list) and category else category);k=str(kind[0] if isinstance(kind,list) and kind else kind).upper();used=0
        # V53: no binary core edge. Dilate then multi-pass feather so the edit fades
        # continuously into the untouched source instead of exposing segmentation cuts.
        if k=='SURFACE':dilate=9;kernel=81;strength=.72
        elif k=='STRUCTURE':dilate=7;kernel=65;strength=.88
        else:dilate=6;kernel=55;strength=.96
        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if not meta or meta.get('noop',False):continue
            p=patches[i];m=masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev)[...,:3].float();m=m.to(dev).float();x=int(meta['x']);y=int(meta['y']);w=int(meta['width']);h=int(meta['height'])
            if w<=0 or h<=0:continue
            p=F.interpolate(p.movedim(-1,1),size=(h,w),mode='bicubic',align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(m.unsqueeze(1),size=(h,w),mode='bilinear',align_corners=False).clamp(0,1)
            if dilate>0:m=F.max_pool2d(m,2*dilate+1,1,dilate)
            soft=F.avg_pool2d(m,kernel,1,kernel//2)
            soft=F.avg_pool2d(soft,21,1,10).clamp(0,1)
            alpha=(soft*strength).movedim(1,-1)
            reg=result[:,y:y+h,x:x+w,:];result[:,y:y+h,x:x+w,:]=(reg*(1-alpha)+p*alpha).clamp(0,1);used+=1
        return (result,f"V53 soft feather stitch | {cat} [{k}] | {used} region(s) | no hard mask core")


# =========================
# DOGMA v44 — SOURCE-GROUNDED / ALIGNED-NOISE SUPPORT
# =========================

class DOGMATilePromptComposerV44:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "tile_report":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING","STRING")
    RETURN_NAMES=("prompt","clean_report")
    FUNCTION="compose"
    CATEGORY="DOGMA/v44"

    @staticmethod
    def _clean(s):
        s=re.sub(r"```(?:json|text|markdown)?","",str(s or ""),flags=re.I).replace("```","")
        return re.sub(r"\s+"," ",s).strip()[:1400]

    @staticmethod
    def _items(s):
        bits=re.split(r"[,;|]",str(s or ""))
        out=[];seen=set()
        for b in bits:
            x=re.sub(r"\s+"," ",b).strip(" .:-").lower()
            if not x or x in seen: continue
            seen.add(x);out.append(x)
        return out[:28]

    def compose(self,tile_report,project_context):
        r=self._clean(tile_report)
        ms=re.search(r"SUPPORTED\s*:\s*(.*?)(?=AMBIGUOUS_OR_EMPTY\s*:|$)",r,re.I)
        ma=re.search(r"AMBIGUOUS_OR_EMPTY\s*:\s*(.*)$",r,re.I)
        supported=self._items(ms.group(1) if ms else "")
        ambiguous=self._items(ma.group(1) if ma else "")
        sup="; ".join(supported) if supported else "no reliable semantic subject; only source geometry and low-information fields"
        amb="; ".join(ambiguous) if ambiguous else "none specifically reported"

        low=(" ".join(supported)).lower()
        ctx=self._clean(project_context)
        # Keep only the first period/location lock clause. Object-specific context
        # is injected only when that family is visibly supported in THIS tile.
        first=re.split(r"(?<=[.!?])\s+",ctx)[0].strip() if ctx else ""
        if len(first)>220: first=first[:220]
        style=[]
        if re.search(r"\b(car|cars|vehicle|vehicles|automobile|bus|truck|van|motorcycle|bicycle)\b",low):
            style.append("Existing visible vehicles must keep period-correct design.")
        if re.search(r"\b(building|buildings|facade|architecture|balcony|window|roof)\b",low):
            style.append("Existing visible architecture must keep period-correct materials and design.")
        if re.search(r"\b(person|people|pedestrian|human|crowd)\b",low):
            style.append("Existing visible people and clothing must remain period-correct.")
        if re.search(r"\b(traffic light|streetlight|lamp|pole|sign|street furniture)\b",low):
            style.append("Existing visible street furniture must remain period-correct.")
        style_text=" ".join(style)

        p=(
            "VISIBLE TILE CONTENT — RESTORE ONLY THESE EXISTING THINGS: "+sup+".\n"
            "SOURCE GEOMETRY IS ABSOLUTE GROUND TRUTH. Do not introduce any semantic subject absent from the visible-content allowlist. "
            "Preserve exact object count, positions, silhouettes, perspective, occlusion, lighting, exposure, white balance, haze, smoke, reflections and composition. "
            "Indistinct shapes must stay indistinct unless the source pixels themselves clearly define them. "
            "Do not transform rooftop vents, chimneys, smoke, highlights, shadows, reflections, texture or haze into semantic objects.\n"
            +(("PERIOD/LOOK LOCK: "+first+". ") if first else "")+
            style_text+
            "\nAMBIGUOUS / LOW-INFORMATION REGIONS TO PRESERVE AS AMBIGUOUS: "+amb+".\n"
            "TARGET: clean high-definition photographic reconstruction of existing supported content; remove synthetic AI grain, speckling and mush, "
            "but do not rewrite the scene, modernize it, invent text, or create new objects."
        )
        return (p,r)


class DOGMASemanticSourceViewV44:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "target_side":("INT",{"default":3584,"min":1536,"max":4096,"step":64}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    FUNCTION="resize"
    CATEGORY="DOGMA/v44"

    def resize(self,image,target_side):
        x=image[...,:3].float()
        H,W=x.shape[1:3]
        target=int(target_side)
        scale=target/float(max(H,W))
        nh=max(16,int(round(H*scale/16))*16)
        nw=max(16,int(round(W*scale/16))*16)
        if (nh,nw)==(H,W):
            return (x,f"v44 semantic SOURCE kept {W}x{H}")
        mode="bicubic"
        out=F.interpolate(
            x.movedim(-1,1),size=(nh,nw),mode=mode,align_corners=False,
            antialias=(scale<1.0)
        ).movedim(1,-1).clamp(0,1)
        return (out,f"v44 semantic SOURCE {W}x{H} -> {nw}x{nh}; source-only, no generated pixels")


class DOGMASceneInventoryPlanV44:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "inventory_text":("STRING",{"forceInput":True,"multiline":True}),
            "project_context":("STRING",{"forceInput":True,"multiline":True}),
        }}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}"))
    FUNCTION="parse"
    CATEGORY="DOGMA/v44"

    @staticmethod
    def _canon(raw):
        s=re.sub(r"[^a-z0-9 _-]"," ",str(raw or "").lower())
        s=re.sub(r"\s+"," ",s).strip()
        if not s:return None
        tests=[
            ("people",("person","people","pedestrian","human","crowd")),
            ("cars",("car","cars","automobile","sedan","hatchback","passenger vehicle","vehicles")),
            ("bus",("bus","buses","coach")),
            ("trucks",("truck","trucks","lorry","van","vans")),
            ("buildings",("building","buildings","facade","architecture","balcony","window")),
            ("grass",("grass","lawn")),
            ("trees",("tree","trees","vegetation","foliage","bush","shrub")),
            ("sky",("sky","cloud","clouds")),
            ("road",("road","roads","street","asphalt","pavement","sidewalk")),
            ("water",("water","sea","ocean","lake","river")),
            ("animals",("animal","animals","dog","cat","horse","bird")),
            ("furniture",("furniture","chair","table","sofa","couch","bed")),
            ("machinery",("machinery","machine","equipment","tool")),
            ("products",("product","products","bottle","package","box")),
            ("clothing",("clothing","clothes","garment","shirt","dress","coat","jacket")),
            ("food",("food","dish","meal","fruit","bread","cake")),
        ]
        for c,ks in tests:
            if any(re.search(r"\b"+re.escape(k)+r"\b",s) for k in ks):
                return c
        return None

    @staticmethod
    def _spec(c):
        specs={
            "people":("people, pedestrians, persons","OBJECT",0.020),
            "cars":("cars, automobiles, passenger vehicles","OBJECT",0.020),
            "bus":("bus, buses, city buses","OBJECT",0.025),
            "trucks":("trucks, vans, lorries","OBJECT",0.025),
            "animals":("animals, dogs, cats, horses, birds","OBJECT",0.035),
            "furniture":("furniture, chairs, tables, sofas","OBJECT",0.045),
            "machinery":("machinery, machines, equipment","OBJECT",0.045),
            "products":("products, bottles, packages, boxes","OBJECT",0.045),
            "clothing":("clothing, garments","OBJECT",0.045),
            "food":("food, dishes, fruit","OBJECT",0.045),
            "buildings":("buildings, facades, architecture","STRUCTURE",0.050),
            "grass":("grass, lawn","SURFACE",0.040),
            "trees":("trees, vegetation, bushes","SURFACE",0.040),
            "sky":("sky, clouds","SURFACE",0.060),
            "road":("road, street, asphalt, pavement","SURFACE",0.040),
            "water":("water, river, sea, lake","SURFACE",0.050),
        }
        return specs.get(c,(c or "nonexistent_placeholder_object_xyz","OBJECT",0.08))

    def parse(self,inventory_text,project_context):
        txt=str(inventory_text or "").replace("```","")
        candidates=[];seen=set()

        # Explicit GROUP lines first.
        for line in txt.splitlines():
            if "|" not in line: continue
            p=[x.strip() for x in line.split("|")]
            if len(p)>=2 and p[0].upper().startswith(("GROUP","CATEGORY")):
                c=self._canon(p[1])
                if c and c not in seen:
                    candidates.append(c);seen.add(c)

        # Recover malformed prose without inventing from project context.
        low=txt.lower()
        scan=[
            ("people",r"\b(person|people|pedestrian|pedestrians|human|humans|crowd)\b"),
            ("cars",r"\b(car|cars|automobile|automobiles|sedan|sedans|hatchback|passenger vehicle|passenger vehicles)\b"),
            ("bus",r"\b(bus|buses|coach|coaches)\b"),
            ("trucks",r"\b(truck|trucks|lorry|lorries|van|vans)\b"),
            ("buildings",r"\b(building|buildings|facade|facades|architecture|balcony|balconies|window|windows)\b"),
            ("grass",r"\b(grass|lawn|lawns)\b"),
            ("trees",r"\b(tree|trees|vegetation|foliage|bush|bushes|shrub|shrubs)\b"),
            ("sky",r"\b(sky|cloud|clouds)\b"),
            ("road",r"\b(road|roads|street|streets|asphalt|pavement|sidewalk)\b"),
            ("water",r"\b(water|sea|ocean|lake|river)\b"),
            ("animals",r"\b(animal|animals|dog|dogs|cat|cats|horse|horses|bird|birds)\b"),
            ("furniture",r"\b(furniture|chair|chairs|table|tables|sofa|couch|bed)\b"),
            ("machinery",r"\b(machine|machinery|equipment|tool|tools)\b"),
            ("products",r"\b(product|products|bottle|package|box)\b"),
            ("clothing",r"\b(clothing|clothes|garment|shirt|dress|coat|jacket)\b"),
            ("food",r"\b(food|dish|meal|fruit|bread|cake)\b"),
        ]
        for c,pat in scan:
            if c not in seen and re.search(pat,low):
                candidates.append(c);seen.add(c)

        # Diversity/priority: discrete objects first, then one structure and surfaces.
        priority=["people","cars","bus","trucks","animals","furniture","machinery","products","clothing","food",
                  "buildings","grass","trees","sky","road","water"]
        ordered=[c for c in priority if c in seen]
        objects=[c for c in ordered if self._spec(c)[1]=="OBJECT"]
        structures=[c for c in ordered if self._spec(c)[1]=="STRUCTURE"]
        surfaces=[c for c in ordered if self._spec(c)[1]=="SURFACE"]

        selected=[]
        selected.extend(objects[:4])
        if len(selected)<6:selected.extend(structures[:1])
        if len(selected)<6:selected.extend(surfaces[:2])
        # Fill remaining ONLY from actually observed categories.
        for c in ordered:
            if len(selected)>=6:break
            if c not in selected:selected.append(c)

        rows=[]
        for c in selected[:6]:
            p,k,t=self._spec(c);rows.append((c,p,k,t))
        while len(rows)<6:
            rows.append(("none","nonexistent_placeholder_object_xyz","OBJECT",0.50))

        out=[];prev=[]
        for i,(c,p,k,t) in enumerate(rows,1):
            out.extend([c,p,k,float(t)])
            origin="SOURCE-EVIDENCE" if c!="none" else "INACTIVE"
            prev.append(f"GROUP {i}: {c} [{k}] | SAM='{p}' | threshold={t:.3f} | {origin}")
        return ("\n".join(prev),*out)


class DOGMARegionCropsV44(DOGMARegionCropsV43):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "masks":("MASK",),
            "category":("STRING",{"forceInput":True}),
            "kind":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="make"
    CATEGORY="DOGMA/v44"

    def make(self,image,masks,category,kind):
        src=image[:1,...,:3].float()
        H,W=src.shape[1:3]
        cat=_v43_canonical(category)
        k=str(kind or "OBJECT").upper()
        m=masks.detach().float().cpu()
        if cat=="none": return self._noop(src,cat)
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return self._noop(src,cat)

        N,MH,MW=m.shape
        sx=W/float(MW);sy=H/float(MH)
        union=m.max(0).values

        # Broad structures/surfaces: true connected regions only, NEVER grids.
        if k in ("SURFACE","STRUCTURE"):
            comps=self._components(union,0.16 if k=="SURFACE" else 0.18,1024)
            if not comps:return self._noop(src,cat)
            comps=sorted(comps,key=lambda q:q[4],reverse=True)[:(2 if k=="SURFACE" else 4)]
            full=self._rm(union[None],H,W).to(src.device)
            crops=[];cms=[];meta=[]
            target=2048;ctx=128 if k=="SURFACE" else 160
            for x1s,y1s,x2s,y2s,cnt in comps:
                x1=max(0,int(x1s*sx)-ctx);y1=max(0,int(y1s*sy)-ctx)
                x2=min(W,int(math.ceil(x2s*sx))+ctx);y2=min(H,int(math.ceil(y2s*sy))+ctx)
                c=src[:,y1:y2,x1:x2,:];cm=full[:,y1:y2,x1:x2]
                h,w=c.shape[1:3]
                if max(h,w)>target:
                    sc=target/float(max(h,w))
                    nh=max(64,int(h*sc)//16*16);nw=max(64,int(w*sc)//16*16)
                    c=self._ri(c,nh,nw);cm=self._rm(cm,nh,nw)
                crops.append(c);cms.append(cm.clamp(0,1))
                meta.append({"x":x1,"y":y1,"width":x2-x1,"height":y2-y1,"noop":False,"kind":k})
            return (crops,cms,meta,f"{cat} [{k}]: {len(comps)} source-grounded connected region(s); NEVER grid-tiled")

        # Objects: aggressively preserve disconnected instances, including small/distant ones.
        comp_thr=0.10 if cat in ("cars","bus","trucks","people") else 0.15
        det=[]
        for mi in range(N):
            for x1s,y1s,x2s,y2s,cnt in self._components(m[mi],comp_thr,1024):
                box=(max(0,int(x1s*sx)),max(0,int(y1s*sy)),
                     min(W,int(math.ceil(x2s*sx))),min(H,int(math.ceil(y2s*sy))))
                if box[2]-box[0]>=3 and box[3]-box[1]>=3:
                    det.append({"mi":mi,"sbox":(x1s,y1s,x2s,y2s),"bbox":box,"area":cnt*sx*sy})
        if not det:return self._noop(src,cat)

        det.sort(key=lambda q:q["area"],reverse=True)
        uniq=[]
        for q in det:
            if not any(self._iou(q["bbox"],u["bbox"])>=0.72 for u in uniq):
                uniq.append(q)
        det=uniq

        if cat=="cars":
            max_obj,max_groups,gap,ctx,target=3,28,115,128,1664
        elif cat in ("bus","trucks"):
            max_obj,max_groups,gap,ctx,target=2,16,130,144,1792
        elif cat=="people":
            max_obj,max_groups,gap,ctx,target=4,24,100,112,1536
        else:
            max_obj,max_groups,gap,ctx,target=3,16,115,128,1664

        rem=list(range(len(det)));groups=[]
        while rem:
            seed=rem.pop(0);members=[seed];ub=det[seed]["bbox"]
            while len(members)<max_obj and rem:
                best=None
                for ri,j in enumerate(rem):
                    g=self._gap(ub,det[j]["bbox"])
                    if g<=gap and (best is None or g<best[0]):best=(g,ri,j)
                if best is None:break
                _,ri,j=best;rem.pop(ri);members.append(j)
                b=det[j]["bbox"]
                ub=(min(ub[0],b[0]),min(ub[1],b[1]),max(ub[2],b[2]),max(ub[3],b[3]))
            groups.append((members,ub))

        # Keep many groups; then restore spatial order for predictable mapped processing.
        groups.sort(key=lambda gb:sum(det[i]["area"] for i in gb[0]),reverse=True)
        groups=groups[:max_groups]
        groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))

        crops=[];cms=[];meta=[]
        for members,ub in groups:
            x1,y1,x2,y2=ub
            cx1=max(0,x1-ctx);cy1=max(0,y1-ctx);cx2=min(W,x2+ctx);cy2=min(H,y2+ctx)
            c=src[:,cy1:cy2,cx1:cx2,:]
            ch,cw=c.shape[1:3]
            local=torch.zeros((1,ch,cw))
            for di in members:
                q=det[di];mi=q["mi"]
                lx1=max(0,int(math.floor(cx1/W*MW)));ly1=max(0,int(math.floor(cy1/H*MH)))
                lx2=min(MW,int(math.ceil(cx2/W*MW)));ly2=min(MH,int(math.ceil(cy2/H*MH)))
                sub=m[mi,ly1:ly2,lx1:lx2].clone()
                if sub.numel()==0:continue
                bx1,by1,bx2,by2=q["sbox"]
                yy=torch.arange(ly1,ly2)[:,None];xx=torch.arange(lx1,lx2)[None,:]
                sub=sub*((xx>=bx1)&(xx<bx2)&(yy>=by1)&(yy<by2)).float()
                sub=F.interpolate(sub[None,None],size=(ch,cw),mode="bilinear",align_corners=False)[0,0]
                local=torch.maximum(local,sub[None])
            if max(ch,cw)>target:
                sc=target/float(max(ch,cw))
                nh=max(64,int(ch*sc)//16*16);nw=max(64,int(cw*sc)//16*16)
                c=self._ri(c,nh,nw);local=self._rm(local,nh,nw)
            crops.append(c);cms.append(local.clamp(0,1))
            meta.append({"x":cx1,"y":cy1,"width":cx2-cx1,"height":cy2-cy1,
                         "noop":False,"kind":"OBJECT","members":len(members)})
        return (crops,cms,meta,
                f"{cat} [OBJECT]: {len(det)} SOURCE-grounded component(s) -> {len(crops)} crop group(s), cap {max_groups}")



# =========================
# DOGMA COMPLEX V52.1
# =========================

class DOGMAV50TileInstruction:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",); RETURN_NAMES=("instruction",); FUNCTION="build"; CATEGORY="DOGMA/v50"
    def build(self,project_context):
        ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()
        return (f"""Look ONLY at this exact image tile. Produce ONE short English prompt describing only clearly visible existing content and its obvious relationship.\nProject context: {ctx}\nUse the project context only as an adjective/style qualifier; NEVER use it as evidence that an object exists.\nPrefer 3-10 words. Put the main visible subject first. If a relationship is visually clear, include it.\nExamples of form only: '1970s Italian cars on a road', '1970s Italian apartment buildings', 'grass lawn and concrete skylights', 'pedestrians beside parked cars'.\nDo not say restore, improve, detailed, high quality, damaged, blurry or grainy. No OCR. No brands. No guessed objects.\nReturn exactly one line: PROMPT: <phrase>""",)


class DOGMAV50PromptClean:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"vlm_output":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING"); RETURN_NAMES=("prompt","preview"); FUNCTION="clean"; CATEGORY="DOGMA/v50"
    def clean(self,vlm_output):
        s=str(vlm_output or "").strip().replace("```","")
        lines=[x.strip() for x in s.splitlines() if x.strip()]
        p=""
        for x in lines:
            if x.upper().startswith("PROMPT:"):
                p=x.split(":",1)[1].strip();break
        if not p and lines:p=lines[0]
        p=re.sub(r"^(prompt|answer)\s*:\s*","",p,flags=re.I).strip(' \"\'`')
        p=re.sub(r"\s+"," ",p)
        # Avoid verbose VLM drift: keep a phrase, not a paragraph.
        words=p.split()
        if len(words)>16:p=" ".join(words[:16])
        if not p:p="existing photographic scene"
        return (p,f"ACTUAL KLEIN TILE PROMPT: {p}")


class DOGMAV50SceneInstruction:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",);RETURN_NAMES=("instruction",);FUNCTION="build";CATEGORY="DOGMA/v50"
    def build(self,project_context):
        ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()
        return (f"""Inventory the clearly visible content of this image for segmentation and local detail refinement.\nProject context: {ctx}\nReturn up to SIX distinct useful groups, one per line, exactly as:\nGROUP|category|kind|prompt\nkind must be OBJECT, STRUCTURE, or SURFACE.\nprompt must be a short 3-10 word English phrase describing that visible category in its actual relationship/context.\nExample if truly visible: GROUP|cars|OBJECT|1970s Italian cars on a road\nExample: GROUP|buildings|STRUCTURE|1970s Italian apartment buildings and balconies\nInclude small repeated cars or people if they are genuinely visible. Separate cars, bus and trucks when useful.\nUseful categories: cars, bus, trucks, people, buildings, grass, trees, road, water, animals, furniture, machinery, products, clothing, food.\nDo NOT use sky, haze, fog, text, logos, signs, brands or defects as editable groups.\nNever add an object merely because the project context suggests it. No OCR. Output GROUP lines only.""",)


def _v50_ctx_prefix(context):
    s=str(context or "").lower()
    if "1970" in s and "ital" in s:return "1970s Italian"
    if "1970" in s:return "1970s"
    return ""

class DOGMAV50ScenePlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT","STRING"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}",f"local_prompt_{i}"))
    FUNCTION="parse";CATEGORY="DOGMA/v50"

    @staticmethod
    def _canon(raw):
        s=re.sub(r"[^a-z0-9 _-]"," ",str(raw or "").lower());s=re.sub(r"\s+"," ",s).strip()
        tests=[
            ("people",("person","people","pedestrian","human","crowd")),("cars",("car","cars","automobile","sedan","hatchback","passenger vehicle")),
            ("bus",("bus","buses","coach")),("trucks",("truck","trucks","lorry","van","vans")),
            ("buildings",("building","buildings","facade","architecture","balcony","house","tower")),("grass",("grass","lawn")),
            ("trees",("tree","trees","vegetation","foliage","bush","shrub")),("road",("road","street","asphalt","pavement","sidewalk")),
            ("water",("water","sea","ocean","lake","river")),("animals",("animal","dog","cat","horse","bird")),
            ("furniture",("furniture","chair","table","sofa","couch","bed")),("machinery",("machinery","machine","equipment","tool")),
            ("products",("product","bottle","package","box")),("clothing",("clothing","clothes","garment","shirt","dress","coat","jacket")),
            ("food",("food","dish","meal","fruit","bread","cake"))]
        for c,ks in tests:
            if any(re.search(r"\b"+re.escape(k)+r"\b",s) for k in ks):return c
        return None

    @staticmethod
    def _spec(c):
        specs={
          "cars":("cars, automobiles, passenger vehicles","OBJECT",0.18),"people":("people, pedestrians, persons","OBJECT",0.18),
          "bus":("bus, buses, city buses","OBJECT",0.20),"trucks":("trucks, vans, lorries","OBJECT",0.20),
          "animals":("animals, dogs, cats, horses, birds","OBJECT",0.23),"furniture":("furniture, chairs, tables, sofas","OBJECT",0.25),
          "machinery":("machinery, machines, equipment","OBJECT",0.25),"products":("products, bottles, packages, boxes","OBJECT",0.25),
          "clothing":("clothing, garments","OBJECT",0.25),"food":("food, dishes, fruit","OBJECT",0.25),
          "buildings":("buildings, facades, architecture","STRUCTURE",0.24),"grass":("grass, lawn","SURFACE",0.22),
          "trees":("trees, vegetation, bushes","SURFACE",0.22),"road":("road, street, asphalt, pavement","SURFACE",0.22),
          "water":("water, river, sea, lake","SURFACE",0.24)}
        return specs.get(c,(c or "nonexistent_placeholder_object_xyz","OBJECT",0.35))

    @staticmethod
    def _fallback(c,ctx):
        pre=_v50_ctx_prefix(ctx)
        m={"cars":"cars on a road","people":"pedestrians in the street","bus":"city bus on a road","trucks":"trucks and vans on a road",
           "buildings":"apartment buildings and facades","grass":"grass lawn","trees":"trees and vegetation","road":"street and asphalt",
           "water":"water surface","animals":"animals","furniture":"furniture","machinery":"machinery","products":"products","clothing":"clothing","food":"food"}
        tail=m.get(c,c or "existing subject")
        return (pre+" "+tail).strip()

    def parse(self,inventory_text,project_context):
        txt=str(inventory_text or "").replace("```",""); found=[];seen=set()
        for line in txt.splitlines():
            if not line.strip().upper().startswith("GROUP|"):continue
            p=[x.strip() for x in line.split("|")]
            if len(p)<2:continue
            c=self._canon(p[1])
            if not c or c in seen:continue
            k=(p[2].upper() if len(p)>2 else self._spec(c)[1]);
            if k not in ("OBJECT","STRUCTURE","SURFACE"):k=self._spec(c)[1]
            prompt=(p[3] if len(p)>3 else "").strip(' \"\'`')
            prompt=re.sub(r"\s+"," ",prompt)
            if len(prompt.split())>16:prompt=" ".join(prompt.split()[:16])
            if not prompt:prompt=self._fallback(c,project_context)
            sam,_,thr=self._spec(c)
            found.append((c,sam,k,float(thr),prompt));seen.add(c)
        priority=["cars","people","bus","trucks","animals","machinery","furniture","products","clothing","food","buildings","grass","trees","road","water"]
        found.sort(key=lambda r: priority.index(r[0]) if r[0] in priority else 999)
        objects=[r for r in found if r[2]=="OBJECT"]; structs=[r for r in found if r[2]=="STRUCTURE"]; surfs=[r for r in found if r[2]=="SURFACE"]
        selected=objects[:4]
        if len(selected)<6:selected+=structs[:1]
        if len(selected)<6:selected+=surfs[:2]
        for r in found:
            if len(selected)>=6:break
            if r not in selected:selected.append(r)
        selected=selected[:6]
        while len(selected)<6:selected.append(("none","nonexistent_placeholder_object_xyz","OBJECT",1.0,"existing subject"))
        vals=[];prev=[]
        for i,(c,sam,k,thr,lp) in enumerate(selected,1):
            vals += [c,sam,k,float(thr),lp]
            prev.append(f"GROUP {i}: {c} [{k}] | SAM='{sam}' | threshold={thr:.2f} | KLEIN='{lp}' | "+("ACTIVE" if c!="none" else "BYPASS"))
        return ("\n".join(prev),*vals)


class DOGMAV50SAMInputGate:
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"image":("IMAGE",),"category":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");FUNCTION="gate";CATEGORY="DOGMA/v50"
    def gate(self,image,category):
        c=str(category or "none").strip().lower()
        if c in ("","none","unused"):
            return (torch.zeros((1,64,64,3),dtype=image.dtype,device=image.device),"inactive -> 64px SAM bypass")
        return (image[:1,...,:3],f"active '{c}' -> full 5K image to tiled SAM3")


class DOGMAV50RegionCrops(DOGMARegionCropsV44):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"masks":("MASK",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True}),
                            "target_long_side":("INT",{"default":2048,"min":512,"max":4096,"step":64})}}
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING");RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False);FUNCTION="make_v50";CATEGORY="DOGMA/v50"
    def make_v50(self,image,masks,category,kind,target_long_side):
        crops,cms,meta,info=super().make(image,masks,category,kind)
        target=int(target_long_side); oc=[];om=[]; active=0
        for c,m,st in zip(crops,cms,meta):
            if st is None or st.get("noop",False):
                oc.append(c);om.append(m);continue
            if c.ndim==3:c=c.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            h,w=c.shape[1:3];sc=target/float(max(h,w))
            nh=max(64,int(round((h*sc)/16.0))*16);nw=max(64,int(round((w*sc)/16.0))*16)
            # Ensure the long side is effectively the requested target after multiple rounding.
            if h>=w:nh=max(64,int(round(target/16.0))*16)
            else:nw=max(64,int(round(target/16.0))*16)
            c=F.interpolate(c[...,:3].movedim(-1,1),size=(nh,nw),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
            m=F.interpolate(m.unsqueeze(1).float(),size=(nh,nw),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)
            oc.append(c);om.append(m);active+=1
        return (oc,om,meta,f"{info} | V50 forced {active} active crop(s) to {target}px long side before Klein")



class DOGMAV52SceneInstruction:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",); RETURN_NAMES=("instruction",); FUNCTION="build"; CATEGORY="DOGMA/v53"
    def build(self,project_context):
        ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()
        return (f"""Inventory ONLY clearly visible content for exhaustive SAM segmentation and local generative restoration.
Project context: {ctx}
Return up to SIX NON-OVERLAPPING semantic families, exactly:
GROUP|category|kind
kind = OBJECT, STRUCTURE, or SURFACE.
Use these broad families:
vehicles, people, buildings, vegetation, road, water, animals, furniture, machinery, products, clothing, food.
CRITICAL RECALL RULES:
- ALL cars, buses, trucks, vans, motorcycles and bicycles belong to ONE vehicles group.
- Vehicles must be included even when tiny, partially occluded, touching, overlapping, distorted or only partly visible.
- Include the family if several small repeated instances are visible anywhere in the image; do not require a clean isolated example.
- ALL grass, lawn, trees, bushes, shrubs and foliage belong to ONE vegetation group.
- Do NOT split one semantic family into multiple groups.
- Do NOT use sky, haze, fog, text, logos, signs, brands, windows or defects as editable groups.
- Never invent a category because project context suggests it.
- No OCR.
Output GROUP lines only.""",)

class DOGMAV52ScenePlan:
    @classmethod
    def INPUT_TYPES(cls): return {"required":{"inventory_text":("STRING",{"forceInput":True,"multiline":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING",)+tuple(x for _ in range(6) for x in ("STRING","STRING","STRING","FLOAT","STRING"))
    RETURN_NAMES=("preview",)+tuple(x for i in range(1,7) for x in (f"category_{i}",f"sam_prompt_{i}",f"kind_{i}",f"threshold_{i}",f"local_prompt_{i}"))
    FUNCTION="parse"; CATEGORY="DOGMA/v52"
    @staticmethod
    def _canon(raw):
        s=re.sub(r"[^a-z0-9 _-]"," ",str(raw or "").lower()); s=re.sub(r"\s+"," ",s).strip()
        tests=[("vehicles",("vehicle","vehicles","car","cars","automobile","bus","buses","truck","trucks","van","vans","motorcycle","bicycle")),
               ("people",("person","people","pedestrian","pedestrians","human","crowd")),
               ("buildings",("building","buildings","facade","architecture","balcony","house","tower","storefront")),
               ("vegetation",("vegetation","grass","lawn","tree","trees","bush","bushes","shrub","foliage","plants")),
               ("road",("road","roads","street","streets","asphalt","pavement","sidewalk","curb","crosswalk")),
               ("water",("water","sea","ocean","lake","river")),("animals",("animal","animals","dog","cat","horse","bird")),
               ("furniture",("furniture","chair","table","sofa","couch","bed")),("machinery",("machinery","machine","equipment","tool")),
               ("products",("product","products","bottle","package","box")),("clothing",("clothing","clothes","garment","shirt","dress","coat","jacket")),
               ("food",("food","dish","meal","fruit","bread","cake"))]
        for c,ks in tests:
            if any(re.search(r"\b"+re.escape(k)+r"\b",s) for k in ks): return c
        return None
    @staticmethod
    def _spec(c):
        return {
            "buildings":("buildings, facades, architecture","STRUCTURE",0.14),
            "vegetation":("grass, lawn, trees, bushes, vegetation","SURFACE",0.12),
            "road":("road, street, asphalt, pavement, sidewalk, crosswalk","SURFACE",0.14),
            "water":("water, river, sea, lake","SURFACE",0.16),
            "machinery":("machinery, machines, equipment","OBJECT",0.16),
            "furniture":("furniture, chairs, tables, sofas","OBJECT",0.16),
            "products":("products, bottles, packages, boxes","OBJECT",0.16),
            "clothing":("clothing, garments","OBJECT",0.16),
            "food":("food, dishes, fruit","OBJECT",0.16),
            "animals":("animals, dogs, cats, horses, birds","OBJECT",0.12),
            "vehicles":("car, cars, automobile, automobiles, vehicle, vehicles, bus, buses, truck, trucks, van, vans, motorcycle, motorcycles, bicycle, bicycles","OBJECT",0.06),
            "people":("person, persons, people, pedestrian, pedestrians","OBJECT",0.08)
        }.get(c,("nonexistent_placeholder_object_xyz","OBJECT",1.0))
    @staticmethod
    def _edit(c,ctx):
        # V53: these are GENERATIVE category prompts. Spatial preservation comes from
        # the source latent + low denoise + feathered mask, not from restrictive prose.
        context=re.sub(r"\s+"," ",str(ctx or "")).strip()
        period="Milan, Italy in the 1970s" if ("1970" in context.lower() or "milan" in context.lower() or "ital" in context.lower()) else context
        m={
            "vehicles":f"Cars, buses, vans, trucks, motorcycles and bicycles on a busy street in {period}. Period-correct 1970s Italian and European vehicle design, believable wheels, windows, body proportions, traffic spacing, natural overlaps and occlusions, realistic photographic detail.",
            "people":f"Pedestrians and people in {period}, period-correct 1970s clothing, natural anatomy, poses and scale, realistic photographic detail.",
            "buildings":f"Urban apartment buildings, facades, balconies and architecture in {period}, period-correct materials and architectural detail, realistic photographic texture.",
            "vegetation":f"Grass, lawns, trees, bushes and urban vegetation in {period}, natural density, coherent foliage and realistic photographic detail.",
            "road":f"Street, asphalt, pavement, curbs and sidewalks in {period}, period-correct road surface and urban street detail, realistic photographic texture.",
            "water":f"Natural water surface in {period}, coherent reflections, waves and photographic detail.",
            "animals":f"Realistic animals in {period}, natural anatomy, pose, scale and photographic detail.",
            "furniture":f"Period-correct furniture in {period}, coherent materials, proportions and realistic photographic detail.",
            "machinery":f"Period-correct machinery and equipment in {period}, coherent mechanical structure and realistic photographic detail.",
            "products":f"Period-correct products and packaging in {period}, coherent shapes and realistic photographic detail.",
            "clothing":f"1970s clothing and garments in {period}, coherent fabric, folds, silhouettes and realistic photographic detail.",
            "food":f"Realistic food in {period}, coherent shape, texture and photographic detail."
        }
        return m.get(c,"Photorealistic period-correct local detail matching the visible scene.")
    def parse(self,inventory_text,project_context):
        seen=set(); found=[]
        for line in str(inventory_text or "").replace("```","").splitlines():
            if not line.strip().upper().startswith("GROUP|"): continue
            p=[x.strip() for x in line.split("|")]
            if len(p)<2: continue
            c=self._canon(p[1])
            if c and c not in seen: seen.add(c); found.append(c)
        coarse=["buildings","vegetation","road","water","machinery","furniture","products","clothing","food","animals"]
        selected=[c for c in coarse if c in found][:4]
        if "vehicles" in found:selected.append("vehicles")
        if "people" in found:selected.append("people")
        for c in coarse:
            if len(selected)>=6:break
            if c in found and c not in selected:
                p=max(0,len(selected)-sum(x in ("vehicles","people") for x in selected)); selected.insert(p,c)
        selected=selected[:6]
        while len(selected)<6:selected.append("none")
        vals=[];prev=[]
        for i,c in enumerate(selected,1):
            if c=="none":sam,kind,thr=("nonexistent_placeholder_object_xyz","OBJECT",1.0);edit="Preserve the reference image unchanged."
            else:sam,kind,thr=self._spec(c);edit=self._edit(c,project_context)
            vals += [c,sam,kind,float(thr),edit]
            prev.append(f"SLOT {i} TARGET: {c} [{kind}]\nSAM SEARCH: {sam}\nTHRESHOLD: {thr:.2f}\nGENERATIVE PROMPT: {edit}\n")
        return ("\n".join(prev),*vals)

class DOGMAV52MaskDeoverlap:
    @classmethod
    def INPUT_TYPES(cls):
        req={"image":("IMAGE",)}
        for i in range(1,7): req[f"mask_{i}"]=("MASK",)
        for i in range(1,7): req[f"kind_{i}"]=("STRING",{"forceInput":True})
        req["protect_px"]=("INT",{"default":6,"min":0,"max":32,"step":1})
        return {"required":req}

    RETURN_TYPES=("MASK","MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("mask_1","mask_2","mask_3","mask_4","mask_5","mask_6","info")
    FUNCTION="clean"
    CATEGORY="DOGMA/v52"

    @staticmethod
    def _safe_mask(m, H, W, device):
        # SAM may legally return an empty batch: shape [0,H,W].
        # Treat that as "nothing detected", not as an execution error.
        if m is None or not torch.is_tensor(m) or m.numel() == 0:
            return torch.zeros((1,H,W), dtype=torch.float32, device=device)

        m = m.float().to(device)

        # Normalize common ComfyUI MASK shapes:
        # [H,W] -> [1,H,W]
        # [B,H,W] -> union instances
        # [B,1,H,W] / [B,C,H,W] -> collapse channel then union instances
        if m.ndim == 2:
            m = m.unsqueeze(0)

        elif m.ndim == 3:
            if m.shape[0] == 0:
                return torch.zeros((1,H,W), dtype=torch.float32, device=device)
            m = m.amax(dim=0, keepdim=True)

        elif m.ndim == 4:
            if m.shape[0] == 0:
                return torch.zeros((1,H,W), dtype=torch.float32, device=device)
            # Collapse channels first, then instances.
            m = m.amax(dim=1)
            if m.shape[0] == 0:
                return torch.zeros((1,H,W), dtype=torch.float32, device=device)
            m = m.amax(dim=0, keepdim=True)

        else:
            # Unknown/degenerate shape: if no spatial plane can be recovered,
            # fail safe to an empty mask.
            if m.ndim < 2:
                return torch.zeros((1,H,W), dtype=torch.float32, device=device)
            m = m.reshape((-1, m.shape[-2], m.shape[-1]))
            if m.shape[0] == 0:
                return torch.zeros((1,H,W), dtype=torch.float32, device=device)
            m = m.amax(dim=0, keepdim=True)

        if m.shape[-2:] != (H,W):
            m = F.interpolate(
                m.unsqueeze(1),
                size=(H,W),
                mode="bilinear",
                align_corners=False
            ).squeeze(1)

        return m.clamp(0,1)

    def clean(self,image,mask_1,mask_2,mask_3,mask_4,mask_5,mask_6,
              kind_1,kind_2,kind_3,kind_4,kind_5,kind_6,protect_px):

        H,W=int(image.shape[1]),int(image.shape[2])
        device=image.device

        masks=[mask_1,mask_2,mask_3,mask_4,mask_5,mask_6]
        kinds=[kind_1,kind_2,kind_3,kind_4,kind_5,kind_6]

        norm=[self._safe_mask(m,H,W,device) for m in masks]

        # All OBJECT masks form a protected union.
        obj=torch.zeros((1,H,W),dtype=torch.float32,device=device)
        for m,k in zip(norm,kinds):
            if str(k).upper()=="OBJECT":
                obj=torch.maximum(obj,m)

        px=max(0,int(protect_px))
        if px>0:
            k=2*px+1
            obj=F.max_pool2d(
                obj.unsqueeze(1),
                kernel_size=k,
                stride=1,
                padding=px
            ).squeeze(1).clamp(0,1)

        cleaned=[]
        removed=[]
        empty_count=0

        for original,m,k in zip(masks,norm,kinds):
            if (original is None or not torch.is_tensor(original)
                    or original.numel()==0
                    or (original.ndim>=1 and original.shape[0]==0)):
                empty_count += 1

            if str(k).upper() in ("STRUCTURE","SURFACE"):
                c=(m*(1.0-obj)).clamp(0,1)
                removed.append(float((m-c).mean().item()))
            else:
                c=m
                removed.append(0.0)
            cleaned.append(c)

        info=(
            "V52.1 mask de-overlap | "
            f"empty SAM masks safely converted to black masks: {empty_count}/6 | "
            f"protect_px={px} | "
            f"mean_removed={[round(x,5) for x in removed]}"
        )

        return (*cleaned,info)



# =========================
# DOGMA v54 — GENERATIVE CATEGORY PROMPTS FOR SAM CHUNKS
# =========================

class DOGMAMaskAuditSheetV564:
    """Build one small contact sheet for an automatic five-category mask audit.
    This does NOT alter masks. It only visualizes the exact SAM selections for Qwen.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "mask_1":("MASK",),"mask_2":("MASK",),"mask_3":("MASK",),"mask_4":("MASK",),"mask_5":("MASK",),
            "category_1":("STRING",{"forceInput":True}),"category_2":("STRING",{"forceInput":True}),
            "category_3":("STRING",{"forceInput":True}),"category_4":("STRING",{"forceInput":True}),
            "category_5":("STRING",{"forceInput":True}),
            "panel_max_side":("INT",{"default":320,"min":192,"max":512,"step":32}),
        }}
    RETURN_TYPES=("IMAGE","STRING","STRING")
    RETURN_NAMES=("audit_sheet","audit_prompt","info")
    FUNCTION="build"
    CATEGORY="DOGMA/v56.4"

    @staticmethod
    def _union(mask,H,W):
        m=mask.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return torch.zeros((1,H,W),dtype=torch.float32)
        u=m.max(0,keepdim=True).values
        if u.shape[-2:]!=(H,W):u=F.interpolate(u.unsqueeze(1),size=(H,W),mode="bilinear",align_corners=False).squeeze(1)
        return u.clamp(0,1)

    @staticmethod
    def _resize(x,max_side):
        H,W=x.shape[1:3];sc=min(1.0,float(max_side)/float(max(H,W)));h=max(32,int(round(H*sc)));w=max(32,int(round(W*sc)))
        if (h,w)==(H,W):return x
        return F.interpolate(x.movedim(-1,1),size=(h,w),mode="bilinear",align_corners=False,antialias=True).movedim(1,-1)

    def build(self,image,mask_1,mask_2,mask_3,mask_4,mask_5,category_1,category_2,category_3,category_4,category_5,panel_max_side):
        src=image[:1,...,:3].detach().float().cpu().clamp(0,1);H,W=src.shape[1:3]
        masks=[mask_1,mask_2,mask_3,mask_4,mask_5];cats=[category_1,category_2,category_3,category_4,category_5]
        panels=[self._resize(src,int(panel_max_side))];coverage=[]
        ph,pw=panels[0].shape[1:3]
        for m in masks:
            u=self._union(m,H,W);hard=(u>=.35).float();coverage.append(float(hard.mean())*100.0)
            base=src*.20
            # bright cyan selection; unselected pixels stay dark but visible for semantic context
            cyan=torch.tensor([0.10,0.95,1.00],dtype=src.dtype).view(1,1,1,3)
            sel=hard.unsqueeze(-1)
            ov=(base*(1-sel)+(src*.32+cyan*.68)*sel).clamp(0,1)
            ov=self._resize(ov,int(panel_max_side))
            if ov.shape[1:3]!=(ph,pw):ov=F.interpolate(ov.movedim(-1,1),size=(ph,pw),mode="bilinear",align_corners=False).movedim(1,-1)
            panels.append(ov)
        gap=6;grid=torch.zeros((1,ph*2+gap,pw*3+gap*2,3),dtype=src.dtype)
        for idx,p in enumerate(panels):
            r=idx//3;c=idx%3;y=r*(ph+gap);x=c*(pw+gap);grid[:,y:y+ph,x:x+pw,:]=p
        clean_cats=[re.sub(r"\s+"," ",str(c or "none")).strip() or "none" for c in cats]
        cat_lines="\n".join("SLOT {}: {}".format(i+1,c) for i,c in enumerate(clean_cats))
        prompt=(
            "Audit this 2x3 contact sheet automatically. Panel order is row-major: ORIGINAL first, then SLOT 1, SLOT 2, SLOT 3, SLOT 4, SLOT 5. "
            "In each SLOT panel the SAM-selected pixels are bright cyan and the rest of the original image is darkened.\n\n"+cat_lines+"\n\n"
            "For each slot decide whether the cyan selection is SAFE to send to an image-restoration inpaint for that category. "
            "PASS a useful mask even if it misses some instances, has holes, imperfect edges, or the category is deliberately broad. "
            "FAIL only when there is CLEAR SUBSTANTIAL semantic contamination: a large unrelated surface/object is selected, the selection is mostly the wrong thing, or the named category is absent. "
            "Examples of FAIL: floor/pavement selected as part of a cathedral/building mask; sky selected as part of a lamp/person mask; unrelated furniture selected for books. "
            "Do NOT fail because the category could be more specific. Do NOT demand colors/styles/materials/subclasses. Tiny boundary spill is PASS. "
            "For category none, FAIL.\n\nReturn EXACTLY five lines in slot order. Each line must contain only PASS or FAIL."
        )
        info=" | ".join(f"slot{i+1} {cats[i]}={coverage[i]:.2f}%" for i in range(5))
        return (grid,prompt,info)


class DOGMAMaskAuditGateV564:
    """Automatic fail-safe. PASS preserves the original SAM tensor pixel-for-pixel.
    FAIL returns an all-zero mask so the existing crop path becomes a safe no-op.
    No morphological cleanup is done here, specifically to avoid damaging good masks.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "mask_1":("MASK",),"mask_2":("MASK",),"mask_3":("MASK",),"mask_4":("MASK",),"mask_5":("MASK",),
            "category_1":("STRING",{"forceInput":True}),"category_2":("STRING",{"forceInput":True}),
            "category_3":("STRING",{"forceInput":True}),"category_4":("STRING",{"forceInput":True}),
            "category_5":("STRING",{"forceInput":True}),
            "audit_text":("STRING",{"forceInput":True,"multiline":True}),
            "enabled":("BOOLEAN",{"default":True}),
        }}
    RETURN_TYPES=("MASK","MASK","MASK","MASK","MASK","STRING")
    RETURN_NAMES=("safe_mask_1","safe_mask_2","safe_mask_3","safe_mask_4","safe_mask_5","report")
    FUNCTION="gate"
    CATEGORY="DOGMA/v56.4"

    @staticmethod
    def _zero_like(m):
        return torch.zeros_like(m.detach().float().cpu())

    def gate(self,mask_1,mask_2,mask_3,mask_4,mask_5,category_1,category_2,category_3,category_4,category_5,audit_text,enabled):
        masks=[m.detach().float().cpu().contiguous() for m in (mask_1,mask_2,mask_3,mask_4,mask_5)]
        cats=[str(x or '').strip() for x in (category_1,category_2,category_3,category_4,category_5)]
        if not enabled:
            return (*masks,"MASK SAFETY AUDIT DISABLED — all five original masks passed unchanged.")
        decisions=[]
        for raw in str(audit_text or '').splitlines():
            u=raw.strip().upper()
            if not u:continue
            if re.search(r'\bFAIL\b|\bREJECT\b',u):decisions.append(False)
            elif re.search(r'\bPASS\b|\bACCEPT\b',u):decisions.append(True)
            if len(decisions)>=5:break
        # Formatting/model failure is fail-safe: skip rather than corrupt the image.
        while len(decisions)<5:decisions.append(False)
        out=[];report=[]
        for i,(m,c,d) in enumerate(zip(masks,cats,decisions),1):
            fam=_dogma_v16_family(c)
            if fam=='none' or c.lower() in ('none','__none__','unused','n/a',''):
                d=False;reason='unused slot'
            elif float((m>=.35).float().mean())<=0.0:
                d=False;reason='empty mask'
            else:reason='Qwen audit PASS' if d else 'Qwen audit FAIL / malformed audit'
            if d:out.append(m);report.append(f"SLOT {i} PASS — {c} — original SAM mask preserved unchanged")
            else:out.append(self._zero_like(m));report.append(f"SLOT {i} SKIP — {c or 'none'} — {reason}; zero mask prevents any inpaint")
        return (*out,"\n".join(report))


class DOGMAGenerativeCategoryPromptV54:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"category":("STRING",{"forceInput":True}),"project_context":("STRING",{"forceInput":True,"multiline":True})}}
    RETURN_TYPES=("STRING","STRING","STRING")
    RETURN_NAMES=("kind","prompt","info")
    FUNCTION="build"
    CATEGORY="DOGMA/v56.4"

    @staticmethod
    def _family(category):
        fam=_dogma_v16_family(category)
        kind={"architecture":"STRUCTURE","road":"SURFACE","vegetation":"SURFACE","water":"SURFACE","sky":"SURFACE"}.get(fam,"OBJECT")
        return fam,kind

    def build(self,category,project_context):
        fam,kind=self._family(category)
        clean=re.sub(r"\s+"," ",str(category or "object")).strip() or "object"
        ctx=re.sub(r"\s+"," ",str(project_context or "")).strip()
        context_rule=(f" Context constraint for already-visible period-sensitive details only: {ctx}" if ctx and fam in ("vehicles","people","clothing","street_objects") else "")
        if fam=="vehicles":
            body=("Refine ALL masked existing vehicles while preserving exact vehicle count, identity, body type, silhouette, color, windows, wheels, trim, lettering, position, perspective, spacing and occlusion. Repair only malformed or mushy local geometry; never invent, replace, recolor or modernize a vehicle.")
        elif fam=="people":
            body=("Refine ALL masked existing people while preserving exact count, identity cues, pose, scale, clothing colors, position and occlusion. Repair only malformed anatomy or mushy local detail; never add, remove, duplicate or relocate a person.")
        elif fam=="architecture":
            body=("Refine ONLY the existing masked architecture while preserving exact architectural identity, style, footprint, facade system, construction type, materials, window grid, balconies, roofline, perspective, color and lighting. Glass curtain-wall remains glass curtain-wall; modernist remains modernist; masonry remains masonry. Never infer style from period or location, never add floors/windows/roofs, and never redesign the building.")
        elif fam=="road":
            body=("Refine ONLY the existing masked ground/road surface while preserving exact boundaries, perspective, markings, curb geometry, material, wear, color, lighting and all existing objects crossing it. Improve texture only; never create new markings, shadows, objects or structures.")
        elif fam=="vegetation":
            body=("Refine ONLY the existing masked vegetation while preserving exact plant/foliage boundaries, positions, density, silhouette, color and lighting. Improve natural texture without inventing new plants, branches, flowers or objects.")
        elif fam=="street_objects":
            body=("Refine ONLY the existing masked street objects while preserving exact count, identity, silhouette, material, color, position, attachment points, lighting and shadows. Never add a pole, lamp, sign, shelter or street object that is not visibly present.")
        elif fam=="water":
            body=("Refine ONLY the existing masked water while preserving exact shoreline/boundaries, reflections, color, lighting and perspective. Improve surface detail without inventing objects or changing the scene geometry.")
        elif fam=="sky":
            body=("Refine ONLY visibly supported sky/cloud detail. Preserve exact sky color, gradient, haze and cloud boundaries. Never turn haze, glare, empty sky or faint patterns into buildings, poles, aircraft or other objects.")
        elif fam=="animals":
            body=("Refine ONLY the existing masked animals while preserving exact count, species/body identity, pose, silhouette, color, position and occlusion. Repair malformed detail without inventing or replacing animals.")
        elif fam=="furniture":
            body=("Refine ONLY the existing masked furniture while preserving exact count, identity, construction, material, color, position, geometry and perspective. Repair local detail without redesigning or replacing anything.")
        elif fam=="clothing":
            body=("Refine ONLY the existing masked clothing while preserving exact garment identity, cut, color, pattern, folds, position and wearer relationship. Do not replace or redesign garments.")
        elif fam=="machinery":
            body=("Refine ONLY the existing masked machinery/equipment while preserving exact identity, geometry, material, controls, color, position and perspective. Repair local detail without inventing components.")
        elif fam=="food":
            body=("Refine ONLY the existing masked food while preserving exact item count, type, shape, color, plating/container and position. Improve texture without adding ingredients or objects.")
        elif fam=="none":
            body="Preserve the image unchanged."
        else:
            body=(f"Refine ONLY the existing masked {clean}. Preserve exact count, identity, silhouette, geometry, material, color, position, scale, perspective, lighting and occlusion. Repair only visibly malformed or mushy local detail. Do not invent, replace, redesign, recolor, complete or reinterpret anything.")
        prompt=(body+context_rule).strip()
        return (kind,re.sub(r"\s+"," ",prompt),f"{clean} -> {fam} [{kind}] | generic preserve-first v56.4")


# =========================
# DOGMA v54.1 — NO-DROP INSTANCE → SPATIAL CHUNK CROPS
# =========================
class DOGMAInstanceChunkCropsV541:
    """
    Preserve SAM instance identity during grouping, but NEVER edit one instance
    at a time and NEVER discard detections.

    OBJECT categories:
      individual SAM masks -> de-duplicate -> spatial groups -> one crop/group.
      Every detected instance belongs to exactly one group.

    STRUCTURE/SURFACE categories:
      individual masks/components -> spatial groups. No fixed tile grid and no
      ownership split can cut an object/building merely to satisfy crop size.

    Large groups are resized as a whole for Klein. They are not spatially split.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "image":("IMAGE",),
            "masks":("MASK",),
            "category":("STRING",{"forceInput":True}),
            "kind":("STRING",{"forceInput":True}),
            "target_long_side":("INT",{"default":1792,"min":768,"max":2048,"step":32}),
            "group_gap_px":("INT",{"default":180,"min":0,"max":1200,"step":16}),
            "context_px":("INT",{"default":160,"min":32,"max":640,"step":16}),
            "max_objects_per_chunk":("INT",{"default":6,"min":1,"max":20,"step":1}),
            "max_chunks":("INT",{"default":24,"min":1,"max":64,"step":1}),
            "mask_threshold":("FLOAT",{"default":0.30,"min":0.05,"max":0.80,"step":0.01}),
        }}

    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="make"
    CATEGORY="DOGMA/v54"

    @staticmethod
    def _resize_image(x,h,w):
        return F.interpolate(
            x.movedim(-1,1),size=(h,w),mode="bicubic",
            align_corners=False,antialias=True
        ).movedim(1,-1).clamp(0,1)

    @staticmethod
    def _resize_mask(x,h,w):
        if x.ndim==2:x=x.unsqueeze(0)
        return F.interpolate(
            x.unsqueeze(1).float(),size=(h,w),mode="bilinear",
            align_corners=False
        ).squeeze(1).clamp(0,1)

    @staticmethod
    def _bbox(mask,thr):
        ys,xs=torch.where(mask>thr)
        if xs.numel()==0:return None
        return (int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1)

    @staticmethod
    def _gap(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b
        dx=max(0,max(ax1,bx1)-min(ax2,bx2))
        dy=max(0,max(ay1,by1)-min(ay2,by2))
        return math.sqrt(dx*dx+dy*dy)

    @staticmethod
    def _iou(a,b):
        ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b
        ix1=max(ax1,bx1);iy1=max(ay1,by1);ix2=min(ax2,bx2);iy2=min(ay2,by2)
        inter=max(0,ix2-ix1)*max(0,iy2-iy1)
        if inter<=0:return 0.0
        aa=max(1,(ax2-ax1)*(ay2-ay1));bb=max(1,(bx2-bx1)*(by2-by1))
        return inter/float(aa+bb-inter)

    @staticmethod
    def _union_bbox(a,b):
        return (min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))

    def _noop(self,src,cat):
        H,W=src.shape[1:3]
        side=min(384,H,W);x=max(0,(W-side)//2);y=max(0,(H-side)//2)
        crop=src[:,y:y+side,x:x+side,:]
        z=torch.zeros((1,side,side),dtype=torch.float32,device=src.device)
        return ([crop],[z],[{"x":x,"y":y,"width":side,"height":side,"noop":True}],
                f"{cat}: no valid SAM instance — safe no-op")

    def make(self,image,masks,category,kind,target_long_side,group_gap_px,
             context_px,max_objects_per_chunk,max_chunks,mask_threshold):
        src=image[:1,...,:3].float()
        H,W=src.shape[1:3]
        cat=_v40_canonical(category)
        k=str(kind or "OBJECT").upper()
        if cat=="none":return self._noop(src,cat)

        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return self._noop(src,cat)
        N,MH,MW=m.shape
        sx=W/float(MW);sy=H/float(MH)
        thr=float(mask_threshold)

        # One candidate per SAM mask. Keep every real detection; remove only
        # near-duplicate masks of the same instance.
        det=[]
        for mi in range(N):
            b=self._bbox(m[mi],thr)
            if b is None:continue
            x1s,y1s,x2s,y2s=b
            x1=max(0,int(math.floor(x1s*sx)));y1=max(0,int(math.floor(y1s*sy)))
            x2=min(W,int(math.ceil(x2s*sx)));y2=min(H,int(math.ceil(y2s*sy)))
            if x2-x1<3 or y2-y1<3:continue
            area=float((m[mi]>thr).sum())*sx*sy
            det.append({"mask_idx":mi,"bbox":(x1,y1,x2,y2),"area":area})

        if not det:return self._noop(src,cat)

        # De-duplicate multiple SAM masks that describe the same physical object.
        det.sort(key=lambda q:q["area"],reverse=True)
        unique=[]
        for q in det:
            if any(self._iou(q["bbox"],u["bbox"])>=0.72 for u in unique):
                continue
            unique.append(q)
        det=unique

        # Build chunks greedily by nearest spatial neighbour. No detection is dropped.
        gap=int(group_gap_px)
        max_obj=int(max_objects_per_chunk)
        if k in ("STRUCTURE","SURFACE"):
            # Broad categories are allowed larger coherent chunks.
            gap=max(gap,280 if k=="STRUCTURE" else 360)
            max_obj=max(max_obj,8)

        # Stable reading order seed makes the graph easier to inspect.
        remaining=sorted(range(len(det)),key=lambda i:(det[i]["bbox"][1],det[i]["bbox"][0]))
        groups=[]
        while remaining:
            seed=remaining.pop(0)
            members=[seed];ub=det[seed]["bbox"]
            while remaining and len(members)<max_obj:
                candidates=[]
                for ri,j in enumerate(remaining):
                    g=self._gap(ub,det[j]["bbox"])
                    candidates.append((g,ri,j))
                candidates.sort(key=lambda x:x[0])
                if not candidates or candidates[0][0]>gap:break
                _,ri,j=candidates[0]
                remaining.pop(ri)
                members.append(j)
                ub=self._union_bbox(ub,det[j]["bbox"])
            groups.append([members,ub])

        # If there are more chunks than requested, MERGE nearest chunks.
        # Nothing is ever sliced away or discarded.
        while len(groups)>int(max_chunks):
            best=None
            for i in range(len(groups)):
                for j in range(i+1,len(groups)):
                    g=self._gap(groups[i][1],groups[j][1])
                    if best is None or g<best[0]:best=(g,i,j)
            _,i,j=best
            members=groups[i][0]+groups[j][0]
            ub=self._union_bbox(groups[i][1],groups[j][1])
            groups=[g for z,g in enumerate(groups) if z not in (i,j)]
            groups.append([members,ub])

        groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))
        crops=[];cms=[];meta=[]
        ctx=int(context_px);target=int(target_long_side)

        for gid,(members,ub) in enumerate(groups):
            x1,y1,x2,y2=ub
            cx1=max(0,x1-ctx);cy1=max(0,y1-ctx)
            cx2=min(W,x2+ctx);cy2=min(H,y2+ctx)

            # 16px spatial alignment only expands crop edges; it never cuts masks.
            cx1=(cx1//16)*16;cy1=(cy1//16)*16
            cx2=min(W,int(math.ceil(cx2/16.0))*16)
            cy2=min(H,int(math.ceil(cy2/16.0))*16)

            crop=src[:,cy1:cy2,cx1:cx2,:]
            ch,cw=crop.shape[1:3]
            local=torch.zeros((1,ch,cw),dtype=torch.float32)

            for di in members:
                mi=det[di]["mask_idx"]
                full=self._resize_mask(m[mi:mi+1],H,W)
                local=torch.maximum(local,full[:,cy1:cy2,cx1:cx2])

            # Resize the WHOLE chunk if necessary. Never split an instance/group.
            if max(ch,cw)!=target:
                scale=target/float(max(ch,cw))
                nh=max(64,int(round(ch*scale/16.0))*16)
                nw=max(64,int(round(cw*scale/16.0))*16)
                crop=self._resize_image(crop,nh,nw)
                local=self._resize_mask(local,nh,nw)

            crops.append(crop)
            cms.append(local.clamp(0,1))
            meta.append({
                "x":int(cx1),"y":int(cy1),
                "width":int(cx2-cx1),"height":int(cy2-cy1),
                "source_width":int(W),"source_height":int(H),
                "noop":False,"group_id":int(gid),
                "members":int(len(members)),
            })

        counts=", ".join(str(len(g[0])) for g in groups)
        info=(f"{cat} [{k}]: {len(det)} unique SAM instance(s) -> {len(groups)} spatial chunk(s) "
              f"[members/chunk: {counts}]. 0 detections dropped; 0 instances spatially split; "
              f"whole chunks resized to {target}px long side.")
        return (crops,cms,meta,info)



# =========================
# DOGMA v54.2 — NATIVE-HD CHUNKS + OPAQUE MASK CORE + TIGHT FEATHER
# =========================
class DOGMAInstanceChunkCropsV542(DOGMAInstanceChunkCropsV541):
    """
    v54.2 geometry policy:
    - keep the proven v54.1 SAM instance grouping unchanged;
    - small chunks may still be enlarged aggressively to target_long_side;
    - chunks already larger than target_long_side are NEVER downsampled;
      they remain at the post-Stage-2 native resolution;
    - native chunks are padded only to /16 for Flux/VAE compatibility;
      padding is removed again before stitching.
    """
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="make"
    CATEGORY="DOGMA/v54.2"

    @staticmethod
    def _pad16_image_mask(crop, mask):
        h,w=crop.shape[1:3]
        ph=(16-(h%16))%16
        pw=(16-(w%16))%16
        if ph==0 and pw==0:
            return crop,mask,0,0
        chw=crop.movedim(-1,1)
        # Replicate real edge pixels only for model padding; these padded pixels
        # are stripped before compositing back into the master.
        chw=F.pad(chw,(0,pw,0,ph),mode="replicate")
        crop=chw.movedim(1,-1)
        mm=mask.unsqueeze(1).float()
        mm=F.pad(mm,(0,pw,0,ph),mode="constant",value=0.0).squeeze(1)
        return crop,mm,pw,ph

    def make(self,image,masks,category,kind,target_long_side,group_gap_px,
             context_px,max_objects_per_chunk,max_chunks,mask_threshold):
        src=image[:1,...,:3].float()
        H,W=src.shape[1:3]
        cat=_v40_canonical(category)
        k=str(kind or "OBJECT").upper()
        if cat=="none":
            return self._noop(src,cat)

        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:
            return self._noop(src,cat)
        N,MH,MW=m.shape
        sx=W/float(MW); sy=H/float(MH)
        thr=float(mask_threshold)

        det=[]
        for mi in range(N):
            b=self._bbox(m[mi],thr)
            if b is None: continue
            x1s,y1s,x2s,y2s=b
            x1=max(0,int(math.floor(x1s*sx))); y1=max(0,int(math.floor(y1s*sy)))
            x2=min(W,int(math.ceil(x2s*sx))); y2=min(H,int(math.ceil(y2s*sy)))
            if x2-x1<3 or y2-y1<3: continue
            area=float((m[mi]>thr).sum())*sx*sy
            det.append({"mask_idx":mi,"bbox":(x1,y1,x2,y2),"area":area})
        if not det:
            return self._noop(src,cat)

        det.sort(key=lambda q:q["area"],reverse=True)
        unique=[]
        for q in det:
            if any(self._iou(q["bbox"],u["bbox"])>=0.72 for u in unique):
                continue
            unique.append(q)
        det=unique

        gap=int(group_gap_px)
        max_obj=int(max_objects_per_chunk)
        if k=="STRUCTURE":
            gap=max(gap,220)
            max_obj=min(max_obj,3)
        elif k=="SURFACE":
            gap=max(gap,300)
            max_obj=min(max_obj,6)

        remaining=sorted(range(len(det)),key=lambda i:(det[i]["bbox"][1],det[i]["bbox"][0]))
        groups=[]
        while remaining:
            seed=remaining.pop(0)
            members=[seed]; ub=det[seed]["bbox"]
            while remaining and len(members)<max_obj:
                candidates=[]
                for ri,j in enumerate(remaining):
                    g=self._gap(ub,det[j]["bbox"])
                    candidates.append((g,ri,j))
                candidates.sort(key=lambda x:x[0])
                if not candidates or candidates[0][0]>gap: break
                _,ri,j=candidates[0]
                remaining.pop(ri); members.append(j)
                ub=self._union_bbox(ub,det[j]["bbox"])
            groups.append([members,ub])

        while len(groups)>int(max_chunks):
            best=None
            for i in range(len(groups)):
                for j in range(i+1,len(groups)):
                    g=self._gap(groups[i][1],groups[j][1])
                    if best is None or g<best[0]: best=(g,i,j)
            _,i,j=best
            members=groups[i][0]+groups[j][0]
            ub=self._union_bbox(groups[i][1],groups[j][1])
            groups=[g for z,g in enumerate(groups) if z not in (i,j)]
            groups.append([members,ub])

        groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))
        crops=[]; cms=[]; meta=[]
        ctx=int(context_px); target=int(target_long_side)
        native_count=0; upscaled_count=0

        for gid,(members,ub) in enumerate(groups):
            x1,y1,x2,y2=ub
            cx1=max(0,x1-ctx); cy1=max(0,y1-ctx)
            cx2=min(W,x2+ctx); cy2=min(H,y2+ctx)

            cx1=(cx1//16)*16; cy1=(cy1//16)*16
            cx2=min(W,int(math.ceil(cx2/16.0))*16)
            cy2=min(H,int(math.ceil(cy2/16.0))*16)

            crop=src[:,cy1:cy2,cx1:cx2,:]
            ch,cw=crop.shape[1:3]
            local=torch.zeros((1,ch,cw),dtype=torch.float32)

            for di in members:
                mi=det[di]["mask_idx"]
                full=self._resize_mask(m[mi:mi+1],H,W)
                local=torch.maximum(local,full[:,cy1:cy2,cx1:cx2])

            original_ch, original_cw = ch, cw
            model_mode="native"

            # v54.4: keep aggressive enlargement for small post-Stage-2 chunks,
            # but never allow one giant facade/surface group to become a 4K-5K
            # diffusion latent and OOM the 5090. The WHOLE group is resized as one
            # coherent image; it is never spatially cut. Objects retain a higher cap.
            cap = 2304 if k=="OBJECT" else 2048
            long_side=max(ch,cw)
            if long_side<target:
                scale=target/float(long_side)
                nh=max(64,int(round(ch*scale/16.0))*16)
                nw=max(64,int(round(cw*scale/16.0))*16)
                crop=self._resize_image(crop,nh,nw)
                local=self._resize_mask(local,nh,nw)
                pad_right=pad_bottom=0
                model_mode="upscaled"
                upscaled_count+=1
            elif long_side>cap:
                scale=cap/float(long_side)
                nh=max(64,int(round(ch*scale/16.0))*16)
                nw=max(64,int(round(cw*scale/16.0))*16)
                crop=self._resize_image(crop,nh,nw)
                local=self._resize_mask(local,nh,nw)
                pad_right=pad_bottom=0
                model_mode="capped_whole_chunk"
            else:
                crop,local,pad_right,pad_bottom=self._pad16_image_mask(crop,local)
                native_count+=1

            crops.append(crop)
            cms.append(local.clamp(0,1))
            meta.append({
                "x":int(cx1),"y":int(cy1),
                "width":int(cx2-cx1),"height":int(cy2-cy1),
                "source_width":int(W),"source_height":int(H),
                "noop":False,"group_id":int(gid),
                "members":int(len(members)),
                "model_mode":model_mode,
                "content_width":int(crop.shape[2]-pad_right),
                "content_height":int(crop.shape[1]-pad_bottom),
                "pad_right":int(pad_right),
                "pad_bottom":int(pad_bottom),
                "original_chunk_width":int(original_cw),
                "original_chunk_height":int(original_ch),
            })

        counts=", ".join(str(len(g[0])) for g in groups)
        info=(f"{cat} [{k}]: {len(det)} unique SAM instance(s) -> {len(groups)} spatial chunk(s) "
              f"[members/chunk: {counts}]. 0 detections dropped; 0 instances split. "
              f"{upscaled_count} small chunk(s) enlarged to >= {target}px; "
              f"{native_count} chunk(s) stayed native; oversized whole chunks use 2304px OBJECT / 2048px STRUCTURE-SURFACE cap for VRAM safety.")
        return (crops,cms,meta,info)


class DOGMAMaskedLatentV542:
    """
    v54.2 generation mask:
    preserve a fully opaque semantic core so denoise=0.30 is actually applied
    uniformly inside the selected object, with only a short outward feather.
    This avoids the old fractional mask across the entire car/person that could
    create soft, half-regenerated detail.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"latent":("LATENT",),"mask":("MASK",)}}
    RETURN_TYPES=("LATENT","STRING")
    RETURN_NAMES=("latent","info")
    FUNCTION="apply"
    CATEGORY="DOGMA/v54.2"

    @staticmethod
    def _dilate(x,r):
        if r<=0:return x
        return F.max_pool2d(x,2*r+1,1,r)

    def apply(self,latent,mask):
        out=latent.copy()
        m=mask
        if m.ndim==2:m=m.unsqueeze(0)
        m=m.float().clamp(0,1).unsqueeze(1)

        # SAM soft edge -> stable hard semantic body.
        core=(m>=0.20).float()
        # Give Klein a little room to correct wheels/body edges/occlusion.
        core=self._dilate(core,8).clamp(0,1)
        # Short feather OUTSIDE the core, but never make the semantic body translucent.
        soft=F.avg_pool2d(core,kernel_size=17,stride=1,padding=8).clamp(0,1)
        gen=torch.maximum(core,soft*0.85).clamp(0,1)
        out["noise_mask"]=gen
        cov=float((gen>0.10).float().mean())*100.0
        return (out,f"v54.2 opaque generation core +8 / outward feather 8 | coverage={cov:.2f}%")


class DOGMARegionStitchV542:
    """
    v54.2 high-definition stitch:
    - strips model-only /16 padding;
    - avoids any resample when the chunk ran at native post-Stage-2 resolution;
    - uses a fully opaque slightly-expanded semantic core;
    - feathers only a few final/master pixels OUTSIDE that core.
    No broad translucent blend, so no double-image halo and no low-definition
    'pasted patch' surrounding an otherwise good vehicle.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "base_image":("IMAGE",),
            "patches":("IMAGE",),
            "masks":("MASK",),
            "stitch":("DOGMA_STITCH",),
            "category":("STRING",{"forceInput":True}),
            "kind":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    INPUT_IS_LIST=True
    FUNCTION="stitch_regions"
    CATEGORY="DOGMA/v54.2"

    @staticmethod
    def _dilate(x,r):
        if r<=0:return x
        return F.max_pool2d(x,2*r+1,1,r)

    def stitch_regions(self,base_image,patches,masks,stitch,category,kind):
        base=base_image[0] if isinstance(base_image,list) else base_image
        result=base.clone()[...,:3]
        dev=result.device
        cat=_v43_canonical(category[0] if isinstance(category,list) and category else category)
        k=str(kind[0] if isinstance(kind,list) and kind else kind).upper()
        used=0; native=0; resized=0

        # Final/master-pixel policy. Objects need enough opaque expansion to
        # avoid clipping a corrected silhouette, but only a narrow feather.
        if k=="SURFACE":
            threshold=0.34; grow=1; feather=10
        elif k=="STRUCTURE":
            threshold=0.28; grow=2; feather=8
        else:
            threshold=0.20; grow=3; feather=6

        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if not meta or meta.get("noop",False): continue
            p=patches[i]; m=masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev)[...,:3].float()
            m=m.to(dev).float()
            x=int(meta["x"]); y=int(meta["y"])
            w=int(meta["width"]); h=int(meta["height"])
            if w<=0 or h<=0: continue

            # Remove only model padding. Never include replicated pad pixels.
            pr=int(meta.get("pad_right",0)); pb=int(meta.get("pad_bottom",0))
            if pr>0:
                p=p[:,:,:max(1,p.shape[2]-pr),:]
                m=m[:,:,:max(1,m.shape[2]-pr)]
            if pb>0:
                p=p[:,:max(1,p.shape[1]-pb),:,:]
                m=m[:,:max(1,m.shape[1]-pb),:]

            # Native chunks are already exactly the master crop size: do not
            # interpolate them a second time. Small chunks were intentionally
            # enlarged for Klein, so only those are reduced back here.
            if int(p.shape[1])==h and int(p.shape[2])==w:
                native+=1
            else:
                p=F.interpolate(
                    p.movedim(-1,1),size=(h,w),mode="bicubic",
                    align_corners=False,antialias=True
                ).movedim(1,-1).clamp(0,1)
                resized+=1

            if int(m.shape[1])!=h or int(m.shape[2])!=w:
                m=F.interpolate(
                    m.unsqueeze(1),size=(h,w),mode="bilinear",
                    align_corners=False
                ).squeeze(1).clamp(0,1)

            # Final semantic shape is rebuilt at FINAL resolution.
            core=(m.unsqueeze(1)>=threshold).float()
            core=self._dilate(core,grow).clamp(0,1)

            # Short OUTWARD transition. max(core, ...) guarantees every pixel
            # inside the selected body is 100% generated, never a blurry 50/50 mix.
            if feather>0:
                soft=F.avg_pool2d(core,2*feather+1,1,feather).clamp(0,1)
                alpha=torch.maximum(core,soft*0.90)
            else:
                alpha=core
            alpha=alpha.squeeze(1).unsqueeze(-1).clamp(0,1)

            reg=result[:,y:y+h,x:x+w,:]
            result[:,y:y+h,x:x+w,:]=(reg*(1-alpha)+p*alpha).clamp(0,1)
            used+=1

        return (result,
                f"v54.2 HD stitch | {cat} [{k}] | {used} region(s) | "
                f"opaque core grow {grow}px / feather {feather}px | "
                f"{native} native no-resample, {resized} enlarged-small chunks reduced back")



# =========================
# DOGMA v54.3 — TRUE INPAINT MASK + EXACT INWARD STITCH
# =========================
class DOGMAInpaintMaskV543:
    """v54.4.1 fast generation mask.
    Keeps the v54.4 behavior, but removes the pathological huge 2-D max-pool.
    Large structure/surface closing is done on a temporary binary workspace,
    while the untouched full-resolution SAM mask is always preserved.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"mask":("MASK",),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("MASK","IMAGE","STRING")
    RETURN_NAMES=("mask","mask_image","info")
    FUNCTION="build"
    CATEGORY="DOGMA/v54.4.1"

    @staticmethod
    def _dilate_sep(x,r):
        if r<=0:return x
        k=2*r+1
        x=F.max_pool2d(x,(1,k),(1,1),(0,r))
        x=F.max_pool2d(x,(k,1),(1,1),(r,0))
        return x

    @classmethod
    def _erode_sep(cls,x,r):
        if r<=0:return x
        return 1.0-cls._dilate_sep(1.0-x,r)

    @classmethod
    def _closing_fast(cls,raw,r,max_work_side):
        if r<=0:return raw
        H,W=int(raw.shape[-2]),int(raw.shape[-1])
        longest=max(H,W)
        if longest<=max_work_side:
            return cls._erode_sep(cls._dilate_sep(raw,r),r).clamp(0,1)

        scale=float(max_work_side)/float(longest)
        h=max(32,int(round(H*scale)))
        w=max(32,int(round(W*scale)))
        small=F.interpolate(raw,size=(h,w),mode="nearest")
        rs=max(1,int(round(r*scale)))
        small=cls._erode_sep(cls._dilate_sep(small,rs),rs).clamp(0,1)
        filled=F.interpolate(small,size=(H,W),mode="nearest")

        # Important: low-res morphology only ADDS fills/joins.
        # It never replaces the original full-resolution SAM boundary.
        return torch.maximum(raw,filled).clamp(0,1)

    def build(self,mask,kind):
        m=mask
        if m.ndim==2:m=m.unsqueeze(0)
        m=m.float().clamp(0,1).unsqueeze(1)
        k=str(kind[0] if isinstance(kind,list) and kind else kind).upper()
        H,W=int(m.shape[-2]),int(m.shape[-1])
        short=max(1,min(H,W))

        if k=="STRUCTURE":
            threshold=0.20
            close=max(16,min(72,int(round(short*0.040))))
            grow=max(6,min(18,int(round(short*0.008))))
            work_side=768
        elif k=="SURFACE":
            threshold=0.28
            close=max(8,min(40,int(round(short*0.020))))
            grow=max(4,min(12,int(round(short*0.006))))
            work_side=896
        else:
            threshold=0.18
            close=3
            grow=6
            work_side=0

        raw=(m>=threshold).float()
        before=float(raw.mean())*100.0

        if k in ("STRUCTURE","SURFACE"):
            core=self._closing_fast(raw,close,work_side)
        else:
            core=self._erode_sep(self._dilate_sep(raw,close),close).clamp(0,1)

        # Final grow remains full-resolution but is now separable and fast.
        core=self._dilate_sep(core,grow).clamp(0,1)
        gen=(core>=0.5).float()
        after=float(gen.mean())*100.0
        img=gen.squeeze(1).unsqueeze(-1).repeat(1,1,1,3)

        return (gen.squeeze(1),img,
                f"v54.4.1 FAST HARD mask [{k}] | threshold {threshold:.2f} | "
                f"close {close}px @ max-side {work_side if work_side else 'native'} | "
                f"grow {grow}px native | coverage {before:.2f}% -> {after:.2f}%")


class DOGMARegionStitchV543:
    """v54.4 final composite.
    The model is allowed to generate through the wider hard inpaint mask, while
    the master receives a tighter mask whose feather lives entirely INSIDE the
    generated area. Alpha is exactly zero outside the generation mask.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{
            "base_image":("IMAGE",),"patches":("IMAGE",),"masks":("MASK",),
            "stitch":("DOGMA_STITCH",),"category":("STRING",{"forceInput":True}),
            "kind":("STRING",{"forceInput":True}),
        }}
    RETURN_TYPES=("IMAGE","STRING")
    RETURN_NAMES=("image","info")
    INPUT_IS_LIST=True
    FUNCTION="stitch_regions"
    CATEGORY="DOGMA/v54.4"

    @staticmethod
    def _erode(x,r):
        if r<=0:return x
        return 1.0-F.max_pool2d(1.0-x,2*r+1,1,r)

    def stitch_regions(self,base_image,patches,masks,stitch,category,kind):
        base=base_image[0] if isinstance(base_image,list) else base_image
        result=base.clone()[...,:3]
        dev=result.device
        cat=_v43_canonical(category[0] if isinstance(category,list) and category else category)
        k=str(kind[0] if isinstance(kind,list) and kind else kind).upper()
        feather=10 if k in ("STRUCTURE","SURFACE") else 5
        used=native=resized=0

        for i in range(min(len(patches),len(masks),len(stitch))):
            meta=stitch[i]
            if not meta or meta.get("noop",False): continue
            p=patches[i]; m=masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if m.ndim==2:m=m.unsqueeze(0)
            p=p.to(dev)[...,:3].float(); m=m.to(dev).float().clamp(0,1)
            x=int(meta["x"]); y=int(meta["y"]); w=int(meta["width"]); h=int(meta["height"])
            if w<=0 or h<=0: continue

            pr=int(meta.get("pad_right",0)); pb=int(meta.get("pad_bottom",0))
            if pr>0:
                p=p[:,:,:max(1,p.shape[2]-pr),:]; m=m[:,:,:max(1,m.shape[2]-pr)]
            if pb>0:
                p=p[:,:max(1,p.shape[1]-pb),:,:]; m=m[:,:max(1,m.shape[1]-pb)]

            if int(p.shape[1])==h and int(p.shape[2])==w:
                native+=1
            else:
                p=F.interpolate(p.movedim(-1,1),size=(h,w),mode="bicubic",align_corners=False,antialias=True).movedim(1,-1).clamp(0,1)
                resized+=1
            if int(m.shape[1])!=h or int(m.shape[2])!=w:
                m=F.interpolate(m.unsqueeze(1),size=(h,w),mode="bilinear",align_corners=False).squeeze(1).clamp(0,1)

            gen=(m.unsqueeze(1)>=0.50).float()
            # Erode first, then blur the INNER core back toward the generation edge.
            # This creates a 1->0 ramp entirely inside pixels that Klein actually generated.
            inner=self._erode(gen,feather).clamp(0,1)
            if feather>0:
                soft=F.avg_pool2d(inner,2*feather+1,1,feather).clamp(0,1)
                alpha=torch.maximum(inner,soft*gen).clamp(0,1)
            else:
                alpha=gen
            alpha=alpha.squeeze(1).unsqueeze(-1)

            reg=result[:,y:y+h,x:x+w,:]
            result[:,y:y+h,x:x+w,:]=(reg*(1-alpha)+p*alpha).clamp(0,1)
            used+=1

        return (result,
                f"v54.4.1 DIRECT-INPAINT stitch | {cat} [{k}] | {used} region(s) | feather entirely inside generated mask {feather}px | alpha=0 outside | {native} native, {resized} resized-back")




# =========================
# DOGMA v54.5 — HI-RES CHUNKS / DUAL MASK / TILED TRUE INPAINT / SOFT STITCH
# =========================
class DOGMAInstanceChunkCropsV545(DOGMAInstanceChunkCropsV542):
    """High-resolution spatial grouping.
    The important rule is: constrain GROUP SIZE before cropping instead of
    creating a huge group and then downscaling it. No multi-instance chunk is
    ever reduced below its native post-upscale resolution.
    """
    RETURN_TYPES=("IMAGE","MASK","DOGMA_STITCH","STRING")
    RETURN_NAMES=("crops","crop_masks","stitch","info")
    OUTPUT_IS_LIST=(True,True,True,False)
    FUNCTION="make"
    CATEGORY="DOGMA/v54.5"

    @staticmethod
    def _resize_image_lanczos(x,h,w):
        chw=x.movedim(-1,1)
        try:
            out=comfy.utils.common_upscale(chw,int(w),int(h),"lanczos","disabled")
        except Exception:
            out=F.interpolate(chw,size=(int(h),int(w)),mode="bicubic",align_corners=False)
        return out.movedim(1,-1).clamp(0,1)

    @staticmethod
    def _expanded_size(b,H,W,ctx):
        x1,y1,x2,y2=b
        cx1=max(0,x1-ctx); cy1=max(0,y1-ctx)
        cx2=min(W,x2+ctx); cy2=min(H,y2+ctx)
        return max(1,cx2-cx1),max(1,cy2-cy1)

    def make(self,image,masks,category,kind,target_long_side,group_gap_px,
             context_px,max_objects_per_chunk,max_chunks,mask_threshold):
        src=image[:1,...,:3].float(); H,W=src.shape[1:3]
        cat=_v40_canonical(category); k=str(kind or "OBJECT").upper()
        if cat=="none": return self._noop(src,cat)

        m=masks.detach().float().cpu()
        if m.ndim==2:m=m.unsqueeze(0)
        if m.numel()==0 or int(m.shape[0])==0:return self._noop(src,cat)
        N,MH,MW=m.shape; sx=W/float(MW); sy=H/float(MH); thr=float(mask_threshold)

        det=[]
        for mi in range(N):
            b=self._bbox(m[mi],thr)
            if b is None:continue
            x1s,y1s,x2s,y2s=b
            x1=max(0,int(math.floor(x1s*sx))); y1=max(0,int(math.floor(y1s*sy)))
            x2=min(W,int(math.ceil(x2s*sx))); y2=min(H,int(math.ceil(y2s*sy)))
            if x2-x1<3 or y2-y1<3:continue
            area=float((m[mi]>thr).sum())*sx*sy
            det.append({"mask_idx":mi,"bbox":(x1,y1,x2,y2),"area":area})
        if not det:return self._noop(src,cat)

        det.sort(key=lambda q:q["area"],reverse=True)
        unique=[]
        for q in det:
            if any(self._iou(q["bbox"],u["bbox"])>=0.72 for u in unique):continue
            unique.append(q)
        det=unique

        target=max(768,int(target_long_side)); ctx=int(context_px); gap=int(group_gap_px)
        max_obj=max(1,int(max_objects_per_chunk))
        if k=="STRUCTURE":
            gap=max(gap,220); max_obj=min(max_obj,3); group_long=max(2560,int(round(target*1.36))); group_area=6_800_000
        elif k=="SURFACE":
            gap=max(gap,300); max_obj=min(max_obj,6); group_long=max(2432,int(round(target*1.30))); group_area=6_200_000
        else:
            group_long=max(2304,int(round(target*1.25))); group_area=5_800_000

        remaining=sorted(range(len(det)),key=lambda i:(det[i]["bbox"][1],det[i]["bbox"][0]))
        groups=[]
        while remaining:
            seed=remaining.pop(0); members=[seed]; ub=det[seed]["bbox"]
            while remaining and len(members)<max_obj:
                cand=[]
                for ri,j in enumerate(remaining):
                    g=self._gap(ub,det[j]["bbox"])
                    if g<=gap: cand.append((g,ri,j))
                cand.sort(key=lambda z:z[0])
                chosen=None
                for g,ri,j in cand:
                    tub=self._union_bbox(ub,det[j]["bbox"])
                    tw,th=self._expanded_size(tub,H,W,ctx)
                    if max(tw,th)<=group_long and tw*th<=group_area:
                        chosen=(ri,j,tub); break
                if chosen is None:break
                ri,j,ub=chosen; remaining.pop(ri); members.append(j)
            groups.append([members,ub])

        # max_chunks is a SOFT cap. Merge only when the merged crop still fits
        # the native-resolution budget. Never force a huge low-res mega-patch.
        soft_cap=int(max_chunks)
        while len(groups)>soft_cap:
            best=None
            for i in range(len(groups)):
                for j in range(i+1,len(groups)):
                    tub=self._union_bbox(groups[i][1],groups[j][1])
                    tw,th=self._expanded_size(tub,H,W,ctx)
                    if max(tw,th)>group_long or tw*th>group_area:continue
                    g=self._gap(groups[i][1],groups[j][1])
                    if best is None or g<best[0]:best=(g,i,j,tub)
            if best is None:break
            _,i,j,tub=best
            mem=groups[i][0]+groups[j][0]
            groups=[g for z,g in enumerate(groups) if z not in (i,j)]
            groups.append([mem,tub])

        groups.sort(key=lambda gb:(gb[1][1],gb[1][0]))
        crops=[];cms=[];meta=[];up=0;native=0;oversize_single=0
        for gid,(members,ub) in enumerate(groups):
            x1,y1,x2,y2=ub
            cx1=max(0,x1-ctx);cy1=max(0,y1-ctx);cx2=min(W,x2+ctx);cy2=min(H,y2+ctx)
            cx1=(cx1//16)*16;cy1=(cy1//16)*16
            cx2=min(W,int(math.ceil(cx2/16.0))*16);cy2=min(H,int(math.ceil(cy2/16.0))*16)
            crop=src[:,cy1:cy2,cx1:cx2,:]; ch,cw=crop.shape[1:3]
            local=torch.zeros((1,ch,cw),dtype=torch.float32)
            for di in members:
                mi=det[di]["mask_idx"]
                full=self._resize_mask(m[mi:mi+1],H,W)
                local=torch.maximum(local,full[:,cy1:cy2,cx1:cx2])

            orig_h,orig_w=ch,cw; mode="native"
            if max(ch,cw)<target:
                scale=target/float(max(ch,cw)); nh=max(64,int(round(ch*scale/16.0))*16); nw=max(64,int(round(cw*scale/16.0))*16)
                crop=self._resize_image_lanczos(crop,nh,nw); local=self._resize_mask(local,nh,nw)
                pr=pb=0; mode="upscaled_to_min"; up+=1
            else:
                crop,local,pr,pb=self._pad16_image_mask(crop,local); native+=1
                if max(orig_h,orig_w)>group_long:oversize_single+=1

            crops.append(crop);cms.append(local.clamp(0,1))
            meta.append({"x":int(cx1),"y":int(cy1),"width":int(cx2-cx1),"height":int(cy2-cy1),
                         "source_width":int(W),"source_height":int(H),"noop":False,"group_id":int(gid),
                         "members":int(len(members)),"model_mode":mode,"pad_right":int(pr),"pad_bottom":int(pb),
                         "original_chunk_width":int(orig_w),"original_chunk_height":int(orig_h)})

        counts=", ".join(str(len(g[0])) for g in groups)
        extra=(f" soft max_chunks={soft_cap} exceeded to preserve native resolution;" if len(groups)>soft_cap else "")
        warn=(f" {oversize_single} single-instance native crop(s) exceed grouping budget; kept native, never downscaled." if oversize_single else "")
        info=(f"v54.5 {cat} [{k}]: {len(det)} unique SAM instance(s) -> {len(groups)} hi-res chunk(s) [{counts}]. "
              f"0 detections dropped; multi-instance groups constrained to <=~{group_long}px / {group_area/1e6:.1f}MP before cropping; "
              f"{up} small chunk(s) Lanczos-upscaled to >= {target}px; {native} chunk(s) native; NO large chunk downscale.{extra}{warn}")
        return (crops,cms,meta,info)


class DOGMADualMaskV545:
    """v56.4: wide generation support + exact semantic ownership seed.
    The inpaint mask may extend outside the SAM mask to give diffusion context.
    The FINAL blend seed never grows outside the cleaned semantic mask.
    """
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"mask":("MASK",),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("MASK","MASK","IMAGE","IMAGE","STRING")
    RETURN_NAMES=("inpaint_mask","blend_mask","inpaint_preview","blend_preview","info")
    FUNCTION="build";CATEGORY="DOGMA/v56.4"
    @staticmethod
    def _dilate(x,r):
        if r<=0:return x
        k=2*r+1;x=F.max_pool2d(x,(1,k),(1,1),(0,r));x=F.max_pool2d(x,(k,1),(1,1),(r,0));return x
    @classmethod
    def _erode(cls,x,r):
        if r<=0:return x
        return 1.0-cls._dilate(1.0-x,r)
    @classmethod
    def _close_fast(cls,raw,r,max_side=896):
        if r<=0:return raw
        H,W=raw.shape[-2:];longest=max(H,W)
        if longest<=max_side:return cls._erode(cls._dilate(raw,r),r).clamp(0,1)
        sc=max_side/float(longest);h=max(32,int(round(H*sc)));w=max(32,int(round(W*sc)))
        sm=F.interpolate(raw,size=(h,w),mode="nearest");rr=max(1,int(round(r*sc)))
        sm=cls._erode(cls._dilate(sm,rr),rr).clamp(0,1);fill=F.interpolate(sm,size=(H,W),mode="nearest")
        return torch.maximum(raw,fill).clamp(0,1)
    def build(self,mask,kind):
        m=mask
        if m.ndim==2:m=m.unsqueeze(0)
        m=m.float().clamp(0,1).unsqueeze(1);k=str(kind[0] if isinstance(kind,list) and kind else kind).upper();H,W=m.shape[-2:];short=max(1,min(H,W))
        if k=="STRUCTURE":thr=.22;close=max(6,min(28,int(round(short*.010))));gen_grow=max(48,min(128,int(round(short*.045))))
        elif k=="SURFACE":thr=.28;close=max(4,min(20,int(round(short*.008))));gen_grow=max(40,min(112,int(round(short*.040))))
        else:thr=.18;close=2;gen_grow=max(36,min(96,int(round(short*.040))))
        raw=(m>=thr).float();core=self._close_fast(raw,close).clamp(0,1)
        blend=(core>=.5).float()  # NO outward blend growth
        inp=(self._dilate(core,gen_grow)>=.5).float()
        pin=inp.squeeze(1).unsqueeze(-1).repeat(1,1,1,3);pbl=blend.squeeze(1).unsqueeze(-1).repeat(1,1,1,3)
        return (inp.squeeze(1),blend.squeeze(1),pin,pbl,f"v56.4 DUAL MASK [{k}] | thr {thr:.2f} | close {close}px | wide inpaint +{gen_grow}px | FINAL blend seed = semantic mask (no outward growth)")


class DOGMATiledInpaintConditioningV545:
    """ComfyUI InpaintModelConditioning semantics with VRAM-safe tiled VAE encode
    for large native crops. Resolution is unchanged; only VAE execution is tiled.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"positive":("CONDITIONING",),"negative":("CONDITIONING",),"vae":("VAE",),
                            "pixels":("IMAGE",),"mask":("MASK",),
                            "noise_mask":("BOOLEAN",{"default":True}),
                            "tile_size":("INT",{"default":3136,"min":512,"max":4096,"step":64}),
                            "overlap":("INT",{"default":128,"min":64,"max":512,"step":32})}}
    RETURN_TYPES=("CONDITIONING","CONDITIONING","LATENT")
    RETURN_NAMES=("positive","negative","latent")
    FUNCTION="encode"
    CATEGORY="DOGMA/v54.5"

    @staticmethod
    def _enc(vae,pix,tile,overlap):
        H,W=pix.shape[1:3]
        if max(H,W)<=1792 and H*W<=3_200_000:
            return vae.encode(pix)
        return vae.encode_tiled(pix,tile_x=int(tile),tile_y=int(tile),overlap=int(overlap))

    def encode(self,positive,negative,vae,pixels,mask,noise_mask=True,tile_size=3136,overlap=128):
        pix=pixels[...,:3].float(); x=(pix.shape[1]//8)*8; y=(pix.shape[2]//8)*8
        mm=F.interpolate(mask.reshape((-1,1,mask.shape[-2],mask.shape[-1])).float(),size=(pix.shape[1],pix.shape[2]),mode="bilinear",align_corners=False)
        orig=pix
        work=orig.clone()
        if work.shape[1]!=x or work.shape[2]!=y:
            xo=(work.shape[1]%8)//2; yo=(work.shape[2]%8)//2
            work=work[:,xo:x+xo,yo:y+yo,:]; orig=orig[:,xo:x+xo,yo:y+yo,:]; mm=mm[:,:,xo:x+xo,yo:y+yo]
        keep=(1.0-mm.round()).squeeze(1)
        work=(work-0.5)*keep.unsqueeze(-1)+0.5
        concat_latent=self._enc(vae,work,tile_size,overlap)
        orig_latent=self._enc(vae,orig,tile_size,overlap)
        out_latent={"samples":orig_latent}
        if bool(noise_mask):out_latent["noise_mask"]=mm
        out=[]
        for cond in (positive,negative):
            out.append(node_helpers.conditioning_set_values(cond,{"concat_latent_image":concat_latent,"concat_mask":mm}))
        return (out[0],out[1],out_latent)


class DOGMASoftStitchV545:
    """v56.4 inward-only high-resolution composite.
    Gaussian feather happens INSIDE semantic ownership only. Outside the semantic
    blend mask the result is mathematically identical to the incoming master.
    """
    @classmethod
    def INPUT_TYPES(cls):return {"required":{"base_image":("IMAGE",),"patches":("IMAGE",),"generation_masks":("MASK",),"blend_masks":("MASK",),"stitch":("DOGMA_STITCH",),"category":("STRING",{"forceInput":True}),"kind":("STRING",{"forceInput":True})}}
    RETURN_TYPES=("IMAGE","STRING");RETURN_NAMES=("image","info");INPUT_IS_LIST=True;FUNCTION="stitch_regions";CATEGORY="DOGMA/v56.4"
    @staticmethod
    def _resize_image_lanczos(x,h,w):
        chw=x.movedim(-1,1)
        try:out=comfy.utils.common_upscale(chw,int(w),int(h),"lanczos","disabled")
        except Exception:out=F.interpolate(chw,size=(int(h),int(w)),mode="bicubic",align_corners=False)
        return out.movedim(1,-1).clamp(0,1)
    @staticmethod
    def _gauss(x,sigma):
        sigma=max(.5,float(sigma));r=max(1,int(math.ceil(3.0*sigma)));v=torch.arange(-r,r+1,device=x.device,dtype=x.dtype);kk=torch.exp(-(v*v)/(2*sigma*sigma));kk=kk/kk.sum();x=F.conv2d(x,kk.view(1,1,1,-1),padding=(0,r));x=F.conv2d(x,kk.view(1,1,-1,1),padding=(r,0));return x.clamp(0,1)
    def stitch_regions(self,base_image,patches,generation_masks,blend_masks,stitch,category,kind):
        base=base_image[0] if isinstance(base_image,list) else base_image;result=base.clone()[...,:3];dev=result.device
        cat=_v43_canonical(category[0] if isinstance(category,list) and category else category);k=str(kind[0] if isinstance(kind,list) and kind else kind).upper();used=native=resized=0;count=min(len(patches),len(generation_masks),len(blend_masks),len(stitch));sigmas=[]
        for i in range(count):
            meta=stitch[i]
            if not meta or meta.get("noop",False):continue
            p=patches[i];gm=generation_masks[i];bm=blend_masks[i]
            if p.ndim==3:p=p.unsqueeze(0)
            if gm.ndim==2:gm=gm.unsqueeze(0)
            if bm.ndim==2:bm=bm.unsqueeze(0)
            p=p.to(dev)[...,:3].float();gm=gm.to(dev).float();bm=bm.to(dev).float();x=int(meta["x"]);y=int(meta["y"]);w=int(meta["width"]);h=int(meta["height"])
            if w<=0 or h<=0:continue
            pr=int(meta.get("pad_right",0));pb=int(meta.get("pad_bottom",0))
            if pr>0:p=p[:,:,:max(1,p.shape[2]-pr),:];gm=gm[:,:,:max(1,gm.shape[2]-pr)];bm=bm[:,:,:max(1,bm.shape[2]-pr)]
            if pb>0:p=p[:,:max(1,p.shape[1]-pb),:,:];gm=gm[:,:max(1,gm.shape[1]-pb),:];bm=bm[:,:max(1,bm.shape[1]-pb),:]
            if int(p.shape[1])==h and int(p.shape[2])==w:native+=1
            else:p=self._resize_image_lanczos(p,h,w);resized+=1
            if gm.shape[-2:]!=(h,w):gm=F.interpolate(gm.unsqueeze(1),size=(h,w),mode="bilinear",align_corners=False).squeeze(1)
            if bm.shape[-2:]!=(h,w):bm=F.interpolate(bm.unsqueeze(1),size=(h,w),mode="bilinear",align_corners=False).squeeze(1)
            seed=(bm.unsqueeze(1)>=.50).float();support=(gm.unsqueeze(1)>=.40).float();short=max(1,min(h,w))
            if k in ("STRUCTURE","SURFACE"):sigma=max(14,min(42,int(round(short*.016))))
            else:sigma=max(8,min(24,int(round(short*.014))))
            sigmas.append(sigma)
            soft=self._gauss(seed,sigma).pow(.80)
            # INWARD ONLY: outside semantic seed = exactly zero. support is only a safety clamp.
            alpha=(soft*seed*support).squeeze(1).unsqueeze(-1).clamp(0,1)
            reg=result[:,y:y+h,x:x+w,:];result[:,y:y+h,x:x+w,:]=(reg*(1-alpha)+p*alpha).clamp(0,1);used+=1
        sr=f"sigma {min(sigmas)}-{max(sigmas)}px" if sigmas else "no active sigma"
        return (result,f"v56.4 INWARD-ONLY stitch | {cat} [{k}] | {used} region(s) | {sr} inside semantic mask | 0 generated pixels outside ownership | {native} native / {resized} resized")


NODE_CLASS_MAPPINGS = {
    "DOGMAMaskAuditSheetV564": DOGMAMaskAuditSheetV564,
    "DOGMAMaskAuditGateV564": DOGMAMaskAuditGateV564,
    "DOGMATileDetailMergeV56": DOGMATileDetailMergeV56,
    "DOGMATileEdgeAnchorV56": DOGMATileEdgeAnchorV56,
    "DOGMAInstanceChunkCropsV545": DOGMAInstanceChunkCropsV545,
    "DOGMADualMaskV545": DOGMADualMaskV545,
    "DOGMATiledInpaintConditioningV545": DOGMATiledInpaintConditioningV545,
    "DOGMASoftStitchV545": DOGMASoftStitchV545,
    "DOGMAInpaintMaskV543": DOGMAInpaintMaskV543,
    "DOGMARegionStitchV543": DOGMARegionStitchV543,
    "DOGMAInstanceChunkCropsV542": DOGMAInstanceChunkCropsV542,
    "DOGMAMaskedLatentV542": DOGMAMaskedLatentV542,
    "DOGMARegionStitchV542": DOGMARegionStitchV542,
    "DOGMAInstanceChunkCropsV541": DOGMAInstanceChunkCropsV541,
    "DOGMAGenerativeCategoryPromptV54": DOGMAGenerativeCategoryPromptV54,
    "DOGMAV52SceneInstruction": DOGMAV52SceneInstruction,
    "DOGMAV52ScenePlan": DOGMAV52ScenePlan,
    "DOGMAV52MaskDeoverlap": DOGMAV52MaskDeoverlap,
    "DOGMAV50TileInstruction": DOGMAV50TileInstruction,
    "DOGMAV50PromptClean": DOGMAV50PromptClean,
    "DOGMAV50SceneInstruction": DOGMAV50SceneInstruction,
    "DOGMAV50ScenePlan": DOGMAV50ScenePlan,
    "DOGMAV50SAMInputGate": DOGMAV50SAMInputGate,
    "DOGMAV50RegionCrops": DOGMAV50RegionCrops,
    "DOGMATilePromptComposerV44": DOGMATilePromptComposerV44,
    "DOGMASemanticSourceViewV44": DOGMASemanticSourceViewV44,
    "DOGMASceneInventoryPlanV44": DOGMASceneInventoryPlanV44,
    "DOGMARegionCropsV44": DOGMARegionCropsV44,
    "DOGMASceneInventoryPlanV43": DOGMASceneInventoryPlanV43,
    "DOGMARegionCropsV43": DOGMARegionCropsV43,
    "DOGMALocalPromptV43": DOGMALocalPromptV43,
    "DOGMARegionStitchV43": DOGMARegionStitchV43,
    "DOGMATilePromptComposerV42": DOGMATilePromptComposerV42,
    "DOGMATileStatsLockV42": DOGMATileStatsLockV42,
    "DOGMASceneInventoryPlanV42": DOGMASceneInventoryPlanV42,
    "DOGMALocalPromptV42": DOGMALocalPromptV42,
    "DOGMASceneInventoryPlanV40": DOGMASceneInventoryPlanV40,
    "DOGMAMaskVisualV40": DOGMAMaskVisualV40,
    "DOGMAAdaptiveCropsV40": DOGMAAdaptiveCropsV40,
    "DOGMALocalPromptV40": DOGMALocalPromptV40,
    "DOGMAMaskedLatentV40": DOGMAMaskedLatentV40,
    "DOGMAOpaqueLocalStitchV40": DOGMAOpaqueLocalStitchV40,
    "DOGMAControlsV392": DOGMAControlsV392,
    "DOGMAGlobalControlsV39": DOGMAGlobalControlsV39,
    "DOGMATilePromptComposerV39": DOGMATilePromptComposerV39,
    "DOGMAGlobalTileDetailInjectV39": DOGMAGlobalTileDetailInjectV39,
    "DOGMASceneInventoryPlanV39": DOGMASceneInventoryPlanV39,
    "DOGMAMaskPreviewV39": DOGMAMaskPreviewV39,
    "DOGMAAdaptiveSettingsV39": DOGMAAdaptiveSettingsV39,
    "DOGMAAdaptiveCropsV39": DOGMAAdaptiveCropsV39,
    "DOGMAAdaptivePromptV39": DOGMAAdaptivePromptV39,
    "DOGMADetailBandStitchV39": DOGMADetailBandStitchV39,
    "DOGMATilePromptComposerV381": DOGMATilePromptComposerV381,
    "DOGMAEvidenceGateV381": DOGMAEvidenceGateV381,
    "DOGMAConservativeBlendV381": DOGMAConservativeBlendV381,
    "DOGMAAdaptiveGroupedCropsV381": DOGMAAdaptiveGroupedCropsV381,
    "DOGMAInventoryResizeV38": DOGMAInventoryResizeV38,
    "DOGMASceneInventoryPlanV38": DOGMASceneInventoryPlanV38,
    "DOGMASceneInventoryKindsV38": DOGMASceneInventoryKindsV38,
    "DOGMAAdaptiveCategoryPromptV38": DOGMAAdaptiveCategoryPromptV38,
    "DOGMAAdaptiveGroupedCropsV38": DOGMAAdaptiveGroupedCropsV38,
    "DOGMAFixedCategoriesV37": DOGMAFixedCategoriesV37,
    "DOGMASAMInputResizeV37": DOGMASAMInputResizeV37,
    "DOGMAFixedCategoryPromptV37": DOGMAFixedCategoryPromptV37,
    "DOGMACategoryGroupedCropsV37": DOGMACategoryGroupedCropsV37,
    "DOGMAConservativeBlendV37": DOGMAConservativeBlendV37,
    "DOGMAOpaqueMaskedStitchV37": DOGMAOpaqueMaskedStitchV37,
    "DOGMATilePromptComposerV36": DOGMATilePromptComposerV36,
    "DOGMAEvidenceGateV36": DOGMAEvidenceGateV36,
    "DOGMASectorPlanV36": DOGMASectorPlanV36,
    "DOGMAObjectSettingsV36": DOGMAObjectSettingsV36,
    "DOGMALocalPromptV36": DOGMALocalPromptV36,
    "DOGMALocalSafetyGateV36": DOGMALocalSafetyGateV36,
    "DOGMASectorPlanV354": DOGMASectorPlanV354,
    "DOGMASectorMasks4V354": DOGMASectorMasks4V354,
    "DOGMAMaskMatchImageDeviceV354": DOGMAMaskMatchImageDeviceV354,
    "DOGMARunModeMasterV353": DOGMARunModeMasterV353,
    "DOGMAGlobalTestControlsV351": DOGMAGlobalTestControlsV351,
    "DOGMASelect2x2TestTilesV351": DOGMASelect2x2TestTilesV351,
    "DOGMAAlignedTestTileNoiseV351": DOGMAAlignedTestTileNoiseV351,
    "DOGMACombine2x2TestTilesV351": DOGMACombine2x2TestTilesV351,
    "DOGMALatentByDenoiseV351": DOGMALatentByDenoiseV351,
    'DOGMAAlignedDacPrepareV35': DOGMAAlignedDacPrepareV35,
    'DOGMAAlignedTileNoiseV35': DOGMAAlignedTileNoiseV35,
    'DOGMACenterWeightedCombineV35': DOGMACenterWeightedCombineV35,
    'DOGMAObjectSettingsV35': DOGMAObjectSettingsV35,
    'DOGMAObjectClusterCropsV35': DOGMAObjectClusterCropsV35,
    'DOGMALocalPromptV35': DOGMALocalPromptV35,
    'DOGMAFastDualMaskV35': DOGMAFastDualMaskV35,
    'DOGMALocalResultGateV35': DOGMALocalResultGateV35,
    'DOGMAExactCoreStitchV35': DOGMAExactCoreStitchV35,
    "DOGMATilePromptComposerV34A": DOGMATilePromptComposerV34A,
    "DOGMATilePromptComposerV34B": DOGMATilePromptComposerV34B,
    "DOGMATileSecondPassGateV34": DOGMATileSecondPassGateV34,
    "DOGMAShiftPadV34": DOGMAShiftPadV34,
    "DOGMAUnshiftCropV34": DOGMAUnshiftCropV34,
    "DOGMAFastDualMaskV34": DOGMAFastDualMaskV34,
    "DOGMASafeMaskedStitchV34": DOGMASafeMaskedStitchV34,
    "DOGMAObjectSettingsV34": DOGMAObjectSettingsV34,
    "DOGMALocalPromptV34": DOGMALocalPromptV34,
    "DOGMALocalResultGateV34": DOGMALocalResultGateV34,
    "DOGMAObjectSettingsV31": DOGMAObjectSettingsV31,
    "DOGMAObjectClusterCropsV31": DOGMAObjectClusterCropsV31,
    "DOGMAAuditSectorPlanV31": DOGMAAuditSectorPlanV31,
    "DOGMAMergeSamAuditV31": DOGMAMergeSamAuditV31,
    "DOGMAActiveLocalPromptV31": DOGMAActiveLocalPromptV31,
    "DOGMASectorPlanV27": DOGMASectorPlanV27,
    "DOGMAObjectSettingsV27": DOGMAObjectSettingsV27,
    "DOGMAObjectClusterCropsV27": DOGMAObjectClusterCropsV27,
    "DOGMASectorPlanV261": DOGMASectorPlanV261,
    "DOGMASectorSettingsV261": DOGMASectorSettingsV261,
    "DOGMALocalPromptV261": DOGMALocalPromptV261,
    "DOGMASectorPlanV26": DOGMASectorPlanV26,
    "DOGMASectorMasksV26": DOGMASectorMasksV26,
    "DOGMASectorSettingsV26": DOGMASectorSettingsV26,
    "DOGMASectorCropsV26": DOGMASectorCropsV26,
    "DOGMALocalPromptV26": DOGMALocalPromptV26,
    "DOGMALocalVLMBarrierV26": DOGMALocalVLMBarrierV26,
    "DOGMATileBatchToListV25": DOGMATileBatchToListV25,
    "DOGMAImageListToBatchV25": DOGMAImageListToBatchV25,
    "DOGMATilePromptComposerV25": DOGMATilePromptComposerV25,
    "DOGMATileVLMBarrierV25": DOGMATileVLMBarrierV25,
    "DOGMAEvidenceGateV25": DOGMAEvidenceGateV25,
    "DOGMAGlobalLowFreqLockFastV24": DOGMAGlobalLowFreqLockFastV24,
    "DOGMAAdaptiveSemanticPlanV24": DOGMAAdaptiveSemanticPlanV24,
    "DOGMAProtectedMasksV24": DOGMAProtectedMasksV24,
    "DOGMACategorySettingsV24": DOGMACategorySettingsV24,
    "DOGMATileCoherenceBlendFastV231": DOGMATileCoherenceBlendFastV231,
    "DOGMAReflectPadV23": DOGMAReflectPadV23,
    "DOGMACenterCropToReferenceScaleV23": DOGMACenterCropToReferenceScaleV23,
    "DOGMAFixedSemanticPlanV23": DOGMAFixedSemanticPlanV23,
    "DOGMAProtectedMasksV23": DOGMAProtectedMasksV23,
    "DOGMACategorySettingsV23": DOGMACategorySettingsV23,
    "DOGMATileCoherenceBlendV22": DOGMATileCoherenceBlendV22,
    "DOGMACategorySettingsV22": DOGMACategorySettingsV22,
    "DOGMASemanticPlanV21": DOGMASemanticPlanV21,
    "DOGMACategorySettingsV21": DOGMACategorySettingsV21,
    "DOGMAProtectedMasksV21": DOGMAProtectedMasksV21,
    "DOGMASemanticMacroCropsV21": DOGMASemanticMacroCropsV21,
    "DOGMASemanticPlanV16": DOGMASemanticPlanV16,
    "DOGMARestorationBriefV16": DOGMARestorationBriefV16,
    "DOGMATileSemanticComposerV16": DOGMATileSemanticComposerV16,
    "DOGMASemanticOverviewV16": DOGMASemanticOverviewV16,
    "DOGMAResizeMaskToImageV15": DOGMAResizeMaskToImageV15,
    "DOGMAGlobalRefineMaskV14": DOGMAGlobalRefineMaskV14,
    "DOGMALocalRepairMasksV14": DOGMALocalRepairMasksV14,
    "DOGMAResizeToReferenceScaleV14": DOGMAResizeToReferenceScaleV14,
    "DOGMAImageVRAMCleanupV14": DOGMAImageVRAMCleanupV14,
    "DOGMACategorySettingsV13": DOGMACategorySettingsV13,
    "DOGMAProtectedMasksV13": DOGMAProtectedMasksV13,
    "DOGMACategorySettingsV12": DOGMACategorySettingsV12,
    "DOGMASAMMaskCheckpointV12": DOGMASAMMaskCheckpointV12,
    "DOGMAPrepareSAMInputV11_1": DOGMAPrepareSAMInputV11_1,
    "DOGMACategorySettingsV11": DOGMACategorySettingsV11,
    "DOGMASemanticMacroCropsV10": DOGMASemanticMacroCropsV10,
    "DOGMAExactMaskedStitchV10": DOGMAExactMaskedStitchV10,
    "DOGMAAfterMasksVRAMCleanup": DOGMAAfterMasksVRAMCleanup,
    "DOGMAUnionMacroCrops": DOGMAUnionMacroCrops,
    "DOGMAHarmonizedStitchCrops": DOGMAHarmonizedStitchCrops,
    "DOGMAVisionResizeMaxSide": DOGMAVisionResizeMaxSide,
    "DOGMAImageAfterText": DOGMAImageAfterText,
    "DOGMAScenePlanSlots": DOGMAScenePlanSlots,
    "DOGMACategoryMaskGate": DOGMACategoryMaskGate,
    "DOGMAClusteredMaskCrops": DOGMAClusteredMaskCrops,
    "DOGMANativeClusteredMaskCrops": DOGMANativeClusteredMaskCrops,
    "DOGMAStitchCrops": DOGMAStitchCrops,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DOGMAMaskAuditSheetV564": "DOGMA v56.4 Automatic Mask Audit Sheet",
    "DOGMAMaskAuditGateV564": "DOGMA v56.4 Automatic Mask Safety Gate",
    "DOGMATileDetailMergeV56": "DOGMA v56.4 Source-Lowfreq Tile Detail Merge",
    "DOGMATileEdgeAnchorV56": "DOGMA v56.4 Source-Anchored Tile Border",
    "DOGMAInstanceChunkCropsV542": "DOGMA v54.2 Native-HD Spatial Chunks",
    "DOGMAMaskedLatentV542": "DOGMA v54.2 Opaque-Core Generation Mask",
    "DOGMARegionStitchV542": "DOGMA v54.2 HD Opaque-Core Stitch",

    "DOGMAV52SceneInstruction": "DOGMA v52 Non-Overlapping Scene Inventory",
    "DOGMAV52ScenePlan": "DOGMA v52 Coarse-to-Objects Scene Plan",
    "DOGMAV52MaskDeoverlap": "DOGMA v52.1 Mask De-overlap / Empty-Mask Safe",
    "DOGMAV50TileInstruction": "DOGMA V50 Tile VLM Instruction",
    "DOGMAV50PromptClean": "DOGMA V50 Clean Tile Prompt",
    "DOGMAV50SceneInstruction": "DOGMA V50 Scene VLM Instruction",
    "DOGMAV50ScenePlan": "DOGMA V50 Scene Plan",
    "DOGMAV50SAMInputGate": "DOGMA V50 SAM Input Gate",
    "DOGMAV50RegionCrops": "DOGMA V50 2K Region Crops",
    "DOGMATilePromptComposerV44": "DOGMA v44 Source-Grounded Tile Prompt",
    "DOGMASemanticSourceViewV44": "DOGMA v44 Semantic Source View",
    "DOGMASceneInventoryPlanV44": "DOGMA v44 Source-Grounded Scene Plan",
    "DOGMARegionCropsV44": "DOGMA v44 High-Recall Region Crops",
    "DOGMASceneInventoryPlanV43": "DOGMA v43 High-Recall Scene Plan",
    "DOGMARegionCropsV43": "DOGMA v43 Region-Aware Crops",
    "DOGMALocalPromptV43": "DOGMA v43 Base Local Prompt",
    "DOGMARegionStitchV43": "DOGMA v43 Region-Safe Stitch",
    "DOGMATilePromptComposerV42": "DOGMA v42 HD Tile Prompt",
    "DOGMATileStatsLockV42": "DOGMA v42 Safe Tile Statistics Lock",
    "DOGMASceneInventoryPlanV42": "DOGMA v42 Robust Scene Inventory",
    "DOGMALocalPromptV42": "DOGMA v42 Target-First Local Prompt",
    "DOGMASceneInventoryPlanV40": "DOGMA v40 Six Diverse Scene Groups",
    "DOGMAMaskVisualV40": "DOGMA v40 Mask Visual",
    "DOGMAAdaptiveCropsV40": "DOGMA v40 Multi-Instance Crops",
    "DOGMALocalPromptV40": "DOGMA v40 Short Category Prompt",
    "DOGMAMaskedLatentV40": "DOGMA v40 Masked Source Latent",
    "DOGMAOpaqueLocalStitchV40": "DOGMA v40 Opaque Local Stitch",
    "DOGMAControlsV392": "DOGMA v39.2 Global + Local Controls",
    "DOGMAGlobalControlsV39": "DOGMA v39 Global Controls",
    "DOGMATilePromptComposerV39": "DOGMA v39 Context-First Tile Prompt",
    "DOGMAGlobalTileDetailInjectV39": "DOGMA v39 Global Detail Donor",
    "DOGMASceneInventoryPlanV39": "DOGMA v39 Scene Inventory Plan",
    "DOGMAMaskPreviewV39": "DOGMA v39 Mask Preview",
    "DOGMAAdaptiveSettingsV39": "DOGMA v39 Adaptive Settings",
    "DOGMAAdaptiveCropsV39": "DOGMA v39 Adaptive Crops",
    "DOGMAAdaptivePromptV39": "DOGMA v39 Adaptive Prompt",
    "DOGMADetailBandStitchV39": "DOGMA v39 Multiband Detail Stitch",
    "DOGMATilePromptComposerV381": "DOGMA v39 Period-Aware Tile Prompt",
    "DOGMAEvidenceGateV381": "DOGMA v39 Ghost Veto",
    "DOGMAConservativeBlendV381": "DOGMA v39 Safe Conservative Blend",
    "DOGMAAdaptiveGroupedCropsV381": "DOGMA v39 Safe Adaptive Crops",
    "DOGMAInventoryResizeV38": "DOGMA v38 Inventory Resize",
    "DOGMASceneInventoryPlanV38": "DOGMA v38 Scene Inventory Plan",
    "DOGMASceneInventoryKindsV38": "DOGMA v38 Inventory Kinds",
    "DOGMAAdaptiveCategoryPromptV38": "DOGMA v38 Adaptive Category Prompt",
    "DOGMAAdaptiveGroupedCropsV38": "DOGMA v38 Adaptive Grouped Crops",
    "DOGMAFixedCategoriesV37": "DOGMA v37 Fixed Categories",
    "DOGMASAMInputResizeV37": "DOGMA v37 SAM Input Resize",
    "DOGMAFixedCategoryPromptV37": "DOGMA v37 Fixed Category Prompt",
    "DOGMACategoryGroupedCropsV37": "DOGMA v37 Category Grouped Crops",
    "DOGMAConservativeBlendV37": "DOGMA v37 Conservative Blend",
    "DOGMAOpaqueMaskedStitchV37": "DOGMA v37 Opaque Stitch",
    "DOGMATilePromptComposerV36": "DOGMA v36 Compact Tile Prompt",
    "DOGMAEvidenceGateV36": "DOGMA v36 Source + Novel Edge Gate",
    "DOGMASectorPlanV36": "DOGMA v36 Four Present Categories",
    "DOGMAObjectSettingsV36": "DOGMA v36 Positive Target Settings",
    "DOGMALocalPromptV36": "DOGMA v36 Positive Target Prompt",
    "DOGMALocalSafetyGateV36": "DOGMA v36 Local Safety Gate",
    "DOGMASectorPlanV354": "DOGMA v35.4 Four-Sector Plan",
    "DOGMASectorMasks4V354": "DOGMA v35.4 Four-Sector Mask Summary",
    "DOGMAMaskMatchImageDeviceV354": "DOGMA v35.4 Mask Device Guard",
    "DOGMARunModeMasterV353": "DOGMA MASTER SWITCH — Test / Full",
    "DOGMAGlobalTestControlsV351": "DOGMA v35.1 Global Test + Full Controls",
    "DOGMASelect2x2TestTilesV351": "DOGMA v35.1 Select 2x2 Test Tiles",
    "DOGMAAlignedTestTileNoiseV351": "DOGMA v35.1 Aligned 2x2 Noise",
    "DOGMACombine2x2TestTilesV351": "DOGMA v35.1 Combine 2x2 Test Tiles",
    "DOGMALatentByDenoiseV351": "DOGMA v35.1 Latent By Denoise",
    'DOGMAAlignedDacPrepareV35': 'DOGMA v35 Latent-Aligned D&C Prepare',
    'DOGMAAlignedTileNoiseV35': 'DOGMA v35 Global Spatially-Aligned Noise',
    'DOGMACenterWeightedCombineV35': 'DOGMA v35 Center-Weighted Tile Combine',
    'DOGMAObjectSettingsV35': 'DOGMA v35 Object Settings — Defect-Only Prompt',
    'DOGMAObjectClusterCropsV35': 'DOGMA v35 Compact Whole-Object Crops',
    'DOGMALocalPromptV35': 'DOGMA v35 Local Prompt — FIX FIRST',
    'DOGMAFastDualMaskV35': 'DOGMA v35 Fast Category Mask Pair',
    'DOGMALocalResultGateV35': 'DOGMA v35 Local Preserve Gate',
    'DOGMAExactCoreStitchV35': 'DOGMA v35 Exact-Core Stitch',
    "DOGMATilePromptComposerV34A": "DOGMA Tile Prompt v34 A — Short / Front-Loaded",
    "DOGMATilePromptComposerV34B": "DOGMA Tile Prompt v34 B — Shifted QC Repair",
    "DOGMATileSecondPassGateV34": "DOGMA Tile Pass-B Gate v34 — Exact Preserve",
    "DOGMAShiftPadV34": "DOGMA Shift Pad v34 — Half-Stride Grid Offset",
    "DOGMAUnshiftCropV34": "DOGMA Unshift Crop v34 — Exact Frame",
    "DOGMAFastDualMaskV34": "DOGMA Fast Dual Mask v34 — GPU / Opaque Core",
    "DOGMASafeMaskedStitchV34": "DOGMA Safe Masked Stitch v34 — Opaque Core",
    "DOGMAObjectSettingsV34": "DOGMA Object Settings v34 — Short Prompt / Base 0.35",
    "DOGMALocalPromptV34": "DOGMA Local Prompt v34 — FIX FIRST",
    "DOGMALocalResultGateV34": "DOGMA Local Result Gate v34 — Preserve Means Preserve",
    "DOGMAObjectSettingsV31": "DOGMA Object Settings v31 — Compact Groups / Base 0.35",
    "DOGMAObjectClusterCropsV31": "DOGMA Object Cluster Crops v31 — Compact Adjacent Groups",
    "DOGMAAuditSectorPlanV31": "DOGMA Audit Sector Plan v31 — 4B Audit + SAM Fallbacks",
    "DOGMAMergeSamAuditV31": "DOGMA Merge SAM + Audit v31 — Missed Defect Recovery",
    "DOGMAActiveLocalPromptV31": "DOGMA Active Local Prompt v31 — No Per-Object VLM",
    "DOGMASectorPlanV27": "DOGMA Sector Plan v27 — Object-Centric Targets",
    "DOGMAObjectSettingsV27": "DOGMA Object Settings v27 — Complete Object / Small Cluster",
    "DOGMAObjectClusterCropsV27": "DOGMA Object Crops v27 — Whole Objects, Never Tile",
    "DOGMASectorPlanV261": "DOGMA Sector Plan v26.1 — Text Safe",
    "DOGMASectorSettingsV261": "DOGMA Sector Settings v26.1 — Text Identity Lock",
    "DOGMALocalPromptV261": "DOGMA Local Prompt v26.1 — Text Safe",
    "DOGMASectorPlanV26": "DOGMA Sector Plan v26 — 3 Non-Destructive Targets",
    "DOGMASectorMasksV26": "DOGMA Sector Masks v26 — Preserve Instances",
    "DOGMASectorSettingsV26": "DOGMA Sector Settings v26 — Local VLM Brief",
    "DOGMASectorCropsV26": "DOGMA Sector Crops v26 — Grouped High Resolution",
    "DOGMALocalPromptV26": "DOGMA Local Prompt v26 — Safe Sector Instruction",
    "DOGMALocalVLMBarrierV26": "DOGMA Local VLM Barrier v26",
    "DOGMATileBatchToListV25": "DOGMA Tile Batch → Mapped List v25",
    "DOGMAImageListToBatchV25": "DOGMA Mapped Image List → Batch v25",
    "DOGMATilePromptComposerV25": "DOGMA Tile-Specific Restoration Prompt v25",
    "DOGMATileVLMBarrierV25": "DOGMA Tile VLM Barrier v25 — Unload Before Klein",
    "DOGMAEvidenceGateV25": "DOGMA Source Evidence Gate v25 — Anti-Hallucination",
    "DOGMAGlobalLowFreqLockFastV24": "DOGMA Global Low-Frequency Lock FAST v24",
    "DOGMAAdaptiveSemanticPlanV24": "DOGMA Adaptive Semantic Plan v24",
    "DOGMAProtectedMasksV24": "DOGMA Protected Masks v24",
    "DOGMACategorySettingsV24": "DOGMA Category Settings v24 — True Inpaint",
    "DOGMATileCoherenceBlendFastV231": "DOGMA Tile Coherence Blend FAST v23.1",
    "DOGMAReflectPadV23": "DOGMA Reflect Pad v23 — Border Context",
    "DOGMACenterCropToReferenceScaleV23": "DOGMA Center Crop v23 — Remove Context Pad",
    "DOGMAFixedSemanticPlanV23": "DOGMA Semantic Plan v23 — Discrete Objects Only",
    "DOGMAProtectedMasksV23": "DOGMA Protected Masks v23 — Roadway People Split",
    "DOGMACategorySettingsV23": "DOGMA Category Settings v23 — Full-Noise Objects",
    "DOGMATileCoherenceBlendV22": "DOGMA Tile Coherence Blend v22 — Low-Frequency Lock",
    "DOGMACategorySettingsV22": "DOGMA Category Settings v22 — Current Master Ref",
    "DOGMASemanticPlanV21": "DOGMA Semantic Plan v21 — Global First",
    "DOGMACategorySettingsV21": "DOGMA Category Settings v21 — Macro Edit",
    "DOGMAProtectedMasksV21": "DOGMA Protect Semantic Masks v21",
    "DOGMASemanticMacroCropsV21": "DOGMA Semantic Macro Crops v21 — Current + Original",
    "DOGMASemanticPlanV16": "DOGMA Semantic Plan v16 — Concrete Categories",
    "DOGMARestorationBriefV16": "DOGMA Restoration Brief v16",
    "DOGMATileSemanticComposerV16": "DOGMA Semantic Tile Composer v16",
    "DOGMASemanticOverviewV16": "DOGMA Semantic Overview v16",
    "DOGMAResizeMaskToImageV15": "DOGMA Resize Mask To Image v15",
    "DOGMAGlobalRefineMaskV14": "DOGMA Global Refine Mask v14 — Protect Text",
    "DOGMALocalRepairMasksV14": "DOGMA Local Repair Masks v14 — Objects Only",
    "DOGMAResizeToReferenceScaleV14": "DOGMA Resize To Reference Scale v14",
    "DOGMAImageVRAMCleanupV14": "DOGMA Image VRAM Cleanup v14",
    "DOGMACategorySettingsV13": "DOGMA Category Settings v13",
    "DOGMAProtectedMasksV13": "DOGMA Protect Semantic Masks v13",
    "DOGMACategorySettingsV12": "DOGMA Category Settings v12 — Full 4 Step",
    "DOGMASAMMaskCheckpointV12": "DOGMA SAM Mask CPU Checkpoint v12",
    "DOGMAPrepareSAMInputV11_1": "DOGMA Prepare SAM Input v11.1 — VRAM Safe",
    "DOGMACategorySettingsV11": "DOGMA Category Settings v11",
    "DOGMASemanticMacroCropsV10": "DOGMA Semantic Macro Crops v10",
    "DOGMAExactMaskedStitchV10": "DOGMA Exact Masked Stitch v10",
    "DOGMAAfterMasksVRAMCleanup": "DOGMA After Masks VRAM Cleanup",
    "DOGMAUnionMacroCrops": "DOGMA Union Macro Crops — Few Large Crops",
    "DOGMAHarmonizedStitchCrops": "DOGMA Harmonized Stitch Crops",
    "DOGMAVisionResizeMaxSide": "DOGMA Vision Resize — Max Side",
    "DOGMAImageAfterText": "DOGMA Image After Text — VRAM Barrier",
    "DOGMAScenePlanSlots": "DOGMA Scene Plan → 6 Slots",
    "DOGMACategoryMaskGate": "DOGMA Category Mask Gate",
    "DOGMAClusteredMaskCrops": "DOGMA Clustered Mask Crops (2K)",
    "DOGMANativeClusteredMaskCrops": "DOGMA Native Clustered Mask Crops",
    "DOGMAStitchCrops": "DOGMA Stitch Crops",
}


WEB_DIRECTORY = "./web"
