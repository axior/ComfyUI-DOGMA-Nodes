"""Clear HDR controls for the existing DOGMA Nodes package.

The source transfer, internal model working encoding, EXR primaries and MOV
transfer are deliberately separate. The model always receives ACEScct.
"""
from __future__ import annotations

import math
from pathlib import Path
import torch
import folder_paths
import comfy.utils
import nodes
from comfy.cli_args import args
from comfy_api.latest import io, ui
from .dogma_hdr_streaming import convert_frame, export_frames, require_fp32

CONFIG_TYPE = io.Custom("DOGMA_HDR_CONFIG")
ORIGINAL = "Originale - senza upscale"
UHD = "4K UHD - 3840 x 2160"
RESOLUTIONS = [UHD, ORIGINAL]
SOURCE_SPACES = {
    "SDR - sRGB": "sRGB",
    "SDR - Rec.709 gamma 2.4": "Rec709 gamma24",
    "HDR - Rec.2020 HLG": "HDR",
    "HDR - Rec.2020 PQ": "HDR PQ",
    "Lineare - ACEScg": "linear ACEScg",
    "Lineare - Rec.709": "linear",
    "Log - ACEScct": "HDR ACEScct",
    "Log - LogC3 con primarie Rec.709": "HDR LogC3",
}
EXR_SPACES = {"ACEScg lineare - 16 bit float": "linear ACEScg", "Rec.709 lineare - 16 bit float": "linear"}
MOV_SPACES = {"HLG - Rec.2020 / ProRes 4444": "HDR", "PQ - Rec.2020 / ProRes 4444": "HDR PQ",
              "Disattivato - solo EXR": None}


def checked_config(settings):
    if not isinstance(settings, dict) or settings.get("version") != 1:
        raise ValueError("Impostazioni HDR mancanti: collega il nodo DOGMA Impostazioni HDR.")
    for key, options in [("resolution", RESOLUTIONS), ("source", SOURCE_SPACES),
                         ("exr", EXR_SPACES), ("mov", MOV_SPACES)]:
        if settings.get(key) not in options:
            raise ValueError(f"Impostazione HDR non valida: {key}.")
    return settings


class DOGMAHDRSettings(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRSettingsV1", display_name="DOGMA HDR | Impostazioni di generazione",
            category="DOGMA/HDR", description="Risoluzione, colore sorgente e seed. I controlli di export restano separati per riutilizzare la cache del modello.",
            inputs=[
                io.Combo.Input("resolution", display_name="Risoluzione finale", options=RESOLUTIONS, default=UHD,
                    tooltip="Originale: generazione alle dimensioni del sorgente, senza upsampler e senza stadio 2. 4K: percorso 8+3 con upscale latente e consegna UHD."),
                io.Combo.Input("source", display_name="Colore del video sorgente", options=list(SOURCE_SPACES), default=next(iter(SOURCE_SPACES)),
                    tooltip="Descrive i pixel in ingresso. Scegli in base all'export del sorgente; sRGB e Rec.709 gamma 2.4 hanno curve diverse. Non cambia il formato interno richiesto dalla LoRA."),
                io.Int.Input("seed", display_name="Seed", default=42, min=0, max=0xffffffffffffffff, control_after_generate=False),
            ], outputs=[CONFIG_TYPE.Output("settings"), io.Int.Output("seed")])

    @classmethod
    def execute(cls, resolution=UHD, source=next(iter(SOURCE_SPACES)), seed=42):
        settings=checked_config(dict(version=1,resolution=resolution,source=source,
                                     exr=next(iter(EXR_SPACES)),mov=next(iter(MOV_SPACES)),
                                     seed=int(seed),filename_prefix="DOGMA_HDR/master"))
        return io.NodeOutput(settings, int(seed))


