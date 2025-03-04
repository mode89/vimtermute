# pylint: disable=missing-docstring

import glob
import json
import os
import re
import subprocess
import threading
import urllib.request
import urllib.parse

import vim # pylint: disable=import-error

IS_NEOVIM = hasattr(vim, "api")

CHAT_BUFFER_NAME = "[VimtermuteChat]"
ASK_BUFFER_NAME = "[VimtermuteAsk]"

CODE_SYSTEM_PROMPT = """
You are an AI programming assistant.

When asked to generate code, output only those parts of the code that are
relevant to the user's request and need to be modified. DO NOT output
entire files unless asked to do so.

DO NOT output diff patches unless asked to do so. Instead, output
the code as it should be after the change.
"""

COMMIT_PROMPT = """
Write commit message for the change following the Conventional Commits format.
Tell me what the change does, not how it does it.
Explain motivation for the change and how it addresses the issue.
Use imperatiive mood.
"""

CHAT_INTRO = """
# This is the Vimtermute chat window. Press 'i' to enter a prompt.
"""


def chat():
    if getattr(chat, "buffer", None) is None:
        vim.command(f"split {CHAT_BUFFER_NAME}")
        vim.command("setlocal buftype=nofile")
        vim.command("setlocal bufhidden=hide")
        vim.command("setlocal noswapfile")
        vim.command("setlocal filetype=markdown")
        vim.command("setlocal conceallevel=2")
        vim.command("nnoremap <buffer> i :python3 vimtermute.ask()<CR>")
        vim.command("nnoremap <buffer> <leader>cl :python3 vimtermute.clear()<CR>")

        chat.buffer = vim.current.buffer
        chat.buffer[:] = CHAT_INTRO.split("\n")
        chat.buffer.options["modifiable"] = False
        chat.history = []
    else:
        window = buffer_window(chat.buffer.number)
        if window is not None:
            # Close the chat window if it is open
            vim.current.window = window
            vim.command("close")
        else:
            vim.command("split")
            vim.current.buffer = chat.buffer

def ask():
    ask_buffer = None
    for buffer in vim.buffers:
        if buffer.name.endswith(ASK_BUFFER_NAME):
            ask_buffer = buffer
            break

    if ask_buffer is not None:
        window = buffer_window(ask_buffer.number)
        if window is not None:
            vim.current.window = window
            return

    vim.command(f"belowright new {ASK_BUFFER_NAME}")
    vim.command("setlocal buftype=nofile")
    vim.command("setlocal bufhidden=wipe")
    vim.command("setlocal noswapfile")
    vim.command("setlocal filetype=markdown")
    vim.command("nnoremap <buffer> <CR> :python3 vimtermute.ask_finish()<CR>")
    vim.command("startinsert")

def ask_finish():
    ask.finish = None
    prompt_raw = "\n".join(vim.current.buffer[:]).strip()
    prompt, system = compose_prompt(prompt_raw)
    vim.command("bwipeout")

    # If the prompt is empty, do nothing
    if prompt_raw == "":
        return

    # Bring up the chat window
    if getattr(chat, "buffer", None) is None:
        chat()
    chat_window = buffer_window(chat.buffer.number)
    if chat_window is not None:
        vim.current.window = chat_window
    else:
        vim.command("split")
        vim.current.buffer = chat.buffer

    # Compile the chat history for the model
    messages = []
    for entry in chat.history:
        messages.append({
            "role": "user",
            "content": entry["prompt"],
        })
        messages.append({
            "role": "assistant",
            "content": entry["response"],
        })
    messages.append({
        "role": "user",
        "content": prompt,
    })

    chat.buffer.options["modifiable"] = True
    chat.buffer.append([
        "#### User " + "-" * 65,
        "",
        *prompt_raw.split("\n"),
        "",
        "#### Vimtermute " + "-" * 59,
        "",
        "",
        "Thinking ...",
        "",
    ])
    chat.buffer.options["modifiable"] = False
    scroll_to_bottom(chat.buffer)

    def response_thread():
        # Call the model
        response_stream = call_gemini({
            "messages": messages,
            "system": system,
            "stream": True,
        })

        def append_to_chat(lines, thinking=True):
            # Append the prompt and response to the chat buffer
            chat.buffer.options["modifiable"] = True
            chat.buffer[-3:] = [*lines, "", "Thinking ...", ""] \
                if thinking else lines
            chat.buffer.options["modifiable"] = False
            scroll_to_bottom(chat.buffer)
            vim.command("redraw!")

        response = ""
        last_line = ""
        for part in response_stream:
            response += part
            plines = part.split("\n")
            if len(plines) == 1:
                last_line += part
            else:
                complete_lines = [last_line + plines[0]] + plines[1:-1]
                last_line = plines[-1]
                async_call(append_to_chat, complete_lines)
        async_call(append_to_chat, [last_line], False)

        # Append the prompt and response to the chat history
        chat.history.append({
            "prompt_raw": prompt_raw,
            "prompt": prompt,
            "response": response,
        })

    threading.Thread(target=response_thread).start()

