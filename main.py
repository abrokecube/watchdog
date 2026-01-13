import uvicorn
from api import app

def main():
    """
    Entry point for the Process Watcher application.
    Starts the Uvicorn server with the FastAPI app.
    """
    # The monitor thread is already started when importing 'app' from 'api'
    # because of the module-level code in api.py.
    uvicorn.run(app, host="0.0.0.0", port=8110)

if __name__ == "__main__":
    main()
