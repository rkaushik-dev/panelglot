"""The operations the CLI exposes, with no CLI in them.

Each function here takes a :class:`~v4t_translate.config.ProjectConfig` and
returns a result object. None of them print anything, none of them exit, and
none of them know what a terminal is. That is what makes them testable and
what stops the command layer from growing logic.
"""
