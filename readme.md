ai slop project

# Process Watcher

Process Watcher is a lightweight and flexible tool for monitoring and managing system processes. It provides a RESTful API to start, stop, restart, and check the status of configured processes. The watcher runs in the background, automatically restarting any monitored process that goes down.

## Features

- **Automatic Process Restart**: Monitors configured processes and automatically restarts them if they crash or stop.
- **RESTful API**: Provides a simple API to interact with the monitored processes.
- **Flexible Process Identification**: Identify processes by PID file, a unique string in their command line, or executable path.
- **Remote Command Execution**: Includes an endpoint to run `git pull` in a process's working directory.
- **Asynchronous Client**: Comes with an `asyncio`-based client for easy integration into other Python applications.
- **Daemonized Process Spawning (Windows)**: Starts processes in a detached state on Windows to prevent them from being killed if the parent script exits.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd watchdog
    ```

2.  **Install dependencies:**
    It's recommended to use a virtual environment. This project uses `uv` for package management.
    ```bash
    # If you don't have uv
    pip install uv

    # Create a virtual environment
    uv venv

    # Activate it (Windows PowerShell)
    .venv\Scripts\activate.ps1

    # Install dependencies
    uv pip install -r requirements.txt
    ```

## Configuration

1.  Create a `config.json` file in the root directory of the project. You can copy and modify `config_example.json`.

2.  The `config.json` is a list of process objects to monitor. Here's an example configuration:

    ```json
    [
        {
            "name": "my-app",
            "command": ["python", "app.py"],
            "cwd": "C:\\path\\to\\my-app",
            "process_match": "app.py"
        },
        {
            "name": "another-service",
            "command": ["node", "server.js"],
            "cwd": "/path/to/another-service",
            "pid_file": "/path/to/another-service/service.pid"
        }
    ]
    ```

    **Configuration Fields:**

    -   `name`: A unique name for the process.
    -   `command`: A list of strings representing the command and its arguments to execute.
    -   `cwd`: The working directory from which to run the command.
    -   `process_match` (optional): A unique string within the process's command line arguments used to find the process if it's already running. Useful if the process doesn't create a PID file.
    -   `pid_file` (optional): The absolute path to a file containing the process ID (PID). The watcher will use this to check if the process is running.
    -   `executable_path` (optional): The absolute path to the process executable. Can be used for more reliable process matching.

## Usage

To start the Process Watcher API server, run the `run.ps1` script from a PowerShell terminal:

```powershell
.\run.ps1
```

This will start the FastAPI server on `http://localhost:8110`.

## API Endpoints

The API is served from the `main.py` application and provides the following endpoints:

-   **GET `/processes`**
    -   **Description**: Lists all configured processes and their current status (`Running`, `Stopped`, or `Stopped (Manual)`).
    -   **Response**:
        ```json
        {
            "my-app": "Running",
            "another-service": "Stopped"
        }
        ```

-   **POST `/processes/{name}/start`**
    -   **Description**: Starts a configured process by its name.

-   **POST `/processes/{name}/stop`**
    -   **Description**: Stops a running process. This also marks it as manually stopped, so the watcher will not restart it automatically.

-   **POST `/processes/{name}/restart`**
    -   **Description**: Restarts a process.

-   **POST `/processes/{name}/git-pull`**
    -   **Description**: Executes `git pull` in the process's configured working directory (`cwd`).
    -   **Response**:
        ```json
        {
            "name": "my-app",
            "status": "success",
            "output": "Already up to date.\n",
            "error": ""
        }
        ```

## Client Usage

A simple asynchronous client is provided in `client.py` for interacting with the API programmatically.

**Example:**

```python
import asyncio
from client import ProcessWatcherClient

async def main():
    client = ProcessWatcherClient(base_url="http://localhost:8110")

    # Get all process statuses
    statuses = await client.get_processes()
    print("Process Statuses:", statuses)

    # Start a process
    try:
        result = await client.start_process("my-app")
        print("Start result:", result)
    except Exception as e:
        print(f"Failed to start process: {e}")

    # Stop a process
    try:
        result = await client.stop_process("my-app")
        print("Stop result:", result)
    except Exception as e:
        print(f"Failed to stop process: {e}")

if __name__ == "__main__":
    asyncio.run(main())