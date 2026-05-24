from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import os

from database import init_db
from monitor import monitor

# Define the lifespan of the FastAPI application
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("ByteWatch is initializing...")
    init_db()  # Initialize the SQLite database and metrics table
    
    # Only start background monitoring thread if NOT on serverless/Vercel
    import os
    if not (os.environ.get("VERCEL") or os.environ.get("NOW_REGION")):
        monitor.start()  # Start the background system telemetry thread
        
    yield
    # Shutdown logic
    print("ByteWatch is shutting down...")
    if not (os.environ.get("VERCEL") or os.environ.get("NOW_REGION")):
        monitor.stop()  # Cleanly stop the monitor background thread

# Initialize FastAPI with the context manager lifespan
app = FastAPI(title="ByteWatch", lifespan=lifespan)

# Get absolute paths to make it resilient across execution CWDs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

# Ensure static and templates directories exist
os.makedirs(static_dir, exist_ok=True)
os.makedirs(templates_dir, exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize Jinja2 Templates engine
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    """
    Render the main dashboard interface. 
    To deliver a seamless user experience, we pre-render the latest system stats 
    directly into the HTMX container on first-load, avoiding a blank 2-second delay.
    """
    stats = monitor.get_latest_stats()
    
    # Pre-render the vitals panel fragment
    vitals_html = templates.get_template("vitals.html").render(
        request=request,
        cpu_percent=stats["cpu_percent"],
        cpu_cores_logical=stats["cpu_cores_logical"],
        cpu_cores_physical=stats["cpu_cores_physical"],
        cpu_frequency_mhz=stats["cpu_frequency_mhz"],
        cpu_load_avg=stats["cpu_load_avg"],
        memory_percent=stats["memory_percent"],
        memory_used_gb=stats["memory_used_gb"],
        memory_available_gb=stats["memory_available_gb"],
        memory_total_gb=stats["memory_total_gb"],
        processes=stats["processes"]
    )
    
    # Render main index with pre-rendered fragment inside the vitals container
    return templates.TemplateResponse(
        request=request,
        name="index.html", 
        context={"vitals_content": vitals_html}
    )

@app.get("/api/vitals", response_class=HTMLResponse)
async def get_vitals(request: Request):
    """
    HTMX polling endpoint returning raw HTML vitals fragment every 2 seconds.
    Swaps seamlessly into the dashboard's vitals container.
    """
    stats = monitor.get_latest_stats()
    
    return templates.TemplateResponse(
        request=request,
        name="vitals.html",
        context={
            "cpu_percent": stats["cpu_percent"],
            "cpu_cores_logical": stats["cpu_cores_logical"],
            "cpu_cores_physical": stats["cpu_cores_physical"],
            "cpu_frequency_mhz": stats["cpu_frequency_mhz"],
            "cpu_load_avg": stats["cpu_load_avg"],
            "memory_percent": stats["memory_percent"],
            "memory_used_gb": stats["memory_used_gb"],
            "memory_available_gb": stats["memory_available_gb"],
            "memory_total_gb": stats["memory_total_gb"],
            "processes": stats["processes"]
        }
    )

if __name__ == "__main__":
    import uvicorn
    # Start the server locally on port 8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
