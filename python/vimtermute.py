# pylint: disable=missing-docstring

import glob
import json
import os
import re
import subprocess
import threading
from types import SimpleNamespace
import urllib.request
import urllib.parse

import vim # pylint: disable=import-error

IS_NEOVIM = hasattr(vim, "api")

CHAT_BUFFER_NAME = r"\[vimtermute-chat\]"
ASK_BUFFER_NAME = r"\[vimtermute-ask\]"

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

state = SimpleNamespace(
    history=[],
    thinking=False,
)

def chat():
    buffer, window = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
    if buffer is not None:
        # Close the chat window if it is open
        vim.current.window = window
        vim.command("bwipeout")
    else:
        buffer, window = make_chat_buffer()
        update_chat_buffer(buffer, render_chat())

def make_chat_buffer():
    vim.command(f"split {CHAT_BUFFER_NAME}")
    vim.command("setlocal buftype=nofile")
    vim.command("setlocal bufhidden=wipe")
    vim.command("setlocal noswapfile")
    vim.command("setlocal filetype=markdown")
    vim.command("setlocal conceallevel=2")
    vim.command("nnoremap <buffer> i :python3 vimtermute.ask()<CR>")
    vim.command("nnoremap <buffer> <leader>cl :python3 vimtermute.clear()<CR>")
    vim.command("setlocal nomodifiable")
    return vim.current.buffer, vim.current.window

def update_chat_buffer(buffer, lines):
    # Exception handling is a workaround for a bug in Neovim, where
    # buffer object becomes invalid even though its python counterpart
    # is still valid.
    try:
        buffer.options["modifiable"] = True
        buffer[:] = lines
        buffer.options["modifiable"] = False
        window = buffer_window(buffer.number)
        window.cursor = (len(lines), 0)
    except Exception: # pylint: disable=broad-except
        vim.command("echom 'Error updating chat buffer'")

def render_chat():
    if state.history:
        lines = render_history(state.history)
    else:
        lines = CHAT_INTRO.split("\n")
    if state.thinking:
        lines.append("Thinking ...")
    return lines

def render_history(history):
    lines = []
    for entry in history:
        lines.extend([
            "#### User " + "-" * 65,
            "",
            *entry["prompt_raw"].split("\n"),
            "",
        ])

        responses = entry["responses"]
        if len(responses) == 1:
            lines.extend([
                "#### Vimtermute " + "-" * 59,
                "",
                *responses[0].split("\n"),
                "",
            ])
        else:
            rnum = len(responses)
            for i, response in enumerate(responses):
                lines.extend([
                    f"#### Vimtermute {i+1}/{rnum} " + "-" * 53,
                    "",
                    *response.split("\n"),
                    "",
                ])
    return lines

def ask():
    if state.thinking:
        vim.command("echom 'Cannot start new prompt while thinking'")
        return

    buffer, window = find_visible_buffer(f".*{ASK_BUFFER_NAME}")
    if buffer is not None:
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
    prompt_raw = "\n".join(vim.current.buffer[:]).strip()
    prompt, system = compose_prompt(prompt_raw)
    vim.command("bwipeout")

    # If the prompt is empty, do nothing
    if prompt_raw == "":
        return

    state.history.append({
        "prompt_raw": prompt_raw,
        "prompt": prompt,
        "responses": [""],
    })
    state.thinking = True

    # Bring up the chat window
    cbuffer, cwindow = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
    if cbuffer is None:
        cbuffer, cwindow = make_chat_buffer()
    update_chat_buffer(cbuffer, render_chat())
    vim.current.window = cwindow

    threading.Thread(target=response_thread, args=(system, prompt)).start()

