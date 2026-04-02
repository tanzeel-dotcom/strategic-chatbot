from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import os

# Import agent services
from agent_service import stream_chat_response, ingest_website

app = FastAPI(title="Website Support Agent API")

# Enable CORS for any website to use the widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    website_url: str
    history: Optional[List[Dict[str, str]]] = []

class IngestRequest(BaseModel):
    url: str
    max_depth: Optional[int] = 2

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Endpoint that the widget polls when a user sends a message.
    Streams back the LLM response.
    """
    if not request.message or not request.website_url:
        raise HTTPException(status_code=400, detail="Message and website_url are required.")

    # Generator function for streaming response
    def generate():
        for chunk in stream_chat_response(
            url=request.website_url,
            message=request.message,
            history=request.history
        ):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/api/ingest")
async def ingest_endpoint(request: IngestRequest, background_tasks: BackgroundTasks):
    """
    Kicks off a background task to index the website, returning immediately.
    """
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required.")

    # We could run this synchronously, but crawling might take time, so we background it.
    # For now, let's run it synchronously to easily return the status to the admin UI.
    result = ingest_website(request.url, request.max_depth)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
        
    return result

@app.get("/widget.js")
async def get_widget():
    """
    Serves the JS widget that users can embed on their sites.
    """
    filepath = os.path.join("static", "widget.js")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Widget script not found")
    return FileResponse(filepath, media_type="application/javascript")

@app.get("/style.css")
async def get_style():
    """
    Serves the CSS for the JS widget.
    """
    filepath = os.path.join("static", "style.css")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Widget style not found")
    return FileResponse(filepath, media_type="text/css")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
