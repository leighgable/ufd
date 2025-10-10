from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.llama_cpp import LlamaCpp
from agno.tools.e2b import E2BTools
from agno.tools.reasoning import ReasoningTools
from textwrap import dedent
from agno.workflow import Loop, Step, Workflow

e2b_tools = E2BTools(
    timeout=2400,
    include_tools=[
        "run_python_code",
        "list_files",
        "read_file_content",
        "write_file_content"
    ],
)

# Create the Agent
ufd_agent = Agent(
    name="UFD Agent",
    model=LlamaCpp(id="ggml-org/Qwen3-0.6B-GGUF"),
    # Add a database to the Agent
    db=SqliteDb(db_file="tmp/agno.db"),
    # Add the Agno MCP server to the Agent
    tools=[e2b_tools,
        ReasoningTools(
            add_instructions=True,
            # think=True,
            # analyze=True,
        ),
    ],
    instructions=dedent("""\
        You are an expert with strong analytical skills! 🧠

        Your approach to problems:
        1. First, break down complex questions into component parts
        2. Clearly state your assumptions
        3. Develop a structured reasoning path
        4. Consider multiple perspectives
        5. Evaluate evidence and counter-arguments
        6. Draw well-justified conclusions

        When solving problems:
        - Use explicit step-by-step reasoning
        - Identify key variables and constraints
        - Explore alternative scenarios
        - Highlight areas of uncertainty
        - Explain your thought process clearly
        - Consider both short and long-term implications
        - Evaluate trade-offs explicitly

        For quantitative problems:
        - Show your calculations
        - Explain the significance of numbers
        - Consider confidence intervals when appropriate
        - Identify source data reliability

        For qualitative reasoning:
        - Assess how different factors interact
        - Consider psychological and social dynamics
        - Evaluate practical constraints
        - Address value considerations
        \
    """),
    # Add the previous session history to the context
    add_history_to_context=True,
    enable_user_memories=True,
    enable_agentic_memory=True,
    stream_intermediate_steps=True,
    markdown=True,
    # debug_mode=True,
    stream=True
    
)


