#!/usr/bin/env python3
"""Build a normalized mass-conversion dataset from the extracted game data.

Reads oni/data/buildings.json + recipes.json + elements.json (produced by
tools/extract_oni_data.py) and writes oni/data/conversions.json: one entry
per building describing every mass conversion it performs.

Conversion sources covered:
  element_converter  - ElementConverter (electrolyzer, water sieve, ...)
                       outputs at max(input temperature, min temperature)
  generator          - EnergyGenerator formula (coal/hydrogen/petroleum ...)
                       outputs at max(building temperature, min temperature)
  emitter            - BuildingElementEmitter (e.g. fertilizer maker methane)
                       outputs at a fixed temperature
  recipe             - ComplexRecipe on a fabricator (kiln, refinery, grill)
                       batch amounts normalized to kg/s via the recipe time

Pure transport (pumps, vents) and storage-only buildings are not included.

Usage: python3 tools/build_conversions.py [--data-dir oni/data]
"""
import argparse
import json
import os


def is_num(v):
    return isinstance(v, (int, float))


def load(data_dir):
    out = {}
    for name in ('buildings', 'recipes', 'elements'):
        with open(os.path.join(data_dir, f'{name}.json')) as f:
            out[name] = json.load(f)
    return out['buildings'], out['recipes'], out['elements']


def material_state(material, elements):
    e = elements.get(material)
    return e['state'] if e and 'state' in e else None


def via_for(material, building, elements):
    """How an input material reaches the converter."""
    state = material_state(material, elements)
    conduit = building.get('input_conduit_type')
    if state and conduit == state:
        return f'{state.lower()}_conduit'
    if state is None:
        return 'tagged_delivery'
    return 'delivery'


def dest_for(output, building, elements):
    """Where an output material ends up."""
    if output.get('store_output') or output.get('store'):
        out_conduit = building.get('output_conduit_type')
        state = material_state(output.get('material'), elements)
        comps = building.get('components', {})
        has_dispenser = any(k.startswith('ConduitDispenser') for k in comps)
        if out_conduit and (state is None or out_conduit == state) and has_dispenser:
            return f'{out_conduit.lower()}_conduit'
        return 'storage'
    return 'environment'


def converter_entries(bid, building, elements):
    entries = []
    comps = building.get('components', {})
    for comp_name, comp in comps.items():
        if not comp_name.startswith('ElementConverter'):
            continue
        inputs, outputs, incomplete = [], [], False
        for c in comp.get('consumed', []):
            if not (isinstance(c.get('element'), str) and is_num(c.get('kg_per_second'))):
                incomplete = True
                continue
            inputs.append({
                'material': c['element'],
                'kg_per_second': c['kg_per_second'],
                'via': via_for(c['element'], building, elements),
            })
        for p in comp.get('produced', []):
            if not (isinstance(p.get('element'), str) and is_num(p.get('kg_per_second'))):
                incomplete = True
                continue
            o = {
                'material': p['element'],
                'kg_per_second': p['kg_per_second'],
                'to': dest_for({**p, 'material': p['element']}, building, elements),
            }
            if p.get('use_entity_temperature'):
                o['temperature'] = {'rule': 'building_temperature'}
            elif is_num(p.get('min_temperature')) and p['min_temperature'] > 0:
                o['temperature'] = {'rule': 'max_input_or_min',
                                    'min_k': p['min_temperature']}
            outputs.append(o)
        if inputs or outputs:
            entry = {'source': 'element_converter', 'inputs': inputs,
                     'outputs': outputs}
            if incomplete:
                entry['incomplete'] = True
            entries.append(entry)
    return entries


