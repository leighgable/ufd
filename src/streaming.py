import json
import asyncio
from openai import AsyncOpenAI
from typing import Dict, Any, AsyncGenerator
from .utils import (get_current_location,
    get_current_temperature,
    run_code_interpreter,
    parse_sbx_exec,
)

model_cfg = {
    "base_url": "http://localhost:8080/v1",
    "api_key": "EMPTY",
}


async def function_worker_async(call_queue: asyncio.Queue,
    result_queue: asyncio.Queue):
    """Checks queue for function calls to execute, with corrected error handling.
    """
    while True:
        function_call = await call_queue.get()
        if function_call is None:
            print("[Worker] Sentinel value received. Shutting down.")
            break
        
        execution_result = None
        try:
            print(f"[Worker] Executing: {function_call.get('name')}")
            execution_result = call_function(**function_call)
            
        except Exception as e:
            print(f"[Worker] Error during function execution: {e}")
            execution_result = {
                "role": "function",
                "name": function_call.get("name", "unknown_function"),
                "content": f"Error: An exception occurred while executing the tool: {e}",
            }
        finally:
            # This block now correctly ensures that for every item,
            # we ALWAYS put a result back and mark the task as done, exactly once.
            if execution_result:
                await result_queue.put(execution_result)
            call_queue.task_done()

    
async def parse_delta_enqueue_calls(response_stream: AsyncGenerator,
    call_queue: asyncio.Queue
):
    """
    Parse ChoiceDelta stream from AsyncOpenAI stream and enqueue tool calls
    """
    
    async with response_stream as stream:
        async for event in stream:
            yield event
        
            if event.type == "tool_calls.function.arguments.delta":
                tool_call_index = event.index
                tool_name = event.name
                arguments = event.arguments

            elif event.type == "tool_calls.function.arguments.done":
                try:

                    arguments = json.loads(arguments)
                    await call_queue.put({
                                             "name": tool_name,
                                             "id": tool_call_index,
                                             "arguments": arguments
                                         })                    
            
                except json.JSONDecodeError:
                    print(f"Could not parse JSON arguments for tool call: {arguments}")
                    await call_queue.put({
                                         "name": tool_name,
                                         "id": tool_call_index,
                                         "arguments": {"error": f"JSON decode error: {arguments}"}})
                except Exception as e:
                    print(f"Error executing tool '{tool_name}': {e}")
                    await call_queue.put({
                                             "name": tool_name,
                                             "id": tool_call_index,
                                             "arguments": {"error": f"Error: {e}"}
                                         })

def call_function(tool_call: Dict[str, Any]) -> Dict[str, Any]:

    fn_name = tool_call.get("name", "unknown_function")
    fn_args = tool_call.get("arguments", "{}")
    fn_id = tool_call.get("id", "missing_id")

    # 1. Execute the tool to get the raw execution object
    execution_result_obj = get_function_by_name(fn_name)(**fn_args)

    # 2. Parse the raw result into a structured list (text, images, etc.)
    parsed_outputs = parse_sbx_exec(execution_result_obj)

    # 3. For a "function" role, the content must be a simple string.
    #    We will serialize the entire list of parsed outputs into a single JSON string.
    content_str = json.dumps(parsed_outputs)

    # 4. Return the message with the content formatted for the agent
    return {
        "role": "function",
        "tool_call_id": fn_id,
        "name": fn_name,
        "content": content_str,
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

async def main_agent_loop():
    """Main agent loop orchestrating the client, parser, and worker.
    """
    MAX_TURNS = 5
    print("--- Starting Agent Loop ---")

    # 1. Initialize client, queues, and the background worker task
    async_client = AsyncOpenAI(**model_cfg)
    call_queue = asyncio.Queue()
    result_queue = asyncio.Queue()
    worker_task = asyncio.create_task(function_worker_async(
        call_queue=call_queue, result_queue=result_queue
    ))

    # 2. Start with the initial user prompt
    # Using the templates.py file for the initial prompt
    current_messages = messages
    print(f"Initial Prompt: {current_messages[-1]['content']}")

    try:
        for turn in range(MAX_TURNS):
            print(f"\n--- Turn {turn + 1} ---")
            had_tool_call_in_turn = False

            # 3. Get the async stream from the client
            stream = async_client.chat(messages=current_messages, functions=functions)

            # 4. Process the stream with the parser
            # The parser will yield content for the UI and put function calls on the queue
            print("Agent:", end="", flush=True)
            async for event in parse_delta_enqueue_calls(stream, call_queue):
                if isinstance(event, dict) and event.get('name'): # It's a function call
                    had_tool_call_in_turn = True
                    # Optional: print out tool calls as they are found
                    print(f"\n[Tool Call Found: {event.get('name')}]", end="", flush=True)
                elif isinstance(event, str):
                    # This is content from the model
                    print(event, end="", flush=True)
            print() # for a newline

            # 5. Wait for the worker to execute all functions found in this turn
            await call_queue.join()

            # 6. Check if any tools were called. If not, the agent is done.
            if not had_tool_call_in_turn:
                print("\n--- Final Answer Received --- ")
                break

            # 7. Gather results and feed them back to the model
            results = []
            while not result_queue.empty():
                results.append(await result_queue.get())
            
            print(f"\n--- Feeding back {len(results)} tool results ---")
            current_messages.extend(results)
        else:
            print("\n--- Max turns reached --- ")

    except Exception as e:
        print(f"\n[Error in main loop]: {e}")
    finally:
        # 8. Gracefully shut down the worker
        print("\n--- Shutting down worker ---")
        await call_queue.put(None)
        await worker_task

