"""DOGMA Nodes: bounded-working-memory HDR finishing for ComfyUI >= 0.45.0.

No models, dependencies, monkey patches, or changes to ComfyUI are installed.
The native VAE still returns a complete batch; finishing consumes one frame
at a time and returns file paths, never another complete IMAGE batch.
"""
from __future__ import annotations

import json
import logging
import math
import os
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import torch
import safetensors.torch
import folder_paths
import nodes
import comfy.utils
from comfy.cli_args import args
from comfy_api.latest import io, ui
from comfy_api.latest._input_impl.video_types import (
    BT2020_NCL, set_video_color_properties,
)
from comfy_extras import nodes_images as ni

VERSION = "1.0.51"
SPACES = ["sRGB", "HDR", "HDR ACEScct", "HDR LogC3", "HDR PQ", "linear", "linear ACEScg"]
log = logging.getLogger("DOGMA.HDR")


def require_fp32():
    if args.fp16_intermediates:
        raise ValueError("HDR 16-bit float: rimuovi --fp16-intermediates dall'avvio di Comfy. La conversione colore richiede intermedi fp32.")


def convert_frame(frame, source, destination):
    require_fp32()
    return ni.ImageColorSpace.execute(
        frame.to(device="cpu", dtype=torch.float32), source, destination
    ).result[0].to(device="cpu", dtype=torch.float32)


class DogmaHDRColorChunked(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DOGMAHDRColorChunkedV1", display_name="DOGMA HDR | Colore per fotogramma",
            category="DOGMA/HDR",
            description="Stessa trasformazione colore Comfy, con temporanei limitati a un fotogramma. Non riduce risoluzione o precisione.",
            inputs=[io.Image.Input("image"),
                    io.Combo.Input("source", options=SPACES, default="sRGB"),
                    io.Combo.Input("destination", options=SPACES, default="HDR ACEScct")],
            outputs=[io.Image.Output()],
        )

    @classmethod
    def execute(cls, image, source, destination):
        require_fp32()
        # Per-frame tone mapping would differ from the native batch transform.
        # This node is intentionally limited to the non-tone-mapping HDR path.
        if destination == "sRGB" or (source == "HDR PQ" and destination == "HDR"):
            raise ValueError("Questa conversione usa statistiche dell'intero batch: usa ImageColorSpace nativo per il tonemapping SDR/PQ-HLG.")
        if source == destination:
            return io.NodeOutput(image.to(device="cpu", dtype=torch.float32))
        output = torch.empty(image.shape, device="cpu", dtype=torch.float32)
        progress = comfy.utils.ProgressBar(len(image))
        with torch.inference_mode():
            for index in range(len(image)):
                nodes.before_node_execution()
                output[index:index + 1].copy_(convert_frame(image[index:index + 1], source, destination))
                progress.update(1)
        return io.NodeOutput(output)


def fit_frame(frame, source_width, source_height, target_width, target_height):
    width = 2 * math.floor(min(target_width, target_height * source_width / source_height) / 2)
    height = 2 * math.floor(min(target_height, target_width * source_height / source_width) / 2)
    if min(width, height) < 2:
        raise ValueError("Proporzioni del sorgente non valide.")
    frame = nodes.ImageScale().upscale(frame, "bicubic", width, height, "disabled")[0]
    return ni.ResizeAndPadImage.execute(frame, target_width, target_height, "black", "area").result[0]


def create_job(prefix, output_directory):
    # Comfy validates that the requested prefix remains inside its output root.
    directory, name, counter, _, _ = folder_paths.get_save_image_path(prefix, output_directory)
    while True:
        job = Path(directory) / f"{name}_{counter:05d}"
        try:
            job.mkdir()
            return job
        except FileExistsError:
            counter += 1


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def encode_audio(container, audio, count, rate):
    if audio is None:
        return
    sample_rate = int(audio["sample_rate"])
    wave = audio["waveform"][0]
    layouts = {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 6: "5.1", 8: "7.1"}
    if wave.shape[0] not in layouts:
        raise ValueError(f"Audio: {wave.shape[0]} canali non supportati; nessun downmix automatico.")
    layout = layouts[wave.shape[0]]
    stream = container.add_stream("pcm_s24le", rate=sample_rate, layout=layout)
    n = min(wave.shape[-1], math.ceil(Fraction(sample_rate * count, 1) / rate))
    # Audio is also chunked, avoiding an extra full-length contiguous copy.
    for offset in range(0, n, 8192):
        part = wave[:, offset:min(n, offset + 8192)].float().cpu().contiguous().numpy()
        frame = av.AudioFrame.from_ndarray(part, format="fltp", layout=layout)
        frame.sample_rate = sample_rate
        frame.time_base = Fraction(1, sample_rate)
        frame.pts = offset
        container.mux(stream.encode(frame))
    container.mux(stream.encode(None))


