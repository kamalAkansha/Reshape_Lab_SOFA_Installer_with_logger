# SOFA Defrost Bundle — One-Shot Installer

Full setup for [DefrostSofaBundle](https://github.com/SofaDefrost/DefrostSofaBundle) with a containerised Podman environment and a modular diagnostic logger for soft pneumatic gripper simulations.

**Linux only.**

---

## What you get

| | |
|---|---|
| SOFA environment | Containerised via Podman, X11 forwarded — launch with `sofa` from any terminal |
| `gripper_logger` | Drop-in diagnostic controller — add a new log in 3 lines, no registration needed |
| Shell alias | `sofa` wired to your bash / zsh / fish config automatically |

---

## Install

```bash
git clone https://github.com/kamalAkansha/Reshape_Lab_SOFA_Installer_with_logger
cd Reshape_Lab_SOFA_Installer_with_logger
bash install_sofa.sh
```

The script handles everything in order:

1. Installs any missing system deps (`git`, `curl`, `unzip`, `podman`) via apt / dnf / pacman
2. Downloads and extracts the DefrostSofaBundle zip from the official GitHub releases
3. Builds the `sofa-defrost-env` Podman image from the included `Dockerfile`
4. Installs `gripper_logger.py` into the bundle as a Python package (`sofa.gripper_logger`)
5. Writes the `sofa` launch function to your shell config

Safe re-run of script — every step is idempotent.

---

## After install

Reload your shell, then:

```bash
sofa
```

SOFA opens with the bundle mounted at `/bundle` inside the container.

---

## Using the logger in a scene

```python
from sofa import gripper_logger

rootNode.addObject(gripper_logger.GripperLogger(
    name    = 'Logger',
    fingers = [
        ('Index',  mo_index,  pc_index,  cmo_index),
        ('Middle', mo_middle, pc_middle, cmo_middle),
        ('Thumb',  mo_thumb,  pc_thumb,  cmo_thumb),
    ],
))
```

On Animate you get:

- **Init** — bounding boxes, cavity sanity check, band tracking (printed once at sim start)
- **Every 100 steps** — tip position, pressure, velocity, per-band inflation deltas
- **Every step** — explosion detection: halts sim and dumps the offending node on NaN / runaway

See `GRIPPER_LOGGER_README.md` for the full API and all built-in methods.

---

## Extending the logger

Add any method with the right prefix — it's auto-discovered, no registration needed:

```python
from sofa import gripper_logger

class MyLogger(gripper_logger.GripperLogger):

    def log_tip_y(self):                          # runs every LOG_EVERY steps
        for (name, mo, _, _, _, _) in self.fingers:
            pos = np.array(mo.position.value)
            print('  %-8s  tip_y = %.2f mm' % (name, pos[:, 1].max()))

    def check_pressure_limit(self):               # runs every simulation step
        for (name, mo, pc, _, _, _) in self.fingers:
            if float(pc.value.value[0]) > 1.5:
                print('[CHECK] %s over limit!' % name)
                mo.getContext().getRootContext().animate = False

    def init_custom_report(self):                 # runs once at sim start
        print('[INIT] %d fingers loaded' % len(self.fingers))
```

| Prefix | Runs |
|---|---|
| `init_*` | Once at `onSimulationInitDoneEvent` |
| `check_*` | Every step |
| `log_*` | Every `LOG_EVERY` steps (default 100) |

---

## Environment overrides

```bash
SOFA_INSTALL_DIR=~/robotics/sofa   bash install_sofa.sh
SOFA_BUNDLE_VER=v22.06.01          bash install_sofa.sh
SOFA_PYTHON_VER=python3.10         bash install_sofa.sh
```

---

## Requirements

- Linux x86_64
- X11 (Wayland: use XWayland or set `DISPLAY` manually)
- `sudo` access — only needed if deps are missing
- ~4 GB disk for the bundle and container image
