bl_info = {
    "name": "Octane ORBX Export Helper",
    "author": "OnlineRender",
    "version": (4, 2, 0),
    "blender": (3, 0, 0),
    "location": "Properties > Output > Octane ORBX Export",
    "description": "Export ORBX with GUI for single exports and batch chunks (manual + optional auto)",
    "category": "Render",
}

import bpy
import os
import re
from bpy.types import PropertyGroup, Operator, Panel
from bpy.props import (
    StringProperty,
    BoolProperty,
    IntProperty,
    FloatProperty,
    PointerProperty,
    CollectionProperty,
)

# --------------------------------------------------------
# Helpers
# --------------------------------------------------------

def get_base_dir(settings):
    """Resolve a usable base directory from the filepath setting."""
    base_path = bpy.path.abspath(settings.filepath)
    base_dir, _ = os.path.split(base_path)
    if not base_dir:
        base_dir = bpy.path.abspath("//")
    return base_dir


def sync_and_update_filename(self, context):
    """Sync scene frame range (if requested) and update filename suffix."""
    scene = context.scene
    settings = self

    if not settings.use_scene_range and settings.update_frame_range:
        scene.frame_start = settings.frame_start
        scene.frame_end = settings.frame_end

    if settings.use_scene_range:
        fs = scene.frame_start
        fe = scene.frame_end
    else:
        fs = settings.frame_start
        fe = settings.frame_end

    if settings.filename:
        base_filename = settings.filename
    else:
        base_path = bpy.path.abspath(settings.filepath)
        _, base_name = os.path.split(base_path)
        base_filename = base_name or "export.orbx"

    name_root, ext = os.path.splitext(base_filename)
    if not ext:
        ext = ".orbx"

    name_root = re.sub(r"_frame_\d+_\d+$", "", name_root)

    if settings.append_frame_range:
        name_root = f"{name_root}_frame_{fs}_{fe}"

    settings.filename = name_root + ext


def build_final_filename(scene, settings) -> str:
    if settings.filename:
        base_filename = settings.filename
    else:
        base_path = bpy.path.abspath(settings.filepath)
        _, base_name = os.path.split(base_path)
        base_filename = base_name or "export.orbx"

    name_root, ext = os.path.splitext(base_filename)
    if not ext:
        ext = ".orbx"
    return name_root + ext


def build_batch_filename_step(scene, settings, fs, fe) -> str:
    """
    Filename for each batch export in frame-step mode.
    Includes start frame as _F_<start> and optional _frame_<fs>_<fe>.
    """
    if settings.filename:
        base_filename = settings.filename
    else:
        base_path = bpy.path.abspath(settings.filepath)
        _, base_name = os.path.split(base_path)
        base_filename = base_name or "export.orbx"

    name_root, ext = os.path.splitext(base_filename)
    if not ext:
        ext = ".orbx"

    name_root = re.sub(r"_frame_\d+_\d+$", "", name_root)
    name_root = f"{name_root}_F_{fs}"

    if settings.append_frame_range:
        name_root = f"{name_root}_frame_{fs}_{fe}"

    return name_root + ext


def cleanup_previous_export(full_path: str):
    """Delete any old ORBX + its '<name> assets' folder before a new export."""
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
        except OSError:
            pass

    base_no_ext, _ = os.path.splitext(full_path)
    assets_dir = base_no_ext + " assets"
    if os.path.isdir(assets_dir):
        try:
            import shutil
            shutil.rmtree(assets_dir, ignore_errors=True)
        except OSError:
            pass


# --------------------------------------------------------
# Batch chunk data (stored on the scene)
# --------------------------------------------------------

class OrbxBatchChunk(PropertyGroup):
    start: IntProperty(name="Start")
    end: IntProperty(name="End")


# --------------------------------------------------------
# Settings
# --------------------------------------------------------

