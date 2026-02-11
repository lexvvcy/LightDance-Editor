from ...log import logger
from ...models import (
    ControlMap,
    ControlMapElement,
    ControlMapElement_MODIFIED,
    ControlRecord,
    EditMode,
    MapID,
)
from ...states import state
from ...utils.notification import notify
from ...utils.ui import redraw_area
from ..property.animation_data import (
    init_ctrl_keyframes_from_state,
    reset_control_frames_and_fade_sequence,
    reset_ctrl_rev,
)
from .current_status import calculate_current_status_index

# Accept both old and new table frame types for backward compatibility
ControlFrame = ControlMapElement | ControlMapElement_MODIFIED


def set_control_map(control_map: ControlMap):
    state.control_map = control_map


def set_control_record(control_record: ControlRecord):
    state.control_record = control_record


def add_control(id: MapID, frame: ControlFrame):
    logger.info(f"Add control {id} at {frame.start}")

    control_map_updates = state.control_map_updates
    control_map_updates.added[id] = frame  # type: ignore

    if (
        state.edit_state == EditMode.EDITING
        or not state.preferences.auto_sync
        or not state.ready
    ):
        state.control_map_pending = True
        redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    else:
        apply_control_map_updates()
        notify("INFO", f"Added control frame {id}")


def delete_control(id: MapID):
    logger.info(f"Delete control {id}")

    control_map_updates = state.control_map_updates

    # Check if it's a pending addition (not yet applied to control_map)
    if id in control_map_updates.added:
        control_map_updates.added.pop(id)
        if not (
            control_map_updates.added
            or control_map_updates.updated
            or control_map_updates.deleted
        ):
            state.control_map_pending = False
        return

    old_frame = state.control_map.get(id)
    if old_frame is None:
        return

    # Remove from updated if present
    control_map_updates.updated.pop(id, None)

    control_map_updates.deleted[id] = old_frame.start

    if (
        state.edit_state == EditMode.EDITING
        or not state.preferences.auto_sync
        or not state.ready
    ):
        state.control_map_pending = True
        redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    else:
        apply_control_map_updates()
        notify("INFO", f"Deleted control frame {id}")


def update_control(id: MapID, frame: ControlFrame):
    logger.info(f"Update control {id} at {frame.start}")

    control_map_updates = state.control_map_updates

    # If it was a pending addition, update it there
    if id in control_map_updates.added:
        control_map_updates.added[id] = frame  # type: ignore
        return

    # If already pending update, preserve the original old_start
    if id in control_map_updates.updated:
        old_start = control_map_updates.updated[id][0]
        control_map_updates.updated[id] = (old_start, frame)  # type: ignore
        return

    # New update: record old start from control_map
    old_frame = state.control_map.get(id)
    old_start = old_frame.start if old_frame else frame.start
    control_map_updates.updated[id] = (old_start, frame)  # type: ignore

    if (
        state.edit_state == EditMode.EDITING
        or not state.preferences.auto_sync
        or not state.ready
    ):
        state.control_map_pending = True
        redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    else:
        apply_control_map_updates()
        notify("INFO", f"Updated control frame {id}")


def apply_control_map_updates():
    if not state.ready:
        logger.warning("[apply_control_map_updates] state.ready is False, skipping")
        return

    control_map_updates = state.control_map_updates

    added_ids = list(control_map_updates.added.keys())
    updated_ids = list(control_map_updates.updated.keys())
    deleted_ids = list(control_map_updates.deleted.keys())
    logger.info(
        f"[apply_control_map_updates] added={added_ids}, "
        f"updated={updated_ids}, deleted={deleted_ids}"
    )

    # Update control map state (both old table and MODIFIED)
    for id, frame in control_map_updates.added.items():
        state.control_map[id] = frame  # type: ignore
        if isinstance(frame, ControlMapElement_MODIFIED):
            state.control_map_MODIFIED[id] = frame
    for id, (_, frame) in control_map_updates.updated.items():
        state.control_map[id] = frame  # type: ignore
        if isinstance(frame, ControlMapElement_MODIFIED):
            state.control_map_MODIFIED[id] = frame
    for id in list(control_map_updates.deleted.keys()):
        state.control_map.pop(id, None)
        state.control_map_MODIFIED.pop(id, None)

    # Update control record (sorted by start time)
    control_record = list(state.control_map.keys())
    control_record.sort(key=lambda _id: state.control_map[_id].start)
    control_start_record = [state.control_map[_id].start for _id in control_record]

    state.control_record = control_record
    state.control_start_record = control_start_record

    # Update current control index
    state.current_control_index = calculate_current_status_index()
    state.control_map_pending = False

    control_map_updates.added.clear()
    control_map_updates.updated.clear()
    control_map_updates.deleted.clear()

    logger.info(
        f"[apply_control_map_updates] control_record={control_record}, "
        f"control_map_MODIFIED keys={sorted(state.control_map_MODIFIED.keys())}"
    )

    # Dump control map for debugging
    _dump_control_map()

    # Full refresh: scene-level markers + per-part animation keyframes
    init_ctrl_keyframes_from_state()

    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})


def _dump_control_map():
    """Print a concise summary of control_map_MODIFIED for debugging."""
    for map_id in sorted(
        state.control_map_MODIFIED.keys(),
        key=lambda k: state.control_map_MODIFIED[k].start,
    ):
        frame = state.control_map_MODIFIED[map_id]
        parts_summary: list[str] = []
        for dancer_name, parts in frame.status.items():
            none_count = sum(1 for v in parts.values() if v is None)
            total = len(parts)
            if none_count == total:
                parts_summary.append(f"{dancer_name}=ALL_NONE")
            elif none_count > 0:
                parts_summary.append(f"{dancer_name}={total - none_count}/{total}")
            else:
                parts_summary.append(f"{dancer_name}=ALL_SET")
        logger.info(
            f"[CTRL_MAP] id={map_id} start={frame.start} "
            f"fade={frame.fade_for_new_status} | {', '.join(parts_summary)}"
        )
