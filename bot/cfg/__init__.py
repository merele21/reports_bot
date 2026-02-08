"""
Конфигурация бота
"""
from .commands_config import (
    COMMANDS_CONFIG,
    get_command_config,
    format_command_help,
    get_command_input_prompt
)

__all__ = [
    "COMMANDS_CONFIG",
    "get_command_config",
    "format_command_help",
    "get_command_input_prompt"
]