class OrbxExportSettings(PropertyGroup):
    # Single export file settings
    filepath: StringProperty(
        name="File Path",
        description="Directory and/or base path for ORBX export",
        subtype='FILE_PATH',
        default="//my_export.orbx",
    )

    filename: StringProperty(
        name="File Name",
        description="ORBX file name",
        default="my_export.orbx",
    )

    # Frame range (single)
    use_scene_range: BoolProperty(
        name="Use Scene Frame Range",
        description="Use scene frame_start / frame_end for export & naming",
        default=True,
        update=sync_and_update_filename,
    )

    frame_start: IntProperty(
        name="Frame Start",
        description="Start frame for ORBX export when not using scene range",
        default=0,
        min=0,
        update=sync_and_update_filename,
    )

    frame_end: IntProperty(
        name="Frame End",
        description="End frame for ORBX export when not using scene range",
        default=10,
        min=0,
        update=sync_and_update_filename,
    )

    append_frame_range: BoolProperty(
        name="Append Frame Range to Name",
        description="Append _frame_<start>_<end> to the file name",
        default=False,
        update=sync_and_update_filename,
    )

    update_frame_range: BoolProperty(
        name="Update Frame Range",
        description="Keep the scene timeline range synced with the values above",
        default=False,
        update=sync_and_update_filename,
    )

    # Batch export (frame-step) – PREPARED chunks
    batch_enable: BoolProperty(
        name="Enable Batch Export",
        description="Enable batch export using fixed frame steps",
        default=False,
    )

    batch_step: IntProperty(
        name="Step Size",
        description="Number of frames per ORBX chunk",
        default=20,
        min=1,
    )

    batch_use_overlap: BoolProperty(
        name="Overlap for Motion Blur",
        description="Extend each chunk's frame range by a few frames on both sides",
        default=False,
    )

    batch_overlap_frames: IntProperty(
        name="Overlap Frames",
        description="Number of frames to extend before and after each range",
        default=1,
        min=0,
    )

    batch_chunks: CollectionProperty(type=OrbxBatchChunk)
    batch_chunk_index: IntProperty(
        name="Current Chunk Index",
        default=0,
        min=0,
    )

    # Auto-batch options
    batch_auto: BoolProperty(
        name="Auto Batch (Experimental)",
        description="Automatically export each prepared chunk in sequence (may be unstable with Octane)",
        default=False,
    )

    batch_delay: FloatProperty(
        name="Auto Check Delay (s)",
        description="Delay between filesystem checks for auto batch",
        default=1.0,
        min=0.1,
    )

    batch_cooldown: FloatProperty(
        name="Cooldown Between Chunks (s)",
        description="Extra wait time after each chunk finishes before starting the next",
        default=0.0,
        min=0.0,
    )


# --------------------------------------------------------
# Single Export Operator
# --------------------------------------------------------

class EXPORT_OT_orbx_smart(Operator):
    """Export ORBX using settings from the panel"""
    bl_idname = "export.orbx_smart"
    bl_label = "Export ORBX (Single)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        settings = scene.orbx_export_settings

        if settings.use_scene_range:
            frame_start = scene.frame_start
            frame_end = scene.frame_end
        else:
            frame_start = settings.frame_start
            frame_end = settings.frame_end
            if settings.update_frame_range:
                scene.frame_start = frame_start
                scene.frame_end = frame_end

        base_dir = get_base_dir(settings)
        final_filename = build_final_filename(scene, settings)
        full_path = os.path.join(base_dir, final_filename)

        bpy.ops.export.orbx(
            filepath=full_path,
            check_existing=False,
            filename=final_filename,
            frame_start=frame_start,
            frame_end=frame_end,
            frame_subframe=0.0,
            filter_glob="*.orbx",
        )

        self.report(
            {'INFO'},
            f"Exported ORBX to {full_path} (frames {frame_start}–{frame_end})"
        )
        return {'FINISHED'}


# --------------------------------------------------------
# Batch: Prepare chunks
# --------------------------------------------------------

