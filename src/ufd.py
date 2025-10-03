import copy
# from jinja2 import DictLoader
import datetime
import nbformat
# from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
from nbconvert import HTMLExporter
# from e2b_code_interpreter import Sandbox
from traitlets.config import Config
import json
from prompts import TOOLS
from templates import ( assistant_final_answer_template,
    assistant_thinking_template,
    user_template,
    system_template,
    DONE_WIDGET,
    GENERATING_WIDGET,
    EXECUTING_WIDGET,
    custom_css,
    header_message,
    bad_html_bad,
    TIMEOUT_HTML,
    ERROR_HTML,
    STOPPED_SANDBOX_HTML,
)

MAX_TURNS = 50
model_name = "Qwen3"
# Configure the exporter
config = Config()
html_exporter = HTMLExporter(config=config, template_name="classic")

def execute_code(sbx, code):
    execution = sbx.run_code(code, on_stdout=lambda data: print('stdout:', data))
    output = ""
    if len(execution.logs.stdout) > 0:
        output += "\n".join(execution.logs.stdout)
    if len(execution.logs.stderr) > 0:
        output += "\n".join(execution.logs.stderr)
    if execution.error is not None:
        output += execution.error.traceback
    return output, execution


def parse_exec_result_llm(execution, max_code_output=1000):
    output = []

    def truncate_if_needed(text):
        if len(text) > max_code_output:
            return (text[:max_code_output] + f"\n[Output is truncated as it is more than {max_code_output} characters]")
        return text

    if execution.results:
        output.append(truncate_if_needed("\n".join([result.text for result in execution.results])))
    if execution.logs.stdout:
        output.append(truncate_if_needed("\n".join(execution.logs.stdout)))
    if execution.logs.stderr:
        output.append(truncate_if_needed("\n".join(execution.logs.stderr)))
    if execution.error is not None:
        output.append(truncate_if_needed(execution.error.traceback))
    return "\n".join(output)

def clean_messages_for_api(messages):
    """
    Create a clean copy of messages without raw_execution fields for API calls.
    This prevents 413 errors caused by large execution data.
    """
    cleaned_messages = []
    for message in messages:
        cleaned_message = message.copy()
        if "raw_execution" in cleaned_message:
            cleaned_message.pop("raw_execution")
        cleaned_messages.append(cleaned_message)
    return cleaned_messages


def run_interactive_notebook(client, model, messages, sbx, max_new_tokens=512):
    notebook = JupyterNotebook(messages)
    sbx_info = sbx.get_info()
    notebook.add_sandbox_countdown(sbx_info.started_at, sbx_info.end_at)
    yield notebook.render(mode="generating"), notebook.data, messages
    
    max_code_output = 1000
    turns = 0
    done = False

    while not done and (turns <= MAX_TURNS):
        turns += 1
        try:
            # Inference client call - might fail
            response = client.chat.completions.create(
                messages=clean_messages_for_api(messages),
                model=model,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            # Handle inference client errors
            notebook.add_error(f"Inference failed: {str(e)}")
            return notebook.render(), notebook.data, messages

        # Get the response content and tool calls
        full_response = response.choices[0].message.content or ""
        tool_calls = response.choices[0].message.tool_calls or []

        # Add markdown cell for assistant's thinking
        notebook.add_markdown(full_response, "assistant")

        # Handle tool calls
        for tool_call in tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": full_response,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                    ],
                }
            )

            if tool_call.function.name == "add_and_execute_code":
                tool_args = json.loads(tool_call.function.arguments)
            
            notebook.add_code(tool_args["code"])
            yield notebook.render(mode="executing"), notebook.data, messages

            try:
                # Execution sandbox call - might timeout
                execution = sbx.run_code(tool_args["code"])
                notebook.append_execution(execution)
                
            except Exception as e:
                # Handle sandbox timeout/execution errors
                notebook.add_error(f"Code execution failed: {str(e)}")
                return notebook.render(), notebook.data, messages

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": parse_exec_result_llm(execution, max_code_output=max_code_output),
                    "raw_execution": notebook.parse_exec_result_nb(execution)
                }
            )

        if not tool_calls:
            if len(full_response.strip())==0:
                notebook.add_error(f"No tool call and empty assistant response:\n{response.model_dump_json(indent=2)}")
            messages.append({"role": "assistant", "content": full_response})
            done = True
            
        if done:
            yield notebook.render(mode="done"), notebook.data, messages
        else:
            yield notebook.render(mode="generating"), notebook.data, messages


