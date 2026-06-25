# gripper_logger.py -- modular SOFA diagnostic logger for soft gripper simulations
#
# USAGE
#   from gripper_logger import GripperLogger
#
#   rootNode.addObject(GripperLogger(
#       name='Logger',
#       fingers=[
#           (name, mo, pc),                               # minimal
#           (name, mo, pc, cavity_mo),                    # + inflation tracking
#           (name, mo, pc, cavity_mo, roi_base, roi_spine), # + ROI stats
#       ],
#   ))
#
# EXTENDING -- three method prefixes, all auto-discovered (no registration needed):
#
#   init_*   called once at onSimulationInitDoneEvent
#   check_*  called every simulation step
#   log_*    called every LOG_EVERY steps
#
# Each method receives nothing -- use self.fingers and self.step.
# Subclass GripperLogger, add methods with those prefixes, done.
#
# FINGER TUPLE FORMAT  (trailing elements are optional, default None):
#   (name, mo, pc, cavity_mo, roi_base, roi_spine)
#   name       -- string label
#   mo         -- MechanicalObject of the volumetric FEM mesh
#   pc         -- SurfacePressureConstraint
#   cavity_mo  -- MechanicalObject of the cavity mesh  (needed for inflation logs)
#   roi_base   -- BoxROI for the fixed base            (needed for ROI stats)
#   roi_spine  -- BoxROI for the spine zone            (needed for ROI stats)

import Sofa
import Sofa.Core
import numpy as np


