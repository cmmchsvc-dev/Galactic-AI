import os
import google.auth
from google.cloud import aiplatform

def list_vertex_models():
    project_id = "gen-lang-client-0901634078"
    locations = ["us-central1", "us-east5", "europe-west1"]
    
    print(f"Checking project: {project_id}\n")
    
    for loc in locations:
        print(f"--- Location: {loc} ---")
        try:
            aiplatform.init(project=project_id, location=loc)
            models = aiplatform.Model.list()
            if not models:
                print("  No models found.")
            for m in models:
                print(f"  - Model ID: {m.name}, Display Name: {m.display_name}")
        except Exception as e:
            print(f"  Error: {str(e)}")
        print()

if __name__ == "__main__":
    list_vertex_models()
