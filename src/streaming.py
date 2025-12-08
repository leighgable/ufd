import httpx
import json
import re
import sys
import markdown_it
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
        content_str = json.dumps(parsed_outputs)
        
        return {
            "role": "tool",
            "tool_call_id": fn_id,
            "content": content_str,
        }
    except Exception as e:
        print(f"Error executing tool '{fn_name}' (ID: {fn_id}): {e}", file=sys.stderr)
        return {
            "role": "tool",
            "tool_call_id": fn_id,
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

class MarkdownBufferProcessor:
    """
    Manages the streaming of text chunks, buffering content that contains
    unclosed Markdown structures (specifically code fences) to prevent
    rendering glitches in a real-time UI.
    """

    def __init__(self):
        # Initialize the markdown-it parser
        self.md = markdown_it.MarkdownIt()
        # The buffer holds incoming text chunks that are not yet stable
        self.buffer = ""
        # The content that has been previously rendered (stable)
        self.rendered_content = ""
        # Regex to detect an opening code fence (``` followed by optional language name)
        # We look for it starting on a new line.
        self.open_fence_pattern = re.compile(r'\n```[\w-]*\n')

    def process_chunk(self, chunk: str) -> str:
        """
        Processes a new chunk, updates the internal buffer, flushes stable
        content, and returns the newly stable HTML fragment.
        """
        self.buffer += chunk
        
        # 1. Find the index of the last set of closing triple backticks
        last_closed_index = self.buffer.rfind('\n```\n')
        
        # 2. Find the index of the last opening triple backticks
        last_open_index = -1
        # Iterate over all matches to find the very last occurrence
        for match in self.open_fence_pattern.finditer(self.buffer):
            last_open_index = match.start()
        
        stable_index = len(self.buffer)
        
        # CRITICAL LOGIC: If an open fence is found (last_open_index != -1)
        # AND it comes AFTER the last closed fence, the block is incomplete.
        if last_open_index != -1 and last_open_index > last_closed_index:
            # Buffer everything from the start of the open fence.
            stable_index = last_open_index
        
        # Also, hold back the final line to protect against incomplete inline elements
        # like **bold at the very end.
        if stable_index == len(self.buffer):
            last_newline_index = self.buffer.rfind('\n', 0, stable_index - 1)
            if last_newline_index != -1:
                stable_index = last_newline_index + 1
            else:
                # If there are no newlines, we're streaming the first line,
                # and we'll wait for a newline or the end.
                stable_index = 0
        
        new_html_fragment = ""

        if stable_index > 0:
            # Extract the stable text content
            stable_content = self.buffer[:stable_index]
            
            # Update the buffer (remaining content is unstable)
            self.buffer = self.buffer[stable_index:]

            # 3. Render the newly stable content
            # We must render the ENTIRE content (rendered_content + stable_content)
            # to get correct HTML structure (like list numbering), but we only send
            # the *difference* in the rendered HTML to the client via HTMX.
            
            # The total content to be rendered this step
            total_content_now = self.rendered_content + stable_content
            
            # Render the whole document
            full_html_now = self.md.render(total_content_now)
            
            # To get the difference (the fragment to stream), we compare the length
            # of the newly rendered HTML against the HTML rendered in the previous step.
            # NOTE: For simplicity, we assume HTML length difference is sufficient.
            # A more robust solution might track paragraph breaks.
            
            # Simple approach: Just render the *total* content and let HTMX replace/update the whole element.
            # This is simpler and more reliable for full Markdown parsing.
            new_html_fragment = full_html_now
            
            self.rendered_content = total_content_now

        return new_html_fragment

    def finish(self) -> str:
        """
        Flushes any remaining content in the buffer when the stream ends.
        Returns the final rendered HTML for the full document.
        """
        if self.buffer:
            self.rendered_content += self.buffer
            self.buffer = ""
        
        # Render the final complete content
        return self.md.render(self.rendered_content)