class GripperLogger(Sofa.Core.Controller):

    LOG_EVERY      = 100      # print periodic logs every N steps
    EXPLODE_THRESH = 1000.0   # mm -- position magnitude that triggers explosion stop
    N_BINS         = 100      # histogram bins for auto-detecting chambers/septa

    def __init__(self, *args, **kwargs):
        Sofa.Core.Controller.__init__(self, *args, **kwargs)
        self.step = 0

        # Normalize every finger entry to a 6-tuple; missing items become None.
        raw = kwargs['fingers']
        self.fingers = []
        for f in raw:
            pad = list(f) + [None] * (6 - len(f))
            self.fingers.append(tuple(pad[:6]))

        # Per-finger state populated by init_band_tracking
        self._fstate = {}   # name -> {'bands': [...], 'pairs': [...]}

        # Auto-discover hook methods (sorted for stable, predictable order)
        self._init_fns  = [getattr(self, m) for m in sorted(dir(self)) if m.startswith('init_')]
        self._check_fns = [getattr(self, m) for m in sorted(dir(self)) if m.startswith('check_')]
        self._log_fns   = [getattr(self, m) for m in sorted(dir(self)) if m.startswith('log_')]

        print('[LOG] GripperLogger ready -- %d fingers, %d init, %d check, %d log methods.'
              % (len(self.fingers), len(self._init_fns),
                 len(self._check_fns), len(self._log_fns)))

    # --------------------------------------------------------------------------
    # SOFA event hooks
    # --------------------------------------------------------------------------

    def onSimulationInitDoneEvent(self, _):
        print('\n[LOG] ===== SIMULATION INIT =====')
        for fn in self._init_fns:
            fn()
        print('[LOG] =================================\n')

    def onAnimateBeginEvent(self, _):
        self.step += 1
        for fn in self._check_fns:
            fn()
        if self.step % self.LOG_EVERY == 0:
            print('\n[LOG][STEP %d]' % self.step)
            for fn in self._log_fns:
                fn()

    # ==========================================================================
    # init_*  --  run once at simulation start
    # ==========================================================================

    def init_positions(self):
        """Log initial bounding box and centroid for every finger."""
        print('[LOG] --- Initial positions ---')
        for (name, mo, _, _, _, _) in self.fingers:
            try:
                pos = np.array(mo.position.value)
                print('[LOG]   %-8s  nodes=%d  bbox=[%.1f %.1f %.1f]->[%.1f %.1f %.1f]  centroid=%s'
                      % (name, len(pos),
                         pos[:,0].min(), pos[:,1].min(), pos[:,2].min(),
                         pos[:,0].max(), pos[:,1].max(), pos[:,2].max(),
                         pos.mean(0).round(2)))
            except Exception as e:
                print('[LOG]   %s init_positions: %s' % (name, e))

    def init_roi_stats(self):
        """Log base-node count and spine-tet count from BoxROI objects."""
        print('[LOG] --- ROI stats ---')
        for (name, _, _, _, rb, rs) in self.fingers:
            if rb is not None:
                try:
                    n = len(rb.indices.value)
                    print('[LOG]   %-8s  base nodes   = %d' % (name, n))
                except Exception as e:
                    print('[LOG]   %s roi_base: %s' % (name, e))
            if rs is not None:
                try:
                    tets = rs.tetrahedraInROI.value
                    warn = '  *** 0 tets -- spine box may be wrong!' if len(tets) == 0 else ''
                    print('[LOG]   %-8s  spine tets   = %d%s' % (name, len(tets), warn))
                except Exception as e:
                    print('[LOG]   %s roi_spine: %s' % (name, e))

    def init_cavity_check(self):
        """Check that cavity nodes sit inside the body bounding box (BarycentricMapping sanity)."""
        print('[LOG] --- Cavity vs body bounds ---')
        for (name, mo, _, cmo, _, _) in self.fingers:
            if cmo is None:
                continue
            try:
                bp   = np.array(mo.position.value)
                cp   = np.array(cmo.position.value)
                bmin = bp.min(0);  bmax = bp.max(0)
                cmin = cp.min(0);  cmax = cp.max(0)
                n_out = (np.any(cp < bmin, 1) | np.any(cp > bmax, 1)).sum()
                print('[LOG]   %-8s  body  bbox: [%s] -> [%s]' % (name, bmin.round(2), bmax.round(2)))
                print('[LOG]   %-8s  cavity bbox: [%s] -> [%s]' % (name, cmin.round(2), cmax.round(2)))
                if n_out == 0:
                    print('[LOG]   %-8s  cavity OK -- all %d nodes inside body' % (name, len(cp)))
                else:
                    print('[LOG]   %-8s  WARNING: %d / %d cavity nodes OUTSIDE body'
                          ' -- BarycentricMapping will extrapolate!' % (name, n_out, len(cp)))
            except Exception as e:
                print('[LOG]   %s init_cavity_check: %s' % (name, e))

    def init_band_tracking(self):
        """
        Auto-detect pneumatic chambers and septa along the finger length,
        then lock in reference node pairs for inflation tracking later.
        Requires cavity_mo in the fingers tuple.
        """
        print('[LOG] --- Band / inflation tracking setup ---')
        for (name, mo, _, cmo, _, _) in self.fingers:
            if cmo is None:
                self._fstate[name] = {'bands': [], 'pairs': []}
                print('[LOG]   %-8s  skipped (no cavity_mo)' % name)
                continue
            try:
                cpos = np.array(cmo.position.value)
                septa, mids = self._detect_bands(cpos)
                bands = ([(z - 2, z + 2, 'chamber') for z in mids] +
                         [(z - 1, z + 1, 'septum')  for z in septa])
                pairs = self._build_node_pairs(mo, bands)
                self._fstate[name] = {'bands': bands, 'pairs': pairs}
                print('[LOG]   %-8s  %d chambers, %d septa -> %d tracked cross-sections'
                      % (name, len(mids), len(septa), len(pairs)))
            except Exception as e:
                self._fstate[name] = {'bands': [], 'pairs': []}
                print('[LOG]   %s init_band_tracking: %s' % (name, e))

    # ==========================================================================
    # check_*  --  run every simulation step
    # ==========================================================================

    def check_explosion(self):
        """
        Stop the simulation immediately if any finger node explodes
        (NaN / Inf / position magnitude > EXPLODE_THRESH).
        Also prints worst node, max velocity, and current pressure.
        """
        for (name, mo, pc, _, _, _) in self.fingers:
            try:
                pos     = np.array(mo.position.value)
                has_nan = bool(np.any(np.isnan(pos)))
                has_inf = bool(np.any(np.isinf(pos)))
                max_d   = float(np.max(np.abs(pos))) if pos.size > 0 else 0.0
                if not (has_nan or has_inf or max_d > self.EXPLODE_THRESH):
                    continue
                print('\n[LOG][%s] !!! EXPLOSION at step %d !!!' % (name, self.step))
                print('[LOG]   has_nan=%s  has_inf=%s  max_abs=%.2f mm' % (has_nan, has_inf, max_d))
                if pos.size > 0 and not has_nan:
                    w = int(np.argmax(np.linalg.norm(pos, axis=1)))
                    print('[LOG]   worst node %d: %s' % (w, pos[w].round(2)))
                try:
                    vel  = np.array(mo.velocity.value)
                    vmax = float(np.max(np.linalg.norm(vel, axis=1)))
                    wv   = int(np.argmax(np.linalg.norm(vel, axis=1)))
                    print('[LOG]   max velocity: %.2f mm/s at node %d' % (vmax, wv))
                except Exception:
                    pass
                try:
                    print('[LOG]   pressure: %.6f' % float(pc.value.value[0]))
                except Exception:
                    pass
                print('[LOG] Stopping simulation.')
                mo.getContext().getRootContext().animate = False
                return
            except Exception as e:
                print('[LOG][%s] explosion check error: %s' % (name, e))

    # ==========================================================================
    # log_*  --  run every LOG_EVERY steps
    # ==========================================================================

    def log_finger_status(self):
        """tip Z position, current pressure, and max nodal velocity per finger."""
        for (name, mo, pc, _, _, _) in self.fingers:
            try:
                pos  = np.array(mo.position.value)
                p    = float(pc.value.value[0])
                tip  = pos[:, 2].max()
                vmax = 0.0
                try:
                    vel  = np.array(mo.velocity.value)
                    vmax = float(np.max(np.linalg.norm(vel, axis=1)))
                except Exception:
                    pass
                centroid = pos.mean(0).round(2)
                print('  %-8s  tip_z=%6.2f  pressure=%.5f  vmax=%7.3f mm/s  centroid=%s'
                      % (name, tip, p, vmax, centroid))
            except Exception as e:
                print('  %s log_finger_status: %s' % (name, e))

    def log_inflation(self):
        """
        Per-band node expansion: thickness (height integrity) vs lateral bulge (air inflation).
        Only fires for fingers that have cavity_mo (set up by init_band_tracking).
        """
        any_data = False
        for (name, mo, _, _, _, _) in self.fingers:
            pairs = self._fstate.get(name, {}).get('pairs', [])
            if not pairs:
                continue
            any_data = True
            try:
                pos = np.array(mo.position.value)
                print('  %s  thick=height-integrity  bulge=lateral-inflation (delta mm):' % name)
                for pair in pairs:
                    dt = (np.linalg.norm(pos[pair['idx_top']]   - pos[pair['idx_bot']])
                          - pair['init_thick'])
                    db = (np.linalg.norm(pos[pair['idx_right']] - pos[pair['idx_left']])
                          - pair['init_bulge'])
                    print('    z~%5.1f %-8s  thick d=%+.4f  bulge d=%+.4f'
                          % (pair['z_init'], pair['label'], dt, db))
            except Exception as e:
                print('  %s log_inflation: %s' % (name, e))
        if not any_data:
            print('  (inflation tracking disabled -- pass cavity_mo as 4th element of finger tuple)')

    def log_cavity_runtime(self):
        """Warn if any cavity nodes have drifted outside the body bbox during sim."""
        for (name, mo, _, cmo, _, _) in self.fingers:
            if cmo is None:
                continue
            try:
                bp = np.array(mo.position.value)
                cp = np.array(cmo.position.value)
                bmin = bp.min(0);  bmax = bp.max(0)
                n_out = (np.any(cp < bmin, 1) | np.any(cp > bmax, 1)).sum()
                if n_out > 0:
                    print('  %-8s  WARNING: %d cavity nodes outside body (BarycentricMapping extrapolating)'
                          % (name, n_out))
            except Exception as e:
                print('  %s log_cavity_runtime: %s' % (name, e))

    def log_node_norms(self):
        """Quick health check: max and mean nodal position norms per finger."""
        for (name, mo, _, _, _, _) in self.fingers:
            try:
                norms = np.linalg.norm(np.array(mo.position.value), axis=1)
                print('  %-8s  max_norm=%.3f  mean_norm=%.3f' % (name, norms.max(), norms.mean()))
            except Exception as e:
                print('  %s log_node_norms: %s' % (name, e))

    # ==========================================================================
    # Internal helpers  (not auto-discovered -- no init_/log_/check_ prefix)
    # ==========================================================================

    def _detect_bands(self, cavity_pos, min_run=2, edge_margin=3.0):
        """
        Scan the cavity mesh along Z, find narrow cross-sections (septa),
        and return (septa_z_list, chamber_midpoint_z_list).
        """
        z    = cavity_pos[:, 2]
        zmin, zmax = z.min(), z.max()
        edges = np.linspace(zmin, zmax, self.N_BINS + 1)
        centers, widths = [], []
        for i in range(self.N_BINS):
            m = (z >= edges[i]) & (z < edges[i + 1])
            if m.sum() < 3:
                continue
            sub = cavity_pos[m]
            centers.append(0.5 * (edges[i] + edges[i + 1]))
            widths.append(sub[:, 0].max() - sub[:, 0].min())
        centers  = np.array(centers)
        widths   = np.array(widths)
        is_narrow = widths < 0.7 * np.median(widths)

        septa = []
        i = 0
        while i < len(is_narrow):
            if is_narrow[i]:
                j = i
                while j < len(is_narrow) and is_narrow[j]:
                    j += 1
                if (j - i) >= min_run:
                    z_mid = float(centers[(i + j - 1) // 2])
                    if (z_mid - zmin) > edge_margin and (zmax - z_mid) > edge_margin:
                        septa.append(z_mid)
                i = j
            else:
                i += 1
        bounds = [float(zmin)] + septa + [float(zmax)]
        mids   = [(lo + hi) / 2.0 for lo, hi in zip(bounds[:-1], bounds[1:])]
        return septa, mids

    def _build_node_pairs(self, mo, bands):
        """
        For each Z-band, pin the extreme top/bottom and left/right nodes at t=0.
        These pairs are used by log_inflation to measure deformation deltas.
        """
        pos0  = np.array(mo.position.value)
        pairs = []
        for (zlo, zhi, label) in bands:
            idx = np.where((pos0[:, 2] >= zlo) & (pos0[:, 2] < zhi))[0]
            if len(idx) < 4:
                continue
            it = idx[np.argmax(pos0[idx, 1])]
            ib = idx[np.argmin(pos0[idx, 1])]
            ir = idx[np.argmax(pos0[idx, 0])]
            il = idx[np.argmin(pos0[idx, 0])]
            pairs.append({
                'idx_top':    it,  'idx_bot':   ib,
                'idx_right':  ir,  'idx_left':  il,
                'label':      label,
                'z_init':     float(pos0[[it, ib], 2].mean()),
                'init_thick': float(np.linalg.norm(pos0[it] - pos0[ib])),
                'init_bulge': float(np.linalg.norm(pos0[ir] - pos0[il])),
            })
        return pairs
