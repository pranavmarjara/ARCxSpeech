import threading
import time
import uvicorn
import webview
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

from api.routes import router

app = FastAPI(title="ARC Labs API")

# Allow CORS for UI requests (though not strictly necessary when served from same origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Mount the static UI files
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "UI")
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")

def start_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == "__main__":
    # Start FastAPI server in a separate thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait a moment for server to start
    time.sleep(1)
    
    # Create webview window
    webview.create_window(
        "Arc Labs",
        "http://127.0.0.1:8000/patients.html",
        width=1200,
        height=800,
        text_select=True
    )
    
    # Start the pywebview event loop
    webview.start()
