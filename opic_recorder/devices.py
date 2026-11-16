"""List input devices without coupling to the GUI."""

from __future__ import annotations


def microphone_choices(audio) -> tuple[list[tuple[int, str]], int]:
    """One endpoint list, without exposing the same hardware through every driver."""
    hosts = audio.query_hostapis()
    inputs = [
        (i, item) for i, item in enumerate(audio.query_devices()) if item["max_input_channels"] > 0
    ]
    if not inputs:
        return [], -1
    priority = {"Windows WASAPI": 1, "MME": 0, "Windows DirectSound": 2, "Windows WDM-KS": 3}
    host = min(
        (item["hostapi"] for _, item in inputs), key=lambda i: priority.get(hosts[i]["name"], 4)
    )
    selected = [(i, item) for i, item in inputs if item["hostapi"] == host]
    # 기본 장치의 별칭을 제거하여 동일한 마이크가 중복 표시되지 않게 한다.
    selected = [
        (i, item)
        for i, item in selected
        if not item["name"].startswith(
            (
                "Microsoft 사운드 매퍼",
                "Microsoft Sound Mapper",
                "주 사운드 캡처",
                "Primary Sound Capture",
            )
        )
    ]
    default = hosts[host].get("default_input_device", audio.default.device[0])
    if selected and default not in [i for i, _ in selected]:
        default = selected[0][0]
    choices = []
    counts = {}
    for index, item in sorted(selected, key=lambda pair: pair[0] != default):
        name = item["name"].strip()
        if "USB Advanced Audio Device" in name:
            name = "USB 마이크"
        elif name.startswith(
            ("머리에 거는 수화기(", "머리에 거는 수화기 (", "Headset (")
        ) and name.endswith(")"):
            name = name[name.index("(") + 1 : -1] + " 마이크"
        counts[name] = counts.get(name, 0) + 1
        label = name if counts[name] == 1 else f"{name} {counts[name]}"
        if index == default:
            label += " (기본)"
        choices.append((index, label))
    return choices, default
