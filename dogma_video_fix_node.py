"""Standalone VIDEO adapter for the same repair engine used by API Platform."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading

from comfy_api.latest import io, ui, InputImpl, Types


class DOGMASeedanceVideoFix(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DOGMASeedanceVideoFix",
            display_name="DOGMA / Fix video Seedance",
            category="DOGMA/Video",
            description="Corregge gli scatti del solo video generato da Seedance. "
                "Mantiene fps, durata, risoluzione e audio. Non richiede il video originale o API.",
            inputs=[io.Video.Input("video", tooltip="Collega il video generato da Seedance.")],
            outputs=[io.Video.Output("video_corretto")],
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    async def execute(cls, video):
        cancelled=threading.Event()
        worker=asyncio.create_task(asyncio.to_thread(cls._repair,video,cancelled,cls.hidden.unique_id))
        try:
            result,summary=await asyncio.shield(worker)
            return io.NodeOutput(result,ui=ui.PreviewText(summary))
        except asyncio.CancelledError:
            cancelled.set()
            try:await worker
            except Exception:pass
            raise

    @staticmethod
    def _repair(video,cancelled,node_id=None):
        import folder_paths
        import comfy.model_management as management
        from comfy.utils import ProgressBar
        from .dogma_video_repair import RepairCancelled,repair_video

        progress=ProgressBar(100,node_id=node_id)
        def check():
            if cancelled.is_set():raise RepairCancelled("Correzione interrotta.")
            management.throw_exception_if_processing_interrupted()
        def update(stage,fraction):
            check()
            progress.update_absolute(round(max(0,min(1,fraction))*100))

        check()
        root=Path(folder_paths.get_temp_directory());root.mkdir(parents=True,exist_ok=True)
        work=Path(tempfile.mkdtemp(prefix="dogma-seedance-fix-",dir=root))
        source=work/'input.mp4';fixed=work/'corrected.mp4';report_file=work/'repair.json'
        try:
            # Native save remuxes uploaded MP4 streams. It also honors VIDEO trims
            # if this node is reused in a larger graph, without tensorizing the clip.
            video.save_to(str(source),format=Types.VideoContainer.MP4,codec=Types.VideoCodec.AUTO)
            check()
            report=repair_video(source,fixed,Path(folder_paths.models_dir)/'DOGMA'/'rife',cancel=check,progress=update)
            check()
            if report['status']=='repaired':
                summary=f"Correzione completata · {report['fps']} fps · {report['interpolated_frames']} fotogrammi ricostruiti"
            elif report['status']=='unchanged':
                summary="Nessuno scatto riconosciuto: il video è rimasto invariato."
            else:
                summary="Correzione non applicata: il controllo non ha confermato un miglioramento. Video invariato."
            report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            source.unlink()
            # The result stays in Comfy's temp directory for SaveVideo and caching.
            return InputImpl.VideoFromFile(str(fixed)),summary
        except BaseException:
            for path in (source,fixed,report_file):path.unlink(missing_ok=True)
            work.rmdir()
            raise


NODE_CLASS_MAPPINGS={"DOGMASeedanceVideoFix":DOGMASeedanceVideoFix}
NODE_DISPLAY_NAME_MAPPINGS={"DOGMASeedanceVideoFix":"DOGMA / Fix video Seedance"}