def export_frames(images, source_width, source_height, source_frames, fps,
                  filename_prefix="DOGMA_HDR_4K/master", save_mov=True, audio=None,
                  target_width=3840, target_height=2160, output_directory=None,
                  progress=None, metadata=None):
    """Sequential finishing; target size override is for isolated CPU QA only."""
    require_fp32()
    if images.ndim != 4 or images.shape[-1] != 3:
        raise ValueError("Atteso IMAGE RGB [fotogrammi, altezza, larghezza, 3] in ACEScct.")
    if source_width < 1 or source_height < 1 or source_frames < 1 or source_frames > len(images):
        raise ValueError(f"Conteggio/proporzioni non validi: richiesti {source_frames} frame, decode disponibile {len(images)}.")
    if not math.isfinite(float(fps)) or fps <= 0:
        raise ValueError("FPS sorgente non valido.")
    # Recover standard rational rates without rounding 24000/1001 to 23.976.
    rate = Fraction(float(fps)).limit_denominator(1000000)
    output_directory = output_directory or folder_paths.get_output_directory()
    job = create_job(filename_prefix, output_directory)
    exr_dir = job / "EXR"
    exr_dir.mkdir()
    mov_path = job / "DOGMA_4K_HDR_HLG.mov"
    mov_temporary = job / "DOGMA_4K_HDR_HLG.partial.mov"
    manifest = dict(version=VERSION, status="incomplete", completed_frames=0,
                    frames=source_frames, fps=str(rate), width=target_width, height=target_height,
                    master="ACEScg AP1/D60 RGB HALF EXR ZIP16", source_width=source_width,
                    source_height=source_height, decoded_frames=len(images),
                    mov="ProRes 4444 BT.2020 HLG; 10-bit encoding input; PCM24 original audio" if save_mov else None,
                    metadata=metadata or {})
    write_json(job / "manifest.json", manifest)
    container = None
    try:
        if save_mov:
            container = av.open(str(mov_temporary), mode="w", format="mov", options={"movflags": "use_metadata_tags+faststart"})
            stream = container.add_stream("prores_ks", rate=rate)
            stream.width, stream.height = target_width, target_height
            stream.pix_fmt = "yuv444p10le"
            stream.options = {"profile": "4444", "alpha_bits": "16"}
            stream.codec_context.thread_count = 2
            stream.time_base = 1 / rate
            set_video_color_properties(stream.codec_context, "HDR")
            # Register audio before the muxer writes the MOV header.
            # The PCM stream is created below by encode_audio, before video encode.
            if audio is not None:
                encode_audio(container, audio, source_frames, rate)
        with torch.inference_mode():
            for index in range(source_frames):
                nodes.before_node_execution()
                linear = convert_frame(images[index:index + 1], "HDR ACEScct", "linear ACEScg")
                linear = fit_frame(linear, source_width, source_height, target_width, target_height)
                if not torch.isfinite(linear).all():
                    raise ValueError(f"Frame {index}: valori HDR NaN/Inf. Il file non viene dichiarato completo.")
                # HALF cannot represent values outside +-65504. Do not silently clip.
                if linear.abs().max() > 65504:
                    raise ValueError(f"Frame {index}: range oltre HALF (+-65504). Serve EXR float32 per questi valori.")
                encoded = ni._encode_image(linear[0], "exr", "16-bit float", "linear ACEScg")
                encoded = ni.inject_exr_metadata(encoded, None, None, "linear ACEScg")
                exr = exr_dir / f"frame_{index:06d}.exr"
                temporary = exr.with_suffix(".exr.partial")
                temporary.write_bytes(encoded)
                os.replace(temporary, exr)
                del encoded
                if container is not None:
                    hlg = convert_frame(linear, "linear ACEScg", "HDR")[0]
                    pixels = (hlg * 65535).clamp(0, 65535).numpy().astype(np.uint16)
                    frame = av.VideoFrame.from_ndarray(pixels, format="rgb48le")
                    frame = frame.reformat(format="yuv444p10le", dst_colorspace=BT2020_NCL)
                    set_video_color_properties(frame, "HDR")
                    frame.time_base = 1 / rate
                    frame.pts = index
                    container.mux(stream.encode(frame))
                    del hlg, pixels, frame
                del linear
                manifest["completed_frames"] = index + 1
                if (index + 1) % 12 == 0 or index + 1 == source_frames:
                    write_json(job / "manifest.json", manifest)
                    log.info("HDR export: %d/%d frame; %s", index + 1, source_frames, job)
                if progress is not None:
                    progress.update(1)
        if container is not None:
            container.mux(stream.encode(None))
            container.close()
            container = None
            os.replace(mov_temporary, mov_path)
        manifest["status"] = "complete"
        write_json(job / "manifest.json", manifest)
    except BaseException as error:
        manifest["error"] = str(error)
        write_json(job / "manifest.json", manifest)
        raise
    finally:
        if container is not None:
            container.close()
    return job, mov_path if save_mov else None


