
bad_html_bad = """input[type="file"] {
  display: block;
}"""

code_template = """\
<div>
{}
</div>"""

system_template = """\
<details>
  <summary style="display: flex; align-items: center; cursor: pointer; margin-bottom: 12px;">
    <h3 style="color: #374151; margin: 0; margin-right: 8px; font-size: 14px; font-weight: 600;">System</h3>
    <span class="arrow" style="margin-right: 12px; font-size: 12px;">▶</span>
    <div style="flex: 1; height: 2px; background-color: #374151;"></div>
  </summary>
  <div style="margin-top: 8px; padding: 8px; background-color: #f9fafb; border-radius: 4px; border-left: 3px solid #374151; margin-bottom: 16px;">
    {}
  </div>
</details>
<style>
details > summary .arrow {{
  display: inline-block;
  transition: transform 0.2s;
}}
details[open] > summary .arrow {{
  transform: rotate(90deg);
}}
details > summary {{
  list-style: none;
}}
details > summary::-webkit-details-marker {{
  display: none;
}}
</style>
"""

user_template = """\
<div style="display: flex; align-items: center; margin-bottom: 12px;">
    <h3 style="color: #166534; margin: 0; margin-right: 12px; font-size: 14px; font-weight: 600;">User</h3>
    <div style="flex: 1; height: 2px; background-color: #166534;"></div>
</div>
<div style="margin-bottom: 16px;">{}</div>"""

assistant_thinking_template = """\
<div style="display: flex; align-items: center; margin-bottom: 12px;">
    <h3 style="color: #1d5b8e; margin: 0; margin-right: 12px; font-size: 14px; font-weight: 600;">Assistant</h3>
    <div style="flex: 1; height: 2px; background-color: #1d5b8e;"></div>
</div>
<div style="margin-bottom: 16px;">{}</div>"""

assistant_final_answer_template = """<div class="alert alert-block alert-warning">
<b>Assistant:</b> Final answer: {}
</div>
"""

header_message = """<p align="center">
  <img style="max-height:140px; max-width:100%; height:auto;" 
       src="./ufd.png" 
       alt="UFD Logo" />
</p>
<p style="text-align:center;">Reasoning locally with {}</p>"""

bad_html_bad = """input[type="file"] {
  display: block;
}"""

EXECUTING_WIDGET = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #e3f2fd; border-radius: 6px; border-left: 3px solid #2196f3;">
    <div style="display: flex; gap: 4px;">
        <div style="width: 6px; height: 6px; background-color: #2196f3; border-radius: 50%; animation: pulse 1.5s ease-in-out infinite;"></div>
        <div style="width: 6px; height: 6px; background-color: #2196f3; border-radius: 50%; animation: pulse 1.5s ease-in-out 0.1s infinite;"></div>
        <div style="width: 6px; height: 6px; background-color: #2196f3; border-radius: 50%; animation: pulse 1.5s ease-in-out 0.2s infinite;"></div>
    </div>
    <span style="color: #1976d2; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        Executing code...
    </span>
</div>
<style>
@keyframes pulse {
    0%, 80%, 100% {
        opacity: 0.3;
        transform: scale(0.8);
    }
    40% {
        opacity: 1;
        transform: scale(1);
    }
}
</style>
"""

GENERATING_WIDGET = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #f3e5f5; border-radius: 6px; border-left: 3px solid #9c27b0;">
    <div style="width: 80px; height: 4px; background-color: #e1bee7; border-radius: 2px; overflow: hidden;">
        <div style="width: 30%; height: 100%; background-color: #9c27b0; border-radius: 2px; animation: progress 2s ease-in-out infinite;"></div>
    </div>
    <span style="color: #7b1fa2; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        Generating...
    </span>
</div>
<style>
@keyframes progress {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(250%); }
}
</style>
"""

DONE_WIDGET = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #e8f5e8; border-radius: 6px; border-left: 3px solid #4caf50;">
    <div style="width: 16px; height: 16px; background-color: #4caf50; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
            <path d="M1 4L3.5 6.5L9 1" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    </div>
    <span style="color: #2e7d32; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        Generation complete
    </span>