def compose_prompt(raw_prompt):
    system = []
    prompt = []
    preamble = []
    for line in raw_prompt.split("\n"):
        if line.startswith("@"):
            if line.startswith("@buffer"):
                preamble = attach_buffer(preamble)
            elif re.match(r"@files\s*.*", line):
                preamble = attach_files(preamble, line)
            elif re.match(r"@git\s*.*", line):
                preamble = attach_git(preamble, line)
            else:
                raise ValueError(f"Invalid @ directive: {line}")
        elif line.startswith("/"):
            if line.startswith("/code"):
                system.extend(CODE_SYSTEM_PROMPT.strip().split("\n"))
            elif line.startswith("/commit"):
                system.append("You are an AI programming assistant.")
                prompt.extend(COMMIT_PROMPT.strip().split("\n"))
            else:
                raise ValueError(f"Invalid / directive: {line}")
        else:
            prompt.append(line)
    return \
        "\n".join(preamble + prompt), \
        "\n".join(system) if system else None

def attach_buffer(preamble):
    buffers = visible_buffers()
    if len(buffers) == 0: # pylint: disable=no-else-raise
        raise ValueError("Using @buffer, but no buffers open")
    elif len(buffers) > 1:
        raise ValueError(
            "Using @buffer, but multiple buffers open")
    else:
        buffer = buffers[0]
        preamble = preamble + [
            "Here is the content of the current buffer:",
            "",
            "```",
        ] + buffer[:] + [
            "```",
            "",
        ]
    return preamble

def attach_files(preamble, line):
    pattern = re.match(r"@files\s*(.*)", line).group(1).strip()

    # Default to all files in current directory
    if not pattern:
        pattern = "**/*"
    files = glob.glob(pattern, recursive=True)
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise ValueError(
            f"No files found matching pattern `{pattern}`")

    for file in sorted(files):
        try:
            with open(file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as ex:
            raise RuntimeError(
                f"Failed to read file `{file}`") from ex

        preamble = preamble + [
            f"Here is the content of the file `{file}`:",
            "",
            "```",
            content,
            "```",
            "",
        ]
    return preamble

def attach_git(preamble, line):
    if re.match(r"@git\s+staged", line):
        try:
            diff = subprocess.check_output(
                ["git", "diff", "--staged"],
                universal_newlines=True
            ).strip()
        except subprocess.CalledProcessError as ex:
            raise RuntimeError("Git command failed") from ex

        if diff:
            preamble = preamble + [
                "Here are the changes staged for commit:",
                "",
                "```diff",
                diff,
                "```",
                "",
            ]
        else:
            raise ValueError(
                "Using `@git staged`, but no changes staged")
    else:
        raise ValueError(f"Invalid @git directive: {line}")
    return preamble

def clear():
    chat.buffer.options["modifiable"] = True
    chat.buffer[:] = CHAT_INTRO.split("\n")
    chat.buffer.options["modifiable"] = False

    # Dump the chat log to a file
    if hasattr(chat, "history") and chat.history:
        with open(".vimtermute.log", "a", encoding="utf-8") as log:
            log.write("*" * 80 + "\n\n")
            for entry in chat.history:
                log.write("--- User " + "-" * 65 + "\n\n")
                log.write(entry["prompt_raw"] + "\n\n")
                log.write("--- Vimtermute " + "-" * 59 + "\n\n")
                log.write(entry["response"] + "\n\n")
            log.write("\n")

    chat.history = []

def visible_buffers():
    buffers = set()

    for window in vim.windows:
        wname = window.buffer.name
        if not wname.endswith(CHAT_BUFFER_NAME) and \
           not wname.endswith(ASK_BUFFER_NAME):
            buffers.add(window.buffer)

    return list(buffers)

def attach_line_numbers(lines):
    width = len(str(len(lines)))
    return ([
        f"{i+1:>{width}} {line}"
        for i, line in enumerate(lines)
    ])

def call_gemini(call):
    streaming = call.get("stream", False)
    rolls = {
        "user": "user",
        "assistant": "model",
    }

    # Convert contents to the format expected by Gemini API
    contents = []
    for message in call["messages"]:
        contents.append({
            "role": rolls[message["role"]],
            "parts": [{
                "text": message["content"],
            }],
        })

    data = {
        "contents": contents,
    }
    if "system" in call and call["system"]:
        data["system_instruction"] = {
            "parts": [{
                "text": call["system"],
            }],
        }

    method = "streamGenerateContent" if streaming else "generateContent"
    sse = "alt=sse&" if streaming else ""
    key = os.environ["GEMINI_API_KEY"]

    req = urllib.request.Request(
        url="https://generativelanguage.googleapis.com/v1beta/models/" +
            f"gemini-2.0-flash:{method}?{sse}key={key}",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        })

    with urllib.request.urlopen(req) as response:
        if streaming:
            for line in response:
                if line.startswith(b"data:"):
                    data = json.loads(line[5:])
                    yield data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            data = json.load(response)
            yield data["candidates"][0]["content"]["parts"][0]["text"]

def buffer_window(buffer_number):
    for window in vim.windows:
        if window.buffer.number == buffer_number:
            return window
    return None

def scroll_to_bottom(buffer):
    window = buffer_window(buffer.number)
    if window is not None:
        line = len(buffer)
        window.cursor = (line, 0)

def async_call(func, *args):
    if hasattr(do_async_call, "queue"):
        do_async_call.queue.append((func, args))
    else:
        do_async_call.queue = [(func, args)]

    if IS_NEOVIM:
        vim.async_call(do_async_call)
    else:
        vim.eval("timer_start(1, 'VimtermuteDoAsyncCall')")

def do_async_call():
    if hasattr(do_async_call, "queue"):
        func, args = do_async_call.queue.pop(0)
        func(*args)
