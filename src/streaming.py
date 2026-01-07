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
        tool_call = json.loads(tool_call)
        files = call_data.get("files")
        session_id = call_data.get("session_id")
        
        execution_result = None
        try:
            print("[Worker] Executing tool call")
            
            execution_result = await asyncio.to_thread(function,
                                                        tool_call=tool_call,
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

    fn_name = tool_call.get("function", {}).get("name", "run_code_interpreter")
    fn_id = tool_call.get("id", "missing_id")  # Get ID early

    try:
        fn_args_str = tool_call.get("function", {}).get("arguments", "{}")
        
        # Handle empty strings and potential double-encoding from the model
        parsed_args = json.loads(fn_args_str) if fn_args_str.strip() else {}

        # The model sometimes double-encodes the JSON arguments as a string
        if isinstance(parsed_args, str):
            fn_args = json.loads(parsed_args)
        else:
            fn_args = parsed_args

        # Ensure fn_args is a dictionary before proceeding
        if not isinstance(fn_args, dict):
            # This handles cases where the model returns a single value instead of a dict,
            # e.g., just the code string for run_code_interpreter.
            fn_args = {"code": fn_args}

        if fn_name == "run_code_interpreter":
            fn_args['files'] = files
            fn_args['session_id'] = session_id
            
        execution_result_obj = get_function_by_name(fn_name)(**fn_args)
        parsed_outputs = parse_sbx_exec(execution_result_obj)
        
        # Format the parsed outputs into a model-friendly string
        content_str = ""
        for output in parsed_outputs:
            if output['output_type'] == 'stream':
                content_str += f"Output from {output['name']}:\n{output['text']}\n"
            elif output['output_type'] == 'execute_result':
                if 'text/plain' in output['data']:
                    content_str += f"Result:\n{output['data']['text/plain']}\n"
            elif output['output_type'] == 'error':
                content_str += f"An error occurred: {output['ename']}\n{output['evalue']}\n"
        
        if not content_str.strip():
            content_str = "Tool executed successfully with no output."
        
        # Check if the tool execution itself resulted in an error
        tool_had_error = any(out.get('output_type') == 'error' for out in parsed_outputs)
        
        response_dict = {
            "role": "tool",
            "tool_call_id": fn_id,
            "content": content_str,
        }
        if tool_had_error:
            response_dict["is_error"] = True

        return response_dict
    except Exception as e:
        print(f"Error executing tool '{fn_name}' (ID: {fn_id}): {e}", file=sys.stderr)
        return {
            "role": "tool",
            "tool_call_id": fn_id,
            "content": f"Error executing tool: {e}",
            "is_error": True,
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
    This is non-blocking. It accumulates tool calls and yields them at the end.
    """
    payload = {"stream": True}
    if tools:
        payload['tools'] = tools
    if model_name := client_cfg.get('model_name', "default"):
        payload['model'] = model_name
    if messages:
        payload["messages"] = messages
    if files:
        payload["messages"] = create_message_with_files(messages)

    headers = {"Content-Type": "application/json"}
    
    wip_tool_calls = {}  # Work-in-progress tool calls, keyed by index

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            async with client.stream("POST", client_cfg['base_url'], headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip().startswith("data:"):
                        try:
                            data_str = line.split("data:", 1)[1].strip()
                            if data_str == "[DONE]":
                                break
                            chunk = json.loads(data_str)
                            
                            choices = chunk.get("choices")
                            if not isinstance(choices, list) or not choices:
                                continue

                            delta = choices[0].get("delta", {})
                            if not isinstance(delta, dict):
                                yield choices
                                continue
                            
                            # Safely handle tool call accumulation
                            if "tool_calls" in delta:
                                partial_calls = delta["tool_calls"]
                                if isinstance(partial_calls, list):
                                    for p_call in partial_calls:
                                        if not isinstance(p_call, dict): continue
                                        
                                        # Use index to distinguish concurrent tool calls
                                        index = p_call.get("index", 0)

                                        # Initialize tool call if it's the first time we see it
                                        if index not in wip_tool_calls:
                                            wip_tool_calls[index] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                        
                                        # Accumulate parts
                                        if p_call.get("id"):
                                            wip_tool_calls[index]["id"] = p_call["id"]
                                        
                                        if func := p_call.get("function"):
                                            if func.get("name"):
                                                wip_tool_calls[index]["function"]["name"] += func["name"]
                                            if func.get("arguments"):
                                                wip_tool_calls[index]["function"]["arguments"] += func["arguments"]
                            else:
                                # Not a tool call chunk, so yield it
                                yield choices

                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            print(f"\n[An unexpected error occurred during stream processing: {e}]")
                            break
            
            # After the stream is done, yield the completed tool calls
            if wip_tool_calls:
                final_tool_calls = [wip_tool_calls[i] for i in sorted(wip_tool_calls.keys())]
                
                # Final validation of argument JSON
                for call in final_tool_calls:
                    try:
                        json.loads(call["function"]["arguments"])
                    except json.JSONDecodeError as e:
                        # The accumulated arguments are not valid JSON.
                        # This can happen if the model output is malformed.
                        print(f"Warning: Could not parse tool call arguments for call id {call.get('id')}. Error: {e}", file=sys.stderr)

                yield [{
                    "delta": {"tool_calls": final_tool_calls},
                    "finish_reason": "tool_calls"
                }]

        except httpx.RequestError as e:
            print(f"\n[Request Error: Could not connect to the server or request failed. Ensure llama.cpp is running at {client_cfg['base_url']}]")
            print(f"Details: {e}")
            yield None

