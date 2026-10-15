"""Stands in for `claude -p`: echoes what it received so tests exercise the real subprocess path."""
import json
import os
import subprocess
import sys
import time

if sys.argv[1:3] == ["auth", "status"]:
    if os.environ.get("FAKE_AUTH_MODE") == "hang":
        time.sleep(30)
    print(os.environ.get("FAKE_AUTH_STATUS", json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"})))
    sys.exit(0)

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "noread":
    # Hangs before reading stdin; a large message then blocks the parent's write to the pipe.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    with open(os.environ["FAKE_CHILD_PID_FILE"], "w") as handle:
        handle.write(str(child.pid))
    time.sleep(30)
message = json.loads(sys.stdin.readline())
content = message["message"]["content"]
if mode == "sleep":
    time.sleep(30)
if mode == "launcher":
    # Like claude.cmd: a child inherits our stdout/stderr and keeps them open long after the timeout.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    child.wait()
if mode == "orphan":
    # The launcher exits at once, but its child keeps our stdout/stderr open; only a job object reaches it.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    with open(os.environ["FAKE_CHILD_PID_FILE"], "w") as handle:
        handle.write(str(child.pid))
    sys.exit(0)
if mode == "fail":
    print("boom", file=sys.stderr)
    sys.exit(3)
if mode == "partial_fail":
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "talk|半句"}]}}))
    print("crashed", file=sys.stderr)
    sys.exit(2)
summary = {
    "args": sys.argv[1:],
    "kinds": [block["type"] for block in content],
    "visible": sorted(k for k in os.environ if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "AWS_BEARER"))),
}
print(json.dumps({"type": "system", "subtype": "init"}))
print("not json")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(summary)}))
