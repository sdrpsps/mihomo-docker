#!/usr/bin/env python3
import contextlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


DATA = Path("/data")
ACTIVE = DATA / "config.yaml"
LOCAL = Path("/input/config.yaml")
LOCAL_RUNTIME = DATA / "local-runtime.yaml"
MIHOMO = ["/usr/local/bin/mihomo", "-d", str(DATA)]
CONTROLLER = "http://127.0.0.1:9090"
CONTROLLER_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MAX_CONFIG_BYTES = 8 * 1024 * 1024
YAML_TAG = "tag:yaml.org,2002:"
refresh_requested = False


class ConfigError(Exception):
    pass


class RecoveryRequired(ConfigError):
    pass


def log(message):
    print(f"[manager] {message}", flush=True)


def secret_from_env():
    secret = os.environ.get("MIHOMO_SECRET", "")
    if not re.fullmatch(r"[!-~]+", secret):
        raise ConfigError("MIHOMO_SECRET must be nonempty ASCII without spaces or control characters")
    return secret


def read_config(path):
    with path.open("rb") as stream:
        return stream.read(MAX_CONFIG_BYTES + 1)


def download(url):
    if not url.startswith(("http://", "https://")):
        raise ConfigError("SUB_URL must start with http:// or https://")
    redirects = "=https" if url.startswith("https://") else "=http,https"
    command = [
        "curl", "--disable", "--fail", "--silent", "--location", "--max-redirs", "5",
        "--proto", "=http,https", "--proto-redir", redirects, "--connect-timeout", "8",
        "--max-time", "30", "--max-filesize", str(MAX_CONFIG_BYTES),
        "--user-agent", os.environ.get("SUB_USER_AGENT", "clash.meta"),
        "--proxy", os.environ.get("SUB_PROXY", ""), "--noproxy", "",
        "--url", url,
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=True, timeout=35)
    except (subprocess.SubprocessError, OSError) as error:
        raise ConfigError("subscription download failed") from error
    return result.stdout


def render(raw, secret, subscription):
    if not raw.strip() or len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError("configuration is empty or exceeds 8 MiB")
    try:
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError) as error:
        raise ConfigError("configuration is not a single YAML document") from error
    if not isinstance(root, MappingNode) or root.tag != YAML_TAG + "map":
        raise ConfigError("configuration must be a YAML mapping")
    fields = {}
    for key, value in root.value:
        if not isinstance(key, ScalarNode) or key.tag not in (YAML_TAG + "str", YAML_TAG + "merge"):
            raise ConfigError("configuration keys must be strings")
        if key.value in fields:
            raise ConfigError("duplicate top-level configuration key")
        fields[key.value] = value
    if subscription and not any(
        isinstance(fields.get(name), kind) and fields[name].value
        for name, kind in (
            ("rules", SequenceNode), ("proxy-groups", SequenceNode), ("proxy-providers", MappingNode)
        )
    ):
        raise ConfigError("subscription must contain nonempty rules, proxy-groups or proxy-providers")

    fixed = {
        "external-controller": "0.0.0.0:9090",
        "external-controller-tls": "",
        "external-controller-unix": "",
        "external-controller-pipe": "",
        "external-doh-server": "",
        "external-controller-cors": {"allow-origins": [], "allow-private-network": False},
        "external-ui": "/opt/zashboard",
        "external-ui-name": "",
        "external-ui-url": "",
        "secret": secret,
        "mixed-port": 7890,
        "allow-lan": True,
        "bind-address": "*",
    }
    root.value = [(key, value) for key, value in root.value if key.value not in fixed]
    overrides = yaml.compose(yaml.safe_dump(fixed), Loader=yaml.SafeLoader)
    root.value.extend(overrides.value)
    try:
        rendered = yaml.serialize(root, Dumper=yaml.SafeDumper, encoding="utf-8")
    except (yaml.YAMLError, RecursionError) as error:
        raise ConfigError("could not write candidate YAML") from error
    if len(rendered) > MAX_CONFIG_BYTES:
        raise ConfigError("rendered configuration exceeds 8 MiB")
    return rendered


@contextlib.contextmanager
def candidate(raw, secret, subscription):
    rendered = render(raw, secret, subscription)
    with tempfile.NamedTemporaryFile(dir=DATA, prefix=".candidate-", suffix=".yaml",
                                     delete=False) as stream:
        path = Path(stream.name)
        try:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
            try:
                subprocess.run([*MIHOMO, "-t", "-f", str(path)], check=True, timeout=45,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, OSError) as error:
                raise ConfigError("Mihomo native validation failed or timed out") from error
            yield path
        finally:
            path.unlink(missing_ok=True)