class EXPORT_OT_orbx_prepare_batch(Operator):
    """Prepare frame-step batch chunks (no exporting yet)"""
    bl_idname = "export.orbx_prepare_batch"
    bl_label = "Prepare Batch Chunks"

    def execute(self, context):
        scene = context.scene
        settings = scene.orbx_export_settings

        if not settings.batch_enable:
            self.report({'WARNING'}, "Enable 'Enable Batch Export' first")
            return {'CANCELLED'}

        scene_start = scene.frame_start
        scene_end = scene.frame_end
        if scene_start >= scene_end:
            self.report({'WARNING'}, "Invalid scene frame range for batch export")
            return {'CANCELLED'}

        step = max(1, settings.batch_step)
        overlap = settings.batch_overlap_frames if settings.batch_use_overlap else 0

        settings.batch_chunks.clear()

        f = scene_start
        while f <= scene_end:
            start = f
            end = f + step - 1

            if overlap > 0:
                start -= overlap
                end += overlap

            start = max(start, scene_start)
            end = min(end, scene_end)

            if start <= end:
                chunk = settings.batch_chunks.add()
                chunk.start = start
                chunk.end = end

            f += step

        settings.batch_chunk_index = 0

        self.report(
            {'INFO'},
            f"Prepared {len(settings.batch_chunks)} chunks "
            f"(step={step}, overlap={overlap})"
        )
        return {'FINISHED'}


# --------------------------------------------------------
# Batch: Export next chunk (manual click)
# --------------------------------------------------------

class EXPORT_OT_orbx_export_next_chunk(Operator):
    """Export the next prepared batch chunk (one ORBX per click)"""
    bl_idname = "export.orbx_export_next_chunk"
    bl_label = "Export Next Chunk"

    def execute(self, context):
        scene = context.scene
        settings = scene.orbx_export_settings

        chunks = settings.batch_chunks
        idx = settings.batch_chunk_index

        if not settings.batch_enable or len(chunks) == 0:
            self.report({'WARNING'}, "No batch chunks prepared. Click 'Prepare Batch Chunks' first.")
            return {'CANCELLED'}

        if idx >= len(chunks):
            self.report({'INFO'}, "All batch chunks have already been exported.")
            return {'CANCELLED'}

        chunk = chunks[idx]
        fs = chunk.start
        fe = chunk.end

        base_dir = get_base_dir(settings)
        filename = build_batch_filename_step(scene, settings, fs, fe)
        full_path = os.path.join(base_dir, filename)

        scene.frame_current = fs  # for context

        self.report(
            {'INFO'},
            f"Exporting chunk {idx+1}/{len(chunks)}: {filename} frames {fs}–{fe}"
        )

        bpy.ops.export.orbx(
            filepath=full_path,
            check_existing=False,
            filename=filename,
            frame_start=fs,
            frame_end=fe,
            frame_subframe=0.0,
            filter_glob="*.orbx",
        )

        settings.batch_chunk_index += 1

        return {'FINISHED'}


# --------------------------------------------------------
# Auto-batch state + timer (filesystem-based, experimental)
# --------------------------------------------------------

_auto_state = {
    "running": False,
    "index": 0,
    "chunks": [],
    "base_dir": "",
    "orig_current": None,
    "current_path": "",
    "last_size": 0,
    "stable": 0,
    "checks": 0,
    "status": "idle",  # "idle", "waiting"
}

