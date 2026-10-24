# Raspberry Pi 4 setup

From a working Raspberry Pi OS to SortBuddy driving the motors and cameras.
About an hour.

## 1. Check the system

Open a **Terminal** on the Pi and run:

```
uname -m
cat /etc/os-release | grep PRETTY
```

- **`aarch64`** and **Debian 12 (bookworm)** or newer: good, continue.
- **`armv7l`**, or an older version (bullseye, buster): reinstall with
  **Raspberry Pi Imager** (on the PC) → *Raspberry Pi OS (64-bit)*, then
  continue. Reinstalling erases the card, so copy off anything you want first.

## 2. System packages

```
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-tk python3-gpiozero python3-lgpio v4l-utils
```

## 3. Get SortBuddy

```
cd ~
git clone -b claude/diy-tcg-card-sorter-wm9y3n https://github.com/jeffraines/sortbuddy.git
cd sortbuddy
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[ocr]"
```

The `--system-site-packages` flag lets the venv see the system's gpiozero and
Tk. If GitHub asks for a password (private repository), sign in with a
**personal access token**, or download the ZIP on the PC and copy it over.

From now on, start every session in a new terminal with:

```
cd ~/sortbuddy && source .venv/bin/activate
```

## 4. Steady servo signal (hardware PWM)

```
echo "dtoverlay=pwm-2chan,pin=18,func=2,pin2=19,func2=2" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

After the reboot, `ls /sys/class/pwm/` should show `pwmchip0`. This makes
GPIO18 and GPIO19 send rock-steady servo pulses. Without it SortBuddy falls
back to software PWM, which can make servos twitch.

## 5. Test with no motors connected

```
sortbuddy hw cycle --fake
sortbuddy hw cameras
```

`hw cameras` lists each USB camera by the **port** it's plugged into and saves
a snapshot to `camera-test/`. Check that:

- both cameras show up, ideally **MJPG** at about **30 fps**;
- the snapshots are sharp with a card at 12–14 cm.

## 6. Motors

Follow `docs/WIRING.md`, then test one part at a time:

```
sortbuddy hw servo gate
sortbuddy hw servo tray
sortbuddy hw stepper --turns 0.25
sortbuddy hw cycle
```

## 7. The app

```
sortbuddy-gui
```

The same app as on the PC: pick a camera, and sort by hand as before.
Machine mode, with both cameras and the motors, comes next.
