"""
Plugin Loader System for ANSE

Automatically discovers and registers custom sensors and tools from:
- YAML plugin definitions (plugins/*.yaml)
- Python plugin classes (plugins/*.py)

This enables non-programmers to extend ANSE by dropping config files
in the plugins/ directory without modifying the core codebase.
"""

import asyncio
import importlib.util
import inspect
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import yaml

logger = logging.getLogger(__name__)


class PluginValidationError(Exception):
    """Raised when a plugin fails validation checks."""
    pass


class PluginValidator:
    """Validates plugin configurations and handlers."""
    
    @staticmethod
    def validate_yaml(plugin_config: Dict[str, Any]) -> bool:
        """Validate YAML plugin configuration.
        
        Args:
            plugin_config: Parsed YAML plugin dictionary
            
        Returns:
            True if valid, raises PluginValidationError otherwise
        """
        required_fields = ['name', 'description', 'tools']
        
        for field in required_fields:
            if field not in plugin_config:
                raise PluginValidationError(
                    f"Plugin missing required field: {field}"
                )
        
        # Validate name format
        if not re.match(r'^[a-z0-9_-]+$', plugin_config['name']):
            raise PluginValidationError(
                f"Plugin name must be lowercase alphanumeric + underscore/dash: "
                f"{plugin_config['name']}"
            )
        
        # Validate tools list
        if not isinstance(plugin_config['tools'], list):
            raise PluginValidationError("'tools' must be a list")
        
        if not plugin_config['tools']:
            raise PluginValidationError("Plugin must define at least one tool")
        
        # Validate each tool
        for i, tool in enumerate(plugin_config['tools']):
            if 'name' not in tool:
                raise PluginValidationError(
                    f"Tool {i} missing required field: 'name'"
                )
            
            if 'description' not in tool:
                raise PluginValidationError(
                    f"Tool {tool['name']} missing required field: 'description'"
                )
            
            # Handler can be inline Python code or an external reference
            if 'handler' not in tool:
                # If no handler, should define returns (static tool)
                if 'returns' not in tool:
                    raise PluginValidationError(
                        f"Tool {tool['name']} must have 'handler' or 'returns'"
                    )
        
        return True
    
    @staticmethod
    def validate_python(plugin_class) -> bool:
        """Validate Python plugin class structure.
        
        Args:
            plugin_class: Plugin class to validate
            
        Returns:
            True if valid, raises PluginValidationError otherwise
        """
        required_attrs = ['name', 'description']
        
        for attr in required_attrs:
            if not hasattr(plugin_class, attr):
                raise PluginValidationError(
                    f"Plugin {plugin_class.__name__} missing required "
                    f"attribute: {attr}"
                )
        
        # Verify it has at least one tool method (async method)
        tool_methods = [
            name for name, method in inspect.getmembers(plugin_class)
            if (inspect.iscoroutinefunction(method) or 
                callable(method)) and not name.startswith('_')
        ]
        
        if not tool_methods:
            raise PluginValidationError(
                f"Plugin {plugin_class.__name__} has no public methods to expose"
            )
        
        return True