def orbx_auto_batch_timer():
    """Timer callback: automatically exports each chunk, one at a time, watching file size."""
    global _auto_state

    if not _auto_state["running"]:
        return None

    # Scene or settings might vanish if file closes or addon unloads
    scene = bpy.context.scene
    if not hasattr(scene, "orbx_export_settings"):
        _auto_state["running"] = False
        return None

    settings = scene.orbx_export_settings

    # If user unticked auto while running, stop gracefully
    if not settings.batch_auto:
        print("[ORBX Auto Batch] Stopped (batch_auto disabled).")
        _auto_state["running"] = False
        return None

    chunks = _auto_state["chunks"]
    idx = _auto_state["index"]
    status = _auto_state["status"]

    # Finished all chunks?
    if idx >= len(chunks):
        if _auto_state["orig_current"] is not None:
            scene.frame_current = _auto_state["orig_current"]
        print("[ORBX Auto Batch] Complete.")
        _auto_state["running"] = False
        return None

    # Start a new chunk
    if status == "idle":
        chunk = chunks[idx]
        fs = chunk["start"]
        fe = chunk["end"]
        path = chunk["path"]

        scene.frame_current = fs

        print(f"[ORBX Auto Batch] Starting chunk {idx+1}/{len(chunks)}: "
              f"{os.path.basename(path)} frames {fs}–{fe}")

        # Clean previous ORBX + assets
        cleanup_previous_export(path)

        # Fire export
        bpy.ops.export.orbx(
            filepath=path,
            check_existing=False,
            filename=os.path.basename(path),
            frame_start=fs,
            frame_end=fe,
            frame_subframe=0.0,
            filter_glob="*.orbx",
        )

        _auto_state["current_path"] = path
        _auto_state["last_size"] = 0
        _auto_state["stable"] = 0
        _auto_state["checks"] = 0
        _auto_state["status"] = "waiting"

        return max(0.5, settings.batch_delay)

    # Waiting for ORBX file to finish
    if status == "waiting":
        path = _auto_state["current_path"]
        _auto_state["checks"] += 1

        if os.path.exists(path):
            size = os.path.getsize(path)
            if size != _auto_state["last_size"]:
                _auto_state["last_size"] = size
                _auto_state["stable"] = 0
            else:
                _auto_state["stable"] += 1

            # consider done after 3 stable checks
            if _auto_state["stable"] >= 3:
                print(f"[ORBX Auto Batch] Chunk {_auto_state['index']+1} complete: "
                      f"{os.path.basename(path)}")
                _auto_state["index"] += 1
                _auto_state["status"] = "idle"
                # apply cooldown between chunks
                return max(0.5, settings.batch_delay + settings.batch_cooldown)
        else:
            # file not yet created, keep waiting
            pass

        # safety timeout
        if _auto_state["checks"] > 600:
            print(f"[ORBX Auto Batch] WARNING: timeout waiting for {os.path.basename(path)}")
            _auto_state["index"] += 1
            _auto_state["status"] = "idle"
            return max(0.5, settings.batch_delay + settings.batch_cooldown)

        return max(0.5, settings.batch_delay)

    return max(0.5, settings.batch_delay)


class EXPORT_OT_orbx_auto_batch(Operator):
    """Automatically export all prepared batch chunks (EXPERIMENTAL)"""
    bl_idname = "export.orbx_auto_batch"
    bl_label = "Auto Batch (Experimental)"

    def execute(self, context):
        global _auto_state

        scene = context.scene
        settings = scene.orbx_export_settings

        if not settings.batch_enable:
            self.report({'WARNING'}, "Enable 'Enable Batch Export' and prepare chunks first.")
            return {'CANCELLED'}

        if not settings.batch_auto:
            self.report({'WARNING'}, "Enable 'Auto Batch (Experimental)' first.")
            return {'CANCELLED'}

        chunks_prop = settings.batch_chunks
        if len(chunks_prop) == 0:
            self.report({'WARNING'}, "No chunks prepared. Click 'Prepare Batch Chunks' first.")
            return {'CANCELLED'}

        base_dir = get_base_dir(settings)

        # Build a simple chunk list for the timer
        chunks = []
        for ch in chunks_prop:
            fs = ch.start
            fe = ch.end
            filename = build_batch_filename_step(scene, settings, fs, fe)
            full_path = os.path.join(base_dir, filename)
            chunks.append({
                "start": fs,
                "end": fe,
                "path": full_path,
            })

        _auto_state["running"] = True
        _auto_state["index"] = 0
        _auto_state["chunks"] = chunks
        _auto_state["base_dir"] = base_dir
        _auto_state["orig_current"] = scene.frame_current
        _auto_state["current_path"] = ""
        _auto_state["last_size"] = 0
        _auto_state["stable"] = 0
        _auto_state["checks"] = 0
        _auto_state["status"] = "idle"

        bpy.app.timers.register(
            orbx_auto_batch_timer,
            first_interval=max(0.5, settings.batch_delay),
        )

        self.report({'INFO'}, f"Started ORBX auto-batch for {len(chunks)} chunks.")
        return {'FINISHED'}


