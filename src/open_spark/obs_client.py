"""OBS WebSocket client.

Two implementations behind the same async interface:

* :class:`OBSClient`     — talks to a real OBS via ``obsws-python``.
* :class:`MockOBSClient` — in-memory fake. Logs intent. No network.

The injection contract is intentionally tiny:

    await client.upsert_browser_source(name, url, width, height, scene)

It creates the scene if missing, creates the source if missing, otherwise
updates the URL of the existing source. Idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)


class OBSClientProtocol(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_connected(self) -> bool: ...
    async def upsert_browser_source(
        self,
        name: str,
        url: str,
        width: int = 1920,
        height: int = 1080,
        scene: str | None = None,
    ) -> dict: ...
    async def list_scenes(self) -> list[str]: ...
    async def current_scene_name(self) -> str | None: ...
    async def upsert_scene_layout(
        self,
        scene_name: str,
        sources: list[dict],
        replace: bool = False,
    ) -> dict: ...
    async def raw_request(
        self, request_type: str, data: dict | None = None
    ) -> dict: ...


@dataclass
class _MockSource:
    name: str
    url: str
    width: int
    height: int
    scene: str
    transform: dict | None = None  # {x, y, width, height} when placed by upsert_scene_layout


@dataclass
class MockOBSClient:
    """In-memory OBS double for dev without OBS open. No real I/O."""

    scenes: list[str] = field(default_factory=lambda: ["Open Spark"])
    sources: dict[str, _MockSource] = field(default_factory=dict)
    # scene_name -> list of source names in order, mirrors OBS scene items.
    scene_items: dict[str, list[str]] = field(default_factory=dict)
    _connected: bool = False

    async def connect(self) -> None:
        self._connected = True
        log.info("[mock-obs] connected")

    async def disconnect(self) -> None:
        self._connected = False
        log.info("[mock-obs] disconnected")

    async def is_connected(self) -> bool:
        return self._connected

    async def list_scenes(self) -> list[str]:
        return list(self.scenes)

    async def current_scene_name(self) -> str | None:
        return self.scenes[-1] if self.scenes else None

    async def upsert_browser_source(
        self,
        name: str,
        url: str,
        width: int = 1920,
        height: int = 1080,
        scene: str | None = None,
    ) -> dict:
        scene = scene or "Open Spark"
        if scene not in self.scenes:
            self.scenes.append(scene)
            log.info("[mock-obs] created scene %s", scene)
        self.sources[name] = _MockSource(
            name=name, url=url, width=width, height=height, scene=scene
        )
        self.scene_items.setdefault(scene, [])
        if name not in self.scene_items[scene]:
            self.scene_items[scene].append(name)
        log.info("[mock-obs] upsert browser_source name=%s url=%s scene=%s", name, url, scene)
        return {
            "name": name,
            "url": url,
            "scene": scene,
            "kind": "browser_source",
            "mock": True,
        }

    async def upsert_scene_layout(
        self,
        scene_name: str,
        sources: list[dict],
        replace: bool = False,
    ) -> dict:
        if scene_name not in self.scenes:
            self.scenes.append(scene_name)
            log.info("[mock-obs] created scene %s", scene_name)
        if replace:
            for old in list(self.scene_items.get(scene_name, [])):
                self.sources.pop(old, None)
            self.scene_items[scene_name] = []

        applied = []
        for s in sources:
            t = s["transform"]
            self.sources[s["name"]] = _MockSource(
                name=s["name"],
                url=s["url"],
                width=t["width"],
                height=t["height"],
                scene=scene_name,
                transform=dict(t),
            )
            self.scene_items.setdefault(scene_name, [])
            if s["name"] not in self.scene_items[scene_name]:
                self.scene_items[scene_name].append(s["name"])
            applied.append(
                {"name": s["name"], "url": s["url"], "transform": t, "role": s.get("role")}
            )
        log.info("[mock-obs] upsert_scene_layout scene=%s sources=%d replace=%s",
                 scene_name, len(applied), replace)
        return {"scene": scene_name, "sources": applied, "mock": True}

    async def raw_request(
        self, request_type: str, data: dict | None = None
    ) -> dict:
        """Simulate the obs-websocket requests the agent layer uses.

        Only the ones the agent tools actually issue are modelled; the
        rest return an ``ok`` stub so tests stay deterministic without a
        real OBS.
        """
        data = data or {}
        rt = request_type
        if rt == "GetSceneList":
            return {
                "scenes": [{"sceneName": s} for s in self.scenes],
                "currentProgramSceneName": self.scenes[-1] if self.scenes else "",
            }
        if rt == "GetInputKindList":
            return {"inputKinds": [
                "browser_source", "image_source", "color_source_v3",
                "text_ft2_source_v2", "v4l2_input", "ffmpeg_source",
            ]}
        if rt == "GetSceneItemList":
            scene = data.get("sceneName", "")
            items = self.scene_items.get(scene, [])
            return {"sceneItems": [
                {"sceneItemId": i + 1, "sourceName": n}
                for i, n in enumerate(items)
            ]}
        if rt == "GetSourceFilterList":
            return {"filters": []}
        if rt == "CreateInput":
            scene = data.get("sceneName", "Open Spark")
            name = data.get("inputName", "input")
            if scene not in self.scenes:
                self.scenes.append(scene)
            self.scene_items.setdefault(scene, [])
            if name not in self.scene_items[scene]:
                self.scene_items[scene].append(name)
            self.sources[name] = _MockSource(
                name=name, url="", width=0, height=0, scene=scene
            )
            return {"inputUuid": f"uuid-{name}",
                    "sceneItemId": len(self.scene_items[scene])}
        if rt == "SetCurrentProgramScene":
            sn = data.get("sceneName")
            if sn and sn in self.scenes:
                # Move to end → current_scene_name() reports it.
                self.scenes.remove(sn)
                self.scenes.append(sn)
            return {}
        if rt == "RemoveScene":
            sn = data.get("sceneName")
            if sn in self.scenes and len(self.scenes) > 1:
                self.scenes.remove(sn)
                self.scene_items.pop(sn, None)
            return {"ok": True, "mock": True}
        if rt in (
            "CreateSourceFilter", "SetSourceFilterSettings",
            "RemoveSourceFilter", "SetSceneItemTransform",
            "SetSceneItemEnabled", "SetInputSettings", "CreateScene",
        ):
            return {"ok": True, "mock": True}
        return {"ok": True, "mock": True, "unhandled": rt}


class OBSClient:
    """Real obs-websocket client.

    obsws-python is sync. We wrap calls in :func:`asyncio.to_thread` to keep
    the FastAPI event loop responsive.
    """

    def __init__(self, host: str, port: int, password: str | None) -> None:
        self.host = host
        self.port = port
        self.password = password
        self._req = None

    async def connect(self) -> None:
        from obsws_python import ReqClient

        def _open():
            return ReqClient(
                host=self.host,
                port=self.port,
                password=self.password or "",
                timeout=5,
            )

        self._req = await asyncio.to_thread(_open)
        log.info("connected to OBS WebSocket at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        if self._req is not None:
            try:
                await asyncio.to_thread(self._req.disconnect)
            except Exception as e:  # noqa: BLE001
                log.debug("disconnect ignored: %s", e)
            self._req = None

    async def is_connected(self) -> bool:
        return self._req is not None

    async def _reconnect(self) -> None:
        """Drop a stale handle and open a fresh one. Used by retry()."""
        log.info("OBS WebSocket reconnecting…")
        try:
            await self.disconnect()
        except Exception:  # noqa: BLE001
            pass
        await self.connect()

    async def _retry(self, fn, *args, **kwargs):
        """Run a sync obsws-python call, transparently reconnect once on
        broken-pipe / connection-reset errors. OBS restarts (e.g. after
        a settings change or a docker compose restart) leave the client
        with a dead socket; without this the very next call would 502.
        """
        if self._req is None:
            await self.connect()
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            log.warning("OBS call failed (%s); reconnecting and retrying", e)
            await self._reconnect()
            # rebind the bound method to the new client instance
            method_name = getattr(fn, "__name__", None)
            if method_name and self._req is not None:
                fn = getattr(self._req, method_name)
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            # Some obsws errors look like generic OSError on a closed
            # socket; treat the same way.
            msg = str(e).lower()
            if "broken pipe" in msg or "connection reset" in msg \
                    or "not connected" in msg:
                log.warning("OBS call OSError (%s); reconnecting and retrying", e)
                await self._reconnect()
                method_name = getattr(fn, "__name__", None)
                if method_name and self._req is not None:
                    fn = getattr(self._req, method_name)
                return await asyncio.to_thread(fn, *args, **kwargs)
            raise

    async def list_scenes(self) -> list[str]:
        if self._req is None:
            try:
                await self.connect()
            except Exception:  # noqa: BLE001
                return []
        resp = await self._retry(self._req.get_scene_list)
        return [s["sceneName"] for s in resp.scenes]

    async def current_scene_name(self) -> str | None:
        """Name of the program/active scene the user is currently on.

        Used so inject defaults to the visible scene instead of always
        forcing a hidden "Open Spark" scene the user has to switch to
        by hand.
        """
        if self._req is None:
            try:
                await self.connect()
            except Exception:  # noqa: BLE001
                return None
        try:
            resp = await self._retry(self._req.get_current_program_scene)
        except Exception as e:  # noqa: BLE001
            log.debug("current_scene_name failed: %s", e)
            return None
        # obsws-python normalises the field name to current_program_scene_name.
        for attr in (
            "current_program_scene_name",
            "currentProgramSceneName",
            "scene_name",
            "sceneName",
        ):
            v = getattr(resp, attr, None)
            if v:
                return str(v)
        return None

    async def raw_request(
        self, request_type: str, data: dict | None = None
    ) -> dict:
        """Generic obs-websocket passthrough used by the agent tools.

        We send the request with obsws-python's low-level ``send`` and
        normalise the response to a plain dict so the agent layer never
        has to know about obsws-python's attribute objects. Reconnects
        transparently on a dead socket like every other call here.
        """
        if self._req is None:
            await self.connect()

        def _call():
            assert self._req is not None
            # obsws-python ReqClient.send(type, data, raw=True) returns
            # the response dict verbatim.
            try:
                return self._req.send(request_type, data or {}, raw=True)
            except TypeError:
                # Older obsws-python without the `raw` kwarg.
                resp = self._req.send(request_type, data or {})
                if isinstance(resp, dict):
                    return resp
                return {
                    k: v for k, v in vars(resp).items()
                    if not k.startswith("_")
                }

        result = await self._retry(_call)
        if isinstance(result, dict):
            return result
        # Defensive: coerce attribute object → dict.
        return {
            k: v for k, v in vars(result).items() if not k.startswith("_")
        }

    async def upsert_browser_source(
        self,
        name: str,
        url: str,
        width: int = 1920,
        height: int = 1080,
        scene: str | None = None,
    ) -> dict:
        if self._req is None:
            raise RuntimeError("OBS client not connected")

        scene = scene or "Open Spark"
        scenes = await self.list_scenes()
        if scene not in scenes:
            await self._retry(self._req.create_scene, scene)
            log.info("created OBS scene %s", scene)

        settings = {
            "url": url,
            "width": width,
            "height": height,
            "reroute_audio": True,
            "shutdown": True,
            "restart_when_active": True,
        }

        try:
            await self._retry(
                self._req.create_input,
                scene,
                name,
                "browser_source",
                settings,
                True,
            )
            log.info("created browser_source %s on scene %s", name, scene)
            action = "created"
        except Exception as e:
            # Already exists → update settings instead
            log.debug("create_input failed (%s), falling back to update", e)
            await self._retry(self._req.set_input_settings, name, settings, True)
            log.info("updated browser_source %s url=%s", name, url)
            action = "updated"

        return {
            "name": name,
            "url": url,
            "scene": scene,
            "kind": "browser_source",
            "action": action,
            "mock": False,
        }

    async def _ensure_scene(self, scene_name: str) -> None:
        scenes = await self.list_scenes()
        if scene_name not in scenes:
            assert self._req is not None
            await self._retry(self._req.create_scene, scene_name)
            log.info("created OBS scene %s", scene_name)

    async def _clear_scene(self, scene_name: str) -> None:
        if self._req is None:
            return
        try:
            resp = await self._retry(self._req.get_scene_item_list, scene_name)
        except Exception as e:
            log.warning("get_scene_item_list failed for %s: %s", scene_name, e)
            return
        items = getattr(resp, "scene_items", []) or []
        # OBS returns items in z-order; remove from top down to avoid id reuse.
        for item in reversed(items):
            item_id = item.get("sceneItemId") if isinstance(item, dict) else None
            src_name = item.get("sourceName") if isinstance(item, dict) else None
            if item_id is None:
                continue
            try:
                await self._retry(self._req.remove_scene_item, scene_name, item_id)
                log.info("removed scene item %s (%s) from %s", item_id, src_name, scene_name)
            except Exception as e:
                log.warning("remove_scene_item failed for %s: %s", item_id, e)

    async def _create_or_update_browser_input(
        self,
        scene_name: str,
        name: str,
        url: str,
        width: int,
        height: int,
    ) -> int | None:
        """Returns the sceneItemId of the (created or existing) item."""
        assert self._req is not None
        settings = {
            "url": url,
            "width": width,
            "height": height,
            "reroute_audio": True,
            "shutdown": True,
            "restart_when_active": True,
        }
        try:
            resp = await self._retry(
                self._req.create_input,
                scene_name, name, "browser_source", settings, True,
            )
            log.info("created browser_source %s on scene %s", name, scene_name)
            return getattr(resp, "scene_item_id", None)
        except Exception as e:
            log.debug("create_input failed (%s); updating existing source", e)
            await self._retry(self._req.set_input_settings, name, settings, True)
            # Fetch the existing scene item id.
            try:
                resp = await self._retry(
                    self._req.get_scene_item_id, scene_name, name, 0
                )
                return getattr(resp, "scene_item_id", None)
            except Exception as e2:
                # Source exists but not on this scene: add it.
                log.debug("get_scene_item_id failed (%s); adding to scene", e2)
                try:
                    resp = await self._retry(
                        self._req.create_scene_item, scene_name, name, True
                    )
                    return getattr(resp, "scene_item_id", None)
                except Exception as e3:
                    log.warning("create_scene_item also failed for %s: %s", name, e3)
                    return None

    async def _set_transform(
        self,
        scene_name: str,
        scene_item_id: int,
        transform: dict,
    ) -> None:
        assert self._req is not None
        # OBS expects a transform dict with positionX/Y, scaleX/Y. We use
        # bounds to force exact rendered size regardless of source intrinsic.
        t = {
            "positionX": float(transform["x"]),
            "positionY": float(transform["y"]),
            "boundsType": "OBS_BOUNDS_STRETCH",
            "boundsAlignment": 0,
            "boundsWidth": float(transform["width"]),
            "boundsHeight": float(transform["height"]),
            "alignment": 5,  # top-left
        }
        try:
            await self._retry(
                self._req.set_scene_item_transform, scene_name, scene_item_id, t
            )
        except Exception as e:
            log.warning("set_scene_item_transform failed for item %s: %s", scene_item_id, e)

    async def upsert_scene_layout(
        self,
        scene_name: str,
        sources: list[dict],
        replace: bool = False,
    ) -> dict:
        if self._req is None:
            raise RuntimeError("OBS client not connected")

        await self._ensure_scene(scene_name)
        if replace:
            await self._clear_scene(scene_name)

        applied: list[dict] = []
        for s in sources:
            name = s["name"]
            url = s["url"]
            t = s["transform"]
            item_id = await self._create_or_update_browser_input(
                scene_name, name, url, int(t["width"]), int(t["height"])
            )
            if item_id is not None:
                await self._set_transform(scene_name, item_id, t)
            applied.append({
                "name": name,
                "url": url,
                "transform": t,
                "role": s.get("role"),
                "scene_item_id": item_id,
            })
        log.info("upsert_scene_layout scene=%s sources=%d replace=%s",
                 scene_name, len(applied), replace)
        return {"scene": scene_name, "sources": applied, "mock": False}


def make_client(*, mock: bool, host: str, port: int, password: str | None) -> OBSClientProtocol:
    if mock:
        return MockOBSClient()
    return OBSClient(host=host, port=port, password=password)