def api(secret, endpoint, payload=None, timeout=2):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        CONTROLLER + endpoint, data=data, method="GET" if data is None else "PUT",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
    )
    try:
        with CONTROLLER_OPENER.open(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        error.close()
        return error.code
    except OSError:
        return None


def ready(secret):
    if api(secret, "/version") != 200:
        return False
    try:
        with socket.create_connection(("127.0.0.1", 7890), timeout=1):
            return True
    except OSError:
        return False


def reload_config(secret, path):
    return api(secret, "/configs?force=true", {"path": str(path)}, timeout=35)


def refresh(url, secret):
    try:
        with candidate(download(url), secret, subscription=True) as proposed:
            if read_config(proposed) == read_config(ACTIVE):
                log("subscription unchanged")
                return
            status = reload_config(secret, proposed)
            if status is None:
                raise RecoveryRequired("reload outcome unknown; restarting from saved configuration")
            try:
                if status != 204 or not ready(secret):
                    raise ConfigError("Controller did not confirm candidate reload")
                proposed.replace(ACTIVE)
            except (ConfigError, OSError) as error:
                if reload_config(secret, ACTIVE) != 204 or not ready(secret):
                    raise RecoveryRequired("rollback unconfirmed; restarting from saved configuration") from error
                raise
    except RecoveryRequired:
        raise
    except (ConfigError, OSError) as error:
        log(f"subscription kept previous configuration ({error})")
        return
    log("subscription applied and saved")


def prepare_start(url, secret):
    if not url:
        try:
            raw = read_config(LOCAL)
        except FileNotFoundError as error:
            raise ConfigError("set SUB_URL in compose.yaml or mount a local config at /input/config.yaml") from error
        with candidate(raw, secret, subscription=False) as proposed:
            proposed.replace(LOCAL_RUNTIME)
        log("local configuration validated")
        return False
    if ACTIVE.is_file():
        try:
            with candidate(read_config(ACTIVE), secret, subscription=True) as proposed:
                if read_config(proposed) != read_config(ACTIVE):
                    proposed.replace(ACTIVE)
            log("starting with saved configuration")
            return True
        except ConfigError:
            log("saved configuration failed validation, fetching subscription")
    with candidate(download(url), secret, subscription=True) as proposed:
        proposed.replace(ACTIVE)
    log("first subscription validated")
    return False


def stop(signum, _frame):
    raise SystemExit(128 + signum)


def request_refresh(_signum, _frame):
    global refresh_requested
    refresh_requested = True


def run(secret):
    global refresh_requested
    url = os.environ.get("SUB_URL", "")
    try:
        interval = int(os.environ.get("SUB_INTERVAL", "21600")) if url else 0
        if interval < 0:
            raise ValueError
    except ValueError as error:
        raise ConfigError("SUB_INTERVAL must be a nonnegative number of seconds") from error
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGUSR1, request_refresh)
    saved = prepare_start(url, secret)
    config_path = ACTIVE if url else LOCAL_RUNTIME
    with subprocess.Popen([*MIHOMO, "-f", str(config_path)]) as process:
        try:
            deadline = time.monotonic() + 60
            while not ready(secret):
                if process.poll() is not None or time.monotonic() >= deadline:
                    if url and not saved:
                        ACTIVE.unlink(missing_ok=True)
                    raise ConfigError("Mihomo failed to become ready")
                time.sleep(0.25)
            log("Mihomo is ready")
            next_refresh = time.monotonic() + interval
            refresh_requested = refresh_requested or saved
            while process.poll() is None:
                if url and (refresh_requested or (interval and time.monotonic() >= next_refresh)):
                    refresh_requested = False
                    refresh(url, secret)
                    next_refresh = time.monotonic() + interval
                time.sleep(0.25)
            return process.returncode if process.returncode > 0 else 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()


def main():
    try:
        secret = secret_from_env()
        if sys.argv[1:] == ["healthcheck"]:
            return 0 if ready(secret) else 1
        if sys.argv[1:]:
            raise ConfigError("unknown command")
        return run(secret)
    except (ConfigError, OSError) as error:
        log(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
