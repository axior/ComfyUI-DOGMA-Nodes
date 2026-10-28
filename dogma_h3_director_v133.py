"""DOGMA H3 auditions: durable candidate selection, no seed re-entry.

Uses the installed Comfy sampler and VAE; no replacement diffusion implementation.
"""
from pathlib import Path
import hashlib
import json
import os
import secrets
import time
import uuid

import av
import numpy as np
import torch
import folder_paths
import nodes
from comfy.nested_tensor import NestedTensor
from comfy_execution.graph import ExecutionBlocker
from comfy_extras.nodes_custom_sampler import Noise_RandomNoise, SamplerCustomAdvanced, Guider_Basic
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ImageToVideo
from comfy.ldm.minimax.model import FRAME_PER_TOKEN

GENERATE = "GENERA PROVINI"
FINISH = "FINALIZZA SELEZIONATO"
SEEDS = "SEED DIVERSI / stesso prompt"
PROMPTS = "PROMPT DIVERSI / stesso seed"


def make_plan(mode, base, variants, count):
    if mode == PROMPTS:
        lines = [s.strip() for s in variants.splitlines() if s.strip()]
        if not 1 <= len(lines) <= 10:
            raise ValueError("Scrivi da 1 a 10 prompt, uno per riga. Le righe vuote sono ignorate.")
        shared_seed = secrets.randbelow(2**53 - 1)
        return [{"prompt": (base.strip() + "\n" + line).strip(), "variant": line, "seed": shared_seed}
                for line in lines]
    used = set()
    while len(used) < count:
        used.add(secrets.randbelow(2**53 - 1))
    return [{"prompt": base, "variant": "Stesso prompt", "seed": seed} for seed in sorted(used)]


