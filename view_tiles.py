import json
from pathlib import Path
from prefab_ui.app import PrefabApp

spec_path = Path(__file__).parent / "ui_spec.json"

if spec_path.exists():
    try:
        ui_spec = json.loads(spec_path.read_text())
        app = PrefabApp.from_json(ui_spec)
    except Exception as e:
        with PrefabApp() as app:
            from prefab_ui.components import Text
            Text(f"Error loading dashboard: {e}")
else:
    with PrefabApp() as app:
        from prefab_ui.components import Text
        Text("No UI data yet. Run the client script first.")
