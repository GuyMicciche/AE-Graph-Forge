"""Distribution and matrix charts, resolved once for preview and AE export."""
import math
from dataclasses import dataclass
from . import scales as sc
from .animation import item_ease, item_ease_js, item_window, ramp
from .dataset import NUMERIC
from .spec import HISTOGRAM, BOX_PLOT, HEATMAP, palette_color
from .transform import aggregate_groups


@dataclass
class Mark:
    x: float
    y: float
    width: float
    height: float
    color: tuple
    rank: int
    base: float
    kind: str = "rect"  # rect | outline | dot
    text: str = ""
    reveal_at: float = 0
    reveal_span: float = 100


def _values(ds, s):
    name = s.value_column or (s.series[0].column if s.series else "")
    col = ds.col(name)
    if col is None or col.kind != NUMERIC:
        raise ValueError("Choose a numeric Value column for this chart.")
    return name, col


def build_distribution(ds, s, m):
    if s.chart_type == HISTOGRAM:
        return _histogram(ds,s,m)
    if s.chart_type == BOX_PLOT:
        return _boxes(ds,s,m)
    return _heatmap(ds,s,m)


def _histogram(ds,s,m):
    from .build import BarModel, _ticks_for, _reveal_span, _bar_reveal_at
    name,col = _values(ds,s)
    values = [v for v in col.numeric if v is not None and math.isfinite(v)]
    if not values:
        raise ValueError("No finite numeric values for the histogram.")
    if s.x_axis.scale != "linear" or s.y_axis.scale != "linear":
        raise ValueError("Histogram axes must be linear (bins have equal data width).")
    if not 0 <= s.histogram_bins <= 200:
        raise ValueError("Histogram bins must be 0 (auto) through 200.")
    n = int(s.histogram_bins) or min(100,max(1,math.ceil(math.sqrt(len(values)))))
    low,high = min(values),max(values)
    if low == high:
        pad = abs(low)*0.05 or 0.5
        low,high = low-pad,high+pad
    width = (high-low)/n
    edges = [low+i*width for i in range(n+1)]
    edges[-1] = high
    counts = [0]*n
    for v in values:
        counts[min(n-1,max(0,int((v-low)/width)))] += 1
    normalization = s.histogram_normalization
    if normalization not in ("count","probability","density"):
        raise ValueError("Unknown histogram normalization.")
    divisor = 1 if normalization == "count" else len(values)*(width if normalization == "density" else 1)
    heights = [count/divisor for count in counts]
    c = s.comp
    xlo,xhi,xstep = sc.resolve_range(s.x_axis,low,high,zero_base=False,pad=0)
    ylo,yhi,ystep = sc.resolve_range(s.y_axis,0,max(heights) or 1,zero_base=True,pad=0)
    m.x_scale = sc.make_scale(s.x_axis,c.plot_left,c.plot_right,xlo,xhi)
    m.y_scale = sc.make_scale(s.y_axis,c.plot_bottom,c.plot_top,ylo,yhi)
    color = s.histogram_color
    base = m.y_scale.px(0)
    for i,height in enumerate(heights):
        a,b = m.x_scale.px(edges[i]),m.x_scale.px(edges[i+1])
        top = m.y_scale.px(height)
        m.bars.append(BarModel(f"{edges[i]:g}–{edges[i+1]:g}",height,(a+b)/2,min(top,base),
                               (b-a)*0.96,abs(top-base),color,_bar_reveal_at(i,n,s),base,
                               _reveal_span(n,s),sc.format_value(height,0 if normalization=="count" else 3,True)))
    skipped = ds.n_rows-len(values)
    if skipped:
        m.warnings.append(f"Skipped {skipped} missing/nonfinite histogram values.")
    m.histogram_edges = edges
    m.n_points = n
    m.x_ticks = _ticks_for(s.x_axis,m.x_scale,False,xstep)
    m.y_ticks = _ticks_for(s.y_axis,m.y_scale,False,ystep)
    return m


def quantile(values,p):
    """Linear interpolation at (n-1)*p, also defined for a single observation."""
    k = (len(values)-1)*p
    i = int(k)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(k-i)


