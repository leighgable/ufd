from textwrap import dedent
import os
import requests
from .sandbox_manager import get_sandbox
from typing import Any, List, Dict
from e2b_code_interpreter import Sandbox
from typing import Optional

e2b_key = os.environ['E2B_API_KEY']

react_instructions = dedent("""
        You are an expert with strong analytical skills! 🧠""")
        # You have access to tools. To call a tool, you make a function call with the function name and the arguments in json format.
        # Your approach to problems:
        # 1. First, break down complex questions into component parts
        # 2. Use tools with function calls if you don't have the information.
        # Only when you are finished respond with 'Final Answer:'""")

def create_message_with_files(prompt: str,
    file_paths: List[str],
) -> List[Dict[str, Any]]:
    """ Creates a list containing a single user prompt with files. """
    
    content_parts = [{"type": "text", "text": prompt}]
    
    for path in file_paths:
        print(f"[Message Creator] Adding file(s) to message: {path}")
        content_parts.append({"type": "text", "text": f"Attached file: {path}"})

    user_message = {
        "role": "user",
        "content": content_parts,
    }
    
    return [user_message]

def get_current_temperature(latitude, longitude):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
    	"latitude": [float(f"{latitude}")],
    	"longitude": [float(f"{longitude}")],
    	"current": ["temperature_2m"],
    	"timezone": ["auto"],
    }
    response = requests.post(url, json=params).json()
    return response['current']['temperature_2m']
    
def get_current_location():
    ll = requests.post("http://ip-api.com/json?fields=lat,lon").json()
    return ll['lat'], ll['lon']

def edit_dir_str(files: list[dict[str, Any]],
    dirname: str = '/home/user',
) -> list[dict[str, Any]]:
    return [{"path": dirname + x["path"].split("/")[-1], "data": x["data"]} for x in files]

def run_code_interpreter(code: str,
        files: Optional[list[dict[str, Any]]] = None,
        session_id: str = None,
) -> str:
    """
    Calling the actual code execution environment (e.g., E2B).
    Returns a result string simulating stdout/stderr.
    """
    sbx = get_sandbox(session_id)
    if files:
        sbx.files.write(edit_dir_str(files=files))        
    execution = sbx.run_code(code)
    print(f"\n\nSANDBOX CREATED:\n{sbx.get_info()}\n\n")
    return execution

def parse_sbx_exec(execution: Any):
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
    

def read_directory_files(directory_path):
    files = []
    
    # Iterate through all files in the directory
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        
        # Skip if it's a directory
        if os.path.isfile(file_path):
            # Read file contents in binary mode
            with open(file_path, "rb") as file:
                files.append({
                    'path': file_path,
                    'data': file.read()
                })
    return files
