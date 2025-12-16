import time
import os
import sys

def main():
    pid = os.getpid()
    print(f"Test script started with PID: {pid}")
    
    # Write PID to file
    with open("test_script.pid", "w") as f:
        f.write(str(pid))
        
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Test script stopping...")
    finally:
        if os.path.exists("test_script.pid"):
            os.remove("test_script.pid")

if __name__ == "__main__":
    main()
