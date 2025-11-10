import httpx
import json
import sys
import asyncio
from typing import Dict, Any, Callable, List, AsyncGenerator
from .utils import (get_current_location,
    get_current_temperature,
    run_code_interpreter,
    parse_sbx_exec,
    create_message_with_files,
)
MODEL_NAME = "qwen3-0.6B"

client_cfg = {
    "model_name": MODEL_NAME,
    "base_url": "http://localhost:8080/v1/chat/completions",
    "system_prompt": None,
    "api_key": "EMPTY",
}

async def function_worker_async(function: Callable,
    call_queue: asyncio.Queue,
    result_queue: asyncio.Queue
):
    """Checks queue for function calls to execute, with corrected error handling.
    """
    while True:
        call_data = await call_queue.get()
        if call_data is None:
            print("[Worker] Sentinel value received. Shutting down.")
            break
        tool_call = call_data.get("tool_call")
        files = call_data.get("files")
        session_id = call_data.get("session_id")
        
        execution_result = None
        try:
            print(f"[Worker] Executing: {tool_call.get('name')}")
            
            execution_result = await asyncio.to_thread(function,
                                                        tool_call,
                                                        files=files,
                                                        session_id=session_id)
            print(f"EXEC: {execution_result}")
        except Exception as e:
            print(f"[Worker] Error during function execution: {e}")
        finally:
            if execution_result:
                await result_queue.put(execution_result)
            call_queue.task_done()

def call_function(tool_call: Dict[str, Any],
    files: List[Dict[str, Any]] = None,
    session_id: str = None,
) -> Dict[str, Any]:

    fn_name = tool_call.get("function", {}).get("name", "unknown")
    try:
        fn_args: dict = json.loads(tool_call.get("function", "{}").get("arguments", "{}"))
        fn_id = tool_call.get("id", "missing_id")
        
        if fn_name == "run_code_interpreter":
            fn_args['files'] = files
            fn_args['session_id'] = session_id
            
        print(f"ARGS TYPE: {type(fn_args)}")
        execution_result_obj = get_function_by_name(fn_name)(**fn_args)
        parsed_outputs = parse_sbx_exec(execution_result_obj)
        content_str = json.dumps(parsed_outputs)

        # 4. Return the message with the content formatted for the agent
        return {
            "role": "tool",
            "tool_call_id": fn_id,
            "content": content_str,
        }
    except Exception as e:
        print(f"Error during tool call: {e}", file=sys.stderr)
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", "missing"),
            "content": f"Error executing tool: {e}",
        }

def get_function_by_name(name):
    if name == "run_code_interpreter":
        return run_code_interpreter
    if name == "get_current_temperature":
        return get_current_temperature
    if name == "get_current_location":
        return get_current_location
    else:
        return None

async def astream_llama_cpp_response(
    messages: List[Dict[str, Any]] = None,
    tools: List = None,
    files: List[str] = None,
    client_cfg: Dict = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Makes an asynchronous streaming request to the llama.cpp server using httpx.
    This is non-blocking. Parses qwen3-style xml tool calls.
    """

    payload = { "stream": True }
    if tools:
        payload['tools'] = tools
    if model_name := client_cfg.get('model_name', "default"):
        payload['model'] = model_name
    if messages:
        payload["messages"] = messages
    if files:
        payload["messages"] = create_message_with_files(messages)

    headers = {
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            async with client.stream("POST", client_cfg['base_url'], headers=headers, json=payload) as response:
                response.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
                buffer = ""
                async for line in response.aiter_lines():
                    if line.strip().startswith("data:"):
                        try:
                            data_str = line.split("data:", 1)[1].strip()
                            if data_str == "[DONE]":
                                break
                            
                            # yield json.loads(data_str)
                            chunk = json.loads(data_str)
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                            if content:
                                buffer += content
                            if "<tool_call>" in buffer and "</tool_call>" in buffer:
                                start_index = buffer.find("<tool_call>")
                                end_index = buffer.find("</tool_call>") + len("</tool_call>")
                                tool_call_str = buffer[start_index:end_index]
                                json_str = tool_call_str.replace("<tool_call>", "").replace("</tool_call>", "").strip()
                                try:
                                    tool_call_json = json.loads(json_str)
                                    tool_call_event = {
                                        "choices": [{
                                            "delta": {
                                                "tool_calls": [{
                                                    "id": f"call_{hash(json_str)}",
                                                    "type": "function",
                                                    "function": {
                                                        "name": tool_call_json.get("name"),
                                                        "arguments": json.dumps(tool_call_json.get("arguments", {}))
                                                    }
                                                }]
                                            }
                                        }]
                                    }
                                    yield tool_call_event
                                    buffer = buffer[end_index:]
                                except json.JSONDecodeError:
                                    pass
                            yield chunk
                            
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            print(f"\n[An unexpected error occurred during stream processing: {e}]")
                            break

        except httpx.RequestError as e:
            print(f"\n[Request Error: Could not connect to the server or request failed. Ensure llama.cpp is running at {client_cfg['base_url']}]")
            print(f"Details: {e}")
            yield None
