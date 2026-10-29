"""Run inside an image. Never open a real Docker socket or Redis connection."""

import asyncio
import hashlib
import inspect
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, "/app")
import main
from modules.DockerApi import DockerApi


class Containers:
    async def list(self, **kwargs):
        self.last_all = kwargs.get("all", False)
        return [SimpleNamespace(_id="abc123", show=self.show)]

    async def show(self):
        return {"Id": "abc123", "Config": {"Labels": {"com.docker.compose.service": "fixture-mailcow"}},
                "State": {"Running": True}, "NetworkSettings": {"Networks": {"fixture": {"IPAddress": "127.0.0.1"}}}}


class Request:
    def __init__(self, data):
        self.data = data

    async def json(self):
        return self.data


async def fixture():
    containers = Containers()
    calls = []

    def action(request, **kwargs):
        calls.append((request, kwargs))
        return main.Response(content='{"type":"success"}', media_type="application/json")

    main.dockerapi = SimpleNamespace(async_docker_client=SimpleNamespace(containers=containers),
                                   logger=logging.getLogger("fixture"),
                                   container_post__exec__reload__nginx=action)
    listed = json.loads((await main.get_containers()).body)
    assert listed["abc123"]["State"]["Running"] is True
    assert containers.last_all is False
    if "all" in inspect.signature(main.get_containers).parameters:
        await main.get_containers(all=True)
        assert containers.last_all is True
    assert json.loads((await main.get_container("abc123")).body)["Id"] == "abc123"
    assert json.loads((await main.get_container("../bad")).body)["type"] == "danger"
    assert json.loads((await main.get_container("absent")).body)["type"] == "danger"
    assert json.loads((await main.post_containers("abc123", "exec", Request({}))).body)["msg"] == "cmd is missing"
    assert json.loads((await main.post_containers("abc123", "exec", Request({"cmd": "reload"}))).body)["msg"] == "task is missing"
    payload = {"cmd": "reload", "task": "nginx"}
    await main.post_containers("abc123", "exec", Request(payload))
    assert calls[-1] == (payload, {"container_id": "abc123"})

    class Channel:
        async def get_message(self, **kwargs):
            if getattr(self, "sent", False):
                raise asyncio.CancelledError
            self.sent = True
            return {"data": json.dumps({"api_call": "container_post", "post_action": "exec",
                    "container_name": "nginx-mailcow", "request": payload}).encode()}

    try:
        await main.handle_pubsub_messages(Channel())
    except asyncio.CancelledError:
        pass
    assert calls[-1] == (payload, {"container_name": "nginx-mailcow"})
    for task in ("nginx", "postfix", "dovecot"):
        assert callable(getattr(DockerApi, "container_post__exec__reload__" + task))
    import uvicorn
    config = uvicorn.Config("main:app", loop="none")
    if hasattr(config, "get_loop_factory"):
        assert config.get_loop_factory() is None
    else:
        config.setup_event_loop()
    assert hashlib.sha256(Path("/app/modules/DockerApi.py").read_bytes()).hexdigest() == "2e9f2fc8f44902e40fce5842fe230bec539f320039e9c05c3dbc7e9d9b412ca2"
    print("Docker API list/lookup/invalid-input/reload dispatch/pubsub fixtures passed; no real actions")


asyncio.run(fixture())
