"""Timing/geometry regressions and full JSX expression smoke matrix.

Run: python tools/check_animation.py (requires Node for the export checks).
"""
import json
from contextlib import nullcontext
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aegraphforge.core.animation import EASE_FAMILIES, ANIMATION_MODES, ease, ease_js, item_window
from aegraphforge.core.build import build_model
from aegraphforge.core.dataset import Dataset
from aegraphforge.core.geometry import build_path
from aegraphforge.core.jsxgen import generate_jsx
from aegraphforge.core.motion import state, state_js, risen_geometry
from aegraphforge.core.spec import ChartSpec, SeriesSpec, CHART_TYPES

DATA = "x,open,high,low,close,a,b,group\n0,10,15,8,12,5,3,A\n1,12,14,6,7,-2,8,B\n9,7,11,5,7,12,-4,C\n10,7,13,6,12,3,2,D\n"


def spec_for(kind):
    s = ChartSpec(chart_type=kind, x_column="x", group_column="group",
                  series=[SeriesSpec(column="a",show_dots=True,smooth=True),SeriesSpec(column="b",smooth=True)],
                  candle_open="open",candle_high="high",candle_low="low",candle_close="close",
                  value_column="a",heatmap_x="group",heatmap_y="group")
    return s


class AnimationChecks(unittest.TestCase):
    def test_curves_match_export_and_are_monotonic(self):
        cases = []
        for family,_ in EASE_FAMILIES:
            for start,end in ((0,0),(33,80),(100,0),(0,100),(100,100)):
                vals = [ease(i/100,family,start,end) for i in range(101)]
                self.assertAlmostEqual(vals[0],0,places=8)
                self.assertAlmostEqual(vals[-1],1,places=8)
                self.assertTrue(all(a<=b+1e-9 for a,b in zip(vals,vals[1:])),family)
                cases.append({"fn":ease_js(family,start,end),"expected":vals})
        program = '''const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
        for(const c of cases){const fn=new Function(c.fn+';return animEase;')();
          c.expected.forEach((v,i)=>{if(Math.abs(fn(i/100)-v)>1e-8)throw Error('curve mismatch');});}'''
        subprocess.run(["node","-e",program],input=json.dumps(cases),text=True,check=True)

    def test_horizontal_speed_and_distance_speed(self):
        s = ChartSpec()
        c = s.comp
        path = build_path([(c.plot_left,800),(c.plot_left+580,200),(c.plot_right,700)],True)
        for mode in ("uniform_x","uniform_path","legacy"):
            c.animation_mode = mode
            for pct in (0,10,25,50,75,99,100):
                result = state(path,pct,s)
                if mode == "uniform_x":
                    self.assertAlmostEqual(result[1],c.plot_left+(c.plot_right-c.plot_left)*pct/100,places=5)
                if mode == "uniform_path":
                    self.assertAlmostEqual(result[0],pct,places=5)
                program = '\n'.join([f'var progress={pct};']+state_js(path,s)+['console.log(JSON.stringify(motion));'])
                actual = json.loads(subprocess.check_output(["node","-e",program],text=True))
                for a,b in zip(result,actual):
                    self.assertAlmostEqual(a,b,delta=0.03)

    def test_zero_delay_and_reverse_rise(self):
        s = ChartSpec()
        s.comp.animation_mode = "rise"
        s.comp.stagger_seconds = 0
        path = build_path([(0,10),(20,50),(100,30)],True)
        self.assertEqual(risen_geometry(path,s,100,0).points,[(0,100),(20,100),(100,100)])
        self.assertEqual(risen_geometry(path,s,100,100).points,path.points)
        self.assertEqual(item_window(0,3,s.comp),(0,100))
        self.assertEqual(item_window(2,3,s.comp),(0,100))
        s.comp.stagger_seconds = .1
        s.comp.reverse_stagger = True
        self.assertGreater(item_window(0,3,s.comp)[0],item_window(2,3,s.comp)[0])

    def test_candles_validate_and_include_wicks_in_range(self):
        ds = Dataset.from_text(DATA)
        s = spec_for("candlestick")
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        self.assertEqual(len(m.candles),4)
        self.assertEqual(m.candles[0].color,s.candle_up_color)
        self.assertEqual(m.candles[1].color,s.candle_down_color)
        for candle in m.candles:
            self.assertLessEqual(candle.high_y,min(candle.open_y,candle.close_y))
            self.assertGreaterEqual(candle.low_y,max(candle.open_y,candle.close_y))
        bad = Dataset.from_text(DATA.replace('10,15,8,12','10,9,8,12'))
        m = build_model(bad,s)
        self.assertTrue(m.ok)
        self.assertEqual(len(m.candles),3)
        self.assertTrue(m.warnings)
        s.candle_open = "missing"
        self.assertFalse(build_model(ds,s).ok)

    def test_daily_candle_date_labels_are_distinct(self):
        ds = Dataset.from_text("Date,open,high,low,close\n2026-01-01,10,15,8,12\n2026-01-02,12,14,6,7\n2026-01-04,7,13,6,12\n")
        s = spec_for("candlestick")
        s.x_column = "Date"
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        self.assertGreater(len(set(t.label for t in m.x_ticks)),1)
        self.assertTrue(any("Jan" in t.label for t in m.x_ticks))
        self.assertEqual(len(set(t.label for t in m.x_ticks)),len(m.x_ticks))

    def test_pie_sweep_is_proportional_to_values(self):
        s = spec_for("donut")
        s.comp.animation_mode = "uniform_x"
        m = build_model(Dataset.from_text(DATA),s)
        for seg in m.segments:
            self.assertAlmostEqual(seg.reveal_span,seg.fraction*100)
        self.assertAlmostEqual(sum(seg.reveal_span for seg in m.segments),100)

    def test_validation_and_preset_compatibility(self):
        old = ChartSpec.from_dict({"comp":{"ease_influence":72}})
        self.assertIsNone(old.comp.ease_start)
        self.assertEqual(old.comp.ease_influence,72)
        s = spec_for("candlestick")
        s.comp.animation_mode = "rise"
        s.comp.ease_start = 12
        s.comp.ease_end = 95
        self.assertEqual(ChartSpec.from_json(s.to_json()).to_dict(),s.to_dict())
        s.comp.progress_end = s.comp.progress_start
        self.assertFalse(build_model(Dataset.from_text(DATA),s).ok)

    def test_stacked_bars_have_individual_baselines(self):
        m = build_model(Dataset.from_text(DATA),spec_for("stacked_bar"))
        self.assertTrue(m.ok,m.error)
        self.assertTrue(any(b.base != m.y_scale.px(0) for b in m.bars))
        for b in m.bars:
            self.assertGreaterEqual(b.y,m.spec.comp.plot_top-1e-8)
            self.assertLessEqual(b.y+b.height,m.spec.comp.plot_bottom+1e-8)
        js = generate_jsx(m)
        self.assertIn('BAR_BASE[b]',js)
        self.assertIn('g*sign',js)

    def test_every_chart_and_animation_exports(self):
        context = nullcontext(os.environ["AE_GRAPH_TEST_TMP"]) if os.environ.get("AE_GRAPH_TEST_TMP") else tempfile.TemporaryDirectory()
        with context as tmp:
            files = []
            for kind,_ in CHART_TYPES:
                for mode,_ in ANIMATION_MODES:
                    for bound in (True,False):
                        s = spec_for(kind)
                        s.comp.animation_mode = mode
                        s.comp.ease_family = "quint"
                        s.comp.item_ease_family = "sine"
                        s.style.bind_to_controls = bound
                        m = build_model(Dataset.from_text(DATA),s)
                        self.assertTrue(m.ok,(kind,mode,m.error))
                        file = Path(tmp)/f'{kind}_{mode}_{bound}.jsx'
                        file.write_text(generate_jsx(m),encoding="utf-8")
                        files.append(str(file))
            # Batch the mock host, which evaluates every installed expression
            # over 0..100 Progress, including both endpoints.
            result = subprocess.run(["node",str(ROOT/'tools/ae_mock_check.js')]+files,
                                    text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(f'Validated {len(files)} chart / mode / binding combinations.')


if __name__ == "__main__":
    unittest.main(verbosity=2)
