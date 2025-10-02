from ufd import ChatOutput
import datetime


def main():
    """Create a mock chat_output to test styling"""
    # Create mock messages
    mock_messages = [
        {"role": "system", "content": "You are a helpful AI assistant that can write and execute Python code."},
        {"role": "user", "content": "Can you help me create a simple plot of a sine wave?"},
        {"role": "assistant", "content": "I'll help you create a sine wave plot using matplotlib. Let me write the code for that."},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "execute_code", "arguments": '{"code": "import numpy as np\\nimport matplotlib.pyplot as plt\\n\\n# Create x values\\nx = np.linspace(0, 4*np.pi, 100)\\ny = np.sin(x)\\n\\n# Create the plot\\nplt.figure(figsize=(10, 6))\\nplt.plot(x, y, \'b-\', linewidth=2)\\nplt.title(\'Sine Wave\')\\nplt.xlabel(\'x\')\\nplt.ylabel(\'sin(x)\')\\nplt.grid(True)\\nplt.show()"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "raw_execution": [{"output_type": "stream", "name": "stdout", "text": "Plot created successfully!"}]}
    ]
    
    # Create chat_output
    chat_output = ChatOutput(mock_messages)
    
    # Add a timeout countdown (simulating a sandbox that started 2 minutes ago with 5 minute timeout)
    start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)
    end_time = start_time + datetime.timedelta(minutes=5)
    chat_output.add_sandbox_countdown(start_time, end_time)

    html_output = chat_output.render()
    with open("mock_chat_output.html", "w", encoding="utf-8") as f:
        f.write(html_output)
    print(html_output)
    print("Mock chat_output saved as 'mock_chat_output.html'")
    print("Open it in your browser to see the styling changes.")

if __name__ == "__main__":
    main()
