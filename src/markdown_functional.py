import re
from typing import Tuple
import markdown_it

# Initialize the markdown-it parser once to be reused.
md = markdown_it.MarkdownIt(
    "commonmark",
    {
        "html": True,       # Allow HTML tags in source
        "xhtmlout": False,  # Don't create XHTML-compliant tags
        "breaks": True,     # Convert '\n' in paragraphs into <br>
        "linkify": True,    # Autoconvert URL-like text to links
    }
).enable("table")

# Regex to detect an opening code fence (e.g., ```python)
OPEN_FENCE_PATTERN = re.compile(r"^\s*`{3,}[\w-]*\s*$", re.MULTILINE)

def process_markdown_stream(chunk: str, unstable_buffer: str, stable_text: str) -> Tuple[str, str]:
    """
    Processes a new text chunk, managing stable and unstable buffers to correctly
    handle streaming markdown, especially for code blocks and incomplete lines.

    This is a pure function that calculates the next state of the buffers.

    Args:
        chunk: The new piece of text from the stream.
        unstable_buffer: The existing buffer of text that is not yet stable.
        stable_text: The portion of the document already considered stable.

    Returns:
        A tuple containing:
        - The new unstable buffer.
        - The new stable text.
    """
    # Combine the existing unstable buffer with the new chunk
    buffer = unstable_buffer + chunk

    # --- Find the split point between what's stable and what's not ---
    
    # By default, assume the entire buffer is unstable
    stable_part_end = 0

    # Find the start of the last potential code block fence
    last_open_fence_match = None
    for match in OPEN_FENCE_PATTERN.finditer(buffer):
        last_open_fence_match = match
    
    last_open_fence_start = -1
    if last_open_fence_match:
        last_open_fence_start = last_open_fence_match.start()

    # Find the last closing fence '```' that appears on its own line
    last_close_fence_pos = buffer.rfind("\n```\n")
    if last_close_fence_pos == -1 and buffer.endswith("\n```"):
        last_close_fence_pos = len(buffer) - 4

    # Check if we are currently inside an unclosed code block
    in_unclosed_block = last_open_fence_start > last_close_fence_pos

    if in_unclosed_block:
        # If we are in an unclosed block, the stable part ends right before
        # the start of that block's opening fence.
        stable_part_end = last_open_fence_start
    else:
        # If not in a code block, the stable part ends at the last newline.
        # This prevents rendering of incomplete lines or inline formatting.
        last_newline = buffer.rfind('\n')
        if last_newline != -1:
            stable_part_end = last_newline + 1
        else:
            # No newline found, so the entire buffer is considered unstable
            # as it's likely the first line being streamed.
            stable_part_end = 0
            
    # --- Split the buffer into the newly stable part and the new unstable buffer ---
    
    newly_stable_part = buffer[:stable_part_end]
    new_unstable_buffer = buffer[stable_part_end:]

    # The full stable text is the old stable text plus the part that just became stable
    updated_stable_text = stable_text + newly_stable_part
    
    return new_unstable_buffer, updated_stable_text

def finalize_markdown(unstable_buffer: str, stable_text: str) -> str:
    """
    Combines the final stable and unstable text buffers into a single string
    ready for final rendering.

    Args:
        unstable_buffer: The final remaining unstable text.
        stable_text: The body of the stable text.

    Returns:
        The complete document text.
    """
    return stable_text + unstable_buffer