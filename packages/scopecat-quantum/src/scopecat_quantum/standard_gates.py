"""Small opt-in catalog of conventional hardware-independent gate semantics."""

from scopecat_quantum.authoring import single_qubit_gate, two_qubit_gate

X = single_qubit_gate("x")
X90 = single_qubit_gate("x90")
XM90 = single_qubit_gate("xm90")
Y90 = single_qubit_gate("y90")
YM90 = single_qubit_gate("ym90")
CZ = two_qubit_gate("cz")

__all__ = ["CZ", "X90", "XM90", "Y90", "YM90", "X"]