def _boxes(ds,s,m):
    from .build import TickModel, LegendEntry, _ticks_for
    name,col = _values(ds,s)
    group = ds.col(s.group_column) if s.group_column else None
    if s.group_column and group is None:
        raise ValueError("Box plot group column does not exist.")
    groups = {}
    for i,v in enumerate(col.numeric):
        if v is not None and math.isfinite(v):
            label = group.display_at(i) if group else name
            groups.setdefault(label,[]).append(v)
    if not groups:
        raise ValueError("No finite numeric observations for the box plot.")
    skipped = ds.n_rows-sum(len(values) for values in groups.values())
    if skipped:
        m.warnings.append(f"Skipped {skipped} missing/nonfinite box-plot values.")
    rows = []
    for label,values in groups.items():
        values.sort()
        q1,median,q3 = (quantile(values,p) for p in (0.25,0.5,0.75))
        iqr = q3-q1
        inside = [v for v in values if q1-1.5*iqr <= v <= q3+1.5*iqr]
        lower,upper = min(inside),max(inside)
        rows.append(dict(label=label,q1=q1,median=median,q3=q3,low=lower,high=upper,
                         outliers=[v for v in values if v<lower or v>upper],count=len(values)))
    if s.slice_sort == "label":
        rows.sort(key=lambda r:r['label'].lower())
    elif s.slice_sort in ("value_asc","value_desc"):
        rows.sort(key=lambda r:r['median'],reverse=s.slice_sort=="value_desc")
    if s.max_bars > 0 and len(rows)>s.max_bars:
        m.warnings.append(f"Showing {s.max_bars} of {len(rows)} box-plot groups.")
        rows = rows[:s.max_bars]
    c = s.comp
    pool = [v for row in rows for v in ([row['low'],row['high']]+(row['outliers'] if s.box_show_outliers else []))]
    if s.y_axis.scale == "log" and min(pool)<=0:
        raise ValueError("Logarithmic box plots require positive values.")
    lo,hi,step = sc.resolve_range(s.y_axis,min(pool),max(pool),zero_base=False,pad=0.05)
    m.y_scale = sc.make_scale(s.y_axis,c.plot_bottom,c.plot_top,lo,hi)
    m.x_scale = sc.Scale(0,len(rows),c.plot_left,c.plot_right)
    slot = (c.plot_right-c.plot_left)/len(rows)
    width = slot*0.5
    remaining = max(0,s.style.max_dot_layers)
    unlimited = remaining == 0
    skipped = 0
    for rank,row in enumerate(rows):
        x = c.plot_left+(rank+0.5)*slot
        color = s.category.colors.get(row['label'],palette_color(rank+1))
        ys = {key:m.y_scale.px(row[key]) for key in ('low','high','q1','q3','median')}
        base = ys['median']
        def mark(y,w,h,kind='rect'):
            m.marks.append(Mark(x,y,w,max(1,h),color,rank,base,kind))
        mark((ys['low']+ys['q1'])/2,2,abs(ys['low']-ys['q1']))
        mark((ys['q3']+ys['high'])/2,2,abs(ys['q3']-ys['high']))
        for y in (ys['low'],ys['high']):
            mark(y,width*0.6,2)
        mark((ys['q1']+ys['q3'])/2,width,abs(ys['q1']-ys['q3']),'outline')
        mark(ys['median'],width,3)
        if s.box_show_outliers:
            for v in row['outliers']:
                if unlimited or remaining>0:
                    mark(m.y_scale.px(v),7,7,'dot')
                    remaining -= 1
                else:
                    skipped += 1
        m.x_ticks.append(TickModel(rank,x,row['label']))
    if skipped:
        m.warnings.append(f"Omitted {skipped} outlier dots to respect Max dot layers; statistics are unchanged.")
    m.y_ticks = _ticks_for(s.y_axis,m.y_scale,False,step)
    m.boxes = rows
    m.n_points = len(rows)
    return m