class DogmaHDRSaveStreaming(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DOGMAHDRSaveStreamingV1", display_name="DOGMA HDR | Salva 4K EXR16 + MOV progressivo",
            category="DOGMA/HDR", is_output_node=True,
            description="Converte ACEScct, ripristina proporzioni, elimina la sola coda temporale e salva un frame alla volta. Nessun secondo batch IMAGE completo.",
            inputs=[io.Image.Input("images"), io.Int.Input("source_width", force_input=True),
                    io.Int.Input("source_height", force_input=True), io.Int.Input("source_frames", force_input=True),
                    io.Float.Input("fps", force_input=True),
                    io.String.Input("filename_prefix", default="DOGMA_HDR_4K/master"),
                    io.Boolean.Input("save_mov", default=True), io.Audio.Input("audio", optional=True)],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            outputs=[io.String.Output("exr_directory"), io.String.Output("mov_path")],
        )

    @classmethod
    def execute(cls, images, source_width, source_height, source_frames, fps,
                filename_prefix="DOGMA_HDR_4K/master", save_mov=True, audio=None):
        metadata = {}
        if not args.disable_metadata and cls.hidden is not None:
            if cls.hidden.extra_pnginfo:
                metadata.update(cls.hidden.extra_pnginfo)
            if cls.hidden.prompt:
                metadata["prompt"] = cls.hidden.prompt
        job, mov = export_frames(images, source_width, source_height, source_frames, fps,
                                 filename_prefix, save_mov, audio,
                                 progress=comfy.utils.ProgressBar(source_frames), metadata=metadata)
        preview = None
        if mov:
            subfolder = str(job.relative_to(Path(folder_paths.get_output_directory()))).replace("\\", "/")
            preview = ui.PreviewVideo([ui.SavedResult(mov.name, subfolder, io.FolderType.output)])
        return io.NodeOutput(str(job / "EXR"), str(mov) if mov else "", ui=preview)


class DogmaHDRCheckpoint(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DOGMAHDRCheckpointV1", display_name="DOGMA HDR | Checkpoint prima del decode",
            category="DOGMA/HDR",
            description="Salva il latente prima del decode. Per riprendere lo stesso video inserisci il percorso del checkpoint: i sampler vengono saltati.",
            inputs=[io.Latent.Input("samples", lazy=True),
                    io.String.Input("filename_prefix", default="DOGMA_HDR_4K/checkpoints/HDR"),
                    io.String.Input("resume_from", default="", tooltip="Lascia vuoto per una nuova generazione. Percorso .latent relativo a output, oppure assoluto dentro input/output Comfy.")],
            outputs=[io.Latent.Output(), io.String.Output("checkpoint_path")],
        )

    @classmethod
    def check_lazy_status(cls, filename_prefix, resume_from, samples=None):
        return [] if resume_from.strip() or samples is not None else ["samples"]

    @classmethod
    def execute(cls, filename_prefix, resume_from="", samples=None):
        if resume_from.strip():
            path = Path(resume_from.strip()).expanduser()
            if not path.is_absolute():
                path = Path(folder_paths.get_output_directory()) / path
            path = path.resolve()
            roots = [Path(folder_paths.get_output_directory()).resolve(), Path(folder_paths.get_input_directory()).resolve()]
            if not any(path.is_relative_to(root) for root in roots) or path.suffix != ".latent":
                raise ValueError("Il checkpoint deve essere un file .latent nella cartella input/output di Comfy.")
            saved = safetensors.torch.load_file(str(path), device="cpu")
            if "latent_format_version_0" not in saved or "latent_tensor" not in saved:
                raise ValueError("Checkpoint non compatibile: atteso formato latente Comfy attuale.")
            return io.NodeOutput({"samples": saved["latent_tensor"]}, str(path))
        if samples is None or "samples" not in samples:
            raise ValueError("Nessun latente ricevuto dal sampler.")
        directory, name, counter, _, _ = folder_paths.get_save_image_path(filename_prefix, folder_paths.get_output_directory())
        path = Path(directory) / f"{name}_{counter:05d}_.latent"
        temporary = path.with_suffix(".latent.partial")
        saved = {"latent_tensor": samples["samples"].detach().contiguous(),
                 "latent_format_version_0": torch.tensor([])}
        comfy.utils.save_torch_file(saved, str(temporary), metadata={"dogma_hdr_streaming": VERSION})
        os.replace(temporary, path)
        log.info("Checkpoint HDR salvato prima del decode: %s", path)
        return io.NodeOutput(samples, str(path))


# Registered through the existing DOGMA package, not a separate extension.
NODE_CLASS_MAPPINGS = {
    "DOGMAHDRColorChunkedV1": DogmaHDRColorChunked,
    "DOGMAHDRSaveStreamingV1": DogmaHDRSaveStreaming,
    "DOGMAHDRCheckpointV1": DogmaHDRCheckpoint,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DOGMAHDRColorChunkedV1": "DOGMA HDR | Colore per fotogramma",
    "DOGMAHDRSaveStreamingV1": "DOGMA HDR | Salva 4K EXR16 + MOV progressivo",
    "DOGMAHDRCheckpointV1": "DOGMA HDR | Checkpoint prima del decode",
}
# Initialize V3 schema fields while retaining explicit, Registry-readable IDs.
for _node in NODE_CLASS_MAPPINGS.values():
    _node.GET_SCHEMA()
del _node