class DOGMAHDRDeliverySettings(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRDeliverySettingsV1",display_name="DOGMA HDR | Impostazioni di esportazione",
            category="DOGMA/HDR", inputs=[CONFIG_TYPE.Input("settings"),
                io.Combo.Input("exr", display_name="Colore del master EXR", options=list(EXR_SPACES), default=next(iter(EXR_SPACES)),
                    tooltip="EXR sempre RGB 16 bit float, lineare. ACEScg AP1/D60 e il master consigliato per la pipeline ACES."),
                io.Combo.Input("mov", display_name="Video MOV aggiuntivo", options=list(MOV_SPACES), default=next(iter(MOV_SPACES)),
                    tooltip="HLG o PQ in Rec.2020, oppure nessun MOV. Il MOV ProRes usa input encoder 10 bit; il master 16 bit resta l'EXR."),
                io.String.Input("filename_prefix", display_name="Cartella / prefisso output", default="DOGMA_HDR/master")],
            outputs=[CONFIG_TYPE.Output("settings")])

    @classmethod
    def execute(cls,settings,exr=next(iter(EXR_SPACES)),mov=next(iter(MOV_SPACES)),filename_prefix="DOGMA_HDR/master"):
        value={**checked_config(settings),"exr":exr,"mov":mov,"filename_prefix":filename_prefix}
        return io.NodeOutput(checked_config(value))


class DOGMAHDRPrepareSource(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRPrepareSourceV1", display_name="DOGMA HDR | Ingresso automatico ACEScct",
            category="DOGMA/HDR", inputs=[io.Image.Input("image"), CONFIG_TYPE.Input("settings")],
            outputs=[io.Image.Output()])

    @classmethod
    def execute(cls, image, settings):
        source=SOURCE_SPACES[checked_config(settings)["source"]]
        require_fp32()
        if source == "HDR ACEScct":
            return io.NodeOutput(image.to(device="cpu",dtype=torch.float32))
        output=torch.empty(image.shape,device="cpu",dtype=torch.float32)
        progress=comfy.utils.ProgressBar(len(image))
        with torch.inference_mode():
            for i in range(len(image)):
                nodes.before_node_execution()
                frame=image[i:i+1]
                if source == "Rec709 gamma24":
                    frame=frame.to(device="cpu",dtype=torch.float32).clamp_min(0).pow(2.4)
                    value=convert_frame(frame,"linear","HDR ACEScct")
                else:
                    value=convert_frame(frame,source,"HDR ACEScct")
                output[i:i+1].copy_(value)
                progress.update(1)
        return io.NodeOutput(output)


def canvas_plan(width, height, planned_width, planned_height, settings):
    settings=checked_config(settings)
    upscale=settings["resolution"] == UHD
    if min(width,height,planned_width,planned_height) < 1:
        raise ValueError("Dimensioni sorgente/piano HDR non valide.")
    if upscale:
        canvas_width,canvas_height=planned_width,planned_height
        target_width,target_height=3840,2160
        description="Upscale 4K attivo - campionamento 8 + 3"
    else:
        canvas_width=max(32,32*math.floor(width/32+.5))
        canvas_height=max(32,32*math.floor(height/32+.5))
        target_width,target_height=width,height
        description="Originale - nessun upscale e nessuno stadio 2 - 8 passaggi"
    summary=(f"{description}\nSorgente: {width} x {height}\n"
             f"Canvas modello: {canvas_width} x {canvas_height}\nUscita: {target_width} x {target_height}\n"
             f"Sorgente colore: {settings['source']}\nInterno LTX: ACEScct (automatico)")
    return canvas_width,canvas_height,upscale,summary


class DOGMAHDRCanvas(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRCanvasV1",display_name="DOGMA HDR | Piano risoluzione",
            category="DOGMA/HDR",inputs=[io.Image.Input("image"),
                io.Int.Input("planned_width",force_input=True),io.Int.Input("planned_height",force_input=True),
                CONFIG_TYPE.Input("settings")],
            outputs=[io.Int.Output("canvas_width"),io.Int.Output("canvas_height"),
                     io.Boolean.Output("upscale"),io.String.Output("summary")])

    @classmethod
    def execute(cls,image,planned_width,planned_height,settings):
        return io.NodeOutput(*canvas_plan(image.shape[2],image.shape[1],planned_width,planned_height,settings))


