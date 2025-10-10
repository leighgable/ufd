import asyncio
from agno.agent import RunEvent
from .ufd import ufd_agent
from agno.utils.pprint import apprint_run_response
from typing import Any
prompt = "What is the capital of China?"

tool_prompt = "Write me a python function that takes a number and returns the square root."

async def run_agent_with_events(agent: Any, prompt: str):
    content_started = False
    async for run_output_event in agent.arun(
        prompt,
    ):
        if run_output_event.event in [RunEvent.run_started, RunEvent.run_completed]:
            print(f"\nEVENT: {run_output_event.event}")

        if run_output_event.event in [RunEvent.reasoning_started]:
            print(f"\nEVENT: {run_output_event.event}")

        if run_output_event.event in [RunEvent.reasoning_step]:
            print(f"\nEVENT: {run_output_event.event}")
            print(f"REASONING CONTENT: {run_output_event.reasoning_content}")

        if run_output_event.event in [RunEvent.reasoning_completed]:
            print(f"\nEVENT: {run_output_event.event}")

        if run_output_event.event in [RunEvent.tool_call_started]:
            print(f"\nEVENT: {run_output_event.event}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")  # type: ignore
            print(f"TOOL CALL ARGS: {run_output_event.tool.tool_args}")  # type: ignore

        if run_output_event.event in [RunEvent.run_content]:
            if not content_started:
                print("\nCONTENT:")
                content_started = True
            else:
                if run_output_event.content is not None:
                    print(run_output_event.content, end="")


async def streaming(agent: Any):
    async for response in agent.arun(input=prompt):
        print(response.content, end="", flush=True)

async def streaming_print(agent: Any):
    await agent.aprint_response(input=prompt)

async def streaming_pprint(agent: Any):
    await apprint_run_response(agent.arun(input=prompt))
async def event_debug(agent: Any):
    generator = ufd_agent.arun(tool_prompt)
    async for event in generator:
        print(f"{event.event}: {event.content}\n")
if __name__=="__main__":
    asyncio.run(run_agent_with_events(ufd_agent, tool_prompt))

    # ufd_agent.cli_app(stream=True, debug_mode=True)
    # asyncio.run(streaming(ufd_agent))
    # asyncio.run(streaming_print(ufd_agent))
    # asyncio.run(streaming_pprint(ufd_agent))  
    
