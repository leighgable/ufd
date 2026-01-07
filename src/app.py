import os
import shutil
import asyncio
import json
from textwrap import dedent
from typing import Dict, Any, List
from fastapi import (FastAPI,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
)

from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
# from openai import AsyncOpenAI
# --- New Imports for the Async Agent ---
from .streaming import (
    function_worker_async,
    call_function,
    astream_llama_cpp_response,
    client_cfg,
)
from .utils import create_message_with_files
from .sandbox_manager import close_sandbox
from .markdown_functional import (
    process_markdown_stream,
    finalize_markdown as finalize_markdown_text,
    md as md_parser
)
import uuid

# --- Variables from old templates.py ---
react_instructions = {
    "role": "system",
    "content": dedent("""
        You are a powerful problem-solving assistant. You have access to a set of tools to help you answer user questions.
        **IMPORTANT**:
        - Ensure the 'arguments' field for any tool call is always a valid JSON string.
        - Use your python tool to test your code when needed. 
        - Do not provide a final answer until there are no errors from your code tool.""")
}

FN_NAME = '✿FUNCTION✿'
FN_ARGS = '✿ARGS✿'
FN_RESULT = '✿RESULT✿'
FN_EXIT = '✿RETURN✿'

FN_CALL_TEMPLATE_EN = """

# Tools

## You have access to the following tools:

{tool_descs}

## When you need to call a tool, please insert the following command in your reply, which can be called zero or multiple times according to your needs:

%s: The tool to use, should be one of [{tool_names}]
%s: The input of the tool
%s: The result returned by the tool. The image needs to be rendered as ![](url)
%s: Reply based on tool result""" % (
    FN_NAME,
    FN_ARGS,
    FN_RESULT,
    FN_EXIT,
)

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
            "strict": False
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
    # agent_context["client"] = AsyncOpenAI(api_key="EMPTY")
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


@app.post("/upload-file")
async def upload_file(files: list[UploadFile] = File(...)):
    """Handles file uploads and saves them to /tmp"""
    file_paths = []
    for file in files:
        contents = await file.read()
        file_path = f"tmp/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(contents)
        file_paths.append(file_path)
    return HTMLResponse(content="".join([f'<input type="hidden" name="uploaded_file_paths" value="{path}">' for path in file_paths]))
                   

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    
    # --- New Session State ---
    chat_history = [react_instructions]
    session_files = []
    # -------------------------

    try:
        while True:
            response_id = int(asyncio.get_running_loop().time() * 1000)
            session_dir = f"tmp/{response_id}"
            os.makedirs(session_dir, exist_ok=True)
            
            message_data = await websocket.receive_text()
            parsed_data = json.loads(message_data)
            print(f"{parsed_data}")
            prompt = parsed_data.get("prompt", "")
            
            show_reasoning_str = parsed_data.get("show_reasoning", "false")
            max_iterations_str = parsed_data.get("max_iterations", "5")
            uploaded_file_paths = parsed_data.get("uploaded_file_paths", [])

            show_reasoning = show_reasoning_str in ["true", "on"]
            max_iterations = int(max_iterations_str)

            # --- File Handling for Session ---
            newly_uploaded_files = []
            if uploaded_file_paths:
                for path in uploaded_file_paths:
                    if os.path.exists(path):
                        new_path = os.path.join(session_dir, os.path.basename(path))
                        shutil.move(path, new_path)
                        with open(new_path, "rb") as f:
                            file_data = f.read()
                        session_files.append({"path": os.path.basename(new_path), "data": file_data})
                        newly_uploaded_files.append(new_path)
            
            file_list_html = ""
            if newly_uploaded_files:
                items = "".join([f"<li>{os.path.basename(path)}</li>" for path in newly_uploaded_files])
                file_list_html = f"<div class='file-list text-xs text-gray-500 dark:text-gray-400'>Attached:<ul>{items}</ul></div>"
            # ---------------------------------
            
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

            if show_reasoning:
                reasoning_bubble = f'''
                    <div hx-swap-oob="beforeend:#chat-messages">
                        <div class="flex justify-start">
                            <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
                                <b>Reasoning:</b>
                                <div id='reasoning-{response_id}'></div>
                            </div>
                        </div>
                    </div>
                '''
                await websocket.send_text(reasoning_bubble)

            content_bubble = f'''
                <div hx-swap-oob="beforeend:#chat-messages">
                    <div class="flex justify-start">
                        <div class="chat-bubble bg-gray-200 text-gray-800 p-3 rounded-xl">
                            <div id='content-{response_id}'></div>
                        </div>
                    </div>
                </div>
            '''
            await websocket.send_text(content_bubble)

            # --- Updated Agent Logic Call ---
            # 1. Create the user message for this specific turn
            user_message_for_turn = create_message_with_files(prompt, [f['path'] for f in session_files])

            # 2. Construct the message list for this agent run
            messages_for_this_run = chat_history + user_message_for_turn
            
            # 3. Call the agent and get the final answer
            final_answer_text = await agent_stream_logic(
                websocket=websocket,
                messages=messages_for_this_run,
                show_reasoning=show_reasoning,
                response_id=response_id,
                max_iterations=max_iterations,
                session_files=session_files,
                session_id=session_id
            )

            # 4. Permanently update the chat history for the next turn
            chat_history.extend(user_message_for_turn)
            chat_history.append({"role": "assistant", "content": final_answer_text})
            # --------------------------------

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"WebSocket error: {e}")
        error_html = f'<div hx-swap-oob="beforeend:#chat-messages" class="text-sm text-red-500">[WebSocket Error]: {e}</div>'
        await websocket.send_text(error_html)
    finally:
        close_sandbox(session_id)

