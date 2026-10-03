#!/usr/bin/env python3
"""Hyprland Settings — a small control panel for a HyDE/Hyprland desktop.

Panels: Waybar (auto-hide), Appearance, Connectivity (Wi-Fi + Bluetooth),
Date & Time, Display (mirror/extend), Troubleshoot, Logs, About.

Every action is written to ~/.local/share/hypr-settings/logs/actions.log and
files are backed up to logs/backups/ before they are changed, so you can review
or revert what the app did.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf  # noqa: E402

import os
import re
import json
import time
import shutil
import datetime
import subprocess

HOME = os.path.expanduser("~")
# Where the helper scripts live — next to this file (repo / user / system install),
# with sensible fallbacks so it works however it was installed.
_APP_DIR = os.path.dirname(os.path.realpath(__file__))


def _find_script(name):
    for d in (_APP_DIR, os.path.join(_APP_DIR, "scripts"),
              os.path.join(HOME, ".local", "share", "hypr-settings"),
              "/usr/share/hypr-settings"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(_APP_DIR, name)


# User data (writable): logs/backups. Separate from the (possibly read-only) app dir.
SHARE = os.path.join(HOME, ".local", "share", "hypr-settings")
CONF_DIR = os.path.join(HOME, ".config", "hypr-settings")
AUTOHIDE_CONF = os.path.join(CONF_DIR, "autohide.conf")
DAEMON = _find_script("waybar-autohide.sh")
LOG_DIR = os.path.join(SHARE, "logs")
ACTIONS_LOG = os.path.join(LOG_DIR, "actions.log")
BACKUP_DIR = os.path.join(LOG_DIR, "backups")
STATERC = os.path.join(HOME, ".local", "state", "hyde", "staterc")
THEMES_DIR = os.path.join(HOME, ".config", "hyde", "themes")
WALLBASH_GTK = os.path.join(HOME, ".cache", "hyde", "wallbash", "gtk.css")
LIVE_SH = _find_script("live-wallpaper.sh")
LIVE_WALL_DIR = os.path.join(HOME, "Videos", "live-wallpapers")
HYDE_SHELL = os.path.join(HOME, ".local", "bin", "hyde-shell")
WAYBAR_PY = os.path.join(HOME, ".local", "lib", "hyde", "waybar.py")


# ---------- logging ----------
def log(msg):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(ACTIONS_LOG, "a") as f:
            f.write(f"{datetime.datetime.now():%F %T}  {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def backup_file(path):
    try:
        if os.path.exists(path):
            os.makedirs(BACKUP_DIR, exist_ok=True)
            base = os.path.basename(path)
            dst = os.path.join(BACKUP_DIR, f"{base}.{datetime.datetime.now():%Y%m%d_%H%M%S}.bak")
            shutil.copy2(path, dst)
            log(f"backup: {path} -> {dst}")
    except Exception as e:  # noqa: BLE001
        log(f"backup FAILED {path}: {e}")


# ---------- shell helpers ----------
def run(cmd):
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        return cp
    except Exception as e:  # noqa: BLE001
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def run_log(cmd, label=None):
    cp = run(cmd)
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    log(f"{label or ' '.join(cmd)} -> rc={cp.returncode}" + (f" err={err}" if err else ""))
    return cp


def run_bg(cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        log("bg: " + " ".join(cmd))
    except Exception as e:  # noqa: BLE001
        log(f"bg FAILED {cmd}: {e}")


def have(binary):
    return shutil.which(binary) is not None


# ---------- waybar / hyprland ----------
def reserved_top():
    cp = run(["hyprctl", "monitors", "-j"])
    try:
        return max((m.get("reserved", [0, 0, 0, 0])[1] for m in json.loads(cp.stdout)), default=0)
    except Exception:  # noqa: BLE001
        return 0


def waybar_visible():
    return reserved_top() > 0


def ensure_waybar_visible():
    if not waybar_visible():
        run(["killall", "-SIGUSR1", "waybar"])


def monitors():
    cp = run(["hyprctl", "monitors", "-j"])
    try:
        return json.loads(cp.stdout)
    except Exception:  # noqa: BLE001
        return []


# ---------- battery / power ----------
def _bat_dir():
    import glob
    b = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    return b[0] if b else None


def _sysf(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return None


def battery_info():
    d = _bat_dir()
    if not d:
        return None
    gi = lambda n: (int(v) if (v := _sysf(os.path.join(d, n))) and v.lstrip("-").isdigit() else None)  # noqa: E731
    full = gi("charge_full") or gi("energy_full")
    design = gi("charge_full_design") or gi("energy_full_design")
    return {
        "capacity": _sysf(os.path.join(d, "capacity")),
        "status": _sysf(os.path.join(d, "status")),
        "level": _sysf(os.path.join(d, "capacity_level")),
        "cycles": gi("cycle_count"),
        "full": full, "design": design,
        "health": round(full / design * 100) if (full and design) else None,
        "is_charge": os.path.exists(os.path.join(d, "charge_full")),
    }


def power_watts():
    d = _bat_dir()
    if not d:
        return None
    p = _sysf(os.path.join(d, "power_now"))
    if p and p.isdigit():
        return int(p) / 1e6
    v = _sysf(os.path.join(d, "voltage_now"))
    c = _sysf(os.path.join(d, "current_now"))
    if v and c and v.isdigit() and c.lstrip("-").isdigit():
        return abs(int(v) / 1e6 * int(c) / 1e6)
    return None


def power_profiles():
    profs = []
    for line in run(["powerprofilesctl", "list"]).stdout.splitlines():
        m = re.match(r"\s*\*?\s*(performance|balanced|power-saver):", line)
        if m:
            profs.append(m.group(1))
    return profs


def current_profile():
    return run(["powerprofilesctl", "get"]).stdout.strip() or None


def top_power_procs(n=6):
    out = []
    for line in run(["ps", "-eo", "comm,%cpu", "--sort=-%cpu"]).stdout.splitlines()[1:]:
        parts = line.rsplit(None, 1)
        if len(parts) == 2 and parts[0] not in ("ps",):
            try:
                out.append((parts[0], float(parts[1])))
            except ValueError:
                pass
        if len(out) >= n:
            break
    return out


def geoclue_installed():
    return (os.path.isdir("/usr/lib/geoclue-2.0")
            or run(["pacman", "-Q", "geoclue"]).returncode == 0)


def read_conf():
    vals = {"ENABLED": 0, "REVEAL_AT": 3, "HIDE_BELOW": 45, "HIDE_DELAY": 0.5, "POLL": 0.06}
    try:
        with open(AUTOHIDE_CONF) as f:
            for line in f:
                m = re.match(r"\s*(\w+)\s*=\s*([0-9.]+)", line)
                if m and m.group(1) in vals:
                    v = m.group(2)
                    vals[m.group(1)] = float(v) if "." in v else int(v)
    except FileNotFoundError:
        pass
    return vals


def write_conf(vals):
    os.makedirs(CONF_DIR, exist_ok=True)
    backup_file(AUTOHIDE_CONF)
    with open(AUTOHIDE_CONF, "w") as f:
        f.write("# Waybar auto-hide tunables (edited by Hyprland Settings)\n")
        f.write(f"ENABLED={int(vals['ENABLED'])}\n")
        f.write(f"REVEAL_AT={int(vals['REVEAL_AT'])}\n")
        f.write(f"HIDE_BELOW={int(vals['HIDE_BELOW'])}\n")
        f.write(f"HIDE_DELAY={vals['HIDE_DELAY']}\n")
        f.write(f"POLL={vals['POLL']}\n")
    log(f"wrote autohide.conf {vals}")


def daemon_running():
    return run(["pgrep", "-f", "waybar-autohide.sh"]).returncode == 0


def start_daemon():
    run(["pkill", "-f", "waybar-autohide.sh"])
    time.sleep(0.3)
    run_bg(["bash", DAEMON])


def stop_daemon():
    run_log(["pkill", "-f", "waybar-autohide.sh"], "stop autohide daemon")
    time.sleep(0.3)
    ensure_waybar_visible()


def restart_waybar():
    run_log([WAYBAR_PY, "--kill"], "waybar --kill")
    run(["killall", "-q", "waybar"])
    time.sleep(1)
    run(["pkill", "-9", "-q", "waybar"])
    time.sleep(1)
    run_bg([WAYBAR_PY, "-u"])
    log("waybar restarted via waybar.py -u")


def apply_bar_animation():
    run(["hyprctl", "eval",
         'hl.animation({ leaf="layers", enabled=true, speed=4, bezier="default", style="slide" })'])
    run(["hyprctl", "eval",
         'hl.layer_rule({ name="autohide_anim", match={namespace="waybar"}, animation="slide top" })'])
    log("reapplied bar slide animation")


def waybar_layouts():
    cp = run([WAYBAR_PY, "--json"])
    names = []
    try:
        data = json.loads(cp.stdout)
        items = data["layouts"] if isinstance(data, dict) else data
        names = [it["name"] for it in items if it.get("name") and not it.get("is_backup_entry")]
    except Exception:  # noqa: BLE001
        pass
    return names


def list_themes():
    try:
        return sorted(d for d in os.listdir(THEMES_DIR)
                      if os.path.isdir(os.path.join(THEMES_DIR, d)))
    except FileNotFoundError:
        return []


def current_theme():
    try:
        with open(STATERC) as f:
            for line in f:
                m = re.match(r'\s*HYDE_THEME\s*=\s*"?(.*?)"?\s*$', line)
                if m:
                    return m.group(1)
    except FileNotFoundError:
        pass
    return None


def current_layout():
    """Current Waybar layout name (e.g. 'hyprdots/04'), from HyDE state."""
    try:
        with open(STATERC) as f:
            for line in f:
                m = re.match(r'\s*WAYBAR_LAYOUT_PATH\s*=\s*"?(.*?)"?\s*$', line)
                if m:
                    p = m.group(1)
                    base = os.path.join(HOME, ".local", "share", "waybar", "layouts")
                    try:
                        rel = os.path.relpath(p, base)
                    except ValueError:
                        rel = os.path.basename(p)
                    return re.sub(r"\.jsonc$", "", rel)
    except FileNotFoundError:
        pass
    return None


# ---------- theming (follow HyDE theme + translucency) ----------
def theme_css():
    """Map HyDE's wallbash colors onto libadwaita named colors, with alpha so
    the window is translucent like the terminal. Falls back silently if the
    wallbash file is missing."""
    if not os.path.exists(WALLBASH_GTK):
        return ""
    uri = GLib.filename_to_uri(WALLBASH_GTK, None)
    return f'''
@import url("{uri}");

@define-color window_bg_color alpha(@wallbash_pry1, 0.82);
@define-color window_fg_color @wallbash_txt1;
@define-color view_bg_color alpha(@wallbash_pry1, 0.58);
@define-color view_fg_color @wallbash_txt1;
@define-color headerbar_bg_color alpha(@wallbash_pry1, 0.80);
@define-color headerbar_fg_color @wallbash_txt1;
@define-color headerbar_backdrop_color alpha(@wallbash_pry1, 0.70);
@define-color sidebar_bg_color alpha(@wallbash_pry1, 0.68);
@define-color sidebar_fg_color @wallbash_txt1;
@define-color secondary_sidebar_bg_color alpha(@wallbash_pry1, 0.60);
@define-color card_bg_color alpha(@wallbash_1xa2, 0.50);
@define-color card_fg_color @wallbash_txt1;
@define-color popover_bg_color alpha(@wallbash_pry1, 0.96);
@define-color popover_fg_color @wallbash_txt1;
@define-color dialog_bg_color alpha(@wallbash_pry1, 0.94);
@define-color accent_bg_color @wallbash_1xa6;
@define-color accent_fg_color @wallbash_pry1;
@define-color accent_color @wallbash_1xa8;

/* Let the compositor show the wallpaper through the toplevel. */
window.background, window.csd, .background {{
  background-color: alpha(@wallbash_pry1, 0.82);
}}
preferencespage, preferencesgroup, scrolledwindow, viewport {{
  background-color: transparent;
}}
scale trough {{
  background-color: alpha(@window_fg_color, 0.20);
}}
scale highlight, scale slider {{
  background-color: @accent_bg_color;
}}
'''


# ---------- power-draw sparkline ----------
class Sparkline(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.samples = []
        self.set_content_height(72)
        self.set_hexpand(True)
        self.set_draw_func(self._draw, None)

    def push(self, v):
        self.samples.append(max(0.0, v))
        del self.samples[:-90]
        self.queue_draw()

    def _draw(self, area, cr, w, h, _data):
        n = len(self.samples)
        if n < 2:
            return
        mx = max(self.samples) or 1.0
        rgba = area.get_color()
        step = w / (n - 1)
        pts = [(i * step, h - (v / mx) * (h - 10) - 5) for i, v in enumerate(self.samples)]
        cr.move_to(0, h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to((n - 1) * step, h)
        cr.close_path()
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.14)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.9)
        cr.set_line_width(2)
        cr.stroke()


# ---------- window ----------
class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Hyprland Settings")
        self.set_default_size(760, 680)
        self._display_group = None

        self.add(self._waybar_page())
        self.add(self._appearance_page())
        self.add(self._connectivity_page())
        self.add(self._datetime_page())
        self.add(self._battery_page())
        self.add(self._privacy_page())
        self.add(self._display_page())
        self.add(self._troubleshoot_page())
        self.add(self._logs_page())
        self.add(self._about_page())
        log("app opened")
        self._watch_state()

    def _watch_state(self):
        # Keep the Layout / Theme selectors in sync when they're changed
        # elsewhere (keyboard shortcuts, theme switcher, etc.).
        try:
            f = Gio.File.new_for_path(STATERC)
            self._state_mon = f.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._state_mon.connect("changed", self._on_state_changed)
        except Exception as e:  # noqa: BLE001
            log(f"state watch failed: {e}")

    def _on_state_changed(self, _mon, _f, _o, event):
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            GLib.timeout_add(200, self._sync_from_state)

    def _sync_from_state(self):
        lay = current_layout()
        if lay and hasattr(self, "combo_layout") and lay in getattr(self, "_layouts", []):
            self._guard("layout", True)
            self.combo_layout.set_selected(self._layouts.index(lay))
            self._guard("layout", False)
        th = current_theme()
        if th and hasattr(self, "combo_theme") and th in getattr(self, "_themes", []):
            self._guard("theme", True)
            self.combo_theme.set_selected(self._themes.index(th))
            self._guard("theme", False)
        return False

    def toast(self, text):
        self.add_toast(Adw.Toast(title=text, timeout=3))

    # ===== Waybar =====
    def _waybar_page(self):
        page = Adw.PreferencesPage(title="Waybar", icon_name="view-reveal-symbolic")
        conf = read_conf()

        g = Adw.PreferencesGroup(title="Auto-hide")
        page.add(g)

        self.sw_autohide = Adw.SwitchRow(title="Auto-hide Waybar")
        self.sw_autohide.set_active(bool(conf["ENABLED"]))
        self.sw_autohide.connect("notify::active", self._on_autohide)
        g.add(self.sw_autohide)

        self.scale_reveal = self._slider_row(g, "Reveal zone", 1, 60, 1, conf["REVEAL_AT"], 0)
        self.scale_hide = self._slider_row(g, "Hide threshold", 20, 300, 5, conf["HIDE_BELOW"], 0)
        self.scale_delay = self._slider_row(g, "Hide delay", 0.0, 3.0, 0.1, conf["HIDE_DELAY"], 1)

        g2 = Adw.PreferencesGroup(title="Layout")
        page.add(g2)
        layouts = waybar_layouts()
        if layouts:
            self.combo_layout = Adw.ComboRow(title="Active layout")
            self.combo_layout.set_model(Gtk.StringList.new(layouts))
            self._layouts = layouts
            self._guard("layout", True)
            self.combo_layout.connect("notify::selected", self._on_layout)
            self._guard("layout", False)
            self._scroll_combo(self.combo_layout)
            g2.add(self.combo_layout)

        # --- Layout list with screenshots ---
        gp = Adw.PreferencesGroup(title="Preview")
        page.add(gp)

        self._layout_pics = {}
        lbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        for name in (getattr(self, "_layouts", []) or []):
            card = Gtk.Button(tooltip_text=f"Apply {name}")
            card.add_css_class("card")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                            margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            lbl = Gtk.Label(label=name, xalign=0)
            lbl.add_css_class("caption-heading")
            lbl.add_css_class("dim-label")
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, hexpand=True, height_request=30)
            self._layout_pics[name] = pic
            self._set_layout_pic(name)
            inner.append(lbl)
            inner.append(pic)
            card.set_child(inner)
            card.connect("clicked", (lambda n: lambda *_: self._apply_layout(n))(name))
            lbox.append(card)
        gp.add(lbox)
        return page

    def _layout_cache(self, name):
        d = os.path.join(GLib.get_user_cache_dir(), "hypr-settings", "layout-previews")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name.replace("/", "-") + ".png")

    def _set_layout_pic(self, name):
        pic = self._layout_pics.get(name)
        if not pic:
            return
        p = self._layout_cache(name)
        if os.path.exists(p):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(p)
                pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
                pic.set_visible(True)
                return
            except Exception:  # noqa: BLE001
                pass
        pic.set_visible(False)

    def _apply_layout(self, name):
        run_bg([HYDE_SHELL, "waybar.py", "--set", name])
        self.toast(f"Applying {name} — capturing screenshot…")
        log(f"apply layout {name}")
        if hasattr(self, "combo_layout") and name in getattr(self, "_layouts", []):
            self._guard("layout", True)
            self.combo_layout.set_selected(self._layouts.index(name))
            self._guard("layout", False)
        # Wait for the bar to re-render, then screenshot it.
        GLib.timeout_add(2200, lambda: (self._capture_layout(name), False)[1])

    def _capture_layout(self, name):
        try:
            m = next((x for x in monitors() if x.get("focused")), None)
            if m:
                x, y = m.get("x", 0), m.get("y", 0)
                scale = m.get("scale", 1.0) or 1.0
                lw = round(m["width"] / scale)
                rt = m.get("reserved", [0, 0, 0, 0])[1] or 40
                run(["grim", "-g", f"{x},{y} {lw}x{rt + 8}", self._layout_cache(name)])
                self._set_layout_pic(name)
        except Exception as e:  # noqa: BLE001
            log(f"capture layout failed: {e}")

    def _on_autohide(self, row, _):
        on = row.get_active()
        conf = read_conf()
        conf["ENABLED"] = 1 if on else 0
        write_conf(conf)
        if on:
            apply_bar_animation()
            start_daemon()
            self.toast("Auto-hide on — move the pointer to the top to reveal")
            log("auto-hide ENABLED")
        else:
            stop_daemon()
            self.toast("Auto-hide off")
            log("auto-hide DISABLED")

    def _slider_row(self, group, title, lo, hi, step, value, digits):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_value(value)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.set_size_request(190, -1)
        scale.set_valign(Gtk.Align.CENTER)
        val = Gtk.Label(xalign=1, width_chars=4)
        fmt = (lambda v: f"{v:.1f}") if digits else (lambda v: f"{int(round(v))}")
        val.set_text(fmt(value))
        val.add_css_class("dim-label")
        scale.connect("value-changed", lambda s: (val.set_text(fmt(s.get_value())), self._on_tune()))
        box = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
        box.append(scale)
        box.append(val)
        row.add_suffix(box)
        group.add(row)
        return scale

    def _on_tune(self, *_):
        # Sliders fire continuously; debounce the write/restart.
        src = getattr(self, "_tune_src", 0)
        if src:
            GLib.source_remove(src)
        self._tune_src = GLib.timeout_add(350, self._commit_tune)

    def _commit_tune(self):
        self._tune_src = 0
        conf = read_conf()
        conf["REVEAL_AT"] = self.scale_reveal.get_value()
        conf["HIDE_BELOW"] = self.scale_hide.get_value()
        conf["HIDE_DELAY"] = round(self.scale_delay.get_value(), 1)
        write_conf(conf)
        if conf["ENABLED"] and daemon_running():
            start_daemon()  # restart to pick up new values
        return False

    def _on_layout(self, combo, _):
        if self._guarded("layout"):
            return
        name = self._layouts[combo.get_selected()]
        run_bg([HYDE_SHELL, "waybar.py", "--set", name])
        self.toast(f"Waybar layout → {name}")

    # ===== Appearance =====
    def _theme_group(self):
        g = Adw.PreferencesGroup(
            title="Theme",
            description="A HyDE theme sets colors, wallpaper and the Waybar style together.")
        themes = list_themes()
        if themes:
            self.combo_theme = Adw.ComboRow(title="Active theme")
            self.combo_theme.set_model(Gtk.StringList.new(themes))
            cur = current_theme()
            if cur in themes:
                self.combo_theme.set_selected(themes.index(cur))
            self._themes = themes
            self._guard("theme", True)
            self.combo_theme.connect("notify::selected", self._on_theme)
            self._guard("theme", False)
            self._scroll_combo(self.combo_theme)
            g.add(self.combo_theme)
        else:
            g.add(Adw.ActionRow(title="No HyDE themes found"))
        return g

    def _on_theme(self, combo, _):
        if self._guarded("theme"):
            return
        name = self._themes[combo.get_selected()]
        if hasattr(self, "_kill_live_quiet"):
            self._kill_live_quiet()  # so the theme's wallpaper actually shows
        run_bg([HYDE_SHELL, "theme.switch", "-s", name])
        self.toast(f"Applying theme “{name}” …")
        log(f"theme switch -> {name}")

    # ===== Appearance (theme + wallpaper) =====
    def _appearance_page(self):
        page = Adw.PreferencesPage(title="Appearance", icon_name="applications-graphics-symbolic")
        page.add(self._theme_group())
        installed = have("mpvpaper")

        # --- Wallpaper mode + live videos ---
        gm = Adw.PreferencesGroup(title="Wallpaper")
        page.add(gm)
        self.sw_live = Adw.SwitchRow(title="Live wallpaper")
        self.sw_live.set_active(self._live_running())
        self.sw_live.set_sensitive(installed)
        self._guard("live", True)
        self.sw_live.connect("notify::active", self._on_live_toggle)
        self._guard("live", False)
        gm.add(self.sw_live)
        if not installed:
            r = Adw.ActionRow(title="Install mpvpaper for live wallpaper",
                              subtitle="sudo pacman -S mpvpaper")
            r.set_subtitle_selectable(True)
            gm.add(r)
        vids = []
        try:
            vids = sorted(f for f in os.listdir(LIVE_WALL_DIR)
                          if f.lower().endswith((".mp4", ".mkv", ".webm", ".mov")))
        except FileNotFoundError:
            pass
        self._vid_paths = [os.path.join(LIVE_WALL_DIR, v) for v in vids]
        if vids:
            self.combo_video = Adw.ComboRow(title="Video")
            self.combo_video.set_model(Gtk.StringList.new([os.path.splitext(v)[0] for v in vids]))
            self.combo_video.set_sensitive(installed)
            self._scroll_combo(self.combo_video)
            # current video selected, if any
            cur = self._last_video()
            if cur in self._vid_paths:
                self.combo_video.set_selected(self._vid_paths.index(cur))
            setb = Gtk.Button(label="Set", valign=Gtk.Align.CENTER)
            setb.set_sensitive(installed)
            setb.connect("clicked", lambda *_: self._start_live(self._vid_paths[self.combo_video.get_selected()]))
            self.combo_video.add_suffix(setb)
            gm.add(self.combo_video)
        self._row_button(gm, "Choose video…", "", "Browse", self._choose_video, sensitive=installed)
        self._row_button(gm, "Choose image…", "", "Browse", self._choose_image)

        # --- Theme wallpapers gallery (lazy thumbnails per theme) ---
        gt = Adw.PreferencesGroup(title="Theme wallpapers")
        page.add(gt)
        cur = current_theme()
        for theme in list_themes():
            exp = Adw.ExpanderRow(title=theme)
            if theme == cur:
                exp.set_subtitle("current")
            exp._theme = theme
            exp._loaded = False
            exp.connect("notify::expanded", self._on_theme_expand)
            gt.add(exp)
        return page

    # ----- live wallpaper -----
    def _live_running(self):
        return run(["pgrep", "-x", "mpvpaper"]).returncode == 0

    def _live_status(self):
        if not have("mpvpaper"):
            return "mpvpaper not installed"
        return "On (power-save active)" if self._live_running() else "Off"

    def _update_live_ui(self):
        self._guard("live", True)
        self.sw_live.set_active(self._live_running())
        self._guard("live", False)

    def _last_video(self):
        try:
            with open(os.path.join(CONF_DIR, "live-wallpaper.conf")) as f:
                for line in f:
                    m = re.match(r'\s*VIDEO=(.+)', line)
                    if m:
                        return m.group(1).strip().strip("'\"")
        except FileNotFoundError:
            pass
        return None

    def _first_video(self):
        try:
            for v in sorted(os.listdir(LIVE_WALL_DIR)):
                if v.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
                    return os.path.join(LIVE_WALL_DIR, v)
        except FileNotFoundError:
            pass
        return None

    def _on_live_toggle(self, sw, _):
        if self._guarded("live"):
            return
        if sw.get_active():
            if not have("mpvpaper"):
                self.toast("Install mpvpaper first:  sudo pacman -S mpvpaper")
                self._guard("live", True); sw.set_active(False); self._guard("live", False)
                return
            vid = (self._last_video() if (self._last_video() and os.path.exists(self._last_video()))
                   else self._first_video())
            if not vid:
                self.toast("Add a video to ~/Videos/live-wallpapers first")
                self._guard("live", True); sw.set_active(False); self._guard("live", False)
                return
            self._start_live(vid)
        else:
            self._stop_live()

    def _start_live(self, path):
        run_bg(["bash", LIVE_SH, "start", path])
        self.toast(f"Live wallpaper → {os.path.basename(path)}")
        log(f"live start {path}")
        GLib.timeout_add(1600, lambda: (self._update_live_ui(), False)[1])

    def _stop_live(self):
        run_log(["bash", LIVE_SH, "stop"], "stop live wallpaper")
        self.toast("Live wallpaper off — static restored")
        GLib.timeout_add(1200, lambda: (self._update_live_ui(), False)[1])

    def _kill_live_quiet(self):
        run(["pkill", "-f", "mpvpaper-powersave.sh"])
        run(["pkill", "-x", "mpvpaper"])
        try:
            os.remove(os.path.join(GLib.get_user_runtime_dir(), "mpvpaper.sock"))
        except OSError:
            pass
        try:
            with open(os.path.join(CONF_DIR, "live-wallpaper.conf"), "w") as f:
                f.write("ENABLED=0\n")
        except OSError:
            pass

    def _choose_video(self):
        dlg = Gtk.FileDialog(title="Choose live-wallpaper video")
        flt = Gtk.FileFilter(); flt.set_name("Videos")
        for m in ("video/mp4", "video/x-matroska", "video/webm", "video/quicktime"):
            flt.add_mime_type(m)
        dlg.set_default_filter(flt)
        dlg.open(self, None, self._on_video_chosen)

    def _on_video_chosen(self, dlg, res):
        try:
            f = dlg.open_finish(res)
        except GLib.Error:
            return
        if f and f.get_path():
            self._start_live(f.get_path())

    # ----- static image -----
    def _set_image(self, path):
        # Stop any live wallpaper first, otherwise it draws on top and the image
        # never shows — this was the "wallpaper won't change" bug.
        self._kill_live_quiet()
        run_bg([HYDE_SHELL, "wallpaper", "-s", path])
        self.toast(f"Wallpaper → {os.path.basename(path)}")
        log(f"set image {path}")
        GLib.timeout_add(800, lambda: (self._update_live_ui(), False)[1])

    def _choose_image(self):
        dlg = Gtk.FileDialog(title="Choose wallpaper image")
        flt = Gtk.FileFilter(); flt.set_name("Images")
        for m in ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"):
            flt.add_mime_type(m)
        dlg.set_default_filter(flt)
        dlg.open(self, None, self._on_image_chosen)

    def _on_image_chosen(self, dlg, res):
        try:
            f = dlg.open_finish(res)
        except GLib.Error:
            return
        if f and f.get_path():
            self._set_image(f.get_path())

    # ----- theme wallpaper gallery -----
    def _on_theme_expand(self, exp, _pspec):
        if exp.get_expanded() and not exp._loaded:
            exp._loaded = True
            self._load_theme_thumbs(exp)

    def _load_theme_thumbs(self, exp):
        wdir = os.path.join(THEMES_DIR, exp._theme, "wallpapers")
        try:
            files = sorted(f for f in os.listdir(wdir)
                           if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
        except FileNotFoundError:
            files = []
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                           min_children_per_line=2, homogeneous=True, column_spacing=6,
                           row_spacing=6, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        for fn in files:
            path = os.path.join(wdir, fn)
            btn = Gtk.Button(has_frame=False, tooltip_text=fn)
            btn.add_css_class("flat")
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER,
                              width_request=148, height_request=83)
            pic.add_css_class("card")
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 296, 166, False)
                pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
            except Exception:  # noqa: BLE001
                continue
            btn.set_child(pic)
            btn.connect("clicked", (lambda p: lambda *_: self._set_image(p))(path))
            flow.append(btn)
        exp.add_row(flow)

    # ===== Connectivity (Wi-Fi + Bluetooth) =====
    def _connectivity_page(self):
        page = Adw.PreferencesPage(title="Connectivity", icon_name="network-wireless-symbolic")

        gw = Adw.PreferencesGroup(title="Wi-Fi")
        page.add(gw)
        self.sw_wifi = Adw.SwitchRow(title="Wi-Fi", subtitle=self._wifi_status())
        self.sw_wifi.set_active(run(["nmcli", "radio", "wifi"]).stdout.strip() == "enabled")
        self.sw_wifi.connect("notify::active", self._on_wifi)
        gw.add(self.sw_wifi)
        self._row_button(gw, "Show password", "", "View", self._show_wifi_password)
        if have("nm-connection-editor"):
            self._row_button(gw, "Manage networks", "", "Open",
                             lambda: run_bg(["nm-connection-editor"]))
        else:
            self._row_button(gw, "Manage networks", "", "Open",
                             lambda: run_bg(["kitty", "-e", "nmtui"]))

        gb = Adw.PreferencesGroup(title="Bluetooth")
        page.add(gb)
        self.sw_bt = Adw.SwitchRow(title="Bluetooth", subtitle=self._bt_status())
        self.sw_bt.set_active(self._bt_powered())
        self.sw_bt.connect("notify::active", self._on_bt)
        gb.add(self.sw_bt)
        if have("blueman-manager"):
            self._row_button(gb, "Manage devices", "", "Open",
                             lambda: run_bg(["blueman-manager"]))
        return page

    def _wifi_status(self):
        # Use active connections (instant) instead of `dev wifi`, which triggers
        # a Wi-Fi scan that can block for several seconds on launch.
        cp = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
        for line in cp.stdout.splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) == 2 and "wireless" in parts[1]:
                return "Connected to " + parts[0]
        return "Not connected"

    def _active_wifi_name(self):
        cp = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
        for line in cp.stdout.splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) == 2 and "wireless" in parts[1]:
                return parts[0]
        return None

    def _show_wifi_password(self):
        name = self._active_wifi_name()
        if not name:
            self.toast("Not connected to Wi-Fi")
            return
        cp = run(["nmcli", "-s", "-g", "802-11-wireless-security.psk", "connection", "show", name])
        psk = (cp.stdout or "").strip()
        if not psk:
            self.toast(f"No stored password for “{name}” (open network, or needs authorization)")
            return
        dlg = Adw.AlertDialog(heading=f"Wi-Fi — {name}", body=f"Password:  {psk}")
        dlg.add_response("close", "Close")
        dlg.add_response("copy", "Copy")
        dlg.set_default_response("copy")
        dlg.connect("response", self._on_wifi_pw_response, psk)
        dlg.present(self)
        log(f"revealed wifi password for {name}")

    def _on_wifi_pw_response(self, _dlg, response, psk):
        if response == "copy":
            self.get_clipboard().set(psk)
            self.toast("Password copied")

    def _on_wifi(self, row, _):
        run_log(["nmcli", "radio", "wifi", "on" if row.get_active() else "off"], "wifi toggle")
        GLib.timeout_add(1200, lambda: (row.set_subtitle(self._wifi_status()), False)[1])
        self.toast("Wi-Fi " + ("on" if row.get_active() else "off"))

    def _bt_powered(self):
        return "Powered: yes" in run(["bluetoothctl", "show"]).stdout

    def _bt_status(self):
        return "On" if self._bt_powered() else "Off"

    def _on_bt(self, row, _):
        run_log(["bluetoothctl", "power", "on" if row.get_active() else "off"], "bt toggle")
        GLib.timeout_add(800, lambda: (row.set_subtitle(self._bt_status()), False)[1])
        self.toast("Bluetooth " + ("on" if row.get_active() else "off"))

    # ===== Date & Time =====
    def _datetime_page(self):
        page = Adw.PreferencesPage(title="Date & Time", icon_name="x-office-calendar-symbolic")

        g = Adw.PreferencesGroup()
        page.add(g)
        self.row_clock = Adw.ActionRow()
        g.add(self.row_clock)
        self._tick_clock()
        GLib.timeout_add_seconds(1, self._tick_clock)

        cal_row = Adw.PreferencesGroup()
        page.add(cal_row)
        cal = Gtk.Calendar(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        box = Gtk.Box(halign=Gtk.Align.CENTER)
        box.append(cal)
        cal_row.add(box)

        g2 = Adw.PreferencesGroup()
        page.add(g2)
        self.sw_ntp = Adw.SwitchRow(title="Automatic time")
        self.sw_ntp.set_active(run(["timedatectl", "show", "-p", "NTP", "--value"]).stdout.strip() == "yes")
        self.sw_ntp.connect("notify::active", self._on_ntp)
        g2.add(self.sw_ntp)

        tzs = run(["timedatectl", "list-timezones"]).stdout.split()
        if tzs:
            self.combo_tz = Adw.ComboRow(title="Time zone")
            self.combo_tz.set_model(Gtk.StringList.new(tzs))
            try:
                self.combo_tz.set_enable_search(True)
            except Exception:  # noqa: BLE001
                pass
            cur = run(["timedatectl", "show", "-p", "Timezone", "--value"]).stdout.strip()
            if cur in tzs:
                self.combo_tz.set_selected(tzs.index(cur))
            self._tzs = tzs
            self._guard("tz", True)
            self.combo_tz.connect("notify::selected", self._on_tz)
            self._guard("tz", False)
            self._scroll_combo(self.combo_tz)
            g2.add(self.combo_tz)
        return page

    def _tick_clock(self):
        now = datetime.datetime.now()
        self.row_clock.set_title(now.strftime("%H:%M:%S"))
        self.row_clock.set_subtitle(now.strftime("%A, %d %B %Y"))
        return True

    def _on_ntp(self, row, _):
        run_log(["timedatectl", "set-ntp", "true" if row.get_active() else "false"], "set-ntp")
        self.toast("Automatic time " + ("on" if row.get_active() else "off"))

    def _on_tz(self, combo, _):
        if self._guarded("tz"):
            return
        tz = self._tzs[combo.get_selected()]
        run_log(["timedatectl", "set-timezone", tz], "set-timezone")
        self.toast(f"Time zone → {tz}")

    # ===== Battery =====
    def _battery_page(self):
        page = Adw.PreferencesPage(title="Battery", icon_name="battery-good-symbolic")
        info = battery_info()
        if not info:
            g = Adw.PreferencesGroup(title="Battery")
            g.add(Adw.ActionRow(title="No battery detected"))
            page.add(g)
            return page

        g = Adw.PreferencesGroup(title="Status")
        page.add(g)
        self.row_charge = Adw.ActionRow(title="Charge")
        g.add(self.row_charge)
        self.row_pdraw = Adw.ActionRow(title="Power draw")
        g.add(self.row_pdraw)

        # Power-draw live graph
        gg = Adw.PreferencesGroup(title="Power draw")
        page.add(gg)
        self.spark = Sparkline()
        frame = Gtk.Frame()
        frame.add_css_class("view")
        box = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        box.append(self.spark)
        frame.set_child(box)
        gg.add(frame)

        # Health
        gh = Adw.PreferencesGroup(title="Health")
        page.add(gh)
        unit = "mAh" if info["is_charge"] else "mWh"
        sub = (f"{info['full'] // 1000} / {info['design'] // 1000} {unit}"
               if info["full"] and info["design"] else "unknown")
        if info["cycles"] is not None:
            sub += f" · {info['cycles']} cycles"
        gh.add(Adw.ActionRow(title=f"Health: {info['health']}%" if info['health'] else "Health: unknown",
                             subtitle=sub))
        bar = Gtk.LevelBar(min_value=0, max_value=100, value=info["health"] or 0,
                           hexpand=True, margin_top=4, margin_bottom=8, margin_start=12, margin_end=12)
        gh.add(bar)

        # Power mode
        gm = Adw.PreferencesGroup(title="Power mode")
        page.add(gm)
        profs = power_profiles()
        if profs:
            labels = {"power-saver": "Power saver", "balanced": "Balanced", "performance": "Performance"}
            self._profs = profs
            self.combo_prof = Adw.ComboRow(title="Profile")
            self.combo_prof.set_model(Gtk.StringList.new([labels.get(p, p) for p in profs]))
            cur = current_profile()
            if cur in profs:
                self.combo_prof.set_selected(profs.index(cur))
            self._guard("prof", True)
            self.combo_prof.connect("notify::selected", self._on_profile)
            self._guard("prof", False)
            self._scroll_combo(self.combo_prof)
            gm.add(self.combo_prof)
        else:
            gm.add(Adw.ActionRow(title="power-profiles-daemon not available"))

        # Top processes (CPU as a lightweight power proxy)
        gt = Adw.PreferencesGroup(title="Top processes")
        page.add(gt)
        self._proc_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                                      margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
        gt.add(self._proc_rows_box)
        refresh = Adw.ActionRow(title="Refresh")
        rb = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        rb.connect("clicked", lambda *_: self._refresh_procs())
        refresh.add_suffix(rb)
        gt.add(refresh)
        self._refresh_procs()

        # live updates
        self._update_battery()
        self._bat_src = GLib.timeout_add_seconds(2, self._update_battery)
        self.connect("close-request", self._stop_battery)
        return page

    def _stop_battery(self, *_):
        src = getattr(self, "_bat_src", 0)
        if src:
            GLib.source_remove(src)
            self._bat_src = 0
        return False

    def _update_battery(self):
        info = battery_info()
        if not info:
            return True
        icon = {"Charging": "⚡", "Discharging": "▼", "Full": "✓"}.get(info["status"], "")
        self.row_charge.set_subtitle(f"{info['capacity']}%  {icon} {info['status']}")
        w = power_watts()
        if w is not None:
            self.row_pdraw.set_subtitle(f"{w:.1f} W")
            self.spark.push(w)
        return True

    def _on_profile(self, combo, _):
        if self._guarded("prof"):
            return
        p = self._profs[combo.get_selected()]
        run_log(["powerprofilesctl", "set", p], "set power profile")
        self.toast(f"Power mode → {p}")

    def _refresh_procs(self):
        child = self._proc_rows_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._proc_rows_box.remove(child)
            child = nxt
        for comm, cpu in top_power_procs(6):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            lbl = Gtk.Label(label=comm, xalign=0, width_chars=16, ellipsize=3)
            lvl = Gtk.LevelBar(min_value=0, max_value=100, value=min(cpu, 100), hexpand=True)
            val = Gtk.Label(label=f"{cpu:.0f}%", xalign=1, width_chars=5)
            row.append(lbl)
            row.append(lvl)
            row.append(val)
            self._proc_rows_box.append(row)

    # ===== Privacy =====
    def _privacy_page(self):
        page = Adw.PreferencesPage(title="Privacy", icon_name="preferences-system-privacy-symbolic")
        g = Adw.PreferencesGroup(
            title="Location")
        page.add(g)
        if geoclue_installed():
            self.sw_loc = Adw.SwitchRow(title="Location services")
            self.sw_loc.set_active(self._location_enabled())
            self.sw_loc.connect("notify::active", self._on_location)
            g.add(self.sw_loc)
        else:
            g.add(Adw.ActionRow(title="Location off",
                                subtitle="GeoClue not installed"))
        return page

    def _location_enabled(self):
        # Masked geoclue service == location off.
        return run(["systemctl", "is-enabled", "geoclue.service"]).stdout.strip() != "masked"

    def _on_location(self, row, _):
        on = row.get_active()
        action = "unmask" if on else "mask"
        run_log(["pkexec", "systemctl", action, "geoclue.service"], f"location {action}")
        self.toast("Location " + ("on" if on else "off") + " (may ask for your password)")

    # ===== Display =====
    def _display_page(self):
        page = Adw.PreferencesPage(title="Display", icon_name="video-display-symbolic")
        g = Adw.PreferencesGroup(title="Monitors")
        page.add(g)
        self._row_button(g, "Arrange displays", "", "Open",
                         lambda: run_bg(["nwg-displays"]), sensitive=have("nwg-displays"))

        self._display_group = Adw.PreferencesGroup(title="Mirror / Extend")
        page.add(self._display_group)
        self._rebuild_display_rows()
        return page

    def _rebuild_display_rows(self):
        grp = self._display_group
        child = grp.get_first_child()
        # Clear previous rows
        for r in list(getattr(self, "_disp_rows", [])):
            grp.remove(r)
        self._disp_rows = []

        mons = monitors()
        names = [m["name"] for m in mons]
        internal = next((m for m in mons if m["name"].startswith("eDP")), mons[0] if mons else None)
        externals = [m for m in mons if internal and m["name"] != internal["name"]]

        refresh = Adw.ActionRow(title="Detected monitors", subtitle=", ".join(names) or "none")
        b = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: (self._rebuild_display_rows(), self.toast("Rescanned monitors")))
        refresh.add_suffix(b)
        grp.add(refresh)
        self._disp_rows.append(refresh)

        if not externals:
            hint = Adw.ActionRow(title="No external screen", subtitle="Plug one in, then refresh")
            grp.add(hint)
            self._disp_rows.append(hint)
            grp.set_description(None)
            return

        ext = externals[0]
        row = Adw.ActionRow(title=f"{internal['name']} ↔ {ext['name']}")
        bb = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        b_ext = Gtk.Button(label="Extend", valign=Gtk.Align.CENTER)
        b_mir = Gtk.Button(label="Mirror", valign=Gtk.Align.CENTER)
        b_ext.connect("clicked", lambda *_: self._extend(ext))
        b_mir.connect("clicked", lambda *_: self._mirror(ext, internal))
        bb.append(b_ext)
        bb.append(b_mir)
        row.add_suffix(bb)
        grp.add(row)
        self._disp_rows.append(row)

    def _mode_of(self, mon):
        # Build a valid "WxH@RR" string from the monitor's current mode.
        try:
            rr = round(float(mon.get("refreshRate", 60)))
            return f'{mon["width"]}x{mon["height"]}@{rr}'
        except Exception:  # noqa: BLE001
            am = mon.get("availableModes") or []
            return re.sub(r"Hz$", "", am[0]) if am else "preferred"

    def _mirror(self, ext, internal):
        mode = self._mode_of(ext)
        cmd = f'hl.monitor({{output="{ext["name"]}", mode="{mode}", position="0x0", scale=1, mirror="{internal["name"]}"}})'
        run_log(["hyprctl", "eval", cmd], "mirror")
        GLib.timeout_add(700, lambda: self._verify_mirror(ext["name"]))
        self.toast(f"Mirroring {internal['name']} → {ext['name']}")

    def _verify_mirror(self, extname):
        m = next((x for x in monitors() if x["name"] == extname), None)
        if m and m.get("mirrorOf") not in (None, "none"):
            self.toast(f"{extname} is mirroring {m['mirrorOf']}")
        else:
            self.toast("Mirror may not have applied — see Logs")
        return False

    def _extend(self, ext):
        mode = self._mode_of(ext)
        cmd = f'hl.monitor({{output="{ext["name"]}", mode="{mode}", position="auto", scale=1}})'
        run_log(["hyprctl", "eval", cmd], "extend")
        self.toast(f"Extended {ext['name']}")

    # ===== Troubleshoot =====
    def _troubleshoot_page(self):
        page = Adw.PreferencesPage(title="Troubleshoot", icon_name="applications-engineering-symbolic")
        g = Adw.PreferencesGroup(title="Waybar")
        page.add(g)
        self._row_button(g, "Show bar", "", "Show",
                         lambda: (ensure_waybar_visible(), self.toast("Bar shown")))
        self._row_button(g, "Restart Waybar", "", "Restart",
                         lambda: (restart_waybar(), self.toast("Waybar restarted")))

        g3 = Adw.PreferencesGroup(title="Status")
        page.add(g3)
        self.row_diag = Adw.ActionRow(title=self._diag_text())
        b = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self.row_diag.set_title(self._diag_text()))
        self.row_diag.add_suffix(b)
        g3.add(self.row_diag)
        return page

    def _restart_autohide(self):
        if read_conf()["ENABLED"]:
            start_daemon()
            self.toast("Auto-hide restarted")
        else:
            self.toast("Auto-hide is off — enable it on the Waybar page")

    def _diag_text(self):
        n = run(["pgrep", "-c", "waybar"]).stdout.strip() or "?"
        vis = "shown" if waybar_visible() else "hidden"
        ah = "running" if daemon_running() else "stopped"
        return f"Waybar procs: {n} · bar {vis} · auto-hide {ah}"

    # ===== Logs =====
    def _logs_page(self):
        page = Adw.PreferencesPage(title="Logs", icon_name="text-x-generic-symbolic")
        g = Adw.PreferencesGroup(title="Action log")
        page.add(g)

        row = Adw.ActionRow(title="Open logs folder")
        bb = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        b_open = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        b_ref = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        b_open.connect("clicked", lambda *_: run_bg(["xdg-open", LOG_DIR]))
        b_ref.connect("clicked", lambda *_: self._load_log())
        bb.append(b_ref)
        bb.append(b_open)
        row.add_suffix(bb)
        g.add(row)

        gl = Adw.PreferencesGroup(title="Recent")
        page.add(gl)
        sw = Gtk.ScrolledWindow(min_content_height=300, vexpand=True)
        sw.add_css_class("card")
        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                     left_margin=8, right_margin=8, top_margin=8, bottom_margin=8)
        sw.set_child(self.log_view)
        gl.add(sw)
        self._load_log()
        return page

    def _load_log(self):
        try:
            with open(ACTIONS_LOG) as f:
                lines = f.readlines()[-200:]
            text = "".join(lines) or "(no actions logged yet)"
        except FileNotFoundError:
            text = "(no actions logged yet)"
        self.log_view.get_buffer().set_text(text)

    # ===== About =====
    def _about_page(self):
        page = Adw.PreferencesPage(title="About", icon_name="help-about-symbolic")
        g = Adw.PreferencesGroup(title="Hyprland Settings")
        page.add(g)

        def ver(cmd):
            cp = run(cmd)
            s = (cp.stdout or cp.stderr).strip()
            return s.splitlines()[0] if s else "—"

        rows = [
            ("Hyprland", ver(["hyprctl", "version"])),
            ("Waybar", ver(["waybar", "--version"])),
        ]
        for title, val in rows:
            r = Adw.ActionRow(title=title, subtitle=val)
            r.set_subtitle_selectable(True)
            g.add(r)
        return page

    # ===== helpers =====
    def _row_button(self, group, title, subtitle, label, cb, sensitive=True):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        btn = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        btn.set_sensitive(sensitive)
        btn.connect("clicked", lambda *_: cb())
        row.add_suffix(btn)
        row.set_activatable_widget(btn)
        group.add(row)
        return row

    def _scroll_combo(self, combo):
        # Change the selection by scrolling the mouse wheel over the dropdown.
        ctl = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)

        def on_scroll(_c, _dx, dy):
            model = combo.get_model()
            n = model.get_n_items() if model else 0
            if n == 0:
                return False
            i = combo.get_selected()
            if dy > 0 and i < n - 1:
                combo.set_selected(i + 1)
            elif dy < 0 and i > 0:
                combo.set_selected(i - 1)
            return True

        ctl.connect("scroll", on_scroll)
        combo.add_controller(ctl)

    def _guard(self, key, val):
        if not hasattr(self, "_guards"):
            self._guards = {}
        self._guards[key] = val

    def _guarded(self, key):
        return getattr(self, "_guards", {}).get(key, False)


class HyprSettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.hyde.HyprSettings",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._provider = None
        self._monitor = None

    def do_activate(self):
        # Follow the user's HyDE dark/light preference.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        self._install_theme()
        self._watch_theme()
        win = self.props.active_window or SettingsWindow(self)
        win.present()

    def _install_theme(self):
        css = theme_css()
        if not css:
            return
        if self._provider is None:
            self._provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self._provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        try:
            self._provider.load_from_string(css)
        except AttributeError:
            self._provider.load_from_data(css.encode())
        log("theme css applied (follows current HyDE theme)")

    def _watch_theme(self):
        # Reload colors live when the HyDE theme changes.
        try:
            f = Gio.File.new_for_path(WALLBASH_GTK)
            self._monitor = f.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_theme_file_changed)
        except Exception as e:  # noqa: BLE001
            log(f"theme watch failed: {e}")

    def _on_theme_file_changed(self, _mon, _f, _o, event):
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                     Gio.FileMonitorEvent.CREATED):
            GLib.timeout_add(300, lambda: (self._install_theme(), False)[1])


if __name__ == "__main__":
    HyprSettingsApp().run(None)
