# analysis.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import math

def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None

def _last_valid(arr: List[Any]) -> Optional[float]:
    for x in reversed(arr):
        v = _safe_float(x)
        if v is not None:
            return v
    return None

def _trend(arr: List[Any], n: int = 25) -> Optional[float]:
    """
    Simple slope proxy: last - first over last n valid points.
    """
    vals = []
    for x in arr:
        v = _safe_float(x)
        if v is not None:
            vals.append(v)
    if len(vals) < 2:
        return None
    vals = vals[-n:]
    if len(vals) < 2:
        return None
    return vals[-1] - vals[0]

def diagnose_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes the same dict you already jsonify() in /data/<interval>
    and returns a diagnostic block to append.

    Uses fields:
      - kw_ton
      - cooling_tons
      - flow_rate
      - diff_pressure
      - diff_temp
    """

    kw_ton = data.get("kw_ton", []) or []
    cooling = data.get("cooling_tons", []) or []
    flow = data.get("flow_rate", []) or []
    dp = data.get("diff_pressure", []) or []
    dt = data.get("diff_temp", []) or []

    kw_now = _last_valid(kw_ton)
    cool_now = _last_valid(cooling)
    flow_now = _last_valid(flow)
    dp_now = _last_valid(dp)
    dt_now = _last_valid(dt)

    kw_tr = _trend(kw_ton)
    cool_tr = _trend(cooling)
    flow_tr = _trend(flow)

    flags: List[Dict[str, str]] = []
    severity = "OK"

    
    if kw_now is not None and kw_now < 0:
        flags.append({"code": "KW_TON_NEG", "level": "WARN", "msg": "kw/ton is negative (likely bad power or tons calc)."})
    if flow_now is not None and flow_now < 0:
        flags.append({"code": "FLOW_NEG", "level": "WARN", "msg": "Flow rate is negative (sensor/calibration issue)."})
    if dt_now is not None and dt_now < 0:
        flags.append({"code": "DT_NEG", "level": "WARN", "msg": "ΔT is negative (temp sensors may be swapped)."})
    if dp_now is not None and dp_now < 0:
        flags.append({"code": "DP_NEG", "level": "WARN", "msg": "ΔP is negative (pressure sensors may be swapped)."})
    # Many systems expect MA/SA/coil ΔT and ΔP to be within reasonable bounds; we avoid hard physics claims and use gentle flags:
    if dt_now is not None and dt_now > 40:
        flags.append({"code": "DT_HIGH", "level": "WARN", "msg": "ΔT is unusually high; check temp probe placement/calibration."})
    if dp_now is not None and dp_now > 10_000:
        flags.append({"code": "DP_HIGH", "level": "WARN", "msg": "ΔP is unusually high; check pressure tubing or scaling."})


    # These thresholds are adjustable; for demo we keep them conservative.
    if kw_now is not None:
        if kw_now > 2.0:
            flags.append({"code": "EFF_POOR", "level": "WARN", "msg": "High kw/ton → poor efficiency condition."})
            severity = "WARN"
        elif kw_now < 0.6:
            flags.append({"code": "EFF_SUSPICIOUS_GOOD", "level": "INFO", "msg": "Very low kw/ton; verify sensors/calculations."})

    # Cooling present but no flow, or vice versa
    if cool_now is not None and flow_now is not None:
        if cool_now > 1.0 and flow_now < 0.1:
            flags.append({"code": "COOL_WITH_NO_FLOW", "level": "WARN", "msg": "Cooling tons reported but flow rate near zero."})
            severity = "WARN"
        if flow_now > 0.5 and cool_now < 0.1:
            flags.append({"code": "FLOW_WITH_NO_COOL", "level": "INFO", "msg": "Flow present but little cooling; could be unloaded / mild load."})

    # Trend flags
    if kw_tr is not None and kw_tr > 0.5:
        flags.append({"code": "KW_TON_RISING", "level": "INFO", "msg": "kw/ton rising over recent window (efficiency degrading)."})
    if cool_tr is not None and cool_tr < -0.5:
        flags.append({"code": "COOLING_FALLING", "level": "INFO", "msg": "Cooling tons dropping over recent window."})

    # ---- Simple “state” label ----
    state = "Unknown"
    if cool_now is None or flow_now is None or kw_now is None:
        state = "Insufficient data"
        severity = "WARN" if severity == "OK" else severity
    else:
        if cool_now < 0.1:
            state = "Low/No cooling"
        elif kw_now <= 1.3:
            state = "Cooling active (normal-ish efficiency)"
        else:
            state = "Cooling active (high energy/ton)"

    # If we have multiple WARN flags, bump severity
    warn_ct = sum(1 for f in flags if f["level"] == "WARN")
    if warn_ct >= 2:
        severity = "WARN"
    if warn_ct >= 4:
        severity = "ALERT"

    # One-line summary
    summary_parts = []
    if kw_now is not None:
        summary_parts.append(f"kw/ton={kw_now:.2f}")
    if cool_now is not None:
        summary_parts.append(f"tons={cool_now:.2f}")
    if flow_now is not None:
        summary_parts.append(f"flow={flow_now:.2f}")
    summary = ", ".join(summary_parts) if summary_parts else "No current values"

    return {
        "diagnostics": {
            "severity": severity,
            "state": state,
            "summary": summary,
            "flags": flags[:8],  
        }
    }