def _heatmap(ds,s,m):
    from .build import TickModel, LegendEntry
    xcol,ycol = ds.col(s.heatmap_x),ds.col(s.heatmap_y)
    if xcol is None or ycol is None:
        raise ValueError("Choose Heatmap columns and Heatmap rows mappings.")
    col = None
    if s.aggregation != "count":
        _,col = _values(ds,s)
    groups,xnames,ynames = {},[],[]
    skipped = 0
    for i in range(ds.n_rows):
        x,y = xcol.display_at(i),ycol.display_at(i)
        v = 1.0 if col is None else col.numeric[i]
        if not x.strip() or not y.strip() or v is None or not math.isfinite(v):
            skipped += 1
            continue
        if x not in xnames:
            xnames.append(x)
        if y not in ynames:
            ynames.append(y)
        groups.setdefault((x,y),[]).append(v)
    if not groups:
        raise ValueError("No usable heatmap cells after filtering missing values.")
    if skipped:
        m.warnings.append(f"Skipped {skipped} heatmap rows with missing categories or values.")
    if len(xnames)*len(ynames)>1600:
        raise ValueError("Heatmap exceeds 1600 grid cells. Reduce the number of row/column categories.")
    cells = [(x,y,aggregate_groups(['cell']*len(vals),vals,s.aggregation)[0][1]) for (x,y),vals in groups.items()]
    low,high = min(v for _,_,v in cells),max(v for _,_,v in cells)
    c = s.comp
    w,h = (c.plot_right-c.plot_left)/len(xnames),(c.plot_bottom-c.plot_top)/len(ynames)
    m.x_scale = sc.Scale(0,len(xnames),c.plot_left,c.plot_right)
    m.y_scale = sc.Scale(0,len(ynames),c.plot_top,c.plot_bottom)
    for j,y in enumerate(ynames):
        for i,x in enumerate(xnames):
            if (x,y) not in groups:
                continue  # Missing combinations stay blank; zero is a valid colour.
            vals = groups[(x,y)]
            value = aggregate_groups(['cell']*len(vals),vals,s.aggregation)[0][1]
            u = (value-low)/(high-low) if high>low else 0.5
            color = tuple(a+(b-a)*u for a,b in zip(s.heatmap_low_color,s.heatmap_high_color))
            label = sc.format_value(value,s.y_axis.decimals if s.y_axis.decimals>=0 else 2,True)
            m.cells.append(dict(column=x,row=y,value=value,color=color))
            m.marks.append(Mark(c.plot_left+(i+0.5)*w,c.plot_top+(j+0.5)*h,
                                w*0.94,h*0.94,color,len(m.cells)-1,c.plot_bottom,
                                text=label if s.heatmap_show_values else ''))
    m.x_ticks = [TickModel(i,c.plot_left+(i+0.5)*w,x) for i,x in enumerate(xnames)]
    m.y_ticks = [TickModel(j,c.plot_top+(j+0.5)*h,y) for j,y in enumerate(ynames)]
    for u in ([0.5] if high==low else [0,0.25,0.5,0.75,1]):
        value = low+(high-low)*u
        color = tuple(a+(b-a)*u for a,b in zip(s.heatmap_low_color,s.heatmap_high_color))
        m.legend.append(LegendEntry(sc.format_value(value,2,True),color))
    m.n_points = len(m.cells)
    return m


def configure_marks(m):
    s,c = m.spec,m.spec.comp
    for mark in m.marks:
        if c.animation_mode == 'rise':
            mark.reveal_at,mark.reveal_span = item_window(mark.rank,m.n_points,c)
        elif c.animation_mode == 'uniform_x':
            width = (c.plot_right-c.plot_left)/max(1,m.n_points)*0.5 if s.chart_type==BOX_PLOT else mark.width
            mark.reveal_at = max(0,(mark.x-width/2-c.plot_left)/(c.plot_right-c.plot_left)*100)
            mark.reveal_span = max(0.001,width/(c.plot_right-c.plot_left)*100)
        else:
            mark.reveal_at = mark.rank/max(1,m.n_points)*100
            mark.reveal_span = 100/max(1,m.n_points)


def mark_state(mark,progress,s):
    u = ramp(progress,mark.reveal_at,mark.reveal_span)
    g = u if s.comp.animation_mode in ('uniform_x','uniform_path') else item_ease(u,s.comp)
    if s.chart_type == BOX_PLOT:
        base = s.comp.plot_bottom if s.comp.animation_mode=='rise' else mark.base
        return mark.x,base+(mark.y-base)*g,mark.width,max(1,mark.height*g),g
    y = s.comp.plot_bottom+(mark.y-s.comp.plot_bottom)*g if s.comp.animation_mode=='rise' else mark.y
    return mark.x,y,mark.width,mark.height,g


def mark_timing_js(mark,s):
    return [item_ease_js(s.comp),
            f'var u=Math.max(0,Math.min(1,(progress-{mark.reveal_at})/Math.max(0.001,{mark.reveal_span})));',
            'var g=u;' if s.comp.animation_mode in ('uniform_x','uniform_path') else 'var g=animEase(u);']