def response_thread(system, prompt):
    # Compile the chat history for the model
    messages = []
    for entry in state.history[:-1]:
        messages.append({
            "role": "user",
            "content": entry["prompt"],
        })
        messages.append({
            "role": "assistant",
            "content": entry["responses"][-1],
        })
    messages.append({
        "role": "user",
        "content": prompt,
    })

    def update_response(part):
        state.history[-1]["responses"][-1] += part
        buffer, _ = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
        if buffer is not None:
            update_chat_buffer(buffer, render_chat())

    def finalize():
        state.thinking = False
        buffer, _ = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
        if buffer is not None:
            update_chat_buffer(buffer, render_chat())

    try:
        # Call the model
        response_stream = call_gemini({
            "messages": messages,
            "system": system,
            "stream": True,
        })

        for part in response_stream:
            async_call(update_response, part)
    finally:
        async_call(finalize)

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
    if re.match(r"@git\s+diff", line):
        try:
            diff = subprocess.check_output(
                ["git", "diff"],
                universal_newlines=True
            ).strip()
        except subprocess.CalledProcessError as ex:
            raise RuntimeError("Git command failed") from ex

        if diff:
            preamble = preamble + [
                "Here are the current changes:",
                "",
                "```diff",
                diff,
                "```",
                "",
            ]
        else:
            raise ValueError(
                "Using `@git diff`, but no changes found")
    elif re.match(r"@git\s+staged", line):
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
    elif re.match(r"@git\s+files", line):
        pattern = re.match(r"@git\s+files\s*(.*)", line).group(1).strip()
        if not pattern:
            pattern = "**/*"

        try:
            # Get the list of files tracked by git
            files = subprocess.check_output(
                ["git", "ls-files", pattern],
                universal_newlines=True
            ).strip().split("\n")
        except subprocess.CalledProcessError as ex:
            raise RuntimeError("Git command failed") from ex

        if not files:
            raise ValueError(
                f"No tracked files found matching pattern `{pattern}`")

        for file in sorted(files):
            # Skip directories
            if not os.path.isfile(file):
                continue

            try:
                with open(file, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as ex:
                raise RuntimeError(f"Failed to read file `{file}`") from ex

            preamble = preamble + [
                f"Here is the content of the file `{file}`:",
                "",
                "```",
                content,
                "```",
                "",
            ]
    else:
        raise ValueError(f"Invalid @git directive: {line}")
    return preamble

def clear():
    if state.thinking:
        vim.command("echom 'Cannot clear chat while thinking'")
        return

    # Dump the chat log to a file
    if state.history:
        with open(".vimtermute.log", "a", encoding="utf-8") as log:
            log.write("*" * 80 + "\n\n")
            for entry in state.history:
                log.write("--- User " + "-" * 65 + "\n\n")
                log.write(entry["prompt_raw"] + "\n\n")
                responses = entry["responses"]
                if len(responses) == 1:
                    log.write("--- Vimtermute " + "-" * 59 + "\n\n")
                    log.write(responses[0] + "\n\n")
                else:
                    rnum = len(responses)
                    for i, response in enumerate(responses):
                        log.write(f"--- Vimtermute {i+1}/{rnum} " +
                            "-" * 53 + "\n\n")
                        log.write(response + "\n\n")
            log.write("\n")

    state.history = []

    buffer, _ = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
    if buffer is not None:
        update_chat_buffer(buffer, render_chat())

def regenerate_last():
    if state.thinking:
        vim.command("echom 'Cannot generate new response while thinking'")
        return

    if not state.history:
        # No history to work with
        return

    prompt_raw = state.history[-1]["prompt_raw"]
    prompt, system = compose_prompt(prompt_raw)

    state.history[-1]["responses"].append("")
    state.thinking = True

    # Bring up the chat window
    cbuffer, cwindow = find_visible_buffer(f".*{CHAT_BUFFER_NAME}")
    if cbuffer is None:
        cbuffer, cwindow = make_chat_buffer()
    update_chat_buffer(cbuffer, render_chat())
    vim.current.window = cwindow

    threading.Thread(target=response_thread, args=(system, prompt)).start()

def visible_buffers():
    buffers = set()

    for window in vim.windows:
        wname = window.buffer.name
        is_chat = re.match(f".*{CHAT_BUFFER_NAME}", wname)
        is_ask = re.match(f".*{ASK_BUFFER_NAME}", wname)
        if not is_chat and not is_ask:
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

def find_visible_buffer(pattern):
    for window in vim.windows:
        if window.valid:
            buffer = window.buffer
            if re.match(pattern, buffer.name):
                return buffer, window
    return None, None

def buffer_window(buffer_number):
    for window in vim.windows:
        if window.buffer.number == buffer_number:
            return window
    return None

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
