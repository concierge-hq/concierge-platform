import os
import subprocess
import time
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from openmcp.backends.vanilla_backend import VanillaBackend
from openmcp.core.widget import Widget, WidgetMode
from openmcp.telemetry import metrics, ENABLED as METRICS_ENABLED


class ProviderType(Enum):
    PLAIN = "plain"
    SEARCH = "search"


def _get_provider_class(provider_type: ProviderType):
    """Lazy load provider to avoid importing optional dependencies."""
    if provider_type == ProviderType.SEARCH:
        from openmcp.backends.search_backend import SearchBackend
        return SearchBackend
    return VanillaBackend


class Config:
    def __init__(self, max_results=5, provider_type=ProviderType.PLAIN, model=None):
        self.max_results = max_results
        self.provider_type = provider_type
        self.model = model


# Template for Mode 2 (URL → iframe wrapper)
IFRAME_TEMPLATE = '''<!DOCTYPE html>
<html>
<head><style>*{margin:0;padding:0}iframe{width:100%;height:100vh;border:none}</style></head>
<body><iframe src="{url}"></iframe></body>
</html>'''


class OpenMCP:

    def __init__(self, server, *, config=Config(), assets_dir: str | None = None, **fastmcp_kwargs):
        if isinstance(server, FastMCP):
            self._server = server
        else:
            self._server = FastMCP(server, **fastmcp_kwargs)
        self._config = config
        self._widgets: List[Widget] = []
        self._pending_resources: List[types.Resource] = []
        self._assets_dir = Path(assets_dir) if assets_dir else Path.cwd() / "assets"

        provider_cls = _get_provider_class(config.provider_type)
        self._provider = provider_cls()
        self._provider.initialize(config)

    def _get_widget_meta(self, w: Widget) -> dict:
        return {
            "openai/outputTemplate": w.uri,
            "openai/widgetAccessible": w.widget_accessible,
            "openai/toolInvocation/invoking": w.invoking,
            "openai/toolInvocation/invoked": w.invoked,
        }

    def _setup_resource_handler(self) -> None:
        original_list_resources = self._server.list_resources
        widget_resources = self._pending_resources

        async def _list_all_resources() -> List[types.Resource]:
            fastmcp_resources = await original_list_resources()
            return fastmcp_resources + widget_resources

        self._server._mcp_server.list_resources()(_list_all_resources)

    def _get_widget_html(self, widget: Widget) -> str:
        """Get HTML content for a widget based on its mode."""
        mode = widget.mode
        
        if mode == WidgetMode.HTML:
            return widget.html
        
        if mode == WidgetMode.URL:
            return IFRAME_TEMPLATE.format(url=widget.url)
        
        if mode == WidgetMode.ENTRYPOINT:
            dist_path = self._assets_dir / "dist" / widget.dist_file
            if not dist_path.exists():
                raise FileNotFoundError(
                    f"Widget {widget.name}: dist/{widget.dist_file} not found. "
                    f"Run 'npm run build' in {self._assets_dir}"
                )
            return dist_path.read_text()
        
        if mode == WidgetMode.DYNAMIC:
            if not hasattr(widget, '_last_args') or widget._last_args is None:
                raise ValueError(f"Widget {widget.name}: call the tool first")
            return widget.html_fn(widget._last_args)
        
        raise ValueError(f"Unknown widget mode: {mode}")

    def _setup_read_resource_handler(self) -> None:
        widgets_by_uri = {w.uri: w for w in self._widgets}
        get_html = self._get_widget_html

        original_handler = self._server._mcp_server.request_handlers.get(
            types.ReadResourceRequest
        )

        async def _read_resource_with_meta(
            req: types.ReadResourceRequest,
        ) -> types.ServerResult:
            uri_str = str(req.params.uri)
            widget = widgets_by_uri.get(uri_str)

            if widget:
                text = get_html(widget)
                contents = [
                    types.TextResourceContents(
                        uri=widget.uri,
                        mimeType=widget.mime_type,
                        text=text,
                        _meta=self._get_widget_meta(widget),
                    )
                ]
                return types.ServerResult(types.ReadResourceResult(contents=contents))

            if original_handler:
                return await original_handler(req)

            raise ValueError(f"Unknown resource: {uri_str}")

        self._server._mcp_server.request_handlers[
            types.ReadResourceRequest
        ] = _read_resource_with_meta

    def _run_widget_builds(self):
        """Auto-run npm build if any widget uses entrypoint mode."""
        needs_build = any(w.mode == WidgetMode.ENTRYPOINT for w in self._widgets)
        if not needs_build:
            return
        
        package_json = self._assets_dir / "package.json"
        if not package_json.exists():
            raise FileNotFoundError(
                f"{self._assets_dir}/package.json not found. "
                f"Widgets using entrypoint mode require a build system."
            )
        
        print("Installing web dependencies...", flush=True)
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(self._assets_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"npm install failed:\n{result.stderr}")
        
        print("Building widgets...", flush=True)
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(self._assets_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Build failed:\n{result.stdout}\n{result.stderr}")
        print("Build complete", flush=True)

    def _finalize(self):
        """Setup all handlers. Called before run() or streamable_http_app()."""
        if getattr(self, "_finalized", False):
            return
        self._finalized = True

        self._run_widget_builds()

        tools = self._server._tool_manager.list_tools()
        self._provider.index_tools(tools)

        served_tools = self._provider.serve_tools()
        self._server._tool_manager._tools = {t.name: t for t in served_tools}

        self._setup_resource_handler()
        self._setup_read_resource_handler()
        self._setup_metrics()

    def _setup_metrics(self):
        if not METRICS_ENABLED:
            return
        handlers = self._server._mcp_server.request_handlers

        if types.CallToolRequest in handlers:
            original = handlers[types.CallToolRequest]
            async def wrapped_call(req: types.CallToolRequest) -> types.ServerResult:
                metrics.ensure_started()
                start = time.perf_counter()
                is_error, error_msg = False, None
                try:
                    return await original(req)
                except Exception as e:
                    is_error, error_msg = True, str(e)
                    raise
                finally:
                    metrics.track("mcp:tools/call", resource_name=req.params.name,
                                  duration_ms=int((time.perf_counter() - start) * 1000),
                                  is_error=is_error, error_message=error_msg)
            handlers[types.CallToolRequest] = wrapped_call

        if types.ReadResourceRequest in handlers:
            original_read = handlers[types.ReadResourceRequest]
            async def wrapped_read(req: types.ReadResourceRequest) -> types.ServerResult:
                metrics.ensure_started()
                start = time.perf_counter()
                is_error, error_msg = False, None
                try:
                    return await original_read(req)
                except Exception as e:
                    is_error, error_msg = True, str(e)
                    raise
                finally:
                    metrics.track("mcp:resources/read", resource_name=str(req.params.uri),
                                  duration_ms=int((time.perf_counter() - start) * 1000),
                                  is_error=is_error, error_message=error_msg)
            handlers[types.ReadResourceRequest] = wrapped_read

    def run(self, *args, **kwargs):
        self._finalize()
        metrics.start()
        return self._server.run(*args, **kwargs)

    def streamable_http_app(self):
        self._finalize()
        metrics.start()
        app = self._server.streamable_http_app()
        
        # from starlette.middleware.cors import CORSMiddleware
        # app.add_middleware(
        #     CORSMiddleware,
        #     allow_origins=["*"],
        #     allow_methods=["*"],
        #     allow_headers=["*"],
        # )
        return app

    def widget(
        self,
        uri: str,
        # Mode 1: Inline HTML
        html: str | None = None,
        # Mode 2: External URL  
        url: str | None = None,
        # Mode 3: Entrypoint (filename in entrypoints/)
        entrypoint: str | None = None,
        # Mode 4: Dynamic function (takes args dict, returns HTML string)
        html_fn: Callable[[dict], str] | None = None,
        # Metadata
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        invoking: str = "Loading...",
        invoked: str = "Done",
        annotations: dict | None = None,
    ) -> Callable:

        def decorator(fn: Callable) -> Callable:
            w = Widget(
                uri=uri,
                html=html,
                url=url,
                entrypoint=entrypoint,
                html_fn=html_fn,
                name=name or fn.__name__,
                title=title,
                description=description or fn.__doc__,
                invoking=invoking,
                invoked=invoked,
                annotations=annotations,
            )
            self._widgets.append(w)
            self._pending_resources.append(
                types.Resource(
                    uri=w.uri,
                    name=w.name,
                    title=w.title,
                    description=w.description,
                    mimeType=w.mime_type,
                    _meta=self._get_widget_meta(w),
                )
            )

            @wraps(fn)
            async def wrapped(*args, **kwargs) -> types.CallToolResult:
                result = await fn(*args, **kwargs)
                
                if w.html_fn:
                    w._last_args = result
                
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=w.invoked)],
                    structuredContent=result,
                    _meta={
                        "openai/toolInvocation/invoking": w.invoking,
                        "openai/toolInvocation/invoked": w.invoked,
                    },
                )

            self._server.tool(
                name=w.name,
                title=w.title,
                description=w.description,
                annotations=w.annotations,
                meta={
                    "openai/outputTemplate": w.uri,
                    "openai/widgetAccessible": w.widget_accessible,
                    "openai/toolInvocation/invoking": w.invoking,
                    "openai/toolInvocation/invoked": w.invoked,
                },
            )(wrapped)

            return fn

        return decorator

    def __getattr__(self, name):
        return getattr(self._server, name)
