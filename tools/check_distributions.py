"""Regression checks for histograms, box plots and heatmaps.

Run: python tools/check_distributions.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from aegraphforge.core.build import build_model
from aegraphforge.core.dataset import Dataset
from aegraphforge.core.distributions import mark_state, mark_timing_js
from aegraphforge.core.spec import ChartSpec, HISTOGRAM, BOX_PLOT, HEATMAP


class DistributionChecks(unittest.TestCase):
    def test_histogram_boundaries_and_missing_values(self):
        ds = Dataset.from_text('value\n0\n1\n2\n3\n4\nNA\n')
        s = ChartSpec(chart_type=HISTOGRAM,value_column='value',histogram_bins=2)
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        self.assertEqual(m.histogram_edges,[0,2,4])
        self.assertEqual([b.value for b in m.bars],[2,3])
        self.assertTrue(m.warnings)
        self.assertEqual(sum(b.value for b in m.bars),5)

    def test_histogram_probability_and_density(self):
        ds = Dataset.from_text('value\n0\n2\n4\n6\n8\n')
        s = ChartSpec(chart_type=HISTOGRAM,value_column='value',histogram_bins=2)
        s.histogram_normalization = 'probability'
        m = build_model(ds,s)
        self.assertAlmostEqual(sum(b.value for b in m.bars),1)
        s.histogram_normalization = 'density'
        m = build_model(ds,s)
        self.assertAlmostEqual(sum(b.value*(m.histogram_edges[i+1]-m.histogram_edges[i])
                                   for i,b in enumerate(m.bars)),1)

    def test_histogram_constant_and_empty_bins(self):
        s = ChartSpec(chart_type=HISTOGRAM,value_column='value',histogram_bins=5)
        m = build_model(Dataset.from_text('value\n7\n7\n7\n'),s)
        self.assertTrue(m.ok,m.error)
        self.assertEqual(sum(b.value for b in m.bars),3)
        self.assertEqual(sum(b.value==0 for b in m.bars),4)
        s.histogram_bins = 201
        self.assertFalse(build_model(Dataset.from_text('value\n1\n2\n'),s).ok)
        s.histogram_bins = 5
        s.x_axis.scale = 'log'
        self.assertFalse(build_model(Dataset.from_text('value\n1\n2\n'),s).ok)

    def test_box_quartiles_whiskers_and_outliers(self):
        ds = Dataset.from_text('value\n1\n2\n3\n4\n5\n100\n')
        s = ChartSpec(chart_type=BOX_PLOT,value_column='value')
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        b = m.boxes[0]
        self.assertEqual((b['q1'],b['median'],b['q3']),(2.25,3.5,4.75))
        self.assertEqual((b['low'],b['high']),(1,5))
        self.assertEqual(b['outliers'],[100])
        self.assertEqual(sum(mark.kind=='dot' for mark in m.marks),1)
        s.box_show_outliers = False
        hidden = build_model(ds,s)
        self.assertFalse(any(mark.kind=='dot' for mark in hidden.marks))
        self.assertEqual(hidden.boxes,m.boxes)

    def test_box_groups_and_single_observation(self):
        ds = Dataset.from_text('group,value\nA,5\nB,1\nB,3\nB,5\n')
        s = ChartSpec(chart_type=BOX_PLOT,value_column='value',group_column='group',slice_sort='data')
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        a,b = m.boxes
        self.assertEqual((a['q1'],a['median'],a['q3'],a['low'],a['high']),(5,5,5,5,5))
        self.assertEqual((b['q1'],b['median'],b['q3']),(2,3,4))
        s.max_bars = 1
        self.assertEqual(len(build_model(ds,s).boxes),1)

    def test_heatmap_aggregation_missing_cells_and_zero(self):
        ds = Dataset.from_text('x,y,value\nA,R1,2\nA,R1,4\nB,R1,0\nB,R2,-3\nA,R3,NA\n')
        s = ChartSpec(chart_type=HEATMAP,value_column='value',heatmap_x='x',heatmap_y='y')
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        cells = {(c['column'],c['row']):c for c in m.cells}
        self.assertEqual(len(cells),3)
        self.assertEqual(cells['A','R1']['value'],6)
        self.assertEqual(cells['B','R1']['value'],0)
        self.assertNotIn(('A','R2'),cells)
        self.assertEqual(cells['B','R2']['color'],s.heatmap_low_color)
        self.assertEqual(cells['A','R1']['color'],s.heatmap_high_color)
        s.aggregation = 'mean'
        cells = {(c['column'],c['row']):c for c in build_model(ds,s).cells}
        self.assertEqual(cells['A','R1']['value'],3)

    def test_heatmap_count_without_numeric_column(self):
        ds = Dataset.from_text('x,y\nA,R1\nA,R1\nB,R2\n')
        s = ChartSpec(chart_type=HEATMAP,heatmap_x='x',heatmap_y='y',aggregation='count')
        m = build_model(ds,s)
        self.assertTrue(m.ok,m.error)
        self.assertEqual(sorted(c['value'] for c in m.cells),[1,2])

    def test_preset_new_options_round_trip(self):
        s = ChartSpec(chart_type=HISTOGRAM,value_column='amount',histogram_bins=17,
                      histogram_normalization='density',histogram_color=(0.1,0.2,0.3),
                      box_show_outliers=False,heatmap_x='region',heatmap_y='month',
                      heatmap_show_values=False,heatmap_low_color=(0,0,0),heatmap_high_color=(1,0,0))
        s.comp.animation_mode = 'rise'
        s.comp.stagger_seconds = .12
        self.assertEqual(ChartSpec.from_json(s.to_json()).to_dict(),s.to_dict())
        self.assertEqual(ChartSpec.from_dict({}).histogram_bins,0)

    def test_mark_animation_zero_delay_and_export_parity(self):
        ds = Dataset.from_text('group,value\nA,1\nA,3\nB,5\nB,8\n')
        s = ChartSpec(chart_type=BOX_PLOT,value_column='value',group_column='group')
        for mode in ('legacy','uniform_x','uniform_path','rise'):
            s.comp.animation_mode = mode
            s.comp.stagger_seconds = 0
            m = build_model(ds,s)
            cases = []
            for mark in m.marks:
                self.assertEqual(mark_state(mark,0,s)[-1],0)
                self.assertEqual(mark_state(mark,100,s)[-1],1)
                if mode=='rise':
                    self.assertEqual(mark_state(mark,0,s)[1],s.comp.plot_bottom)
                    self.assertEqual((mark.reveal_at,mark.reveal_span),(0,100))
                for p in (0,25,50,100):
                    cases.append({'code':'\n'.join([f'var progress={p};']+mark_timing_js(mark,s)+['g;']),
                                  'expected':mark_state(mark,p,s)[-1]})
            program = "const vm=require('vm'),cases=JSON.parse(require('fs').readFileSync(0,'utf8')); for(const c of cases){if(Math.abs(vm.runInNewContext(c.code)-c.expected)>1e-8)throw Error('mark timing differs');}"
            subprocess.run(['node','-e',program],input=json.dumps(cases),text=True,check=True)

    def test_ui_mapping_and_preset_restore(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from aegraphforge.ui.mainwindow import MainWindow
        app = QApplication.instance() or QApplication([])
        w = MainWindow()
        try:
            w.ds = Dataset.from_text('x,y,value\nA,R1,1\nA,R2,2\nB,R1,3\nB,R2,4\n')
            w._populate_columns()
            for kind in (HISTOGRAM,BOX_PLOT,HEATMAP):
                s = ChartSpec(chart_type=kind,value_column='value',group_column='x',
                              histogram_bins=3,histogram_normalization='probability',
                              heatmap_x='x',heatmap_y='y',box_show_outliers=False,heatmap_show_values=False)
                w.spec = ChartSpec.from_json(s.to_json())
                w._apply()
                w._refresh()
                self.assertTrue(w.model.ok,w.model.error)
                self.assertEqual(w.spec.value_column,'value')
                self.assertEqual(w.spec.histogram_bins,3)
                self.assertFalse(w.spec.box_show_outliers)
                self.assertEqual((w.spec.heatmap_x,w.spec.heatmap_y),('x','y'))
                self.assertFalse(w.spec.heatmap_show_values)
                for p in (0,50,100):
                    w.preview.canvas.set_progress(p)
                    app.processEvents()
                    self.assertFalse(w.preview.canvas.grab().isNull())
        finally:
            w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
