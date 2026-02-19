# label_app.py — PC Version (Brother P-touch Template over Bluetooth) - file-backed config
from flask import (
    Flask, render_template, render_template_string, request, redirect, url_for,
    flash, jsonify, make_response
)
from datetime import datetime, timedelta
import os, json, threading

# Brother P-touch backend (pure Python; no admin installs)
from printer_brother_pt import (
    list_serial_ports, open_bt_serial, print_delimited, print_named
)
# Items data
try:
    from items import ITEMS
except Exception as e:
    ITEMS = {}
    print("WARNING: Failed to import ITEMS from items.py:", e)

app = Flask(__name__)
app.secret_key = 'label-secret-key'  # change if desired

# -----------------------------------------------------------------------------
# Config (file-backed: app folder first, then %APPDATA%\LabelPrinter\config.json)
# -----------------------------------------------------------------------------
_CFG_LOCK = threading.Lock()

def _pick_config_path() -> str:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    primary = os.path.join(app_dir, "config.json")
    try:
        with open(primary + ".touch", "w", encoding="utf-8") as f:
            f.write("")
        os.remove(primary + ".touch")
        return primary
    except Exception:
        pass
    appdata = os.getenv("APPDATA", app_dir)
    fallback = os.path.join(appdata, "LabelPrinter", "config.json")
    os.makedirs(os.path.dirname(fallback), exist_ok=True)
    return fallback

_CONFIG_PATH = _pick_config_path()

_DEFAULT_CFG = {
    "backend": "brother_pt",
    "com_port": "",           # e.g., "COM6"
    "template_num": 1,        # 1..99
    "pt_mode": "named",       # 'named' or 'delimited'
    "delimiter": ",",
    "obj_names": {            # Named Objects (must match P-touch template)
        "item": "NAME",
        "pulled": "PULLED",
        "expires": "EXPIRES"
    },
    "cut_every": 1
}
#gfhghf
def load_cfg() -> dict:
    with _CFG_LOCK:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        # deep-merge onto defaults
        out = {**_DEFAULT_CFG, **data}
        out["obj_names"] = {**_DEFAULT_CFG["obj_names"], **out.get("obj_names", {})}
        return out

def save_cfg(cfg: dict) -> None:
    with _CFG_LOCK:
        tmp = _CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, _CONFIG_PATH)  # atomic on Windows

# -----------------------------------------------------------------------------
# Business rules → label lines (no seconds)
# -----------------------------------------------------------------------------
def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=0, microsecond=0)

def _fmt(dt: datetime) -> str:
    return dt.strftime("%m/%d %I:%M %p")

def build_lines_for_rule(item_name: str, rule):
    """
    Returns (line2, line3) per your rules:

    - Single number (hours):       ("", "Expires: <now + hours>")
    - "end_of_day":                ("", "Expires: <today 11:59 PM>")
    - ("end_of_day", N days):      ("", "Expires: <today+N @ 11:59 PM>")
    - (H_thaw, H_expire):
        * if item == American Cheese - ON LINE:
              ("Tempered: <now+H_thaw>", "Expires: <now+H_expire>")
          else:
              ("Thawed:   <now+H_thaw>", "Expires: <now+H_expire>")
    """
    now = datetime.now()

    if isinstance(rule, (int, float)):
        t = now + timedelta(hours=float(rule))
        return ("", f"Expires: {_fmt(t)}")

    if isinstance(rule, str) and rule == "end_of_day":
        t = _end_of_day(now)
        return ("", f"Expires: {_fmt(t)}")

    if isinstance(rule, tuple) and len(rule) == 2:
        a, b = rule
        if isinstance(a, str) and a == "end_of_day":
            t = _end_of_day(now) + timedelta(days=int(b))
            return ("", f"Expires: {_fmt(t)}")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            t1 = now + timedelta(hours=float(a))
            t2 = now + timedelta(hours=float(b))
            if item_name.strip().lower() == "american cheese - on line":
                return (f"Tempered: {_fmt(t1)}", f"Expires: {_fmt(t2)}")
            else:
                return (f"Thawed: {_fmt(t1)}", f"Expires: {_fmt(t2)}")

    raise ValueError(f"Unsupported rule for {item_name}: {rule!r}")

def make_delimited_values(item_name: str, rule):
    line2, line3 = build_lines_for_rule(item_name, rule)
    if not line2:
        line2 = " "  # force-blank to overwrite any default template text
    return [item_name, line2, line3]

def make_named_fields(item_name: str, rule, cfg: dict):
    line2, line3 = build_lines_for_rule(item_name, rule)
    if not line2:
        line2 = " "
    names = cfg["obj_names"]
    return {
        names["item"]:    item_name,
        names["pulled"]:  line2,
        names["expires"]: line3
    }

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/")
def index_get():
    cfg = load_cfg()
    return render_template("label.html", items=ITEMS, com_port=cfg["com_port"])

