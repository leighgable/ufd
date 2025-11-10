import os
import shutil
import asyncio
import json
from textwrap import dedent
from markdown_it import MarkdownIt
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
import uuid

# --- Variables from old templates.py ---
react_instructions = {
    "role": "system",
    "content": dedent("""
        You are an expert with strong analytical skills! 🧠
        You have access to tools. To call a tool, you make a function call with the function name and the arguments in JSON format.\n
        **IMPORTANT**: Ensure the 'arguments' field is always a valid JSON string.
        Don't overthink your answers, and use your python tool to test your code.""")
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


            new_file_paths = []
            if uploaded_file_paths:
                for path in uploaded_file_paths:
                    if os.path.exists(path):
                        new_path = os.path.join(session_dir, os.path.basename(path))
                        shutil.move(path, new_path)
                    new_file_paths.append(new_path)
            file_list_html = ""
            if new_file_paths:
                items = "".join([f"<li>{os.path.basename(path)}</li>" for path in new_file_paths])
                file_list_html = f"<div class='file-list text-xs text-gray-500 dark:text-gray-400'>Attached:<ul>{items}</ul></div>"
            
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

            # --- Part 2: Send the agent's initial bubble with containers ---
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

            # --- Part 3: Run the agent logic and stream responses ---
            await agent_stream_logic(websocket, prompt, show_reasoning, response_id, max_iterations, new_file_paths, session_id)

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"WebSocket error: {e}")
        # Send an error message to the client
        error_html = f'<div hx-swap-oob="beforeend:#chat-messages" class="text-sm text-red-500">[WebSocket Error]: {e}</div>'
        await websocket.send_text(error_html)
    finally:
        close_sandbox(session_id)

