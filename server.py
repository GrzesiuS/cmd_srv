import json
import subprocess
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any
import uvicorn
import os
from fastapi.responses import HTMLResponse
import re
from loguru import logger
import sys

app = FastAPI()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs.log")

# Configure loguru logger
logger.remove()
logger.add(LOG_PATH, rotation="10 MB", retention="10 days", enqueue=True, backtrace=True, diagnose=True, format="{time} | {level} | {message}")

with open(CONFIG_PATH, "r") as f:
    COMMANDS = json.load(f)

class ExecuteRequest(BaseModel):
    command: str
    # dodatkowe argumenty dynamicznie

@app.post("/execute")
async def execute_command(request: Request):
    data = await request.json()
    cmd_name = data.get("command")
    logger.info(f"Received execute request: {data}")
    if not cmd_name:
        logger.error("Missing 'command' field in request")
        raise HTTPException(status_code=400, detail="Missing 'command' field")
    if cmd_name not in COMMANDS:
        logger.error(f"Unknown command: {cmd_name}")
        raise HTTPException(status_code=404, detail="Unknown command")

    cmd_template = COMMANDS[cmd_name]
    args = {k: v for k, v in data.items() if k != "command"}
    try:
        cmd_str = cmd_template.format(**args)
    except KeyError as e:
        logger.error(f"Missing argument for command '{cmd_name}': {e.args[0]}")
        raise HTTPException(status_code=400, detail=f"Missing argument: {e.args[0]}")

    try:
        logger.info(f"Executing command: {cmd_str}")
        result = subprocess.run(
            cmd_str, shell=True, capture_output=True, text=True, timeout=30
        )
        logger.info(f"Command '{cmd_name}' executed with returncode {result.returncode}")
        if result.stdout:
            logger.info(f"stdout: {result.stdout.strip()}")
        if result.stderr:
            logger.warning(f"stderr: {result.stderr.strip()}")
        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        logger.exception(f"Exception during command execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs", response_class=HTMLResponse)
async def get_logs():
    log_path = LOG_PATH
    if not os.path.exists(log_path):
        return HTMLResponse("<b>No logs found.</b>", status_code=404)
    with open(log_path, "r") as f:
        lines = f.readlines()

    def colorize(line):
        if "ERROR" in line:
            return f'<span style="color:red;">{line}</span>'
        elif "WARNING" in line:
            return f'<span style="color:orange;">{line}</span>'
        elif "INFO" in line:
            return f'<span style="color:green;">{line}</span>'
        else:
            return f'<span>{line}</span>'

    colored_lines = [colorize(line.rstrip()) for line in lines]
    html = f"""
    <html>
    <head>
        <title>Logs</title>
        <meta http-equiv="refresh" content="2">
        <style>
            body {{ background: #222; color: #eee; font-family: monospace; padding: 1em; }}
            span {{ white-space: pre; }}
        </style>
    </head>
    <body>
        <h2>logs.log</h2>
        <pre>
{chr(10).join(colored_lines)}
        </pre>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)

@app.get("/commands", response_class=HTMLResponse)
async def get_commands():
    logger.info("Serving /commands endpoint")
    html_lines = [
        "<html>",
        "<head>",
        "<title>Available Commands</title>",
        "<style>",
        "body { background: #222; color: #eee; font-family: monospace; padding: 1em; }",
        ".cmd { color: #8ec07c; font-weight: bold; }",
        ".desc { color: #b8bb26; }",
        ".args { color: #fabd2f; }",
        "</style>",
        "</head>",
        "<body>",
        "<h2>Available Commands</h2>",
        "<ul>"
    ]
    for cmd, template in COMMANDS.items():
        desc = ""
        if isinstance(template, dict):
            desc = template.get("description", "")
            template_str = template.get("cmd", "")
        else:
            template_str = template
        args = [f"<span class='args'>{a}</span>" for a in re.findall(r"\{(\w+)\}", template_str)]
        args_str = ", ".join(args)
        html_lines.append(
            f"<li><span class='cmd'>{cmd}</span>({args_str})"
            f"<br><span class='desc'>{desc or template_str}</span></li>"
        )
    html_lines += [
        "</ul>",
        "</body>",
        "</html>"
    ]
    return HTMLResponse(content="\n".join(html_lines), status_code=200)

if __name__ == "__main__":
    logger.info("Starting server on 0.0.0.0:8000")
    if sys.platform == "win32":
        import threading
        import pystray
        from PIL import Image, ImageDraw

        def run_server():
            uvicorn.run("server:app", host="0.0.0.0", port=8000, log_level="info")

        def create_image():
            # Simple icon: green circle
            img = Image.new("RGB", (64, 64), color=(34, 40, 49))
            d = ImageDraw.Draw(img)
            d.ellipse((16, 16, 48, 48), fill=(142, 192, 124))
            return img

        def on_quit(icon, item):
            logger.info("Tray icon quit selected, exiting application.")
            icon.stop()
            os._exit(0)

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        menu = (pystray.MenuItem("Quit", on_quit),)
        icon = pystray.Icon("cmd_srv", create_image(), "Command Server", menu)
        icon.run()
    else:
        uvicorn.run("server:app", host="0.0.0.0", port=8000)