@app.post("/")
def index_post():
    cfg = load_cfg()
    try:
        qty = int(request.form.get("quantity", "1"))
        if qty < 1: qty = 1

        raw = request.form.get("item")
        if not raw:
            raise RuntimeError("No item selected.")
        category, selected_item = raw.split("||", 1)

        rule = ITEMS.get(category, {}).get(selected_item)
        if rule is None:
            raise RuntimeError(f"Item not found in category: {category} / {selected_item}")

        if cfg.get("backend") != "brother_pt":
            raise RuntimeError("Backend must be 'brother_pt' (see Setup).")

        port = cfg.get("com_port", "").strip()
        if not port:
            raise RuntimeError("No COM port set. Open Setup and Save a COM port.")

        template_num = int(cfg.get("template_num", 1))
        pt_mode      = cfg.get("pt_mode", "named")
        delimiter    = cfg.get("delimiter", ",")

        with open_bt_serial(port) as ser:
            for _ in range(qty):
                if pt_mode == "delimited":
                    values = make_delimited_values(selected_item, rule)
                    print_delimited(
                        ser, template_num, values,
                        delimiter=delimiter, auto_cut=True,
                        cut_every=int(cfg.get("cut_every", 1))
                    )
                else:
                    fields = make_named_fields(selected_item, rule, cfg)
                    print_named(
                        ser, template_num, fields,
                        auto_cut=True, cut_every=int(cfg.get("cut_every", 1))
                    )

        flash(f"Printed {qty} label(s) for '{selected_item}' on {port}.", "success")
    except Exception as e:
        flash(str(e), "error")

    return redirect(url_for("index_get"))

@app.get("/setup")
def setup_get():
    cfg = load_cfg()
    return render_template("setup.html",
                           com_port=cfg["com_port"],
                           template_num=cfg["template_num"],
                           mode=cfg["pt_mode"],
                           delimiter=cfg["delimiter"],
                           obj_item=cfg["obj_names"]["item"],
                           obj_pulled=cfg["obj_names"]["pulled"],
                           obj_expires=cfg["obj_names"]["expires"],
                           cut_every=cfg["cut_every"])

@app.post("/setup/save")
def setup_save():
    cfg = load_cfg()
    try:
        cfg["com_port"] = (request.form.get("comPort") or request.form.get("com_port") or cfg["com_port"]).strip()
        tpl = request.form.get("template") or request.form.get("template_num")
        if tpl:
            cfg["template_num"] = int(tpl)
        mode = (request.form.get("mode") or request.form.get("pt_mode") or cfg["pt_mode"]).strip().lower()
        cfg["pt_mode"] = mode if mode in ("named", "delimited") else "named"
        cfg["delimiter"] = (request.form.get("delimiter") or cfg["delimiter"]).strip() or ","
        cfg["obj_names"]["item"]    = (request.form.get("obj_item") or cfg["obj_names"]["item"]).strip() or "NAME"
        cfg["obj_names"]["pulled"]  = (request.form.get("obj_pulled") or cfg["obj_names"]["pulled"]).strip() or "PULLED"
        cfg["obj_names"]["expires"] = (request.form.get("obj_expires") or cfg["obj_names"]["expires"]).strip() or "EXPIRES"
        ce = request.form.get("cut_every")
        if ce:
            cfg["cut_every"] = max(1, int(ce))
        save_cfg(cfg)
        flash("Saved.", "success")
    except Exception as e:
        flash(f"Save failed: {e}", "error")
    return redirect(url_for("setup_get"))

@app.get("/api/serial_ports")
def api_serial_ports():
    try:
        names, preferred = list_serial_ports()
        return jsonify(ok=True, ports=names, preferred=preferred)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@app.post("/pt/probe")
def pt_probe():
    data = request.get_json(force=True, silent=True) or {}
    cfg = load_cfg()
    port  = (data.get("com_port") or cfg.get("com_port") or "").strip()
    if not port:
        return jsonify(success=False, error="No COM port set."), 400
    tpl   = int(data.get("template_num") or cfg.get("template_num", 1))
    mode  = (data.get("pt_mode") or cfg.get("pt_mode", "named")).lower()

    # Use a real item/rule if available so the test mimics actual printing
    category = data.get("category") or (list(ITEMS.keys())[0] if ITEMS else "")
    item     = data.get("item") or (list(ITEMS.get(category, {}).keys())[0] if category else "Sample")
    rule     = (ITEMS.get(category, {}) or {}).get(item, 4)

    try:
        with open_bt_serial(port) as ser:
            if mode == "delimited":
                values = make_delimited_values(item, rule)
                print_delimited(ser, tpl, values, delimiter=cfg.get("delimiter", ","), auto_cut=True, cut_every=1)
            else:
                fields = make_named_fields(item, rule, cfg)
                print_named(ser, tpl, fields, auto_cut=True, cut_every=1)
        return jsonify(success=True, message=f"Probe print on {port}, template {tpl}, mode {mode}.")
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@app.post("/pt/test-port")
def pt_test_port():
    port = (request.get_json(silent=True) or {}).get("com_port") or load_cfg().get("com_port")
    if not port:
        return jsonify(success=False, error="No COM port set."), 400
    try:
        with open_bt_serial(port) as _:
            pass
        return jsonify(success=True, message=f"Opened {port} OK.")
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------
def run_app():
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=5000)
    except Exception:
        app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == "__main__":
    run_app()