class JupyterNotebook:
    def __init__(self, messages=None):
        self.exec_count = 0
        self.countdown_info = None
        if messages is None:
            messages = []
        self.data, self.code_cell_counter = self.create_base_notebook(messages)


    def create_base_notebook(self, messages):
        base_notebook = {
            "metadata": {
                "kernel_info": {"name": "python3"},
                "language_info": {
                    "name": "python",
                    "version": "3.12",
                },
            },
            "nbformat": 4,
            "nbformat_minor": 0,
            "cells": []
        }
        
        # Add header
        base_notebook["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": header_message.format(model_name)
        })

        # Set initial data
        self.data = base_notebook
        
        # Add empty code cell if no messages
        if len(messages) == 0:
            self.data["cells"].append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "source": "",
                "outputs": []
            })
            return self.data, 0

        # Process messages using existing methods
        i = 0
        while i < len(messages):
            message = messages[i]
            
            if message["role"] == "system":
                self.add_markdown(message["content"], "system")
                
            elif message["role"] == "user":
                self.add_markdown(message["content"], "user")
                
            elif message["role"] == "assistant":
                if "tool_calls" in message:
                    # Add assistant thinking if there's content
                    if message.get("content"):
                        self.add_markdown(message["content"], "assistant")
                    
                    # Process tool calls - we know the next message(s) will be tool responses
                    for tool_call in message["tool_calls"]:
                        if tool_call["function"]["name"] == "add_and_execute_code":
                            tool_args = json.loads(tool_call["function"]["arguments"])
                            code = tool_args["code"]
                            
                            # Get the next tool response (guaranteed to exist)
                            tool_message = messages[i + 1]
                            if tool_message["role"] == "tool" and tool_message.get("tool_call_id") == tool_call["id"]:
                                # Use the raw execution directly!
                                execution = tool_message["raw_execution"]
                                self.add_code_execution(code, execution, parsed=True)
                                i += 1  # Skip the tool message since we just processed it
                else:
                    # Regular assistant message
                    self.add_markdown(message["content"], "assistant")
                    
            elif message["role"] == "tool":
                # Skip - should have been handled with corresponding tool_calls
                # This shouldn't happen given our assumptions, but just in case
                pass
                
            i += 1
        
        return self.data, 0

    def _update_countdown_cell(self):
        if not self.countdown_info:
            return
            
        start_time = self.countdown_info['start_time']
        end_time = self.countdown_info['end_time']
        
        current_time = datetime.datetime.now(datetime.timezone.utc)
        remaining_time = end_time - current_time
        
        # Show stopped message if expired
        if remaining_time.total_seconds() <= 0:
            # Format display for stopped sandbox
            start_display = start_time.strftime("%H:%M")
            end_display = end_time.strftime("%H:%M")
            
            stopped_html = STOPPED_SANDBOX_HTML.format(
                start_time=start_display,
                end_time=end_display
            )
            
            # Update countdown cell to show stopped message
            stopped_cell = {
                "cell_type": "markdown",
                "metadata": {},
                "source": stopped_html
            }
            
            # Find and update existing countdown cell
            for i, cell in enumerate(self.data["cells"]):
                if cell.get("cell_type") == "markdown" and ("⏱" in str(cell.get("source", "")) or "⏹" in str(cell.get("source", ""))):
                    self.data["cells"][i] = stopped_cell
                    break
            
            return
        
        # Calculate current progress
        total_duration = end_time - start_time
        elapsed_time = current_time - start_time
        current_progress = (elapsed_time.total_seconds() / total_duration.total_seconds()) * 100
        current_progress = max(0, min(100, current_progress))
        
        # Format display
        start_display = start_time.strftime("%H:%M")
        end_display = end_time.strftime("%H:%M")
        remaining_seconds = int(remaining_time.total_seconds())
        remaining_minutes = remaining_seconds // 60
        remaining_secs = remaining_seconds % 60
        remaining_display = f"{remaining_minutes}:{remaining_secs:02d}"
        
        # Generate unique ID to avoid CSS conflicts when updating
        unique_id = int(current_time.timestamp() * 1000) % 100000
        
        # Calculate total timeout duration in seconds
        total_seconds = int(total_duration.total_seconds())
        
        countdown_html = TIMEOUT_HTML.format(
            start_time=start_display,
            end_time=end_display,
            current_progress=current_progress,
            remaining_seconds=remaining_seconds,
            unique_id=unique_id,
            total_seconds=total_seconds
        )
        
        # Update or insert the countdown cell
        countdown_cell = {
            "cell_type": "markdown",
            "metadata": {},
            "source": countdown_html
        }
        
        # Find existing countdown cell by looking for the timer emoji
        found_countdown = False
        for i, cell in enumerate(self.data["cells"]):
            if cell.get("cell_type") == "markdown" and "⏱" in str(cell.get("source", "")):
                # Update existing countdown cell
                self.data["cells"][i] = countdown_cell
                found_countdown = True
                break
        
        if not found_countdown:
            # Insert new countdown cell at position 1 (after header)
            self.data["cells"].insert(1, countdown_cell)

    def add_sandbox_countdown(self, start_time, end_time):
        # Store the countdown info for later updates
        self.countdown_info = {
            'start_time': start_time,
            'end_time': end_time,
            'cell_index': 1  # Remember where we put it
        }

    def add_code_execution(self, code, execution, parsed=False):
        self.exec_count += 1
        self.data["cells"].append({
            "cell_type": "code",
            "execution_count": self.exec_count,
            "metadata": {},
            "source": code,
            "outputs": execution if parsed else self.parse_exec_result_nb(execution)
            })
        
    def add_code(self, code):
        """Add a code cell without execution results"""
        self.exec_count += 1
        self.data["cells"].append({
            "cell_type": "code",
            "execution_count": self.exec_count,
            "metadata": {},
            "source": code,
            "outputs": []
        })

    def append_execution(self, execution):
        """Append execution results to the immediate previous cell if it's a code cell"""
        if (len(self.data["cells"]) > 0 and 
            self.data["cells"][-1]["cell_type"] == "code"):
            self.data["cells"][-1]["outputs"] = self.parse_exec_result_nb(execution)
        else:
            raise ValueError("Cannot append execution: previous cell is not a code cell")
                
    def add_markdown(self, markdown, role="markdown"):
        if role == "system":
            system_message = markdown if markdown else "default"
            markdown_formatted = system_template.format(system_message.replace('\n', '<br>'))
        elif role == "user":
            markdown_formatted = user_template.format(markdown.replace('\n', '<br>'))
        elif role == "assistant":
            markdown_formatted = assistant_thinking_template.format(markdown)
            markdown_formatted = markdown_formatted.replace('<think>', '&lt;think&gt;')
            markdown_formatted = markdown_formatted.replace('</think>', '&lt;/think&gt;')
        else:
            # Default case for raw markdown
            markdown_formatted = markdown

        self.data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": markdown_formatted
        })

    def add_error(self, error_message):
        """Add an error message cell to the notebook"""
        error_html = ERROR_HTML.format(error_message)
    
        self.data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": error_html
        })

    def add_final_answer(self, answer):
        self.data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": assistant_final_answer_template.format(answer)
            })

    def parse_exec_result_nb(self, execution):
        """Convert an E2B Execution object to Jupyter notebook cell output format"""
        outputs = []
        
        if execution.logs.stdout:
            outputs.append({
                'output_type': 'stream',
                'name': 'stdout',
                'text': ''.join(execution.logs.stdout)
            })
        
        if execution.logs.stderr:
            outputs.append({
                'output_type': 'stream',
                'name': 'stderr',
                'text': ''.join(execution.logs.stderr)
            })

        if execution.error:
            outputs.append({
                'output_type': 'error',
                'ename': execution.error.name,
                'evalue': execution.error.value,
                'traceback': [line for line in execution.error.traceback.split('\n')]
            })

        for result in execution.results:
            output = {
                'output_type': 'execute_result' if result.is_main_result else 'display_data',
                'metadata': {},
                'data': {}
            }
            
            if result.text:
                output['data']['text/plain'] = result.text
            if result.html:
                output['data']['text/html'] = result.html
            if result.png:
                output['data']['image/png'] = result.png
            if result.svg:
                output['data']['image/svg+xml'] = result.svg
            if result.jpeg:
                output['data']['image/jpeg'] = result.jpeg
            if result.pdf:
                output['data']['application/pdf'] = result.pdf
            if result.latex:
                output['data']['text/latex'] = result.latex
            if result.json:
                output['data']['application/json'] = result.json
            if result.javascript:
                output['data']['application/javascript'] = result.javascript

            if result.is_main_result and execution.execution_count is not None:
                output['execution_count'] = execution.execution_count

            if output['data']:
                outputs.append(output)

        return outputs

    def filter_base64_images(self, message):
        """Filter out base64 encoded images from message content"""
        if isinstance(message, dict) and 'nbformat' in message:
            for output in message['nbformat']:
                if 'data' in output:
                    for key in list(output['data'].keys()):
                        if key.startswith('image/') or key == 'application/pdf':
                            output['data'][key] = '<placeholder_image>'
        return message
    
    def render(self, mode="default"):
        if self.countdown_info is not None:
            self._update_countdown_cell()

        render_data = copy.deepcopy(self.data)
        
        if mode == "generating":
            render_data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": GENERATING_WIDGET
            })

        elif mode == "executing":
            render_data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": EXECUTING_WIDGET
            })

        elif mode == "done":
            render_data["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": DONE_WIDGET
            })
        elif mode != "default":
            raise ValueError(f"Render mode should be generating, executing or done. Given: {mode}.")
        
        notebook = nbformat.from_dict(render_data)
        notebook_body, _ = html_exporter.from_notebook_node(notebook)
        notebook_body = notebook_body.replace(bad_html_bad, "")

        # make code font a bit smaller with custom css
        if "<head>" in notebook_body:
            notebook_body = notebook_body.replace("</head>", f"{custom_css}</head>")
        return notebook_body
    