</div>
"""

DONE_WIDGET = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #e8f5e8; border-radius: 6px; border-left: 3px solid #4caf50; animation: fadeInOut 4s ease-in-out forwards;">
    <div style="width: 16px; height: 16px; background-color: #4caf50; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
            <path d="M1 4L3.5 6.5L9 1" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    </div>
    <span style="color: #2e7d32; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        Generation complete
    </span>
</div>
<style>
@keyframes fadeInOut {
    0% { opacity: 0; transform: translateY(10px); }
    15% { opacity: 1; transform: translateY(0); }
    85% { opacity: 1; transform: translateY(0); }
    100% { opacity: 0; transform: translateY(-10px); }
}
</style>
"""

ERROR_HTML = """\
<div style="display: flex; align-items: center; gap: 8px; padding: 12px; background-color: #ffebee; border-radius: 6px; border-left: 3px solid #f44336; margin: 8px 0;">
    <div style="width: 20px; height: 20px; background-color: #f44336; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 12px;">
        !
    </div>
    <div style="color: #c62828; font-size: 14px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <strong>Error:</strong> {}
    </div>
</div>"""

STOPPED_SANDBOX_HTML = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #f5f5f5; border-radius: 6px; border-left: 3px solid #9e9e9e; margin-bottom: 16px;">
    <div style="width: 16px; height: 16px; background-color: #9e9e9e; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 10px;">
        ⏹
    </div>
    <div style="flex: 1;">
        <div style="margin-bottom: 4px; font-size: 13px; color: #757575; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-weight: 500;">
            Sandbox stopped
        </div>
        <div style="width: 100%; height: 8px; background-color: #e0e0e0; border-radius: 4px; overflow: hidden;">
            <div style="height: 100%; background-color: #9e9e9e; border-radius: 4px; width: 100%;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 11px; color: #757575; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <span>Started: {start_time}</span>
            <span>Expired: {end_time}</span>
        </div>
    </div>
</div>
"""

TIMEOUT_HTML = """
<div style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #fff3e0; border-radius: 6px; border-left: 3px solid #ff9800; margin-bottom: 16px;">
    <div style="width: 16px; height: 16px; background-color: #ff9800; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 10px;">
        ⏱
    </div>
    <div style="flex: 1;">
        <div style="margin-bottom: 4px; font-size: 13px; color: #f57c00; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-weight: 500;">
            The E2B Sandbox for code execution has a timeout of {total_seconds} seconds.
        </div>
        <div style="width: 100%; height: 8px; background-color: #ffe0b3; border-radius: 4px; overflow: hidden;">
            <div id="progress-bar-{unique_id}" style="height: 100%; background: linear-gradient(90deg, #ff9800 0%, #f57c00 50%, #f44336 100%); border-radius: 4px; width: {current_progress}%; animation: progress-fill-{unique_id} {remaining_seconds}s linear forwards;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 11px; color: #f57c00; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <span>Started: {start_time}</span>
            <span>Expires: {end_time}</span>
        </div>
    </div>
</div>
<style>
@keyframes progress-fill-{unique_id} {{
    from {{ width: {current_progress}%; }}
    to {{ width: 100%; }}
}}
</style>
"""

# just make the code font a bit smaller
custom_css = """
<style type="text/css">
/* Code font size */
.highlight pre, .highlight code,
div.input_area pre, div.output_area pre {
    font-size: 12px !important;
    line-height: 1.4 !important;
}
/* Fix prompt truncation */
.jp-InputPrompt, .jp-OutputPrompt {
    text-overflow: clip !important;
}
</style>
"""
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Final Report</title>
</head>
<body>
    {% for cell in html_output %}
        {% if cell['cell_type'] == 'response' %}
            {{ cell.source }}
        {% elif cell['cell_type'] =='code' %}
            {{ cell['source'] }}
        {% endif %}
    {% endfor %}
</body>
</html>
"""
