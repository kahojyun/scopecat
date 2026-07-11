"""Private config-bound execution package.

Execution types and entrypoints are imported from their defining modules.  The
package deliberately has no eager facade so persistence and engine modules can
depend on each other through narrow leaf boundaries without import cycles.
"""

__all__: list[str] = []
