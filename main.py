"""
main.py
-------
Entry point for Swarm Factory.
Run with: uvicorn main:app --reload
Or:        python main.py
"""
import sys
import os

# Ensure backend/ is on Python path so all imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from backend.api.server import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
