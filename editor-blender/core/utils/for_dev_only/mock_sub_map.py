from enum import Enum
from random import randint

from ....core.actions.state.control_map import (
    add_control,
    delete_control,
    update_control,
)
from ....core.actions.state.pos_map import add_pos, delete_pos, update_pos
from ....core.models import (
    ControlMapElement_MODIFIED,
    ControlMapStatus_MODIFIED,
    CtrlData,
    FiberData,
    LEDBulbData,
    LEDData,
    Location,
    PartType,
    Position,
    PosMapElement,
    PosMapStatus,
    Revision,
    Rotation,
)
from ....core.states import state


class SubType(Enum):
    CreateFrames = (0,)
    UpdateFrames = (1,)
    DeleteFrames = 2


from ....core.utils.convert import (
    SubPositionFrame,
    color_query_to_state,
    control_frame_query_to_state,
    control_frame_sub_to_query,
    effect_list_data_sub_to_query,
    led_record_sub_to_state_item,
    pos_frame_query_to_state,
    pos_frame_sub_to_query,
)


def mock_sub_pos_map(
    type: SubType,
    id: int = 0,
    positionData: list[list[float] | None] = [],
    start: int = 0,
):
    """
    這個函數是用來代替pos_agent.add/save/delete_frame的。
    在pos_editor.py的add/save/delete_pos_frame使用。
    add_frame => mock...(SubType.CreateFrames, start)*
    save_frame => ...(SubType.UpdateFrames, id, positionData, start)
    delete_frame => ...(SubType.DeleteFrames, id)

    如果狀態是None，對應的positionData.append(None)
    *舊版的add_pos()有positionData這個引數，
    但因為新版的add_pos加入的狀態已經固定了(都是None)，因此不需要輸入new_pos_frame。
    """
    cur_max_id = max(state.pos_record)
    next_id = cur_max_id + 1

    new_pos_frame = None
    if type == SubType.UpdateFrames:
        pos_stat: PosMapStatus = {}
        new_zip = zip(state.dancer_names, positionData)
        for dancer, pos_data in new_zip:
            if pos_data is None:
                pos_stat[dancer] = None
            else:
                pos_stat[dancer] = Position(
                    location=Location(x=pos_data[0], y=pos_data[1], z=pos_data[2]),
                    rotation=Rotation(rx=pos_data[3], ry=pos_data[4], rz=pos_data[5]),
                )

        new_pos_frame = PosMapElement(
            start=start,
            rev=Revision(meta=randint(1, 300), data=randint(1, 300)),
            pos=pos_stat,
        )
    elif type == SubType.CreateFrames:
        pos_stat: PosMapStatus = {}
        for dancer in state.dancer_names:
            pos_stat[dancer] = None
        new_pos_frame = PosMapElement(
            start=start,
            rev=Revision(meta=randint(1, 300), data=randint(1, 300)),
            pos=pos_stat,
        )

    match type:
        case SubType.CreateFrames:
            add_pos(next_id, new_pos_frame)  # type: ignore
        case SubType.UpdateFrames:
            update_pos(id, new_pos_frame)  # type: ignore
        case SubType.DeleteFrames:
            delete_pos(id)  # type: ignore


