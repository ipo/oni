#!/usr/bin/env python3
"""Hydra-style oxygen generation: how far does one electrolyzer go?

A "hydra" is the classic ONI build where an Electrolyzer's output is
perfectly separated: oxygen is pumped to the colony and the hydrogen is
burned in Hydrogen Generators to (more than) power the whole thing.

This example answers, for one Electrolyzer with free water and free
sinks for any leftover oxygen/hydrogen:

  1. How much oxygen and hydrogen does it produce?
  2. How many duplicants can breathe that oxygen indefinitely?
  3. How many hydrogen generators burn the hydrogen, and is the build
     power-positive after paying for the electrolyzer and gas pumps?
  4. How much water does it consume?

All rates come from the current game data (oni/machine.yaml, extracted
from the game files by tools/extract_oni_data.py):

  Electrolyzer:       1 kg/s water -> 0.888 kg/s O2 + 0.112 kg/s H2, 120 W
  Gas Pump:           0.5 kg/s gas, 240 W
  Hydrogen Generator: 0.1 kg/s H2 -> 800 W
  Duplicant:          0.1 kg/s O2

The math is closed-form, so we do it directly first; then we verify by
letting the library's LP balancer (System.balance()) solve for machine
uptimes itself.

Run from the repo root:

    python3 examples/hydra_oxygen_generation.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from oni import (  # noqa: E402
    Electrolyzer, HydrogenGenerator, HydrogenPump, MultiMachine, OxygenPump,
    Sink, Source,
)
from oni.resource import _get_or_create_resource  # noqa: E402

PipedWater = _get_or_create_resource("PipedWater")
PipedOxygen = _get_or_create_resource("PipedOxygen")
Power = _get_or_create_resource("Power")
Oxygen = _get_or_create_resource("Oxygen")
Hydrogen = _get_or_create_resource("Hydrogen")

SECONDS_PER_CYCLE = 600

# Game constants that aren't machine entries
DUPE_OXYGEN_KG_S = 0.1      # duplicant breathing rate
GAS_PUMP_RATE_KG_S = 0.5    # gas pump throughput


def direct_math():
    """Closed-form answer, computed from the machine data."""
    electrolyzer = Electrolyzer()

    o2 = electrolyzer.gives()[Oxygen]          # kg/s
    h2 = electrolyzer.gives()[Hydrogen]        # kg/s
    water = electrolyzer.needs()[PipedWater]   # kg/s

    # Pumps only pay for the fraction of capacity actually used.
    o2_pumps = o2 / GAS_PUMP_RATE_KG_S
    h2_pumps = h2 / GAS_PUMP_RATE_KG_S
    pump_power = (o2_pumps + h2_pumps) * OxygenPump().needs()[Power]

    dupes = o2 / DUPE_OXYGEN_KG_S

    generators = h2 / HydrogenGenerator().needs()[_get_or_create_resource("PipedHydrogen")]
    generated = generators * HydrogenGenerator().gives()[Power]

    consumed = electrolyzer.needs()[Power] + pump_power

    return {
        "o2_kg_s": o2,
        "h2_kg_s": h2,
        "water_kg_s": water,
        "o2_pumps": o2_pumps,
        "h2_pumps": h2_pumps,
        "pump_power": pump_power,
        "dupes": dupes,
        "generators": generators,
        "generated_w": generated,
        "consumed_w": consumed,
        "surplus_w": generated - consumed,
    }


def optimizer_check():
    """Same question, but let the LP balancer pick machine uptimes.

    We give the system two of each pump and two generators (more than
    needed) plus free sources/sinks, and read the operating points off
    the balanced system.
    """
    system = (Electrolyzer()
              + MultiMachine(OxygenPump(), 2)
              + HydrogenPump()
              + MultiMachine(HydrogenGenerator(), 2)
              + Source(PipedWater, 10)
              + Sink(PipedOxygen, 10)
              + Sink(Power, 1e6))
    system.balance()
    return system


def main():
    r = direct_math()

    print("Hydra oxygen generation: one Electrolyzer, perfectly separated output")
    print("=" * 72)

    print("\n1) Electrolyzer output")
    print(f"   Oxygen:   {r['o2_kg_s']:.3f} kg/s "
          f"({r['o2_kg_s'] * SECONDS_PER_CYCLE:6.1f} kg/cycle)")
    print(f"   Hydrogen: {r['h2_kg_s']:.3f} kg/s "
          f"({r['h2_kg_s'] * SECONDS_PER_CYCLE:6.1f} kg/cycle)")

    print("\n2) Duplicants sustained on the oxygen")
    print(f"   {r['o2_kg_s']:.3f} / {DUPE_OXYGEN_KG_S} kg/s per dupe "
          f"= {r['dupes']:.2f} dupes")

    print("\n3) Power balance")
    print(f"   Hydrogen generators needed: {r['h2_kg_s']:.3f} / 0.1 kg/s "
          f"= {r['generators']:.2f}")
    print(f"   Generated: {r['generated_w']:7.1f} W")
    print(f"   Consumed:  {r['consumed_w']:7.1f} W")
    print(f"     - Electrolyzer:          {Electrolyzer().needs()[Power]:5.0f} W")
    print(f"     - Oxygen pumps:   {r['o2_pumps']:.3f} x 240 W "
          f"= {r['o2_pumps'] * 240:6.1f} W")
    print(f"     - Hydrogen pumps: {r['h2_pumps']:.3f} x 240 W "
          f"= {r['h2_pumps'] * 240:6.1f} W")
    print(f"   Surplus:   {r['surplus_w']:+7.1f} W")

    print("\n4) Water consumption")
    print(f"   {r['water_kg_s']} kg/s = "
          f"{r['water_kg_s'] * SECONDS_PER_CYCLE:.0f} kg/cycle")

    print("\n" + "-" * 72)
    print("Optimizer verification (System.balance() picks the uptimes):")
    system = optimizer_check()
    for machine in system:
        if isinstance(machine, (Source, Sink)):
            continue
        print(f"   {machine}")
    net = system.net_output()
    leftover = {str(k): round(float(v), 4)
                for k, v in net.items() if str(k) != "Heat"}
    print(f"   Leftover from the free source/sinks: {leftover or '{}'}")


if __name__ == "__main__":
    main()
