import os
import gradio as gr
from e2b_code_interpreter import Sandbox
from pathlib import Path
import json
from openai import OpenAI
from prompts import DEFAULT_SYSTEM_PROMPT
from ufd import run_interactive_notebook, JupyterNotebook

E2B_API_KEY = "e2b_f6b6a6d1bab11a193685469f5d1fe6fe1f3c6c16"
DEFAULT_MAX_TOKENS = 512
SANDBOXES = {}
SANDBOX_TIMEOUT = int(60 * 59)
TMP_DIR = './tmp/'
model_name = "Qwen3-0.6B-Q8_0.gguf"
model = "Qwen3"
init_notebook = JupyterNotebook()

if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)

with open(TMP_DIR+"jupyter-agent.ipynb", 'w', encoding='utf-8') as f:
    json.dump(JupyterNotebook().data, f, indent=2)

def list_files_with_relative_paths(start_dir: str):
    if not os.path.isdir(start_dir):
        print(f"Error: Directory not found or is not a directory: {start_dir}")
        return []

    # Normalize the starting path to ensure consistency
    start_dir = os.path.abspath(start_dir)
    relative_file_paths = []
    try:
        for root, _, files in os.walk(start_dir):
            for file_name in files:
                # 1. Construct the full absolute path
                full_path = os.path.join(root, file_name)

                # 2. Calculate the path relative to the starting directory
                # This uses os.path.relpath(path, start=current_directory)
                relative_path = os.path.relpath(full_path, start_dir)
                
                relative_file_paths.append(relative_path)

    except OSError as e:
        print(f"An OS error occurred during directory traversal: {e}")
        return []

    return relative_file_paths

def execute_jupyter_agent(
    user_input, files, message_history, request: gr.Request
):

    if request.session_hash not in SANDBOXES:
        SANDBOXES[request.session_hash] = Sandbox.create(timeout=SANDBOX_TIMEOUT, api_key=E2B_API_KEY)
    sbx = SANDBOXES[request.session_hash]

    save_dir = os.path.join(TMP_DIR, request.session_hash)
    os.makedirs(save_dir, exist_ok=True)
    save_dir = os.path.join(save_dir, 'jupyter-agent.ipynb')

    with open(save_dir, 'w', encoding='utf-8') as f:
        json.dump(init_notebook.data, f, indent=2)
    yield init_notebook.render(), message_history, save_dir

    client = OpenAI(
        base_url="http://localhost:8080/v1",
        api_key="FAKE_TOKEN",
    )

    filenames = []
    if files is not None:
        for filepath in files:
            fpath = Path(filepath)
            with open(filepath, "rb") as file:
                print(f"uploading {filepath}...")
                sbx.files.write(fpath.name, file)
                filenames.append(fpath.name)

    system_prompt = DEFAULT_SYSTEM_PROMPT
    # Initialize message_history if it doesn't exist
    if len(message_history) == 0:
        if files is None:
            system_prompt = system_prompt.format("- None")
        else:
            system_prompt = system_prompt.format("- " + "\n- ".join(filenames))

        message_history.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )
    message_history.append({"role": "user", "content": user_input})

    # print("history:", message_history)

    for notebook_html, notebook_data, messages in run_interactive_notebook(
        client, model, message_history, sbx,
    ):
        message_history = messages
        
        yield notebook_html, message_history, TMP_DIR+"jupyter-agent.ipynb"
    
    with open(save_dir, 'w', encoding='utf-8') as f:
        json.dump(notebook_data, f, indent=2)
    yield notebook_html, message_history, save_dir

def clear(msg_state, request: gr.Request):
    if request.session_hash in SANDBOXES:
        SANDBOXES[request.session_hash].kill()
        SANDBOXES.pop(request.session_hash)

    msg_state = []
    return init_notebook.render(), msg_state


css = """
#component-0 {
    height: 100vh;
    overflow-y: auto;
    padding: 20px;
}
.gradio-container {
    height: 100vh !important;
}
.contain {
    height: 100vh !important;
}
"""
# Create the interface
with gr.Blocks() as demo:
    msg_state = gr.State(value=[])

    html_output = gr.HTML(value=JupyterNotebook().render())
    
    user_input = gr.Textbox(
        #value="Write code to multiply three numbers: 10048, 32, 19", lines=3, label="Agent task"
        value="Open the attached Excel files and list the column names.", label="Agent task"
    )

    with gr.Row():
        generate_btn = gr.Button("Run!")
        clear_btn = gr.Button("Clear Notebook")
    
    with gr.Accordion("Upload files ⬆ | Download notebook⬇", open=False):
        files = gr.File(label="Upload files to use",
                        file_count="multiple")
        file = gr.File(TMP_DIR+"jupyter-agent.ipynb", label="Download Jupyter Notebook")

    generate_btn.click(
        fn=execute_jupyter_agent,
        inputs=[user_input, files, msg_state],
        outputs=[html_output, msg_state, file],
        show_progress="hidden",
    )

    clear_btn.click(fn=clear, inputs=[msg_state], outputs=[html_output, msg_state])

    demo.load(
        fn=None,
        inputs=None,
        outputs=None,
        js=""" () => {
    if (document.querySelectorAll('.dark').length) {
        document.querySelectorAll('.dark').forEach(el => el.classList.remove('dark'));
    }
}
"""
    )

demo.launch(ssr_mode=False, server_name="0.0.0.0", server_port=7860)