class DOGMAHDRResolutionSelect(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRResolutionSelectV1",display_name="DOGMA HDR | Selezione risoluzione automatica",
            category="DOGMA/HDR",inputs=[CONFIG_TYPE.Input("settings"),
                io.Latent.Input("original",lazy=True),io.Latent.Input("upscaled",lazy=True)],
            outputs=[io.Latent.Output()])

    @classmethod
    def check_lazy_status(cls, settings, original=None, upscaled=None):
        branch="upscaled" if checked_config(settings)["resolution"]==UHD else "original"
        return [branch] if (upscaled if branch=="upscaled" else original) is None else []

    @classmethod
    def execute(cls, settings, original=None, upscaled=None):
        result=upscaled if checked_config(settings)["resolution"]==UHD else original
        if result is None:
            raise ValueError("Latente del ramo selezionato non disponibile.")
        return io.NodeOutput(result)


class DOGMAHDRSaveConfigured(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRSaveConfiguredV1",display_name="DOGMA HDR | Salva master e video",
            category="DOGMA/HDR",is_output_node=True,
            inputs=[io.Image.Input("images"),CONFIG_TYPE.Input("settings"),
                io.Int.Input("source_width",force_input=True),io.Int.Input("source_height",force_input=True),
                io.Int.Input("source_frames",force_input=True),io.Float.Input("fps",force_input=True),
                io.Audio.Input("audio",optional=True)],hidden=[io.Hidden.prompt,io.Hidden.extra_pnginfo],
            outputs=[io.String.Output("exr_directory"),io.String.Output("mov_path")])

    @classmethod
    def execute(cls,images,settings,source_width,source_height,source_frames,fps,audio=None):
        cfg=checked_config(settings)
        target=(3840,2160) if cfg["resolution"]==UHD else (source_width,source_height)
        transfer=MOV_SPACES[cfg["mov"]]
        metadata={"dogma_hdr_settings":cfg,"model_working_space":"ACEScct"}
        if not args.disable_metadata and cls.hidden is not None:
            if cls.hidden.extra_pnginfo:metadata.update(cls.hidden.extra_pnginfo)
            if cls.hidden.prompt:metadata["prompt"]=cls.hidden.prompt
        job,mov=export_frames(images,source_width,source_height,source_frames,fps,
            cfg["filename_prefix"],transfer is not None,audio,target_width=target[0],target_height=target[1],
            progress=comfy.utils.ProgressBar(source_frames),metadata=metadata,
            exr_color_space=EXR_SPACES[cfg["exr"]],mov_color_space=transfer or "HDR",
            mov_stem="DOGMA_HDR_PQ" if transfer=="HDR PQ" else "DOGMA_HDR_HLG")
        preview=None
        if mov:
            subfolder=str(job.relative_to(Path(folder_paths.get_output_directory()))).replace('\\','/')
            preview=ui.PreviewVideo([ui.SavedResult(mov.name,subfolder,io.FolderType.output)])
        return io.NodeOutput(str(job/'EXR'),str(mov) if mov else "",ui=preview)


class DOGMAHDRSummary(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="DOGMAHDRSummaryV1",display_name="DOGMA HDR | Riepilogo scelte",
            category="DOGMA/HDR",inputs=[io.String.Input("generation_summary",force_input=True),CONFIG_TYPE.Input("settings")],
            outputs=[io.String.Output("summary")])

    @classmethod
    def execute(cls,generation_summary,settings):
        cfg=checked_config(settings)
        return io.NodeOutput(f"{generation_summary}\nMaster EXR: {cfg['exr']}\nMOV: {cfg['mov']}")


NODE_CLASS_MAPPINGS={
    "DOGMAHDRSettingsV1":DOGMAHDRSettings,
    "DOGMAHDRPrepareSourceV1":DOGMAHDRPrepareSource,
    "DOGMAHDRCanvasV1":DOGMAHDRCanvas,
    "DOGMAHDRResolutionSelectV1":DOGMAHDRResolutionSelect,
    "DOGMAHDRSaveConfiguredV1":DOGMAHDRSaveConfigured,
    "DOGMAHDRDeliverySettingsV1":DOGMAHDRDeliverySettings,
    "DOGMAHDRSummaryV1":DOGMAHDRSummary,
}
NODE_DISPLAY_NAME_MAPPINGS={key:node.GET_SCHEMA().display_name for key,node in NODE_CLASS_MAPPINGS.items()}
