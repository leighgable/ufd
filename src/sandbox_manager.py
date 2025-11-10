from e2b_code_interpreter import Sandbox
import os

e2b_key = os.environ.get('E2B_API_KEY')
sandboxes = {}

def get_sandbox(session_id):
    if session_id not in sandboxes:
        sandboxes[session_id] = Sandbox.create(api_key=e2b_key, timeout=1800)
    return sandboxes[session_id]

def close_sandbox(session_id):
    if session_id in sandboxes:
        sandboxes[session_id].kill()
        del sandboxes[session_id]
