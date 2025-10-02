#-------------------------
# Prompts
#-------------------------

# Removed for hygene
# ---------------------
# beautifulsoup4==4.13.4
# joblib==1.5.0
# librosa==0.11.0
# nltk==3.9.1
# soundfile==0.13.1
# spacy==3.8.2 # doesn't work on 3.13.x
# scikit-image==0.25.2
# scikit-learn==1.6.1

DEFAULT_SYSTEM_PROMPT = """You are a coding agent with access to a Jupyter Kernel. \
When possible break down tasks step-by-step. \
The following files are available (if any):
{}
Make sure to reference the exact filepath and filename in any code. \
List of available packages:
# Jupyter server requirements
jupyter-server==2.16.0
ipykernel==6.29.5
ipython==9.2.0
orjson==3.10.18
pandas==2.2.3 # hint: use the read_excel function with excel files
matplotlib==3.10.3
pillow==11.3.0
# Latest version for
e2b_charts
# Other packages
aiohttp==3.12.14
bokeh==3.7.3
gensim==4.3.3 # unmaintained, blocking numpy and scipy bump
imageio==2.37.0
numpy==1.26.4 # bump blocked by gensim
numba==0.61.2
opencv-python==4.11.0.86
openpyxl==3.1.5
plotly==6.0.1
kaleido==1.0.0
pytest==8.3.5
python-docx==1.1.2
pytz==2025.2
requests==2.32.4
scipy==1.13.1 # bump blocked by gensim
seaborn==0.13.2
textblob==0.19.0
tornado==6.5.1
urllib3==2.5.0
xarray==2025.4.0
xlrd==2.0.1
sympy==1.14.0
If you need to install additional packages:
1. install uv first with `pip install uv` 
2. then use uv to install the package with `uv pip install PACKAGE_NAME --system`.
/think
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_and_execute_code",
            "description": "A Python code execution environment that runs code in a Jupyter notebook interface. This is stateful - variables and imports persist between executions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute."
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "Provide the final answer to the user's question after completing all necessary analysis and computation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The complete final answer to the user's question"
                    },
                },
                "required": ["answer"]
            }
        }
    }
]
