import time
import os
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import ( Environment,
    FileSystemLoader,
    select_autoescape,
    DictLoader,
)
import python_multipart
import markdown

from .ufd import ufd_agent

# --- Configuration ---
# Your llama-server C++ backend runs at port 8080 inside the container.
LLM_SERVER_URL = "http://127.0.0.1:8080/v1/chat/completions"

# --- Template Definitions (In a production app, these would be in separate .html files) ---

INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>llama</title>
    <!-- Load Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Load HTMX -->
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        .chat-bubble { max-width: 80%; }
    </style>
</head>
<body class="bg-gray-50 flex flex-col h-screen antialiased">
    <div class="flex flex-col flex-1 max-w-4xl mx-auto w-full p-4">
        <h1 class="text-3xl font-bold text-center text-gray-800 mb-6">UFD Chat</h1>
        
        <!-- Chat Area -->
        <div id="chat-messages" class="flex-1 overflow-y-auto space-y-4 p-4 bg-white rounded-lg shadow-inner">
            <!-- Messages will be injected here -->
            <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
                Hello! Ask me anything.
            </div>
        </div>

        <!-- Input Form -->
        <form hx-post="/chat" hx-target="#chat-messages" hx-swap="beforeend" class="mt-4 flex space-x-2 p-4 bg-white rounded-lg shadow">
            <input type="text" name="prompt" placeholder="Ask the model..."
                   class="flex-1 p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" required>
            <button type="submit" class="px-6 py-3 bg-indigo-600 text-white font-semibold rounded-lg hover:bg-indigo-700 transition duration-150">
                Send
            </button>
        </form>
    </div>
</body>
</html>
"""

# Template for a single response fragment (HTMX swap target)
RESPONSE_TEMPLATE = """
<!-- User Message Bubble -->
<div class="flex justify-end">
    <div class="chat-bubble bg-indigo-500 text-white p-3 rounded-xl">
        {{ user_prompt }}
    </div>
</div>

<!-- Assistant Message Bubble -->
<div class="flex justify-start">
    <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
        {{ assistant_response }}
    </div>
</div>
"""


templates = {
    'index.html': INDEX_TEMPLATE,
    'response.html': RESPONSE_TEMPLATE
}

jinja_env = Environment(loader=DictLoader(templates), autoescape=select_autoescape(['html']))

# --- FastAPI Setup ---
app = FastAPI()

async def generate_llm_response(prompt: str) -> str:
    """Proxies the request to the llama-server C++ backend."""
    try:
        start_time = time.time()
        generator = ufd_agent.arun(input=prompt)
        async for event in generator:
            current_time = time.time() - start_time
            if hasattr(event, "event"):
                if "RunCompleted" in event.event:
                    yield f"{event.content}\n"
                elif "RunStarted" in event.event:
                    yield  f"[{current_time:.2f}s] {event.event}\n"
        total_time = time.time() - start_time
        yield f"Total execution time: {total_time:.2f}s\n"

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to LLM server: {e}")
        yield f"Error: Could not connect to LLM server at {LLM_SERVER_URL}"

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Serves the main HTMX-enabled chat page."""
    template = jinja_env.get_template('index.html')
    return template.render()

async def combined_stream_generator(prompt: str):
    """
    Yields the full HTML fragment for HTMX, starting with the user message, 
    followed by the streaming assistant content, and closing tags.
    """
    # 1. Yield the User Message HTML (fully rendered)
    yield f"""
<!-- User Message Bubble -->
<div class="flex justify-end">
    <div class="chat-bubble bg-indigo-500 text-white p-3 rounded-xl">
        {prompt}
    </div>
</div>

<!-- Assistant Message Bubble (START) -->
<div class="flex justify-start">
    <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
"""

    # 2. Yield LLM tokens (raw text)
    # The browser/HTMX will append this raw text continuously to the DOM.
    async for token in generate_llm_response(prompt):
        if token is not None:
            if "Total execution time:" in token:
                final_time_message = token
            else:
                yield token.replace('\n', '<br>')
        
    # 3. Yield the closing HTML tags
    yield """
    </div>
</div>
"""
    # 4. Yield the Annotation BELOW the bubble
    if final_time_message:
        yield f"""
<!-- Annotation: Total execution time placed outside the main bubble -->
<div class="flex justify-start text-xs text-gray-500 mt-1 mb-4 pl-3">
    {final_time_message}
</div>
"""

@app.post("/chat", response_class=HTMLResponse)
async def post_chat(prompt: str = Form(...)):
    """
    Handles HTMX POST request, calls the LLM, and returns the HTML fragment 
    to swap into the #chat-messages container.
    """
    # The StreamingResponse handles the asynchronous delivery of the generator's output
    return StreamingResponse(combined_stream_generator(prompt), media_type="text/html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
