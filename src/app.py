import asyncio
import json
from textwrap import dedent
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

# --- New Imports for the Async Agent ---
from .streaming import (
    function_worker_async,
    call_function,
    model_cfg,
)
from .utils import create_message_with_files

# --- Variables from old templates.py ---
react_instructions = {
    "role": "system",
    "content": dedent("""
        You are an expert with strong analytical skills! 🧠
        You have access to tools. To call a tool, you make a function call with the function name and the arguments in JSON format.\n
        **IMPORTANT**: Ensure the 'arguments' field is always a valid JSON string.
        Don't overthink your answers, and use your python tool to test your code.""")
}

AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_code_interpreter",
            "description": "A powerful Python code execution environment for complex math, data analysis, and general programming tasks. Input only raw Python code, no explanation needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The python code to execute."
                    },
                },
                "required": ["code"],
                
            },
            "strict": True
        }
    },
]

# This will hold our persistent agent components
agent_context: Dict[str, Any] = {}

# --- FastAPI Setup ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="src/static"), name="static")

@app.on_event("startup")
async def startup_event():
    """Initializes the agent components when the application starts."""
    print("--- Application starting up... ---")
    agent_context["call_queue"] = asyncio.Queue()
    agent_context["result_queue"] = asyncio.Queue()
    agent_context["client"] = AsyncOpenAI(**model_cfg)
    agent_context["worker_task"] = asyncio.create_task(function_worker_async(
        call_function,
        call_queue=agent_context["call_queue"],
        result_queue=agent_context["result_queue"],
    ))
    print("--- Agent worker started in the background. ---")

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shuts down the agent worker."""
    print("--- Application shutting down... ---")
    if "worker_task" in agent_context and not agent_context["worker_task"].done():
        agent_context["call_queue"].put_nowait(None)
        agent_context["worker_task"].cancel()
        await asyncio.sleep(1)
    print("--- Agent worker shut down. ---")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return FileResponse("src/static/index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message_data = await websocket.receive_text()
            print(f"[Debug_WS] Raw message_data recieved: {message_data!r}")
            parsed_data = json.loads(message_data)
            
            print(f"[Debug_WS] Parsed data: {parsed_data!r}")
            prompt = parsed_data.get("prompt", [""])
            print(f"[Debug_WS] Extracted prompt: {prompt!r}")
            show_reasoning_str = parsed_data.get("show_reasoning", ["false"])[0]
            max_iterations_str = parsed_data.get("max_iterations", ["5"])[0]

            show_reasoning = show_reasoning_str in ["true", "on"]
            max_iterations = int(max_iterations_str)

            response_id = int(asyncio.get_running_loop().time() * 1000)
            reasoning_id = f"reasoning-{response_id}"
            content_id = f"content-{response_id}"
            tool_id = f"tool-{response_id}"

            # --- Part 1: Send the user's message bubble ---
            file_names = [] # Files are not handled via WebSocket form submission directly
            file_list_html = ""
            # This block will currently not execute as file_names is empty
            if file_names: 
                items = "".join([f"<li>{name}</li>" for name in file_names])
                file_list_html = f"<div class='file-list'>Attached:<ul>{items}</ul></div>"
            
            display_prompt = prompt + file_list_html
            user_bubble = f'''
                <div hx-swap-oob="beforeend:#chat-messages">
                    <div class="flex justify-end">
                        <div class="chat-bubble bg-primary text-white p-3 rounded-lg">
                            {display_prompt}
                        </div>
                    </div>
                </div>
            '''
            await websocket.send_text(user_bubble)

            # --- Part 2: Send the agent's initial bubble with containers ---
            agent_bubble_start = f'''
                <div hx-swap-oob="beforeend:#chat-messages">
                    <div class="flex justify-start">
                        <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
                            <div id='{reasoning_id}'></div>
                            <div id='{content_id}'></div>
                        </div>
                    </div>
                </div>
            '''
            await websocket.send_text(agent_bubble_start)

            # --- Part 3: Run the agent logic and stream responses ---
            await agent_stream_logic(websocket, prompt, show_reasoning, reasoning_id, content_id, tool_id, max_iterations)

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"WebSocket error: {e}")
        # Send an error message to the client
        error_html = f'<div id="chat-messages" hx-swap-oob="beforeend" class="text-sm text-red-500">[WebSocket Error]: {e}</div>'
        await websocket.send_text(error_html)

async def agent_stream_logic(websocket: WebSocket, prompt: str, show_reasoning: bool, reasoning_id: str, content_id: str, tool_id: str, max_iterations: int) -> None:
    """The main agent loop, now sending HTML directly over WebSocket."""

    user_message = create_message_with_files(prompt, [])
    
    current_messages = [react_instructions]
    
    current_messages.extend(user_message)
    
    async_client = agent_context["client"]
    call_queue = agent_context["call_queue"]
    result_queue = agent_context["result_queue"]
    # async_worker = agent_context["worker_task"]

    while not call_queue.empty():
        call_queue.get_nowait()
    while not result_queue.empty():
        result_queue.get_nowait()

    try:
        for turn in range(max_iterations):
            async with async_client.chat.completions.stream(messages=current_messages, model="Qwen3-0.6B", tools=AVAILABLE_TOOLS) as stream:
                had_tool_call = False
                current_tool_calls = {}
                answer = ""
                async for event in stream:
                    if event.type == "content.delta":
                        html_chunk = f'<span hx-swap-oob="beforeend:#{content_id}">{event.delta.replace("\\n", "<br>")}</span>'
                        await websocket.send_text(html_chunk)
                    elif event.type == "content.done":
                        answer = event.content        
                    elif event.type == "chunk":
                        finish_reason = event.chunk.choices[0].finish_reason
                        if reason := event.chunk.choices[0].delta.model_extra.get('reasoning_content'):
                            if reason is not None: # put show_reason back
                                html_chunk = f'<span hx-swap-oob="beforeend:#{reasoning_id}">{reason.replace("\\n", "<br>")}</span>'
                                await websocket.send_text(html_chunk)
                    elif event.type == "tool_calls.function.arguments.done":
                        tool_call_name = getattr(event, 'name', None)
                        if tool_call_name:
                            had_tool_call = True
                            tool_update = f'<div hx-swap-oob="beforeend:#{tool_id}" class=f"text-xs text-blue-400">[{tool_call_name} call in queue.]</div>'
                            current_tool_calls[tool_id] = {
                                "id": tool_id,
                                "function": {"name": event.name, "arguments": event.arguments}
                            }
                            await websocket.send_text(tool_update)
                            await call_queue.put({"name": event.name,
                                                 "id": tool_id,
                                             "arguments": event.arguments,
                                         })
                    else:
                        pass
                    if finish_reason:
                        if had_tool_call:
                            current_messages.append({"role": "assistant", "tool_calls": list(current_tool_calls.values())})
                            await call_queue.join()

                            tool_results = []

                            while not result_queue.empty():
                                result = await result_queue.get()
                                tool_results.append(result)
                                result_queue.task_done()        
                            
                            current_messages.extend(tool_results)
                            break                
                    
                        elif finish_reason == "stop":
                            current_messages.append({"role": "assistant", "content": answer})
                            return

    except Exception as e:
        error_html = f'<div hx-swap-oob="beforeend:#{content_id}" class="text-sm text-red-500">[Error]: {e}</div>'
        await websocket.send_text(error_html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
            
