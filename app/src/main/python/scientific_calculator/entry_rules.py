"""Pure rules for structured calculator entry and recall.

Repairing a pasted integral body, bounding a table's row range, and rebuilding
template fields from a stored history record are all decisions about the
calculator's input, not about how the LCD draws it. Keeping them here lets
their edge cases be exercised without an application instance.
"""

from __future__ import annotations

import math

from .errors import CalculatorError


def repair_integral_body(text):
    """Remove only trailing unmatched ``)`` copied from the integral shell."""
    original=str(text).strip()

    def balanced(candidate):
        depth=0
        for character in candidate:
            if character=="(": depth+=1
            elif character==")":
                depth-=1
                if depth<0: return False
        return depth==0

    if balanced(original):
        return original
    repaired=original
    while repaired.endswith(")"):
        repaired=repaired[:-1].rstrip()
        if balanced(repaired):
            return repaired
    return original

def table_row_count(start, end, step, two_functions=False):
    try:
        start=float(start); end=float(end); step=float(step)
    except (TypeError, ValueError) as exc:
        raise CalculatorError("Range ERROR") from exc
    if not all(math.isfinite(v) for v in (start,end,step)) or step==0:
        raise CalculatorError("Range ERROR")
    span=(end-start)/step
    if not math.isfinite(span):
        raise CalculatorError("Range ERROR")
    if span<0:
        raise CalculatorError("Range ERROR: adım yönü başlangıç/bitiş ile uyuşmuyor")
    count=int(math.floor(span+1e-12))+1
    limit=30 if two_functions else 45
    if count<1 or count>limit:
        raise CalculatorError("Range ERROR")
    return count

def history_integral_preview(entry):
    """Return the renderer state for a structured integral history item."""
    metadata=entry.metadata
    if entry.kind in {"integral_single","integral_indefinite"}:
        bounds=metadata.get("bounds")
        bound=bounds[0] if isinstance(bounds,tuple) and bounds and isinstance(bounds[0],dict) else {}
        variable=(metadata.get("variables") or ["x"])[0]
        return "integral",{
            "body":str(metadata.get("integrand","")),
            "lower":str(bound.get("lower","")),
            "upper":str(bound.get("upper","")),
            "var":str(variable),
        },["body","lower","upper","var"]
    if entry.kind in {"integral_double","integral_triple"}:
        order="double" if entry.kind=="integral_double" else "triple"
        names=["outer","inner"] if order=="double" else ["outer","middle","inner"]
        fields={"body":str(metadata.get("integrand","")),"order":order}
        bounds=metadata.get("bounds")
        for name,bound in zip(names,bounds if isinstance(bounds,tuple) else (),strict=False):
            if isinstance(bound,dict):
                fields[f"{name}_var"]=str(bound.get("variable",""))
                fields[f"{name}_lower"]=str(bound.get("lower",""))
                fields[f"{name}_upper"]=str(bound.get("upper",""))
        for name in names:
            fields.setdefault(f"{name}_var","")
            fields.setdefault(f"{name}_lower","")
            fields.setdefault(f"{name}_upper","")
        return "multiple_integral",fields,["body"]
    if entry.kind=="complex_calculus" and metadata.get("operation")=="double_integral":
        bounds=metadata.get("bounds")
        fields={"body":str(metadata.get("integrand","")),"order":"double"}
        for name,bound in zip(["outer","inner"],bounds if isinstance(bounds,tuple) else (),strict=False):
            if isinstance(bound,dict):
                fields[f"{name}_var"]=str(bound.get("variable",""))
                fields[f"{name}_lower"]=str(bound.get("lower",""))
                fields[f"{name}_upper"]=str(bound.get("upper",""))
        for name in ("outer","inner"):
            fields.setdefault(f"{name}_var","")
            fields.setdefault(f"{name}_lower","")
            fields.setdefault(f"{name}_upper","")
        return "multiple_integral",fields,["body"]
    return None

__all__ = ["history_integral_preview", "repair_integral_body", "table_row_count"]