async def agent_stream_logic(websocket: WebSocket, prompt: str, show_reasoning: bool, response_id: str, max_iterations: int, uploaded_file_paths: List[str], session_id: str) -> None:
    """The main agent loop, now sending HTML directly over WebSocket."""

    uploaded_files = []
    for file_path in uploaded_file_paths:
        with open(file_path, "rb") as f:
            uploaded_files.append({"path": os.path.basename(file_path), "data": f.read()})

    user_message = create_message_with_files(prompt, uploaded_file_paths)

    current_messages = [react_instructions] 
    current_messages.extend(user_message)
    print(f"CURRENT_MESSAGES: {current_messages}")
    call_queue = agent_context["call_queue"]
    result_queue = agent_context["result_queue"]

    while not call_queue.empty():
        call_queue.get_nowait()
    while not result_queue.empty():
        result_queue.get_nowait()

    content_id = f"content-{response_id}"
    reasoning_id = f"reasoning-{response_id}"
    
    try:
        for turn in range(max_iterations):
            print(f"----TURN: {turn} ----")
            stream = astream_llama_cpp_response(messages=current_messages, tools=AVAILABLE_TOOLS, client_cfg=client_cfg)
            had_tool_call = False
            tool_id = None
            tool_call = None
            answer = ""
            reasoning_content = ""
            arguments_buffer = ""
            finish_reason = None
            async for event in stream:
                if event is None:
                    continue
                if not event.get("choices") or not event["choices"][0].get("delta"):
                    continue
                choices = event.get("choices")
                if not choices:
                    continue
                first_choice = choices[0]
                delta = first_choice.get("delta")
                if not delta:
                    continue
                if first_choice.get("finish_reason"):
                    finish_reason = first_choice["finish_reason"]
                    
                content = delta.get("content")
                if content:
                    html_chunk = f'<span hx-swap-oob="beforeend:#{content_id}">{content.replace("\\n", "<br>")}</span>'
                    # content_buffer += content
                    # rendered_html = md.render(content_buffer)
                    # html_chunk = f'<div hx-swap-oob="innerHTML:#{content_id}">{rendered_html</div>'
                    await websocket.send_text(html_chunk)
                    answer += content
                    
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    reasoning_content += reasoning   
                if show_reasoning and reasoning:
                    html_chunk = f'<span hx-swap-oob="beforeend:#{reasoning_id}">{reasoning.replace("\\n", "<br>")}</span>'
                    await websocket.send_text(html_chunk)
                    
                # tool_calls = delta.get("tool_calls")
                if "tool_calls" in delta:
                    try:
                        arguments_buffer += delta.get("tool_calls")[0].get("function").get("arguments")
                        if not tool_call:
                            tool_call = delta.get("tool_calls")[0].get("function")
                        if not tool_id:
                            tool_id = delta.get("id")
                        pending_tool_json = json.loads(arguments_buffer)
                        had_tool_call = True
                        tool_call['arguments'] = pending_tool_json
                        await call_queue.put({"tool_call": tool_call, "files": uploaded_files, "session_id": session_id})
                        await call_queue.join()
                        while not result_queue.empty():
                            result = await result_queue.get()
                            result_queue.task_done()
                        current_messages.append({
                            "role": "assistant",
                            "tool_calls": tool_call,
                            "content": "",
                            "reasoning_content": reasoning_content or ""
                        })
                        current_messages.append({
                            "role": "tool",
                            "content": result,
                            "name": pending_tool_json.get("name")
                        })
                    except json.JSONDecodeError:
                        continue
                    
                # if finish_reason == "tool_calls":
                #     if had_tool_call:
                #         current_messages.append({"role": "assistant", "tool_calls": tool_calls_to_execute})
                #         for tool_call in tool_calls_to_execute:
                #             await call_queue.put({"tool_call": tool_call, "files": uploaded_files})

                #         await call_queue.join()
                #         tool_results = []
                #         while not result_queue.empty():
                #             result = await result_queue.get()
                #             tool_results.append(result)
                #             result_queue.task_done()
                #         current_messages.extend(tool_results)
                #         continue
                elif finish_reason == "stop":
                    if reasoning_content and ("</think>" not in reasoning_content):
                        print("⚠️ Incomplete <think> detected at stop; clearing reasoning_content.")
                        reasoning_content = ""
                    # if had_tool_call:
                    #     current_messages.append({"role": "assistant", "tool_calls": tool_calls_to_execute})
                    #     for tool_call in tool_calls_to_execute:
                    #         await call_queue.put({"tool_call": tool_call, "files": uploaded_files})

                    #     await call_queue.join()
                    #     tool_results = []
                    #     while not result_queue.empty():
                    #         result = await result_queue.get()
                    #         tool_results.append(result)
                    #         result_queue.task_done()
                    #     current_messages.extend(tool_results)
                    else:
                        current_messages.append({"role": "assistant", "content": answer, "reasoning_content": reasoning_content})
                        break
            if finish_reason is None:
                print("⚠️ Stream ended without a finish_reason.")
                # Handle partial reasoning separately
                if reasoning_content and ("</think>" not in reasoning_content):
                    print("⚠️ Incomplete <think> block detected; trimming reasoning.")
                    reasoning_content = reasoning_content.split("<think>")[-1]  # keep inner text only, drop tag
                    reasoning_content = reasoning_content[:reasoning_content.find("</think>")] if "</think>" in reasoning_content else ""

                # 🧠 if a full tool_call JSON chunk was parsed, execute it anyway
                if had_tool_call: # and pending_tool_json:
                    print("🛠️ Forcing tool execution despite missing finish_reason.")


                    try:
                        arguments_buffer += delta.get("tool_calls")[0].get("function").get("arguments")
                        pending_tool_json = json.loads(arguments_buffer)
                        had_tool_call = True
                        await call_queue.put({"tool_call": pending_tool_json, "files": uploaded_files, "session_id": session_id})
                        await call_queue.join()
                        while not result_queue.empty():
                            result = await result_queue.get()
                            result_queue.task_done()
                        current_messages.append({
                            "role": "assistant",
                            "tool_calls": [pending_tool_json],
                            "content": "",
                            "reasoning_content": reasoning_content or ""
                        })
                        current_messages.append({
                            "role": "tool",
                            "content": result,
                            "name": pending_tool_json.get("name")
                        })
                    except json.JSONDecodeError:
                        continue
                    
                    # await call_queue.put({"tool_call": pending_tool_json, "files": uploaded_files})
                    # await call_queue.join()
                    # while not result_queue.empty():
                    #     result = await result_queue.get()
                    #     result_queue.task_done()
                    # current_messages.append({
                    #     "role": "assistant",
                    #     "tool_calls": [pending_tool_json],
                    #     "content": "",
                    #     "reasoning_content": reasoning_content or ""
                    # })
                    # current_messages.append({
                    #     "role": "tool",
                    #     "content": result,
                    #     "name": pending_tool_json.get("name")
                    # })
                    # continue

                # otherwise just append a normal assistant turn if clean
                if answer or reasoning_content:
                    current_messages.append({
                        "role": "assistant",
                        "content": answer.strip(),
                        "reasoning_content": reasoning_content.strip()
                    })
                continue



            # if finish_reason is None:
            #     print("⚠️ Stream ended without a finish_reason.")
            #     # Discard incomplete reasoning or tool calls — they corrupt next prefill
            #     if reasoning_content and ("</think>" not in reasoning_content):
            #         print("⚠️ Incomplete <think> block detected, skipping this assistant turn.")
            #         reasoning_content = ""
            #     if had_tool_call and not finish_reason:
            #         print("⚠️ Incomplete tool call, skipping this assistant turn.")
            #         continue
            #     if answer or reasoning_content:
            #         current_messages.append({
            #             "role": "assistant",
            #             "content": answer.strip() if answer else "",
            #             "reasoning_content": reasoning_content.strip() if reasoning_content else ""
            #         })
            #     continue
            # else:
            #     break
                
    except Exception as e:
        error_html = f'<div hx-swap-oob="beforeend:#{content_id}" class="text-sm text-red-500">[Error]: {e}</div>'
        await websocket.send_text(error_html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
            
