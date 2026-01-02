#!/usr/bin/env python3
"""Fix max_results and disqualifier weights."""
import json

CONFIG_FILE = "unified_config.json"

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Change to 10 results per query (2500 queries instead of 250)
old_max = config['step1']['max_results']
config['step1']['max_results'] = 10
print(f"max_results: {old_max} -> 10")

# Reduce disqualifier weights by 10x
for factor in config['step3']['negative_factors']:
    old_weight = factor['weight']
    factor['weight'] = max(10, old_weight // 10)  # Floor at 10
    if factor['name'] and factor['keywords']:
        print(f"  {factor['name']}: {old_weight} -> {factor['weight']}")

with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print("\nConfig updated!")
print("- 2,500 queries x 10 results each")
print("- Disqualifier weights reduced 10x")