def main():
    """Create a mock notebook to test styling"""
    # Create mock messages
    mock_messages = [
        {"role": "system", "content": "You are a helpful AI assistant that can write and execute Python code."},
        {"role": "user", "content": "Can you help me create a simple plot of a sine wave?"},
        {"role": "assistant", "content": "I'll help you create a sine wave plot using matplotlib. Let me write the code for that."},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "add_and_execute_code", "arguments": '{"code": "import numpy as np\\nimport matplotlib.pyplot as plt\\n\\n# Create x values\\nx = np.linspace(0, 4*np.pi, 100)\\ny = np.sin(x)\\n\\n# Create the plot\\nplt.figure(figsize=(10, 6))\\nplt.plot(x, y, \'b-\', linewidth=2)\\nplt.title(\'Sine Wave\')\\nplt.xlabel(\'x\')\\nplt.ylabel(\'sin(x)\')\\nplt.grid(True)\\nplt.show()"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "raw_execution": [{"output_type": "stream", "name": "stdout", "text": "Plot created successfully!"}]}
    ]
    
    # Create notebook
    notebook = JupyterNotebook(mock_messages)
    
    # Add a timeout countdown (simulating a sandbox that started 2 minutes ago with 5 minute timeout)
    start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)
    end_time = start_time + datetime.timedelta(minutes=5)
    notebook.add_sandbox_countdown(start_time, end_time)
    
    # Render and save
    html_output = notebook.render()
    
    with open("mock_notebook.html", "w", encoding="utf-8") as f:
        f.write(html_output)
    
    print("Mock notebook saved as 'mock_notebook.html'")
    print("Open it in your browser to see the styling changes.")

if __name__ == "__main__":
    main()
