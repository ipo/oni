# ONI

The `oni` library helps balance systems of machines in the game Oxygen Not Included. For details, see the interactive demo notebook here:

[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/ChrisBeaumont/oni/master?filepath=doc%2FONI%20Guide.ipynb)

## Installation

``pip install oni``

## Acknowledgements

Most of the data for machines and resources comes from [Oxygen Not Included Database](http://oni-db.com), [oni-assistant](http://oni-assistant.com), and the [Oxygen Not Included Wiki](https://oxygennotincluded.gamepedia.com/Oxygen_Not_Included_Wiki). Thanks to those tools. Errors in the data are likely my fault, introduced during transcription.

## Game data

Machine and resource data is extracted directly from the current game files
with `tools/extract_oni_data.py`, which parses the game's StreamingAssets YAML
and a decompiled `Assembly-CSharp.dll` (via `ilspycmd`). Extracted raw data
lives in `oni/data/` (`elements.json`, `buildings.json`, `recipes.json`);
`oni/machine.yaml` and the liquid/gas lists in `oni/resource.py` are derived
from it. Resource names are internal element ids (e.g. `DirtyWater` is
Polluted Water, `Methane` is Natural Gas, `Carbon` is Coal).
