from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import threading
import uvicorn
from watcher import ProcessWatcher
import os

app = FastAPI()
watcher = ProcessWatcher("config.json")

# Start monitoring in a background thread
monitor_thread = threading.Thread(target=watcher.monitor_loop, daemon=True)
monitor_thread.start()

class ProcessActionResponse(BaseModel):
    name: str
    status: str
    message: str

@app.get("/processes")
def list_processes():
    return watcher.get_all_statuses()

@app.post("/processes/{name}/start", response_model=ProcessActionResponse)
def start_process(name: str):
    if watcher.start_process(name):
        return {"name": name, "status": "success", "message": "Process started"}
    else:
        raise HTTPException(status_code=500, detail="Failed to start process")

@app.post("/processes/{name}/stop", response_model=ProcessActionResponse)
def stop_process(name: str):
    if watcher.stop_process(name):
        return {"name": name, "status": "success", "message": "Process stopped"}
    else:
        raise HTTPException(status_code=500, detail="Failed to stop process or process not running")

@app.post("/processes/{name}/restart", response_model=ProcessActionResponse)
def restart_process(name: str):
    if watcher.restart_process(name):
        return {"name": name, "status": "success", "message": "Process restarted"}
    else:
        raise HTTPException(status_code=500, detail="Failed to restart process")

@app.post("/processes/{name}/git-pull")
def git_pull(name: str):
    result = watcher.run_command(name, ["git", "pull"])
    
    response = {
        "name": name,
        "status": "success" if result["success"] else "error",
        "output": result["output"],
        "error": result["error"]
    }
    
    if result["success"] and "Already up to date" not in result["output"]:
        log_result = watcher.run_command(name, ["git", "log", "-1", "--format=%H|%an|%s"])
        if log_result["success"]:
            parts = log_result["output"].strip().split('|', 2)
            if len(parts) == 3:
                response["latest_commit"] = {
                    "hash": parts[0],
                    "author": parts[1],
                    "message": parts[2]
                }
                
    return response

@app.post("/config/reload")
def reload_config():
    watcher.load_config()
    return {"status": "success", "message": "Configuration reloaded"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