class PluginLoader:
    """Loads and manages ANSE plugins from YAML and Python files."""
    
    def __init__(self, plugin_dir: str = "plugins"):
        """Initialize plugin loader.
        
        Args:
            plugin_dir: Directory containing plugin files
        """
        self.plugin_dir = Path(plugin_dir)
        self.plugins: Dict[str, Dict[str, Any]] = {}
        self.plugin_instances: Dict[str, Any] = {}
        self.validator = PluginValidator()
        
    def load_all(self) -> Dict[str, Any]:
        """Load all plugins from the plugin directory.
        
        Returns:
            Dictionary of loaded plugins {name: plugin_config}
        """
        if not self.plugin_dir.exists():
            logger.warning(f"Plugin directory not found: {self.plugin_dir}")
            return {}
        
        # Load YAML plugins
        self._load_yaml_plugins()
        
        # Load Python plugins
        self._load_python_plugins()
        
        logger.info(f"Loaded {len(self.plugins)} plugin(s)")
        return self.plugins
    
    def _load_yaml_plugins(self) -> None:
        """Load all YAML plugin definitions."""
        # rglob, not glob: plugins live under category subdirectories
        # (plugins/sensors/, plugins/actuators/, plugins/cognition/,
        # plugins/system/), not flat in plugins/ itself.
        for yaml_file in self.plugin_dir.rglob("*.yaml"):
            # Skip template files
            if yaml_file.name.startswith("_"):
                logger.debug(f"Skipping template: {yaml_file.name}")
                continue
            
            try:
                with open(yaml_file, 'r') as f:
                    plugin_config = yaml.safe_load(f)
                
                if not plugin_config:
                    logger.warning(f"Empty YAML file: {yaml_file}")
                    continue
                
                # Validate
                self.validator.validate_yaml(plugin_config)
                
                # Store
                self.plugins[plugin_config['name']] = {
                    'type': 'yaml',
                    'config': plugin_config,
                    'source': str(yaml_file)
                }
                
                logger.info(f"Loaded YAML plugin: {plugin_config['name']}")
                
            except PluginValidationError as e:
                logger.error(f"Validation error in {yaml_file.name}: {e}")
            except Exception as e:
                logger.error(f"Error loading YAML plugin {yaml_file.name}: {e}")
    
    def _load_python_plugins(self) -> None:
        """Load all Python plugin classes."""
        for py_file in self.plugin_dir.rglob("*.py"):
            # Skip __init__ and template files
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                logger.debug(f"Skipping template: {py_file.name}")
                continue
            
            try:
                # Import the module
                module_name = py_file.stem
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                
                if not spec or not spec.loader:
                    logger.warning(f"Could not load module spec: {py_file.name}")
                    continue
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find plugin classes (look for classes with 'name' attribute)
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and hasattr(obj, 'name'):
                        # Skip imported classes
                        if obj.__module__ != module.__name__:
                            continue
                        
                        try:
                            self.validator.validate_python(obj)
                            
                            # Instantiate the plugin
                            instance = obj()
                            self.plugin_instances[obj.name] = instance
                            
                            self.plugins[obj.name] = {
                                'type': 'python',
                                'instance': instance,
                                'class': obj,
                                'source': str(py_file)
                            }
                            
                            logger.info(f"Loaded Python plugin: {obj.name}")
                            
                        except PluginValidationError as e:
                            logger.error(f"Validation error in {py_file.name}: {e}")
                        except Exception as e:
                            logger.error(
                                f"Error instantiating {name} from {py_file.name}: {e}"
                            )
                
            except Exception as e:
                logger.error(f"Error loading Python plugin {py_file.name}: {e}")
    
    def register_with_engine(self, engine_core) -> None:
        """Register all loaded plugins with the ANSE engine.
        
        Args:
            engine_core: EngineCore instance to register tools with
        """
        for plugin_name, plugin_info in self.plugins.items():
            try:
                if plugin_info['type'] == 'yaml':
                    self._register_yaml_plugin(engine_core, plugin_info)
                elif plugin_info['type'] == 'python':
                    self._register_python_plugin(engine_core, plugin_info)
                    
            except Exception as e:
                logger.error(f"Error registering plugin {plugin_name}: {e}")
    
    def _register_yaml_plugin(self, engine_core, plugin_info: Dict) -> None:
        """Register a YAML-based plugin."""
        config = plugin_info['config']
        plugin_name = config['name']
        
        # Get sensitivity and rate_limit if specified
        sensitivity = config.get('sensitivity', 'low')
        rate_limit = config.get('rate_limit', 60)
        
        # Register each tool in the plugin
        for tool_config in config['tools']:
            tool_name = tool_config['name']
            description = tool_config['description']
            parameters = tool_config.get('parameters', {})
            
            # Create handler function
            if 'handler' in tool_config:
                # Handler is embedded Python code
                handler_code = tool_config['handler']

                # make_tool_func only builds and returns a closure — it never
                # needs to be async itself. It used to be defined as `async
                # def` and invoked via asyncio.run(), which raised
                # "asyncio.run() cannot be called from a running event loop"
                # any time plugin loading happened inside async code (i.e.
                # always, in real use — EngineCore is constructed from an
                # async context), silently breaking every YAML tool.
                def make_tool_func(code: str, parms: Dict):
                    async def tool_func(**kwargs):
                        # Create execution context
                        context = {'kwargs': kwargs, 'result': None}

                        # Execute the handler code in the context
                        try:
                            exec(code, context)
                            return context.get('result', kwargs)
                        except Exception as e:
                            logger.error(f"Error executing handler: {e}")
                            return {'error': str(e)}

                    return tool_func

                tool_func = make_tool_func(handler_code, parameters)

            else:
                # Static tool (returns predefined values)
                static_returns = tool_config.get('returns', {})

                def make_static_tool(returns_dict: Dict):
                    async def static_tool(**kwargs):
                        return returns_dict
                    return static_tool

                tool_func = make_static_tool(static_returns)
            
            # Build schema from parameters
            schema = self._build_parameter_schema(parameters)
            
            # Register with engine
            engine_core.register_tool(
                name=f"{plugin_name}_{tool_name}",
                func=tool_func,
                description=description,
                parameters=schema,
                sensitivity=sensitivity,
                cost_hint={'latency_ms': 100}
            )
            
            logger.debug(f"Registered YAML tool: {plugin_name}_{tool_name}")
    
    def _register_python_plugin(self, engine_core, plugin_info: Dict) -> None:
        """Register a Python-based plugin."""
        instance = plugin_info['instance']
        plugin_name = instance.name
        
        # Get sensitivity and rate_limit if specified
        sensitivity = getattr(instance, 'sensitivity', 'low')
        rate_limit = getattr(instance, 'rate_limit', 60)
        
        # Find all public async methods to expose as tools
        for method_name, method in inspect.getmembers(instance):
            if method_name.startswith('_'):
                continue
            
            if inspect.iscoroutinefunction(method):
                # Get method signature for parameters. sig.parameters is a
                # name -> Parameter mapping; iterating it directly yields the
                # string keys, not Parameter objects, so `param.default`
                # below used to raise "'str' object has no attribute
                # 'default'" for every single Python-plugin method — meaning
                # no Python plugin tool had ever actually been registered.
                sig = inspect.signature(method)
                parameters = {
                    param.name: {
                        'type': 'string',  # Default type
                        'required': param.default == inspect.Parameter.empty
                    }
                    for param in sig.parameters.values()
                    if param.name != 'self'
                }
                
                # Build description from docstring
                description = (
                    inspect.getdoc(method) or 
                    f"{method_name} from {plugin_name} plugin"
                )
                
                # Register with engine
                engine_core.register_tool(
                    name=f"{plugin_name}_{method_name}",
                    func=method,
                    description=description,
                    parameters=parameters,
                    sensitivity=sensitivity,
                    cost_hint={'latency_ms': 100}
                )
                
                logger.debug(f"Registered Python tool: {plugin_name}_{method_name}")
    
    @staticmethod
    def _build_parameter_schema(parameters: Dict) -> Dict:
        """Build a parameter schema for tool registration.
        
        Args:
            parameters: Parameter definitions from plugin config
            
        Returns:
            Schema dictionary
        """
        schema = {}
        
        for param_name, param_def in parameters.items():
            if isinstance(param_def, dict):
                schema[param_name] = param_def
            else:
                # Simple type definition
                schema[param_name] = {
                    'type': param_def,
                    'required': True
                }
        
        return schema
    
    def get_plugins(self) -> Dict[str, Dict]:
        """Get all loaded plugins.
        
        Returns:
            Dictionary of plugins with their metadata
        """
        return {
            name: {
                'type': info['type'],
                'source': info['source'],
                'name': name
            }
            for name, info in self.plugins.items()
        }
    
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict]:
        """Get information about a specific plugin.
        
        Args:
            plugin_name: Name of the plugin
            
        Returns:
            Plugin info dict or None if not found
        """
        if plugin_name not in self.plugins:
            return None
        
        info = self.plugins[plugin_name]
        result = {
            'name': plugin_name,
            'type': info['type'],
            'source': info['source']
        }
        
        if info['type'] == 'yaml':
            config = info['config']
            result['description'] = config.get('description', '')
            result['tool_count'] = len(config.get('tools', []))
            result['tools'] = [t['name'] for t in config.get('tools', [])]
        else:
            instance = info['instance']
            result['description'] = getattr(instance, 'description', '')
            result['tools'] = [
                name for name, method in inspect.getmembers(instance)
                if inspect.iscoroutinefunction(method) and not name.startswith('_')
            ]
            result['tool_count'] = len(result['tools'])
        
        return result
