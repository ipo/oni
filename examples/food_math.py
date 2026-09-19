#!/usr/bin/env python3
"""Food math: what does a quality +4 (or better) diet cost to farm?

For every food of quality +4 or better in the current game data, this
example walks the recipe chain recursively down to its terminal inputs
and reports, per 1000 kcal of final food (one duplicant eats exactly
1000 kcal per cycle, so "per 1000 kcal" == "per duplicant per cycle"):

  * which farm plants are needed and how many of each,
  * how much irrigation/fertilization those plants consume,
  * any non-farm inputs (water for the Microbe Musher, animal products
    such as meat/fish/eggs/tallow that require ranching, etc.),
  * how much time the cooking stations spend (and the power / natural
    gas that implies).

Assumptions, matching how the question is usually asked:

  * Domesticated plants only, no farm-station fertilizer boost
    (baseline growth rate), plants tended perfectly.
  * Wild plants and wild critters are not harvested; anything that
    cannot be grown on a farm plot is listed as an external input.
  * When a recipe offers alternative ingredients (e.g. Sleet Wheat
    Grain *or* Fern Meal) the first (base-game) option is costed and
    the alternatives are listed as notes.

Data comes from oni/data/*.json (extracted from the game files by
tools/extract_oni_data.py). Run from the repo root:

    python3 examples/food_math.py
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "oni", "data")

SECONDS_PER_CYCLE = 600
MIN_QUALITY = 4

# The Gas Range burns piped natural gas while cooking. Its FUEL_TAG is a
# private const in GourmetCookingStationConfig.cs (Tag("Methane")), which
# the extractor cannot resolve statically, so it is spelled out here.
GAS_RANGE_METHANE_KG_S = 0.1

# Sim elements that are actually critter products, not mineable/farmable
# resources (Tallow is dropped by Seals, see BaseSealConfig.cs).
CRITTER_SOURCED_ELEMENTS = {"Tallow"}


def load(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


class FoodCalculator:
    """Recursively resolves food recipes to farm and external inputs."""

    def __init__(self):
        self.foods = load("foods.json")
        self.plants = load("plants.json")
        recipes = load("recipes.json")
        self.elements = load("elements.json")
        self.buildings = load("buildings.json")

        # output material -> [(fabricator, recipe, result)], in file order
        self.producers = {}
        for fabricator, recs in recipes.items():
            for rec in recs:
                for res in rec["results"]:
                    mat = res["material"]
                    if isinstance(mat, str):
                        self.producers.setdefault(mat, []).append(
                            (fabricator, rec, res))

        # crop id -> (plant id, plant data)
        self.crop_plant = {}
        for pid, p in self.plants.items():
            # Skip "crops" that are plain sim elements (e.g. Hydrocactus
            # grows Water): as recipe inputs those are raw resources.
            if p.get("crop") and p["crop"] not in self.elements:
                self.crop_plant[p["crop"]] = (pid, p)

    # -- accumulation --------------------------------------------------

    @staticmethod
    def new_totals():
        return {
            "plants": {},     # plant id -> plant-cycles (== plants per dupe)
            "resources": {},  # element id -> kg
            "external": {},   # material id -> units
            "stations": {},   # fabricator id -> active seconds
            "notes": [],
        }

    @staticmethod
    def merge(dst, src, scale=1.0):
        for key in ("plants", "resources", "external", "stations"):
            for k, v in src[key].items():
                dst[key][k] = dst[key].get(k, 0.0) + v * scale
        dst["notes"].extend(src["notes"])

    @staticmethod
    def _first(material, amount, notes, where):
        """Pick the first option of an alternatives array."""
        if isinstance(material, list):
            amounts = amount if isinstance(amount, list) \
                else [amount] * len(material)
            alts = [f"{a:g} {m}" for m, a in zip(material[1:], amounts[1:])]
            notes.append(f"{where}: alternatives not costed: "
                         + ", ".join(alts))
            return material[0], amounts[0]
        return material, amount

    # -- recursive resolution ------------------------------------------

    def resolve(self, material, amount, totals, chain, depth=0):
        """Resolve `amount` units/kg of `material` into totals."""
        pad = "  " * depth

        if material in self.crop_plant:
            pid, p = self.crop_plant[material]
            per_harvest = p.get("units_per_harvest") or 1
            grow_s = p.get("growth_seconds") or 0.0
            plant_seconds = amount / per_harvest * grow_s
            plant_cycles = plant_seconds / SECONDS_PER_CYCLE
            totals["plants"][pid] = totals["plants"].get(pid, 0.0) \
                + plant_cycles
            for c in p.get("consumes", []):
                kg = c["kg_per_second"] * plant_seconds
                totals["resources"][c["material"]] = \
                    totals["resources"].get(c["material"], 0.0) + kg
            name = p.get("name", pid)
            chain.append(f"{pad}{amount:g} {material} <- "
                         f"{plant_cycles:.2f} {name} plant(s)")
            return

        if material in self.elements and \
                material not in CRITTER_SOURCED_ELEMENTS:
            totals["resources"][material] = \
                totals["resources"].get(material, 0.0) + amount
            chain.append(f"{pad}{amount:g} kg {material}")
            return

        if material in self.producers:
            fabricator, rec, res = self.producers[material][0]
            extra = len(self.producers[material]) - 1
            if extra:
                totals["notes"].append(
                    f"{material}: {extra} more recipe(s) not costed")
            batches = amount / res["amount"]
            totals["stations"][fabricator] = \
                totals["stations"].get(fabricator, 0.0) \
                + batches * rec["time"]
            chain.append(f"{pad}{amount:g} {material} <- "
                         f"{batches:g}x {fabricator} recipe")
            for ing in rec["ingredients"]:
                if not isinstance(ing["material"], (str, list)):
                    totals["notes"].append(
                        f"{material}: unresolved ingredient in "
                        f"{fabricator} recipe (skipped)")
                    continue
                imat, iamt = self._first(ing["material"], ing["amount"],
                                         totals["notes"], material)
                self.resolve(imat, iamt * batches, totals, chain, depth + 1)
            return

        # Not a crop, not craftable in the kitchen chain, not an element:
        # an animal product or something else that must be sourced outside
        # the farm (ranching, shearing, ...).
        totals["external"][material] = \
            totals["external"].get(material, 0.0) + amount
        chain.append(f"{pad}{amount:g} {material} (external)")

    def food_chain(self, food_id):
        """Resolve one unit of food to its terminal inputs."""
        totals = self.new_totals()
        chain = []
        self.resolve(food_id, 1.0, totals, chain)
        return totals, chain

    # -- reporting -----------------------------------------------------

    def station_overhead(self, stations):
        """Power (kJ), natural gas (kg) and heat (kDTU) for station time."""
        power_kj = gas_kg = heat_kdtu = 0.0
        for fab, seconds in stations.items():
            b = self.buildings.get(fab, {})
            power_kj += (b.get("power_consumption") or 0) * seconds / 1000
            heat_kdtu += ((b.get("self_heat_kw") or 0)
                          + (b.get("exhaust_heat_kw") or 0)) * seconds
            if fab == "GourmetCookingStation":
                gas_kg += GAS_RANGE_METHANE_KG_S * seconds
        return power_kj, gas_kg, heat_kdtu

    def report(self, food_id):
        info = self.foods[food_id]
        totals, chain = self.food_chain(food_id)
        scale = 1000.0 / info["kcal"]
        name = info.get("name", food_id)

        lines = []
        dlc = f"  [{info['dlc']}]" if info.get("dlc") else ""
        lines.append(f"== {name} ({food_id}) - quality +{info['quality']}, "
                     f"{info['kcal']:.0f} kcal/unit{dlc}")
        lines.append("   recipe for 1 unit:")
        lines.extend(f"   {c}" for c in chain)
        lines.append("   per 1000 kcal (one duplicant-cycle):")

        if totals["plants"]:
            parts = [f"{n * scale:.2f} {self.plants[p].get('name', p)}"
                     for p, n in sorted(totals["plants"].items())]
            lines.append(f"     plants:     {' + '.join(parts)}")
        if totals["resources"]:
            parts = [f"{kg * scale:.1f} kg {r}"
                     for r, kg in sorted(totals["resources"].items())]
            lines.append(f"     farm input: {' + '.join(parts)}")
        if totals["external"]:
            parts = [f"{n * scale:.2f} {m.removesuffix('Config')}"
                     for m, n in sorted(totals["external"].items())]
            lines.append(f"     external:   {' + '.join(parts)}"
                         "  (ranching/shearing required)")
        power_kj, gas_kg, heat_kdtu = self.station_overhead(
            {k: v * scale for k, v in totals["stations"].items()})
        st = ", ".join(f"{f} {s * scale:.0f}s"
                       for f, s in sorted(totals["stations"].items()))
        lines.append(f"     kitchen:    {st}")
        extra = f"{power_kj:.1f} kJ power, {heat_kdtu:.0f} kDTU heat"
        if gas_kg:
            extra += f", {gas_kg * 1000:.0f} g natural gas"
        lines.append(f"                  -> {extra} per 1000 kcal")
        for note in totals["notes"]:
            lines.append(f"     note: {note}")
        return lines


def main():
    calc = FoodCalculator()
    foods = [(fid, f) for fid, f in calc.foods.items()
             if f["quality"] >= MIN_QUALITY and f["kcal"] > 0]
    foods.sort(key=lambda kv: (-kv[1]["quality"], -kv[1]["kcal"]))

    print(f"Foods of quality +{MIN_QUALITY} or better, resolved to farm "
          "inputs per 1000 kcal.")
    print("Domesticated plants, no fertilizer boost; one duplicant eats "
          "1000 kcal/cycle,")
    print("so all per-1000-kcal numbers are also per-duplicant-per-cycle.\n")

    # Summary table first, then the detailed chains.
    header = ("Food", "Q", "kcal", "Plants per dupe", "Farm inputs (kg)",
              "External (units)")
    rows = []
    for fid, info in foods:
        totals, _ = calc.food_chain(fid)
        scale = 1000.0 / info["kcal"]
        res = "; ".join(f"{kg * scale:.1f} {r}"
                        for r, kg in sorted(totals["resources"].items()))
        ext = "; ".join(f"{n * scale:.2f} {m}"
                        for m, n in sorted(totals["external"].items()))
        ext = ext.replace("GingerConfig", "Ginger")
        plants = "; ".join(
            f"{n * scale:.2f} {calc.plants[p].get('name', p)}"
            for p, n in sorted(totals["plants"].items()))
        rows.append((info.get("name", fid), f"+{info['quality']}",
                     f"{info['kcal']:.0f}", plants, res, ext))

    widths = [max(len(r[i]) for r in rows + [header]) for i in range(6)]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))

    print("\n\nDetailed recipe chains\n")
    for fid, _info in foods:
        print("\n".join(calc.report(fid)))
        print()


if __name__ == "__main__":
    main()
