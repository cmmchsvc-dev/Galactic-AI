import json
import os

def register_senior_coder():
    registry_path = "c:\\Users\\Chesley\\Galactic AI\\skills\\registry.json"
    if not os.path.exists(registry_path):
        print("Registry not found.")
        return

    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # Check if already installed
    for item in registry.get("installed", []):
        if item.get("module") == "senior_coder":
            print("SeniorCoder already registered.")
            return

    new_entry = {
        "module": "senior_coder",
        "class": "SeniorCoder",
        "file": "senior_coder.py",
        "installed_at": "2026-03-08T08:20:00.000000",
        "source": "ai_authored",
        "description": "Senior-tier coding engine with interactive plan/apply stages and autonomous mode."
    }

    registry.setdefault("installed", []).append(new_entry)

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    
    print("SeniorCoder registered successfully.")

if __name__ == "__main__":
    register_senior_coder()