def mock_sub_control_map(
    type: SubType,
    id: int = 0,
    fade_for_new_status=False,
    controlData=None,
    ledControlData=None,
    fadeData=None,
    start: int = 0,
):
    """
    這個函數是用來代替control_agent.add/save/delete_frame的。
    在control_editor.py的add/save/delete_control_frame使用。
    add_frame => mock...(SubType.CreateFrames, fade_for_new_status, start)*
    save_frame => ...(SubType.UpdateFrames, id, fade_for_new_status, controlData, ledControlData, fadeData, start)**
    delete_frame => ...(SubType.DeleteFrames, id)

    如果狀態是None，對應的part(LED)ControlData.append(None)
    *舊版的add_pos()有controlData跟ledControlData這個引數，
    但因為新版的add_pos加入的狀態已經固定了(都是None)，因此不需要輸入它們。
    **save_frame需要多加fadeData(list[list[bool|None]])
    """
    cur_max_id = max(state.control_record)
    next_id = cur_max_id + 1

    new_zip = []
    for i in range(len(state.dancer_names)):
        dancer = state.dancer_names[i]
        new_sublist = []
        for j in range(len(state.dancers[dancer])):
            part = state.dancers[dancer][j]
            new_sublist.append((part, controlData[i][j], ledControlData[i][j], fadeData[i][j]))  # type: ignore
        new_zip.append((dancer, new_sublist))

    new_ctrl_frame = None
    if type == SubType.UpdateFrames:
        ctrl_stat: ControlMapStatus_MODIFIED = {}
        for dancer, ctrl_dancer_data in new_zip:
            ctrl_stat[dancer] = {}
            for part, ctrl_data, led_ctrl_data, fade in ctrl_dancer_data:
                if ctrl_data is None:
                    ctrl_stat[dancer][part] = None
                elif state.part_type_map[part] == PartType.FIBER:
                    part_data = FiberData(color_id=ctrl_data[0], alpha=ctrl_data[1])
                    led = []
                    ctrl_stat[dancer][part] = CtrlData(
                        part_data=part_data, bulb_data=led, fade=fade
                    )
                else:
                    part_data = LEDData(effect_id=ctrl_data[0], alpha=ctrl_data[1])
                    led = []
                    for colorid, alpha in led_ctrl_data:
                        rgb = state.color_map[colorid].rgb
                        led.append(LEDBulbData(color_id=colorid, alpha=alpha, rgb=rgb))
                    ctrl_stat[dancer][part] = CtrlData(
                        part_data=part_data, bulb_data=led, fade=fade
                    )
        new_ctrl_frame = ControlMapElement_MODIFIED(
            start=start,
            fade_for_new_status=fade_for_new_status,
            rev=Revision(meta=randint(1, 300), data=randint(1, 300)),
            status=ctrl_stat,
        )
    elif type == SubType.CreateFrames:
        ctrl_stat: ControlMapStatus_MODIFIED = {}
        for dancer in state.dancer_names:
            ctrl_stat[dancer] = {}
            for part in state.dancers[dancer]:
                ctrl_stat[dancer][part] = None
        new_ctrl_frame = ControlMapElement_MODIFIED(
            start=start,
            fade_for_new_status=fade_for_new_status,
            rev=Revision(meta=randint(1, 300), data=randint(1, 300)),
            status=ctrl_stat,
        )

    match type:
        case SubType.CreateFrames:
            add_control(next_id, new_ctrl_frame)  # type: ignore
        case SubType.UpdateFrames:
            update_control(id, new_ctrl_frame)  # type: ignore
        case SubType.DeleteFrames:
            delete_control(id)


def inject_partial_test_frames():
    """Insert test frames with partial data for testing partial delete.

    Creates 2 frames:
      - Frame A (start=99999): dancer 0,1 have data, dancer 2,3 = None
      - Frame B (start=99998): dancer 0 has data, dancer 1,2,3 = None

    Call this after init (e.g. after tmp_format_conv) to have ready-made
    partial frames for testing delete logic.
    """
    from ....core.log import logger

    fallback_color_id = next(iter(state.color_map), 0)
    cur_max_id = max(state.control_record) if state.control_record else 0

    for frame_idx, (start_time, dancers_with_data) in enumerate(
        [(1500, [0, 1]), (3500, [0])]
    ):
        fid = cur_max_id + 1 + frame_idx
        ctrl_stat: ControlMapStatus_MODIFIED = {}
        for di, dancer_name in enumerate(state.dancer_names):
            ctrl_stat[dancer_name] = {}
            for part_name in state.dancers[dancer_name]:
                if di in dancers_with_data:
                    if state.part_type_map[part_name] == PartType.FIBER:
                        ctrl_stat[dancer_name][part_name] = CtrlData(
                            part_data=FiberData(color_id=fallback_color_id, alpha=128),
                            bulb_data=[],
                            fade=False,
                        )
                    else:
                        ctrl_stat[dancer_name][part_name] = CtrlData(
                            part_data=LEDData(effect_id=-1, alpha=128),
                            bulb_data=[],
                            fade=False,
                        )
                else:
                    ctrl_stat[dancer_name][part_name] = None

        frame = ControlMapElement_MODIFIED(
            start=start_time,
            fade_for_new_status=False,
            rev=Revision(meta=0, data=0),
            status=ctrl_stat,
        )
        # Write directly to state (bypassing add_control which needs state.ready)
        state.control_map[fid] = frame  # type: ignore
        state.control_map_MODIFIED[fid] = frame
        logger.info(
            f"[inject_partial_test] id={fid} start={start_time} "
            f"dancers_with_data={dancers_with_data}"
        )

    # Rebuild control_record sorted by start time
    control_record = list(state.control_map.keys())
    control_record.sort(key=lambda _id: state.control_map[_id].start)
    state.control_record = control_record
    state.control_start_record = [
        state.control_map[_id].start for _id in control_record
    ]