def pack(value):
    if isinstance(value, NestedTensor):
        return {"__dogma_nested__": [pack(t) for t in value.unbind()]}
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().contiguous()
    if isinstance(value, dict):
        return {k: pack(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [pack(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported latent metadata: {type(value).__name__}")


def unpack(value):
    if isinstance(value, dict):
        if set(value) == {"__dogma_nested__"}:
            return NestedTensor([unpack(v) for v in value["__dogma_nested__"]])
        return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unpack(v) for v in value]
    return value


def atomic_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def session_dir(session_id):
    # A UUID, never an arbitrary path supplied by a workflow.
    key = str(uuid.UUID(str(session_id)))
    return Path(folder_paths.get_output_directory()) / "DOGMA_H3_PROVINI" / key


def fingerprint(prompt, unique_id):
    """Compare stage-one ancestors, not final-stage controls or UI placement."""
    root = prompt[str(unique_id)]["inputs"]
    found = {}

    def visit(value):
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in prompt:
            key = value[0]
            if key in found:
                return
            source = prompt[key]
            entry = {"class_type": source["class_type"], "inputs": source["inputs"]}
            found[key] = entry
            if source["class_type"] == "LoadImage":
                image_name = source["inputs"].get("image")
                if isinstance(image_name, str):
                    p = Path(folder_paths.get_annotated_filepath(image_name))
                    if p.exists():
                        stat = p.stat()
                        entry["file_version"] = [stat.st_size, stat.st_mtime_ns]
            for v in source["inputs"].values():
                visit(v)

    for key in ("guider", "sampler", "sigmas", "latent", "video_vae", "clip", "first_frame", "prompt_base", "prompt_varianti"):
        visit(root.get(key))
    found["__explorer__"] = {key: root.get(key) for key in ("modalita", "prompt_base", "prompt_varianti")}
    return hashlib.sha256(json.dumps(found, sort_keys=True, default=str).encode()).hexdigest()


def save_preview(images, path):
    """Encode a silent motion preview; original AV latents remain untouched."""
    height, width = images.shape[1:3]
    with av.open(str(path), "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=24)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "24", "preset": "ultrafast"}
        for image in images:
            import comfy.model_management
            comfy.model_management.throw_exception_if_processing_interrupted()
            pixels = (image.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def load_manifest(session_id):
    root = session_dir(session_id)
    path = root / "latest.json"
    if not path.exists():
        raise ValueError("Nessun provino salvato per questa sessione. Scegli GENERA PROVINI e premi Run.")
    data = json.loads(path.read_text(encoding="utf-8"))
    str(uuid.UUID(data["run_id"]))
    if data.get("version") != 1 or not data.get("complete"):
        raise ValueError("Il giro di provini non e completo. Genera un nuovo giro.")
    return root, data


def send_status(unique_id, message):
    try:
        from server import PromptServer
        PromptServer.instance.send_sync("dogma.h3.status", {"node": str(unique_id), "message": message})
    except (AttributeError, RuntimeError):
        pass


class DOGMAH3Auditions:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "azione": ([GENERATE, FINISH],),
            "modalita": ([SEEDS, PROMPTS],),
            "numero_provini": ("INT", {"default": 10, "min": 1, "max": 10}),
            "provino_scelto": ("INT", {"default": 1, "min": 1, "max": 10}),
            "nuovo_giro": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            "session_id": ("STRING", {"default": "", "multiline": False}),
            "guider": ("GUIDER", {"lazy": True}),
            "sampler": ("SAMPLER", {"lazy": True}),
            "sigmas": ("SIGMAS", {"lazy": True}),
            "latent": ("LATENT", {"lazy": True}),
            "video_vae": ("VAE", {"lazy": True}),
            "clip": ("CLIP", {"lazy": True}),
            "prompt_base": ("STRING", {"forceInput": True}),
            "prompt_varianti": ("STRING", {"forceInput": True}),
        }, "optional": {"first_frame": ("IMAGE", {"lazy": True})},
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("LATENT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("selezionato_AV", "seed_automatico", "nome_finale", "prompt_scelto")
    FUNCTION = "run"
    CATEGORY = "DOGMA/H3"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, azione, session_id, provino_scelto, **kwargs):
        if azione == GENERATE:
            return float("nan")
        path = session_dir(session_id) / "latest.json"
        return f"{path.stat().st_mtime_ns if path.exists() else 0}:{provino_scelto}"

    def check_lazy_status(self, azione, modalita, guider=None, sampler=None, sigmas=None,
                          latent=None, video_vae=None, clip=None, first_frame=None, **kwargs):
        if azione == FINISH:
            return []
        vals = locals()
        needed = [k for k in ("guider", "sampler", "sigmas", "latent", "video_vae") if vals[k] is None]
        if modalita == PROMPTS:
            if clip is None:
                needed.append("clip")
            root = kwargs.get("prompt", {}).get(str(kwargs.get("unique_id")), {}).get("inputs", {})
            if first_frame is None and "first_frame" in root:
                needed.append("first_frame")
        return needed

    def run(self, azione, modalita, numero_provini, provino_scelto, nuovo_giro, session_id,
            prompt_base, prompt_varianti, prompt, unique_id, guider=None, sampler=None,
            sigmas=None, latent=None, video_vae=None, clip=None, first_frame=None):
        signature = fingerprint(prompt, unique_id)
        if azione == FINISH:
            root, manifest = load_manifest(session_id)
            if manifest["fingerprint"] != signature:
                raise ValueError("Immagine, prompt o impostazioni dei provini sono cambiati. Ripristinali oppure genera nuovi provini prima di finalizzare.")
            if not 1 <= provino_scelto <= len(manifest["candidates"]):
                raise ValueError("Scegli un provino presente nella galleria.")
            entry = manifest["candidates"][provino_scelto - 1]
            path = root / manifest["run_id"] / f"candidate_{provino_scelto:02d}.pt"
            payload = torch.load(path, map_location="cpu", weights_only=True)
            prefix = f"video/DOGMA_H3_PROVINI/FINALE_{manifest['run_id'][:8]}_P{provino_scelto:02d}_{entry['seed']}"
            send_status(unique_id, f"Finalizzazione provino {provino_scelto}: caricati i latenti originali.")
            return {"ui": {"dogma_gallery": [manifest], "dogma_selected": [provino_scelto]},
                    "result": (unpack(payload), entry["seed"], prefix, entry["prompt"])}

        root = session_dir(session_id)
        run_id = str(uuid.uuid4())
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        start = time.perf_counter()
        plan = make_plan(modalita, prompt_base, prompt_varianti, numero_provini)
        total = len(plan)
        manifest = {"version": 1, "run_id": run_id, "session_id": session_id, "mode": modalita,
                    "fingerprint": signature, "complete": False, "candidates": [], "fps": 24}
        # Encode all prompt alternatives before sampling, avoiding 10 CLIP/DiT swaps.
        guiders = []
        if modalita == PROMPTS:
            video = latent["samples"].unbind()[0]
            height, width = video.shape[3] * 16, video.shape[4] * 16
            length = sum(FRAME_PER_TOKEN[k % 5] for k in range(video.shape[2]))
            for i, item in enumerate(plan):
                send_status(unique_id, f"Preparazione prompt {i + 1}/{total}")
                conditioning = MiniMaxH3ImageToVideo.execute(clip, video_vae, item["prompt"], width, height, length,
                                                            first_frame=first_frame)[0]
                variant_guider = Guider_Basic(guider.model_patcher)
                variant_guider.set_conds(conditioning)
                guiders.append(variant_guider)
        else:
            guiders = [guider] * total
        # Keep the diffusion model resident across all auditions. Decode after sampling.
        for index, item in enumerate(plan, 1):
            import comfy.model_management
            comfy.model_management.throw_exception_if_processing_interrupted()
            seed = item["seed"]
            send_status(unique_id, f"Provino {index}/{total}: generazione")
            tick = time.perf_counter()
            result = SamplerCustomAdvanced.execute(Noise_RandomNoise(seed), guiders[index - 1], sampler, sigmas, latent)
            temp = run_dir / f"candidate_{index:02d}.tmp"
            torch.save(pack(result[0]), temp)
            os.replace(temp, run_dir / f"candidate_{index:02d}.pt")
            manifest["candidates"].append({"index": index, **item,
                "sample_seconds": round(time.perf_counter() - tick, 3),
                "filename": f"candidate_{index:02d}.mp4",
                "subfolder": f"DOGMA_H3_PROVINI/{session_id}/{run_id}", "type": "output"})
            del result
            atomic_json(run_dir / "manifest.json", manifest)
        for entry in manifest["candidates"]:
            import comfy.model_management
            comfy.model_management.throw_exception_if_processing_interrupted()
            index = entry["index"]
            send_status(unique_id, f"Anteprima {index}/{total}: decodifica")
            payload = unpack(torch.load(run_dir / f"candidate_{index:02d}.pt", map_location="cpu", weights_only=True))
            images = nodes.VAEDecode().decode(video_vae, payload)[0]
            entry["frames"] = len(images)
            entry["width"], entry["height"] = images.shape[2], images.shape[1]
            save_preview(images, run_dir / entry["filename"])
            del images, payload
        manifest["complete"] = True
        manifest["total_seconds"] = round(time.perf_counter() - start, 2)
        atomic_json(run_dir / "manifest.json", manifest)
        atomic_json(root / "latest.json", manifest)
        send_status(unique_id, "Provini pronti. Scegli una scheda, poi Finalizza questo nel Director.")
        return {"ui": {"dogma_gallery": [manifest], "dogma_selected": [0]},
                "result": tuple(ExecutionBlocker(None) for _ in range(4))}


class DOGMAH3SelectedSampler:
    """Strong selected input gates every expensive final-stage dependency."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "selected": ("LATENT",),
            "seed": ("INT", {"forceInput": True}),
            "guider": ("GUIDER", {"lazy": True}),
            "sampler": ("SAMPLER", {"lazy": True}),
            "sigmas": ("SIGMAS", {"lazy": True}),
            "upscaled_latent": ("LATENT", {"lazy": True}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "run"
    CATEGORY = "DOGMA/H3"

    def check_lazy_status(self, selected, seed, guider=None, sampler=None,
                          sigmas=None, upscaled_latent=None):
        vals = locals()
        return [k for k in ("guider", "sampler", "sigmas", "upscaled_latent") if vals[k] is None]

    def run(self, selected, seed, guider, sampler, sigmas, upscaled_latent):
        result = SamplerCustomAdvanced.execute(Noise_RandomNoise(seed), guider, sampler, sigmas, upscaled_latent)
        return (result[0],)


NODE_CLASS_MAPPINGS = {"DOGMAH3Auditions": DOGMAH3Auditions, "DOGMAH3SelectedSampler": DOGMAH3SelectedSampler}
NODE_DISPLAY_NAME_MAPPINGS = {"DOGMAH3Auditions": "DOGMA / H3 DIRECTOR",
                            "DOGMAH3SelectedSampler": "DOGMA / FINALIZZA solo il selezionato"}
