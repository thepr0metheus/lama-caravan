"""Subprocess helpers: never raise, always return an {ok, code, stdout, stderr} dict."""
import os
import subprocess


def run(cmd, timeout=10, env=None):
    return run_in(cmd, timeout=timeout, env=env)

def run_in(cmd, timeout=10, cwd=None, env=None):
    try:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, cwd=cwd, env=run_env)
        return {
            "ok": result.returncode == 0,
            "code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}
