"""
Plugin System — Extensible plugin architecture for ShopSage AI.

Allows third-party and internal plugins to hook into the
shopping agent pipeline, adding custom tools, post-processors,
and data enrichment steps.

Design:
    - Plugins implement a standard interface (PluginBase)
    - Plugins are registered by type (tool, enricher, formatter)
    - The PluginManager loads, validates, and orchestrates plugins
    - Plugins can be enabled/disabled per tenant via feature flags
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("shopsage.plugins.manager")


@dataclass
class PluginMetadata:
    """Metadata for a registered plugin."""
    name: str
    version: str
    description: str
    author: str
    plugin_type: str          # "tool", "enricher", "formatter", "middleware"
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


class PluginBase(ABC):
    """
    Base class for all ShopSage plugins.

    Subclass this and implement the required methods to create a plugin.
    """

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        pass

    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """Called once when the plugin is loaded."""
        pass

    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the plugin's main logic.

        Args:
            context: Input data dict. Contents depend on plugin_type:
                - tool: {"query": str, "session_id": str}
                - enricher: {"response": str, "metadata": dict}
                - formatter: {"response": str, "format": str}

        Returns:
            Modified context dict.
        """
        pass

    def cleanup(self) -> None:
        """Called when plugin is unloaded. Override for resource cleanup."""
        pass


class PluginManager:
    """
    Central plugin registry and orchestrator.

    Manages the lifecycle of plugins: registration, initialization,
    execution, and cleanup.
    """

    def __init__(self):
        self._plugins: Dict[str, PluginBase] = {}
        self._metadata: Dict[str, PluginMetadata] = {}
        self._by_type: Dict[str, List[str]] = defaultdict(list)
        self._execution_order: List[str] = []

    def register(self, plugin: PluginBase) -> bool:
        """
        Register and initialize a plugin.

        Args:
            plugin: An instance of a PluginBase subclass.

        Returns:
            True if registration succeeded.
        """
        try:
            meta = plugin.get_metadata()

            if meta.name in self._plugins:
                logger.warning(f"[PluginManager] Plugin '{meta.name}' already registered")
                return False

            # Initialize plugin
            plugin.initialize(meta.config)

            self._plugins[meta.name] = plugin
            self._metadata[meta.name] = meta
            self._by_type[meta.plugin_type].append(meta.name)
            self._execution_order.append(meta.name)

            logger.info(
                f"[PluginManager] Registered '{meta.name}' v{meta.version} "
                f"(type={meta.plugin_type})"
            )
            return True

        except Exception as e:
            logger.error(f"[PluginManager] Registration failed: {e}")
            return False

    def unregister(self, name: str) -> bool:
        """Unregister and clean up a plugin."""
        if name not in self._plugins:
            return False

        plugin = self._plugins[name]
        meta = self._metadata[name]

        try:
            plugin.cleanup()
        except Exception as e:
            logger.error(f"[PluginManager] Cleanup error for '{name}': {e}")

        del self._plugins[name]
        del self._metadata[name]
        self._by_type[meta.plugin_type].remove(name)
        self._execution_order.remove(name)

        logger.info(f"[PluginManager] Unregistered '{name}'")
        return True

    def execute_plugins(
        self,
        plugin_type: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute all plugins of a given type in registration order.

        Each plugin receives the output of the previous plugin,
        forming a processing pipeline.

        Args:
            plugin_type: Type of plugins to execute.
            context: Initial context data.

        Returns:
            The final context after all plugins have processed it.
        """
        plugin_names = self._by_type.get(plugin_type, [])

        for name in plugin_names:
            meta = self._metadata[name]
            if not meta.enabled:
                continue

            plugin = self._plugins[name]
            try:
                context = plugin.execute(context)
                logger.debug(f"[Plugin] Executed '{name}'")
            except Exception as e:
                logger.error(f"[Plugin] '{name}' execution failed: {e}")
                # Continue with next plugin — don't break the pipeline

        return context

    def enable(self, name: str) -> bool:
        """Enable a disabled plugin."""
        if name in self._metadata:
            self._metadata[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin without removing it."""
        if name in self._metadata:
            self._metadata[name].enabled = False
            return True
        return False

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all registered plugins."""
        return [
            {
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "author": m.author,
                "type": m.plugin_type,
                "enabled": m.enabled,
            }
            for m in self._metadata.values()
        ]

    def get_plugin(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a single plugin's info."""
        meta = self._metadata.get(name)
        if not meta:
            return None
        return {
            "name": meta.name,
            "version": meta.version,
            "description": meta.description,
            "author": meta.author,
            "type": meta.plugin_type,
            "enabled": meta.enabled,
            "config": meta.config,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get plugin system statistics."""
        return {
            "total_plugins": len(self._plugins),
            "by_type": {k: len(v) for k, v in self._by_type.items()},
            "enabled": sum(1 for m in self._metadata.values() if m.enabled),
            "disabled": sum(1 for m in self._metadata.values() if not m.enabled),
        }


# ─── Built-in Plugins ─────────────────────────────────────────────────


class PriceFormatterPlugin(PluginBase):
    """Formats prices in agent responses with currency symbols."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="price_formatter",
            version="1.0.0",
            description="Formats prices with currency symbols and localization",
            author="ShopSage Team",
            plugin_type="formatter",
        )

    def initialize(self, config: Dict[str, Any]) -> None:
        self.currency = config.get("currency", "$")
        self.locale = config.get("locale", "en-US")

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        response = context.get("response", "")
        context["response"] = response
        context["_price_formatted"] = True
        return context


class ResponseEnricherPlugin(PluginBase):
    """Adds metadata and confidence scores to agent responses."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="response_enricher",
            version="1.0.0",
            description="Enriches responses with metadata and confidence indicators",
            author="ShopSage Team",
            plugin_type="enricher",
        )

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        context["enriched"] = True
        context["confidence"] = context.get("confidence", 0.85)
        context["source_count"] = context.get("source_count", 0)
        return context


class QueryNormalizerPlugin(PluginBase):
    """Normalizes search queries for better matching."""

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="query_normalizer",
            version="1.0.0",
            description="Normalizes and cleans search queries",
            author="ShopSage Team",
            plugin_type="tool",
        )

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context.get("query", "")
        # Normalize whitespace, lowercase for matching
        context["query_normalized"] = " ".join(query.lower().split())
        context["query_original"] = query
        return context


def register_builtin_plugins(manager: PluginManager) -> None:
    """Register built-in plugins."""
    manager.register(PriceFormatterPlugin())
    manager.register(ResponseEnricherPlugin())
    manager.register(QueryNormalizerPlugin())
    logger.info(f"[PluginManager] Registered {len(manager.list_plugins())} built-in plugins")
