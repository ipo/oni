# Oxygen Not Included data and calculator

`oni` is a Python library for balancing Oxygen Not Included resource systems.
This repository also contains a reproducible, game-data-backed export of ONI
elements, buildings, recipes, plants, food, and critters.

## Installation

``pip install oni``

## Game data

The exports originate from a matching installed copy of ONI and its
`Assembly-CSharp.dll` source:

- `StreamingAssets` supplies element definitions and localized names.
- The assembly source supplies building components, recipes, food, plants,
  and critter behaviour/configuration.

Run the extractor against those two inputs to refresh the generated data:

```bash
python3 tools/extract_oni_data.py \
  --game-dir /path/to/OxygenNotIncluded \
  --source-dir /path/to/assembly-source \
  --out-dir oni/data
python3 tools/build_conversions.py --data-dir oni/data
```

The raw exports are in `oni/data/`: `elements.json`, `buildings.json`,
`recipes.json`, `foods.json`, `plants.json`, and the normalized building
conversion data in `conversions.json`. `oni/critter.yaml` holds per-critter
lifecycle, ranching space, movement, temperature, reproduction, and
statically traceable diet/conversion data.

Resource names use internal element IDs: for example, `DirtyWater` is Polluted
Water, `Methane` is Natural Gas, and `Carbon` is Coal.
