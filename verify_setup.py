import sys
import os

try:
    print("Verifying imports...")
    import psutil
    import fastapi
    import uvicorn
    import aiohttp
    from watcher import ProcessWatcher
    from api import app
    from client import ProcessWatcherClient
    print("Imports successful.")

    print("Verifying ProcessWatcher initialization...")
    watcher = ProcessWatcher("config.json")
    print("ProcessWatcher initialized.")
    
    print("Verifying Config Loading...")
    if len(watcher.processes) > 0:
        print(f"Loaded {len(watcher.processes)} processes from config.")
    else:
        print("Warning: No processes loaded from config.")

    print("Verification complete.")

except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
