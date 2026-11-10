"""Sample actual Bezier geometry once for matching trim, tip and wipe positions."""
import bisect
import math
from .animation import clamp, item_ease, item_ease_js
from .geometry import _bezier_point
from .animation import item_window, ramp


def risen_geometry(path, spec, baseline, progress):
    from .geometry import PathGeometry
    weights = [item_ease(ramp(progress, *item_window(i, path.n, spec.comp)), spec.comp)
               for i in range(path.n)]
    pts = [(x, baseline+(y-baseline)*w) for (x,y),w in zip(path.points,weights)]
    ins = [(x,y*w) for (x,y),w in zip(path.in_tangents,weights)]
    outs = [(x,y*w) for (x,y),w in zip(path.out_tangents,weights)]
    return PathGeometry(pts,ins,outs,path.arc,path.closed)


def rise_js(points, ins, outs, spec, baseline, ranks=None, count=None, closed=False):
    from .geometry import fmt_list, fmt_pairs
    count = count or len(points)
    ranks = ranks or list(range(len(points)))
    windows = [item_window(i,count,spec.comp) for i in ranks]
    return [item_ease_js(spec.comp),
            "var pts="+fmt_pairs(points)+", it="+fmt_pairs(ins)+", ot="+fmt_pairs(outs)+";",
            "var at="+fmt_list([w[0] for w in windows])+", span="+fmt_list([w[1] for w in windows])+";",
            "for(var k=0;k<pts.length;k++){var w=animEase((progress-at[k])/Math.max(0.001,span[k]));",
            "pts[k][1]=%r+(pts[k][1]-%r)*w; it[k][1]*=w; ot[k][1]*=w;}" % (baseline,baseline),
            "createPath(pts,it,ot,%s);" % ("true" if closed else "false")]


def samples(path):
    cached = getattr(path, "_motion_samples", None)
    if cached is not None:
        return cached
    pts, times, distances = [path.points[0]], [0.0], [0.0]
    for i in range(path.n-1):
        p, q = path.points[i:i+2]
        c1 = (p[0]+path.out_tangents[i][0], p[1]+path.out_tangents[i][1])
        c2 = (q[0]+path.in_tangents[i+1][0], q[1]+path.in_tangents[i+1][1])
        curved = path.out_tangents[i] != (0, 0) or path.in_tangents[i+1] != (0, 0)
        steps = 32 if curved else 1
        for k in range(1, steps+1):
            t = k/steps
            # Straight Bezier segments have zero handles; their spatial parameter
            # is smoothstep(t). Interpolate them geometrically instead.
            xy = _bezier_point(p, c1, c2, q, t) if curved else q
            prev = pts[-1]
            distances.append(distances[-1]+math.hypot(xy[0]-prev[0], xy[1]-prev[1]))
            pts.append(xy)
            times.append((i+t)/(path.n-1))
    total = distances[-1] or 1
    arcs = [d/total for d in distances]
    path._motion_samples = times, arcs, pts
    return path._motion_samples


def state(path, progress, spec):
    times, arcs, pts = samples(path)
    u = clamp(progress/100)
    mode = spec.comp.animation_mode
    if mode == "uniform_path":
        keys = arcs
    elif mode == "uniform_x":
        keys = [p[0] for p in pts]
        if any(b < a for a, b in zip(keys, keys[1:])):
            keys = arcs  # Connected scatter may loop; use distance instead.
        else:
            c = spec.comp
            u = c.plot_left + u*(c.plot_right-c.plot_left)
    else:
        keys = arcs
        idx = u*(path.n-1)
        i = min(path.n-2, int(idx))
        f = item_ease(idx-i, spec.comp, "linear")
        u = path.arc[i]+(path.arc[i+1]-path.arc[i])*f
    j = max(0, min(len(keys)-2, bisect.bisect_right(keys, u)-1))
    f = clamp((u-keys[j])/max(1e-12, keys[j+1]-keys[j]))
    return (100*(arcs[j]+(arcs[j+1]-arcs[j])*f),
            pts[j][0]+(pts[j+1][0]-pts[j][0])*f,
            pts[j][1]+(pts[j+1][1]-pts[j][1])*f)


def state_js(path, spec):
    from .geometry import fmt_list, fmt_pairs
    times, arcs, pts = samples(path)
    mode = spec.comp.animation_mode
    keys, convert = times, ""
    if mode == "uniform_path":
        keys = arcs
    elif mode == "uniform_x":
        keys = [p[0] for p in pts]
        if any(b < a for a, b in zip(keys, keys[1:])):
            keys = arcs
        else:
            c = spec.comp
            convert = "u=%r+u*%r;" % (c.plot_left, c.plot_right-c.plot_left)
    else:
        keys = arcs
        convert = "var va="+fmt_list(path.arc,lambda x:round(x,8))+";"
        convert += "var ix=u*%d, k=Math.min(%d,Math.floor(ix)); u=va[k]+(va[k+1]-va[k])*animEase(ix-k);" % (path.n-1, path.n-2)
    return [item_ease_js(spec.comp, "linear"),
            "var u=Math.max(0,Math.min(1,progress/100));", convert,
            "var keys="+fmt_list(keys, lambda x: round(x, 8))+";",
            "var arcs="+fmt_list(arcs, lambda x: round(x, 8))+";",
            "var pts="+fmt_pairs(pts)+";",
            "var lo=0, hi=keys.length-1; while(hi-lo>1){var mid=Math.floor((lo+hi)/2); if(keys[mid]<=u)lo=mid; else hi=mid;}",
            "var f=Math.max(0,Math.min(1,(u-keys[lo])/Math.max(1e-12,keys[hi]-keys[lo])));",
            "var motion=[100*(arcs[lo]+(arcs[hi]-arcs[lo])*f),pts[lo][0]+(pts[hi][0]-pts[lo][0])*f,pts[lo][1]+(pts[hi][1]-pts[lo][1])*f];"]
