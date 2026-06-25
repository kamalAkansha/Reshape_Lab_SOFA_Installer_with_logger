# gripper_logger — Modular SOFA Diagnostic Logger

A drop-in diagnostic controller for soft pneumatic gripper simulations in SOFA.
Every diagnostic is a plain Python method — adding a new one takes about 3 lines.

---

## Quick start

```python
from gripper_logger import GripperLogger

rootNode.addObject(GripperLogger(
    name    = 'Logger',
    fingers = [
        ('Index',  mo_index,  pc_index,  cmo_index),
        ('Middle', mo_middle, pc_middle, cmo_middle),
        ('Thumb',  mo_thumb,  pc_thumb,  cmo_thumb),
    ],
))
```

That's it. On `Animate` you'll see init diagnostics in the console, then a
status block every 100 steps.

---

## The `fingers` tuple

Each entry is a tuple of 3 to 6 elements. Trailing elements are optional and
default to `None` — methods that need them check gracefully and skip.

```
(name, mo, pc [, cavity_mo [, roi_base [, roi_spine]]])
```

| Position | Type | Required | Needed for |
|---|---|---|---|
| `name` | `str` | yes | all labels |
| `mo` | `MechanicalObject` | yes | all position/velocity logs |
| `pc` | `SurfacePressureConstraint` | yes | pressure logs, explosion dump |
| `cavity_mo` | `MechanicalObject` (cavity) | recommended | inflation tracking, cavity check |
| `roi_base` | `BoxROI` | optional | ROI stats at init |
| `roi_spine` | `BoxROI` | optional | ROI stats at init |

Whether your .pyscn scene builds a single PneuNet finger or a full gripper, simply pass the main mechanical and 
cavity objects returned by your builder function to unlock all primary tracking features (except ROI stats).

---

## What runs out of the box

### At simulation start (`onSimulationInitDoneEvent`)

| Method | Output |
|---|---|
| `init_positions` | Bounding box + centroid for every finger |
| `init_roi_stats` | Base node count + spine tet count (warns if 0 tets) |
| `init_cavity_check` | Cavity bbox vs body bbox — flags nodes outside body |
| `init_band_tracking` | Auto-detects pneumatic chambers and septa along Z, pins reference node pairs for inflation tracking |

### Every simulation step (`onAnimateBeginEvent`)

| Method | Output |
|---|---|
| `check_explosion` | Halts sim + dumps worst node position, max velocity, and pressure if any finger explodes (NaN / Inf / position > 1000 mm) |

### Every 100 steps (`onAnimateBeginEvent`, periodic)

| Method | Output |
|---|---|
| `log_finger_status` | tip Z, pressure, max nodal velocity, centroid per finger |
| `log_inflation` | Per-band thickness delta (structural integrity) and lateral bulge delta (air expansion) |
| `log_cavity_runtime` | Warns if cavity nodes have drifted outside the body bbox |
| `log_node_norms` | Max and mean position norms — quick sanity check |

Change the interval with `GripperLogger.LOG_EVERY = 50` before adding to rootNode.

---

## Adding your own diagnostics

### New periodic log (printed every `LOG_EVERY` steps)

Define any method whose name starts with `log_`. It is auto-discovered and
called automatically — no registration needed.

```python
class MyLogger(GripperLogger):
    def log_tip_y(self):
        """Track how far each fingertip has curled in Y."""
        for (name, mo, _, _, _, _) in self.fingers:
            pos = np.array(mo.position.value)
            tip_y = pos[pos[:, 2].argmax(), 1]
            print('  %-8s  tip_y = %.2f mm' % (name, tip_y))
```

### New per-step check

Define any method whose name starts with `check_`.

```python
class MyLogger(GripperLogger):
    def check_pressure_runaway(self):
        for (name, mo, pc, _, _, _) in self.fingers:
            p = float(pc.value.value[0])
            if p > 1.5:
                print('[CHECK] %s pressure %.4f exceeds safe limit!' % (name, p))
                mo.getContext().getRootContext().animate = False
```

### New init log (printed once at sim start)

Define any method whose name starts with `init_`.

```python
class MyLogger(GripperLogger):
    def init_volume_estimate(self):
        for (name, mo, _, _, _, _) in self.fingers:
            pos = np.array(mo.position.value)
            span = pos.max(0) - pos.min(0)
            print('  %-8s  approx span: %.1f x %.1f x %.1f mm' % (name, *span))
```

### Wire it up

```python
rootNode.addObject(MyLogger(
    name    = 'Logger',
    fingers = [...],
))
```

---

## Accessing per-finger band state

`init_band_tracking` stores its results in `self._fstate[name]`:

```python
{
    'bands': [(zlo, zhi, 'chamber' or 'septum'), ...],
    'pairs': [
        {
            'idx_top':    int,   # node index at max Y in this Z-slice
            'idx_bot':    int,   # node index at min Y
            'idx_right':  int,   # node index at max X
            'idx_left':   int,   # node index at min X
            'z_init':     float, # Z position at t=0
            'init_thick': float, # initial top-to-bottom distance (mm)
            'init_bulge': float, # initial left-to-right distance (mm)
        },
        ...
    ]
}
```

Use it in your own `log_*` methods to build custom inflation metrics.

---

## Adjusting constants

Set these as class attributes before the object is added to rootNode,
or override in a subclass.

```python
GripperLogger.LOG_EVERY      = 50      # print logs every 50 steps instead of 100
GripperLogger.EXPLODE_THRESH = 500.0   # tighter explosion detection (mm)
GripperLogger.N_BINS         = 200     # more histogram bins for band detection
```

---

## Execution order

Within each category, methods run in **alphabetical order** by name.
If ordering matters between two `log_*` methods, prefix them:

```python
def log_1_status(self): ...
def log_2_derived(self): ...
```