class EXPORT_OT_orbx_auto_batch_stop(Operator):
    """Stop the running auto batch (if any)"""
    bl_idname = "export.orbx_auto_batch_stop"
    bl_label = "Stop Auto Batch"

    def execute(self, context):
        global _auto_state
        if _auto_state["running"]:
            _auto_state["running"] = False
            self.report({'INFO'}, "Stopped ORBX auto batch.")
        else:
            self.report({'INFO'}, "Auto batch is not running.")
        return {'FINISHED'}


# --------------------------------------------------------
# Panel
# --------------------------------------------------------

class RENDER_PT_orbx_export(Panel):
    bl_label = "Octane ORBX Export"
    bl_idname = "RENDER_PT_orbx_export"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "output"

    def draw(self, context):
        global _auto_state

        layout = self.layout
        scene = context.scene
        settings = scene.orbx_export_settings

        # Single export
        box_single = layout.box()
        box_single.label(text="Single Export")
        box_single.prop(settings, "filepath")
        box_single.prop(settings, "filename")
        box_single.prop(settings, "append_frame_range")

        final_name = build_final_filename(scene, settings)
        row = box_single.row()
        row.enabled = False
        row.label(text=f"Result: {final_name}")

        box_single.separator()
        box_single.prop(settings, "use_scene_range")

        row = box_single.row()
        row.enabled = not settings.use_scene_range
        row.prop(settings, "update_frame_range")

        col = box_single.column()
        col.enabled = not settings.use_scene_range
        col.prop(settings, "frame_start")
        col.prop(settings, "frame_end")

        box_single.separator()
        box_single.operator("export.orbx_smart", icon='EXPORT')

        # Batch export
        layout.separator()
        box_batch = layout.box()
        box_batch.label(text="Batch Export (Frame Step)")

        box_batch.prop(settings, "batch_enable")

        col = box_batch.column()
        col.enabled = settings.batch_enable
        col.prop(settings, "batch_step")
        col.prop(settings, "batch_use_overlap")

        sub = col.column()
        sub.enabled = settings.batch_use_overlap and settings.batch_enable
        sub.prop(settings, "batch_overlap_frames")

        col.separator()
        col.operator("export.orbx_prepare_batch", icon='PRESET')

        if settings.batch_enable and len(settings.batch_chunks) > 0:
            total = len(settings.batch_chunks)
            idx = settings.batch_chunk_index
            idx_clamped = min(idx, total)
            col.label(text=f"Manual Chunk: {idx_clamped}/{total}")
            if idx < total:
                current = settings.batch_chunks[idx]
                col.label(text=f"Frames: {current.start}–{current.end}")

        col.operator("export.orbx_export_next_chunk", icon='EXPORT')

        # Auto-batch options
        layout.separator()
        box_auto = layout.box()
        box_auto.label(text="Auto Batch (Experimental)")
        box_auto.prop(settings, "batch_auto")
        box_auto.prop(settings, "batch_delay")
        box_auto.prop(settings, "batch_cooldown")

        row = box_auto.row()
        row.operator("export.orbx_auto_batch", icon='TIME')
        row.operator("export.orbx_auto_batch_stop", icon='CANCEL')

        # Status display
        if _auto_state["running"]:
            total = len(_auto_state["chunks"])
            idx = _auto_state["index"]
            status = _auto_state["status"]
            box_auto.label(text=f"Status: {status} (chunk {idx+1}/{total})")
        else:
            box_auto.label(text="Status: idle")


# --------------------------------------------------------
# Registration
# --------------------------------------------------------

classes = (
    OrbxBatchChunk,
    OrbxExportSettings,
    EXPORT_OT_orbx_smart,
    EXPORT_OT_orbx_prepare_batch,
    EXPORT_OT_orbx_export_next_chunk,
    EXPORT_OT_orbx_auto_batch,
    EXPORT_OT_orbx_auto_batch_stop,
    RENDER_PT_orbx_export,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.orbx_export_settings = PointerProperty(
        type=OrbxExportSettings
    )


def unregister():
    global _auto_state
    _auto_state["running"] = False  # stop timer gracefully
    del bpy.types.Scene.orbx_export_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
