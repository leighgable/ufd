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

# async def parse_and_enqueue_calls(response_stream: AsyncGenerator, call_queue: asyncio.Queue, show_reasoning: bool = False):
#     """
#     A robust parser that accumulates all tool call chunks throughout a stream
#     and only enqueues the final, complete call at the very end.
#     """
#     accumulating_tool_call = None
#     last_content = ""
#     last_reasoning = ""

#     # This first loop consumes the whole stream for this turn, yielding UI updates
#     # and accumulating one single tool call object if it exists.
#     async for message_list in response_stream:
#         if not isinstance(message_list, list):
#             continue
        
#         for message in message_list:
#             msg_dict = message if isinstance(message, dict) else message.model_dump(exclude_none=True)

#             # Part 1: Accumulate tool call chunks if they exist
#             if is_tool_call_chunk := ('function_call' in msg_dict):
#                 partial_tool_call = msg_dict['function_call']
#                 if not accumulating_tool_call:
#                     accumulating_tool_call = {"name": "", "arguments": ""}
#                 if name_chunk := partial_tool_call.get('name'):
#                     accumulating_tool_call['name'] += name_chunk
#                 if args_chunk := partial_tool_call.get('arguments'):
#                     accumulating_tool_call['arguments'] += args_chunk

#             # Part 2: Process content stream (with diffing)
#             if (content := msg_dict.get('content')) is not None:
#                 if isinstance(content, str):
#                     new_chunk = content[len(last_content):]
#                     if new_chunk:
#                         yield {"type": "content", "data": new_chunk}
#                     last_content = content
#                 elif isinstance(content, list):
#                     for item in content:
#                         if isinstance(item, (dict, ContentItem)) and (text := item.get('text')):
#                             yield {"type": "content", "data": text}
#                             break
            
#             # Part 3: Process reasoning stream (with diffing)
#             if show_reasoning and (reasoning := msg_dict.get('reasoning_content')) is not None:
#                 if isinstance(reasoning, str):
#                     new_chunk = reasoning[len(last_reasoning):]
#                     if new_chunk:
#                         yield {"type": "reasoning", "data": new_chunk}
#                     last_reasoning = reasoning
#                 elif isinstance(reasoning, list):
#                     for item in reasoning:
#                         if isinstance(item, (dict, ContentItem)) and (text := item.get('text')):
#                             yield {"type": "reasoning", "data": text}
#                             break

#     # After the entire stream for this turn is finished, if we have
#     # built a tool call, we yield it for the UI and enqueue it for the worker.
#     if accumulating_tool_call:
#         yield {"type": "tool_call", "data": accumulating_tool_call}
#         await call_queue.put(accumulating_tool_call)
                        
        
async def parse_delta_enqueue_calls(response_stream: AsyncGenerator,
    call_queue: asyncio.Queue,
    show_reasoning: bool = False
):
    """
    Parse ChoiceDelta stream from AsyncOpenAI stream and enqueue tool calls
    """
    accumulated_tool_calls = []
    async for chunk in response_stream:
        if chunk.choices and chunk.choices[0].delta:
            delta = chunk.choices[0].delta
        else:
            break
        if content := delta.content and delta.content is not None:
            yield {"type": "content", "data": content}
            break
        if reason := delta.model_extra.get("reasoning_content"):
            yield {"type": "reasoning", "data": reason}
            break
        if delta.tool_calls:
            for tc_chunk in delta.tool_calls:
                tool_call_index = tc_chunk.index
            while len(accumulated_tool_calls) <= tool_call_index:
                accumulated_tool_calls.append({
                                                  "id": "",
                                                  "type": "function",
                                                  "function": {"name": "",
                                                               "arguments": ""},
                                              })
            # Get the existing tool call object to update
            tc_object = accumulated_tool_calls[tool_call_index]

            # Concatenate attributes from the chunk
            if tc_chunk.id:
                tc_object["id"] += tc_chunk.id
            if tc_chunk.function.name:
                tc_object["function"]["name"] += tc_chunk.function.name
            if tc_chunk.function.arguments:
                tc_object["function"]["arguments"] += tc_chunk.function.arguments
            
    # If the stream finishes and there are tool calls, execute them
    if chunk.choices[0].finish_reason == "tool_calls":
        print(f"\nStream finished. Accumulated tool calls: {len(accumulated_tool_calls)}")
        print(json.dumps(accumulated_tool_calls, indent=2))
        
        for tool_call in accumulated_tool_calls:
            function_id = tool_call["id"]
            function_name = tool_call["function"]["name"]
            arguments_str = tool_call["function"]["arguments"]

            try:
                arguments = json.loads(arguments_str)
                print(f"Tool execution result: {tool_call}")
                yield {
                        "type": "function",
                        "id": function_id,
                        "name": function_name,
                        "data": arguments,
                }
                await call_queue.put({
                                     "name": function_name,
                                     "id": function_id,
                                     "arguments": arguments
                                 })
            except json.JSONDecodeError:
                print(f"Could not parse JSON arguments for tool call: {arguments_str}")
                yield {
                        "type": "tool_call",
                        "id": function_id,
                        "name": function_name,
                        "arguments": f"Json decode error: {arguments_str}",
                    }
                
            except Exception as e:
                print(f"Error executing tool '{function_name}': {e}")
                yield {
                        "type": "tool_call",
                        "id": function_id,
                        "name": function_name,
                        "arguments": f"Json decode error: {e}",
                    }


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
            async for event in parse_and_enqueue_calls(stream, call_queue):
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

