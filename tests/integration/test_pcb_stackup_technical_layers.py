"""Regression: solder mask and silk layers in a stackup are not dielectrics.

``pcb_set_stackup`` wrote every non-copper layer as ``(layer dielectric N``, so a
stackup that lists F.Mask/B.Mask came back from KiCad as two extra dielectric
layers (with FR4 defaults) and no mask layers. The impedance helper then took a
0.01 mm mask as the dielectric under an outer trace, and a mask given without a
material inherited the model default "Copper" and counted as a copper layer.
KiCad's own form is ``(layer "F.Mask" (type "Top Solder Mask") ...)``.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

LAYERS = [
    {"name": "F_SilkS", "thickness_mm": 0.01},
    {"name": "F_Mask", "thickness_mm": 0.01},
    {"name": "F_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
    {
        "name": "dielectric_1",
        "type": "core",
        "thickness_mm": 1.51,
        "material": "FR4",
        "epsilon_r": 4.5,
    },
    {"name": "B_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
    {
        "name": "B_Mask",
        "type": "Bottom Solder Mask",
        "thickness_mm": 0.01,
        "material": "LPI",
    },
]


def _stackup_blocks(pcb_text: str) -> dict[str, str]:
    start = pcb_text.index("(stackup")
    stackup = pcb_text[start : pcb_text.index("(copper_finish", start)]
    blocks: dict[str, str] = {}
    for match in re.finditer(
        r'\(layer ("[^"]+"|dielectric \d+)[^\n]*\n(.*?)\n\t*\)', stackup, re.S
    ):
        blocks[match.group(1).strip('"')] = match.group(2)
    return blocks


@pytest.mark.anyio
async def test_stackup_writes_mask_paste_and_silk_as_kicad_technical_layers(
    sample_project: Path,
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    configured = await call_tool_text(server, "pcb_set_stackup", {"layers": LAYERS})
    assert "Configured stackup with 6 layers." in configured, configured
    blocks = _stackup_blocks((sample_project / "demo.kicad_pcb").read_text(encoding="utf-8"))

    assert list(blocks) == [
        "F.SilkS",
        "F.Mask",
        "F.Cu",
        "dielectric 1",
        "B.Cu",
        "B.Mask",
    ], blocks
    assert '(type "Top Silk Screen")' in blocks["F.SilkS"]
    assert '(type "Top Solder Mask")' in blocks["F.Mask"]
    assert "(thickness 0.0100)" in blocks["F.Mask"]
    # No material given: the mask must not inherit the model's "Copper" default.
    assert "(material" not in blocks["F.Mask"]
    assert '(type "Bottom Solder Mask")' in blocks["B.Mask"]
    assert '(material "LPI")' in blocks["B.Mask"]
    assert '(type "core")' in blocks["dielectric 1"]

    impedance = await call_tool_text(
        server, "pcb_get_impedance_for_trace", {"width_mm": 0.3, "layer_name": "F_Cu"}
    )
    assert "- Trace type: microstrip" in impedance
    assert "- Reference dielectric height: 1.5100 mm" in impedance, impedance