def generator_entries(bid, building, elements):
    comps = building.get('components', {})
    eg = comps.get('EnergyGenerator')
    if not eg or 'formula' not in eg:
        return []
    f = eg['formula']
    raw_inputs = f.get('inputs') or (
        [{'element': f['element'], 'kg_per_second': f['kg_per_second']}]
        if f.get('element') else [])
    raw_outputs = f.get('outputs') or (
        [{'element': f['output_element'], 'kg_per_second': f['output_kg_per_second'],
          'min_temperature': f.get('min_output_temperature'),
          'store': f.get('store_output_mass')}]
        if f.get('output_element') else [])
    inputs, outputs, incomplete = [], [], False
    for i in raw_inputs:
        if not (isinstance(i.get('element'), str) and is_num(i.get('kg_per_second'))):
            incomplete = True
            continue
        inputs.append({'material': i['element'],
                       'kg_per_second': i['kg_per_second'],
                       'via': via_for(i['element'], building, elements)})
    for o in raw_outputs:
        if not (isinstance(o.get('element'), str) and is_num(o.get('kg_per_second'))):
            incomplete = True
            continue
        out = {'material': o['element'], 'kg_per_second': o['kg_per_second'],
               'to': dest_for(o, building, elements)}
        if is_num(o.get('min_temperature')) and o['min_temperature'] > 0:
            out['temperature'] = {'rule': 'max_building_or_min',
                                  'min_k': o['min_temperature']}
        outputs.append(out)
    entry = {'source': 'generator', 'inputs': inputs, 'outputs': outputs}
    if incomplete:
        entry['incomplete'] = True
    return [entry]


def emitter_entries(bid, building, elements):
    entries = []
    for comp_name, comp in building.get('components', {}).items():
        if not comp_name.startswith('BuildingElementEmitter'):
            continue
        element = comp.get('element')
        rate = comp.get('emitRate')
        if not (isinstance(element, str) and is_num(rate)):
            continue
        out = {'material': element, 'kg_per_second': rate, 'to': 'environment'}
        if is_num(comp.get('temperature')):
            out['temperature'] = {'rule': 'fixed', 'k': comp['temperature']}
        entries.append({'source': 'emitter', 'inputs': [], 'outputs': [out]})
    return entries


def recipe_entries(building_id, recipes, elements):
    entries = []
    for rec in recipes.get(building_id, []):
        time = rec.get('time')
        inputs, outputs, incomplete = [], [], not is_num(time)
        for i in rec.get('ingredients', []):
            mat, amt = i.get('material'), i.get('amount')
            if not (isinstance(mat, str) and is_num(amt) and is_num(time)):
                incomplete = True
                continue
            inputs.append({'material': mat, 'kg_per_second': round(amt / time, 6),
                           'via': 'delivery'})
        for o in rec.get('results', []):
            mat, amt = o.get('material'), o.get('amount')
            if not (isinstance(mat, str) and is_num(amt) and is_num(time)):
                incomplete = True
                continue
            outputs.append({'material': mat, 'kg_per_second': round(amt / time, 6),
                            'to': 'environment'})
        # keep the entry even when every quantity failed to resolve, so
        # consumers can see a dynamic recipe exists here
        if inputs or outputs or rec.get('ingredients') or rec.get('results'):
            entry = {'source': 'recipe', 'inputs': inputs, 'outputs': outputs,
                     'batch_seconds': time if is_num(time) else None,
                     'duplicant_operated': True}
            if incomplete:
                entry['incomplete'] = True
            entries.append(entry)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=os.path.join(os.path.dirname(__file__),
                                                       '..', 'oni', 'data'))
    args = ap.parse_args()
    buildings, recipes, elements = load(args.data_dir)

    conversions = {}
    for bid, b in sorted(buildings.items()):
        entries = (converter_entries(bid, b, elements)
                   + generator_entries(bid, b, elements)
                   + emitter_entries(bid, b, elements)
                   + recipe_entries(bid, recipes, elements))
        if not entries:
            continue
        rec = {'conversions': entries}
        if b.get('name'):
            rec['name'] = b['name']
        if is_num(b.get('power_consumption')):
            rec['power_w'] = -b['power_consumption']
        elif is_num(b.get('power_generation')):
            rec['power_w'] = b['power_generation']
        heat = (b.get('self_heat_kw') or 0) + (b.get('exhaust_heat_kw') or 0)
        if is_num(heat) and heat:
            rec['heat_dtu_s'] = heat * 1000
        if b.get('required_dlc'):
            rec['required_dlc'] = b['required_dlc']
        conversions[bid] = rec

    out_path = os.path.join(args.data_dir, 'conversions.json')
    with open(out_path, 'w') as f:
        json.dump(conversions, f, indent=1, sort_keys=True)
    n_entries = sum(len(v['conversions']) for v in conversions.values())
    n_incomplete = sum(1 for v in conversions.values()
                       for e in v['conversions'] if e.get('incomplete'))
    print(f'{len(conversions)} converting buildings, {n_entries} conversions '
          f'({n_incomplete} incomplete/dynamic) -> {out_path}')


if __name__ == '__main__':
    main()
