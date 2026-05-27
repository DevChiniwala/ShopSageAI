"""
Tests for Plugin System and Dynamic Configuration.
"""

import pytest
from shopsage.plugins.manager import (
    PluginManager, PluginBase, PluginMetadata,
    PriceFormatterPlugin, ResponseEnricherPlugin,
    QueryNormalizerPlugin, register_builtin_plugins,
)
from shopsage.config_dynamic import DynamicConfig


# ─── Plugin System Tests ──────────────────────────────────────────────


class MockPlugin(PluginBase):
    """A test plugin."""
    def __init__(self, name="mock_plugin"):
        self._name = name
        self.initialized = False

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name, version="1.0.0",
            description="A test plugin", author="Test",
            plugin_type="tool",
        )

    def initialize(self, config):
        self.initialized = True

    def execute(self, context):
        context["mock_executed"] = True
        return context


@pytest.fixture
def manager():
    return PluginManager()


def test_register_plugin(manager):
    """Should register and initialize a plugin."""
    plugin = MockPlugin()
    assert manager.register(plugin) is True
    assert plugin.initialized is True
    assert len(manager.list_plugins()) == 1


def test_duplicate_registration(manager):
    """Should reject duplicate plugin names."""
    manager.register(MockPlugin("dup"))
    assert manager.register(MockPlugin("dup")) is False


def test_execute_plugins(manager):
    """Should execute plugins and pass context through pipeline."""
    manager.register(MockPlugin())
    context = {"query": "test"}
    result = manager.execute_plugins("tool", context)
    assert result["mock_executed"] is True
    assert result["query"] == "test"


def test_disable_plugin(manager):
    """Disabled plugins should be skipped during execution."""
    manager.register(MockPlugin())
    manager.disable("mock_plugin")

    context = {}
    result = manager.execute_plugins("tool", context)
    assert "mock_executed" not in result


def test_enable_plugin(manager):
    """Re-enabled plugins should execute again."""
    manager.register(MockPlugin())
    manager.disable("mock_plugin")
    manager.enable("mock_plugin")

    context = {}
    result = manager.execute_plugins("tool", context)
    assert result["mock_executed"] is True


def test_unregister_plugin(manager):
    """Should remove a registered plugin."""
    manager.register(MockPlugin())
    assert manager.unregister("mock_plugin") is True
    assert len(manager.list_plugins()) == 0


def test_get_plugin_info(manager):
    """Should retrieve plugin details."""
    manager.register(MockPlugin())
    info = manager.get_plugin("mock_plugin")
    assert info["name"] == "mock_plugin"
    assert info["version"] == "1.0.0"


def test_plugin_stats(manager):
    """Should track plugin statistics."""
    manager.register(MockPlugin("p1"))
    manager.register(MockPlugin("p2"))
    manager.disable("p2")

    stats = manager.get_stats()
    assert stats["total_plugins"] == 2
    assert stats["enabled"] == 1
    assert stats["disabled"] == 1


def test_builtin_plugins(manager):
    """Should register all built-in plugins."""
    register_builtin_plugins(manager)
    plugins = manager.list_plugins()
    names = {p["name"] for p in plugins}
    assert "price_formatter" in names
    assert "response_enricher" in names
    assert "query_normalizer" in names


def test_pipeline_execution_order(manager):
    """Plugins should execute in registration order."""
    order = []

    class OrderPlugin(PluginBase):
        def __init__(self, idx):
            self.idx = idx
        def get_metadata(self):
            return PluginMetadata(
                name=f"order_{self.idx}", version="1.0", description="",
                author="", plugin_type="enricher",
            )
        def initialize(self, config): pass
        def execute(self, context):
            order.append(self.idx)
            return context

    manager.register(OrderPlugin(1))
    manager.register(OrderPlugin(2))
    manager.register(OrderPlugin(3))
    manager.execute_plugins("enricher", {})
    assert order == [1, 2, 3]


# ─── Dynamic Config Tests ─────────────────────────────────────────────


@pytest.fixture
def config(tmp_path):
    return DynamicConfig(db_path=str(tmp_path / "test_config.db"))


def test_defaults_seeded(config):
    """Default config values should be seeded."""
    val = config.get("rate_limit.free.requests_per_minute")
    assert val == 30


def test_get_typed_values(config):
    """Should return correctly typed values."""
    assert isinstance(config.get("agent.temperature"), float)
    assert isinstance(config.get("jobs.max_retries"), int)
    assert isinstance(config.get("security.enable_prompt_injection_check"), bool)


def test_set_global_value(config):
    """Should update a global config value."""
    config.set("agent.temperature", 0.5, value_type="float")
    assert config.get("agent.temperature") == 0.5


def test_tenant_override(config):
    """Per-tenant overrides should take precedence."""
    # Global = 30
    assert config.get("rate_limit.free.requests_per_minute") == 30

    # Set tenant override
    config.set("rate_limit.free.requests_per_minute", 50,
               value_type="int", tenant_id="t1")

    # Tenant gets override
    assert config.get("rate_limit.free.requests_per_minute", tenant_id="t1") == 50

    # Other tenants get global
    assert config.get("rate_limit.free.requests_per_minute", tenant_id="t2") == 30


def test_delete_tenant_override(config):
    """Should delete tenant overrides and fall back to global."""
    config.set("agent.temperature", 0.9, value_type="float", tenant_id="t1")
    assert config.get("agent.temperature", tenant_id="t1") == 0.9

    config.delete("agent.temperature", tenant_id="t1")
    assert config.get("agent.temperature", tenant_id="t1") == 0.7  # global default


def test_list_config(config):
    """Should list all config entries."""
    entries = config.list_config()
    assert len(entries) > 0
    assert any(e["key"] == "agent.temperature" for e in entries)


def test_get_all(config):
    """Should return all global values as a dict."""
    all_config = config.get_all()
    assert "rate_limit.free.requests_per_minute" in all_config
    assert "agent.temperature" in all_config


def test_custom_config_key(config):
    """Should support arbitrary custom keys."""
    config.set("custom.my_feature.enabled", True, value_type="bool")
    assert config.get("custom.my_feature.enabled") is True
