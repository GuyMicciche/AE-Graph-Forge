"""Shared timing for the preview and exported expressions (no Qt dependency)."""
import math

EASE_FAMILIES = [(k, label) for k, label in (
    ("bezier", "Bezier / keyframe influence"), ("linear", "Linear"),
    ("smoothstep", "Smoothstep"), ("sine", "Sine"), ("quad", "Quad"),
    ("cubic", "Cubic"), ("quart", "Quart"), ("quint", "Quint"), ("expo", "Expo"))]
ANIMATION_MODES = [("legacy", "Original / by data point"),
                   ("uniform_x", "Draw on / uniform across screen"),
                   ("uniform_path", "Draw on / uniform path speed"),
                   ("rise", "Rise / stagger items")]


def clamp(u):
    return max(0.0, min(1.0, u))


def ease(u, family="smoothstep", start=100.0, end=100.0):
    u = clamp(u)
    a, b = clamp(start / 100.0), clamp(end / 100.0)
    if family == "bezier":
        # Zero speed handles: influence controls their horizontal lengths.
        lo, hi = 0.0, 1.0
        for _ in range(40):
            t = (lo + hi) / 2
            x = 3*(1-t)**2*t*a + 3*(1-t)*t*t*(1-b) + t**3
            if x < u:
                lo = t
            else:
                hi = t
        t = (lo + hi) / 2
        return t*t*(3-2*t)
    if family == "linear":
        return u
    if family == "smoothstep":
        # Cubic Hermite with independent endpoint slopes.
        return u - a*(u**3-2*u*u+u) - b*(u**3-u*u)
    def incoming(t):
        if family == "sine":
            return 1-math.cos(t*math.pi/2)
        if family == "expo":
            return (2**(10*t)-1)/1023
        return t**{"quad": 2, "cubic": 3, "quart": 4, "quint": 5}.get(family, 2)
    if u < 0.5:
        return u*(1-a) + a*incoming(2*u)/2
    return u*(1-b) + b*(1-incoming(2-2*u)/2)


def overall_ease(u, comp):
    a = comp.ease_influence if comp.ease_start is None else comp.ease_start
    b = comp.ease_influence if comp.ease_end is None else comp.ease_end
    return ease(u, comp.ease_family, a, b)


def item_ease(u, comp, default="smoothstep"):
    family = default if comp.item_ease_family == "original" else comp.item_ease_family
    return ease(u, family, comp.item_ease_in, comp.item_ease_out)


def item_window(i, n, comp):
    """Normalized windows with delay in seconds, fitting the Progress interval."""
    duration = max(0.001, comp.progress_end - comp.progress_start)
    delay = min(max(0, comp.stagger_seconds)/duration, 0.95/max(1, n-1))
    rank = n-1-i if comp.reverse_stagger else i
    return 100*rank*delay, 100*(1-delay*max(0, n-1))


def ramp(progress, at, span):
    return clamp((progress-at)/max(0.001, span))


def ease_js(family, start, end, name="animEase"):
    """ES3-compatible counterpart to ease()."""
    return '''function %s(u) {
u = Math.max(0, Math.min(1, u));
var a=%s, b=%s, f=%r;
if (f === "bezier") {
 var lo=0, hi=1, t=0;
 for (var j=0; j<40; j++) {
  t=(lo+hi)/2;
  var x=3*(1-t)*(1-t)*t*a+3*(1-t)*t*t*(1-b)+t*t*t;
  if(x<u) lo=t; else hi=t;
 }
 t=(lo+hi)/2; return t*t*(3-2*t);
}
if(f === "linear") return u;
if(f === "smoothstep") return u-a*(u*u*u-2*u*u+u)-b*(u*u*u-u*u);
function incoming(t) {
 if(f === "sine") return 1-Math.cos(t*Math.PI/2);
 if(f === "expo") return (Math.pow(2,10*t)-1)/1023;
 var p=f === "quad" ? 2 : f === "cubic" ? 3 : f === "quart" ? 4 : f === "quint" ? 5 : 2;
 return Math.pow(t,p);
}
return u<0.5 ? u*(1-a)+a*incoming(2*u)/2 : u*(1-b)+b*(1-incoming(2-2*u)/2);
}''' % (name, clamp(start/100), clamp(end/100), family)


def item_ease_js(comp, default="smoothstep"):
    family = default if comp.item_ease_family == "original" else comp.item_ease_family
    return ease_js(family, comp.item_ease_in, comp.item_ease_out)