async def agent_stream_logic(
    websocket: WebSocket,
    messages: List[Dict[str, Any]],
    show_reasoning: bool,
    response_id: str,
    max_iterations: int,
    session_files: List[Dict[str, Any]],
    session_id: str
) -> str:
    """
    The main agent loop, now sending HTML directly over WebSocket.
    Accepts the full message history and returns the final answer text.
    """
    current_messages = list(messages)
    print(f"CURRENT_MESSAGES: {current_messages}")
    call_queue = agent_context["call_queue"]
    result_queue = agent_context["result_queue"]

    # Clear queues for this run
    while not call_queue.empty():
        call_queue.get_nowait()
    while not result_queue.empty():
        result_queue.get_nowait()

    content_id = f"content-{response_id}"
    reasoning_id = f"reasoning-{response_id}"

    next_turn_messages = []
    final_answer_text = ""
    error_in_previous_turn = False
    
    try:
        for turn in range(max_iterations):
            print(f"----TURN: {turn} ----")
            current_messages.extend(next_turn_messages)
            next_turn_messages.clear()
            print(f"----- CURRENT_MESSAGES: {current_messages}")

            clear_content_html = f'<div hx-swap-oob="innerHTML:#{content_id}"></div>'
            await websocket.send_text(clear_content_html)

            stream = astream_llama_cpp_response(messages=current_messages, tools=AVAILABLE_TOOLS, client_cfg=client_cfg)
            
            content_buffer = ""
            reasoning_buffer = ""
            unstable_buffer = ""
            stable_text = ""
            tool_calls = []
            finish_reason = None

            async for event in stream:
                if not event or event[0] is None:
                    continue
                delta = event[0].get("delta", {})
                if fr := event[0].get("finish_reason"):
                    finish_reason = fr
                if reasoning := delta.get("reasoning_content"):
                    reasoning_buffer += reasoning
                    if show_reasoning:
                        html_chunk = f'<div hx-swap-oob="beforeend:#{reasoning_id}">{reasoning}</div>'
                        await websocket.send_text(html_chunk)
                if content := delta.get("content"):
                    content_buffer += content
                    unstable_buffer, stable_text = process_markdown_stream(content, unstable_buffer, stable_text)
                    if stable_text:
                        html_fragment = md_parser.render(stable_text)
                        html_chunk = f'<div hx-swap-oob="innerHTML:#{content_id}">{html_fragment}</div>'
                        await websocket.send_text(html_chunk)
                if tc := delta.get("tool_calls"):
                    tool_calls.extend(tc)

            final_text = finalize_markdown_text(unstable_buffer, stable_text)
            if final_text:
                final_html = md_parser.render(final_text)
                html_chunk = f'<div hx-swap-oob="innerHTML:#{content_id}">{final_html}</div>'
                await websocket.send_text(html_chunk)
            
            final_answer_text = final_text

            # 2. After the stream is finished, decide what to do
            # and set up for the next turn if necessary.
            if finish_reason == "tool_calls":
                assistant_message_for_history = {"role": "assistant", "content": content_buffer or "", "tool_calls": tool_calls}
                results = []
                for call in tool_calls:
                    tool_html = f'<div hx-swap-oob="beforeend:#chat-messages" class="text-sm text-blue-500"> Executing {call["function"]["name"]}...</div>'
                    await websocket.send_text(tool_html)
                    await call_queue.put({"tool_call": json.dumps(call), "files": session_files, "session_id": session_id})
                
                await call_queue.join()
                
                while not result_queue.empty():
                    result = await result_queue.get()
                    results.append(result)
                    result_queue.task_done()
                
                # Set the flag for the *next* turn if an error occurred.
                error_in_previous_turn = any(res.get("is_error", False) for res in results)
                next_turn_messages.append(assistant_message_for_history)
                next_turn_messages.extend(results)
                print(f"--- NXT_MSGS: {next_turn_messages}")

            # 3. Decide whether to continue the loop.
            if finish_reason == "stop" and not is_correction_turn:
                # The model wants to stop, and it wasn't a correction turn.
                # This is a genuine, clean stop.
                print(f"Loop ended cleanly. Finish reason: {finish_reason}")
                break
            else:
                # We continue if:
                # 1. The model issued a tool call (`finish_reason` was 'tool_calls').
                # 2. The model tried to stop, but it was during a correction turn, so we force it to try again.
                continue

        if show_reasoning:
            script_container_id = f"script-container-{response_id}"
            script_html = f'''
        <div id={script_container_id} hx-swap-oob="beforeend:#chat-messages">
            <script>
                addShowMore(f"reasoning-{response_id}");
                const scriptContainer = document.getElementById('{script_container_id}');
                if (scriptContainer) {{
                    scriptContainer.remove();
                }}
            </script>
        </div>
            '''
            await websocket.send_text(script_html)
        
        return final_answer_text

    except Exception as e:
        error_html = f'<div hx-swap-oob="beforeend:#{content_id}" class="text-sm text-red-500">[Error]: {e}</div>'
        await websocket.send_text(error_html)
        return f"An error occurred: {e}"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
            
