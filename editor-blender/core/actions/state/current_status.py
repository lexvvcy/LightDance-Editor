import bpy

from ....properties.types import LightType
from ...log import logger
from ...models import (
    ControlMapElement,
    ControlMapElement_MODIFIED,
    CtrlData,
    FiberData,
    LEDData,
)
from ...states import state
from ...utils.algorithms import binary_search


def calculate_current_status_index() -> int:
    if not bpy.context:
        return 0  # Won't actually happen
    return binary_search(state.control_start_record, bpy.context.scene.frame_current)


def update_current_status_by_index():
    """Update current status by index and set ld_color and ld_effect.

    Supports both old table (ControlMapElement) and new table
    (ControlMapElement_MODIFIED).
    """
    if not bpy.context:
        return

    index = state.current_control_index

    control_map = state.control_map
    if not state.control_record:
        return
    control_id = state.control_record[index]

    current_control_map = control_map.get(control_id)
    if current_control_map is None:
        return

    is_modified = isinstance(current_control_map, ControlMapElement_MODIFIED)

    # fade: old table uses .fade, new table uses .fade_for_new_status
    fade = (
        current_control_map.fade_for_new_status
        if is_modified
        else current_control_map.fade  # type: ignore[union-attr]
    )
    setattr(bpy.context.window_manager, "ld_fade", fade)
    setattr(bpy.context.window_manager, "ld_start", current_control_map.start)

    # For old table, update the legacy state fields as before
    if not is_modified:
        old_frame: ControlMapElement = current_control_map  # type: ignore[assignment]
        state.current_status = old_frame.status
        state.current_led_status = old_frame.led_status

    show_dancer_dict = dict(zip(state.dancer_names, state.show_dancers))
    for dancer in state.dancers_array:
        if not show_dancer_dict.get(dancer.name, False):
            continue

        dancer_part_objects = state.dancer_part_objects_map.get(dancer.name)
        if dancer_part_objects is None:
            continue
        part_objects = dancer_part_objects[1]

        # Get dancer-level status depending on table type
        dancer_status_raw = current_control_map.status.get(dancer.name)
        if dancer_status_raw is None:
            continue

        for part_name, part_obj in part_objects.items():
            try:
                light_type = getattr(part_obj, "ld_light_type")
            except ReferenceError:
                logger.error(
                    f"StructRNA of part object {part_obj} with a part name {part_name} has been removed"
                )
                continue

            # ── Extract part_data and bulb_data depending on table type ──
            if is_modified:
                ctrl_data: CtrlData | None = dancer_status_raw.get(part_name)  # type: ignore[union-attr]
                if ctrl_data is None:
                    # None = no effect for this part, skip
                    continue
                part_data = ctrl_data.part_data
                bulb_data = ctrl_data.bulb_data
            else:
                # Old table: separate status and led_status dicts
                old_dancer_status = dancer_status_raw  # DancerStatus
                part_data = old_dancer_status.get(part_name)  # type: ignore[union-attr]
                if part_data is None:
                    continue
                old_led = current_control_map.led_status.get(dancer.name, {})  # type: ignore[union-attr]
                bulb_data = old_led.get(part_name)

            # ── Apply to Blender objects ──
            match light_type:
                case LightType.FIBER.value:
                    if not isinstance(part_data, FiberData):
                        continue

                    color = state.color_map.get(part_data.color_id)
                    if color is not None:
                        setattr(part_obj, "ld_color", color.name)
                    setattr(part_obj, "ld_alpha", part_data.alpha)

                case LightType.LED.value:
                    if not isinstance(part_data, LEDData):
                        continue

                    effect_id = part_data.effect_id
                    if effect_id == -1:
                        setattr(part_obj, "ld_effect", "no-change")
                    elif effect_id == 0:
                        setattr(part_obj, "ld_effect", "[Bulb Color]")
                        if bulb_data is not None:
                            for led_bulb_obj in part_obj.children:
                                pos: int = getattr(led_bulb_obj, "ld_led_pos")
                                if pos < len(bulb_data):
                                    data = bulb_data[pos]
                                    if data.color_id != -1:
                                        color = state.color_map.get(data.color_id)
                                        if color is not None:
                                            setattr(
                                                led_bulb_obj, "ld_color", color.name
                                            )
                                        else:
                                            setattr(
                                                led_bulb_obj, "ld_color", "[gradient]"
                                            )
                                    else:
                                        setattr(led_bulb_obj, "ld_color", "[gradient]")
                                    setattr(led_bulb_obj, "ld_alpha", data.alpha)
                    else:
                        effect = state.led_effect_id_table.get(effect_id)
                        if effect is not None:
                            setattr(part_obj, "ld_effect", effect.name)

                    setattr(part_obj, "ld_alpha", part_data.alpha)

                case _:
                    pass
