import base64
import hashlib
import io
import json
import math
import os
import re
from datetime import datetime, time, date, timezone as datetime_timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import time as _time
import requests
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

import folium
from streamlit_folium import st_folium

# Optional: static map for PDF
try:
    from staticmap import StaticMap, CircleMarker

    STATICMAP_AVAILABLE = True
except ImportError:
    STATICMAP_AVAILABLE = False

# Optional: browser GPS
try:
    from streamlit_js_eval import get_geolocation

    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

# ---------- Database functions for storing/loading reports ----------
REPORTS_DIR = Path(__file__).parent / "data" / "reports"


def ensure_reports_directory():
    """Ensure the reports directory exists."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(text):
    """Sanitize text for use in filenames."""
    # Replace spaces and special characters
    import re
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:50]  # Limit length


def encode_binary_data(site_record):
    """Encode binary data (photos, diagrams) to base64 for JSON storage."""
    encoded = site_record.copy()
    
    # Encode diagram
    if encoded.get("diagram") and encoded["diagram"].get("data"):
        encoded["diagram"] = encoded["diagram"].copy()
        encoded["diagram"]["data"] = base64.b64encode(
            encoded["diagram"]["data"]
        ).decode("utf-8")
    
    # Encode photos
    if encoded.get("photos"):
        encoded["photos"] = []
        for photo in site_record["photos"]:
            photo_copy = photo.copy()
            if photo_copy.get("data"):
                photo_copy["data"] = base64.b64encode(photo_copy["data"]).decode("utf-8")
            encoded["photos"].append(photo_copy)
    
    return encoded


def decode_binary_data(site_record):
    """Decode base64 binary data back to bytes."""
    decoded = site_record.copy()
    
    # Decode diagram
    if decoded.get("diagram") and decoded["diagram"].get("data"):
        decoded["diagram"] = decoded["diagram"].copy()
        try:
            decoded["diagram"]["data"] = base64.b64decode(decoded["diagram"]["data"])
        except Exception:
            decoded["diagram"]["data"] = b""
    
    # Decode photos
    if decoded.get("photos"):
        decoded["photos"] = []
        for photo in site_record["photos"]:
            photo_copy = photo.copy()
            if photo_copy.get("data"):
                try:
                    photo_copy["data"] = base64.b64decode(photo_copy["data"])
                except Exception:
                    photo_copy["data"] = b""
            decoded["photos"].append(photo_copy)
    
    return decoded


def save_report_to_database(site_record):
    """Save a site report to the database as a JSON file."""
    ensure_reports_directory()
    
    # Generate filename
    project = sanitize_filename(site_record.get("project_name", "unknown"))
    site = sanitize_filename(site_record.get("site_name", "unknown"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{project}_{site}_{timestamp}.json"
    filepath = REPORTS_DIR / filename
    
    # Encode binary data
    encoded_record = encode_binary_data(site_record)
    
    # Save to JSON
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(encoded_record, f, indent=2, default=str)
    
    return filename


def load_all_reports():
    """Load all reports from the database."""
    ensure_reports_directory()
    
    reports = []
    for filepath in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Decode binary data
                decoded = decode_binary_data(data)
                decoded["_filename"] = filepath.name
                decoded["_filepath"] = str(filepath)
                reports.append(decoded)
        except Exception as e:
            st.warning(f"Could not load {filepath.name}: {e}")
    
    return reports


def delete_report_from_database(filename):
    """Delete a report from the database."""
    filepath = REPORTS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return True
    return False


def get_report_summary(report):
    """Get a summary string for a report."""
    project = report.get("project_name", "Unknown Project")
    site = report.get("site_name", "Unknown Site")
    date_str = report.get("install_date", "Unknown Date")
    return f"{project} - {site} ({date_str})"
# Offset between the header bar and the start of body content on each page
HEADER_CONTENT_OFFSET = 60 * mm


# ---------- Canvas with "page x of y" ----------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_page_number(self, page_count):
        self.setFont("Helvetica", 8)
        self.setFillGray(0.3)
        text = f"{self._pageNumber} of {page_count}"
        width = self._pagesize[0]
        self.drawCentredString(width / 2.0, 8 * mm, text)


# ---------- Hydraulics helpers ----------
def wetted_area_circular_m2(depth_mm, diameter_mm):
    """Wetted area of a partially full circular pipe (m²)."""
    if diameter_mm <= 0 or depth_mm <= 0:
        return 0.0

    D = diameter_mm / 1000.0
    r = D / 2.0
    h = depth_mm / 1000.0

    if h >= D:
        return math.pi * r * r

    return r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(2 * r * h - h * h)


def calculate_average_depth_velocity_and_flow(
    pipe_diameter_mm,
    depth_primary_meas,
    depth_primary_meter,
    vel_primary_meas,
    vel_primary_meter,
    extra_readings,
):
    """Average all depth/velocity readings and calculate flow in L/s."""
    d_meas = [depth_primary_meas] if depth_primary_meas > 0 else []
    d_meter = [depth_primary_meter] if depth_primary_meter > 0 else []
    v_meas = [vel_primary_meas] if vel_primary_meas > 0 else []
    v_meter = [vel_primary_meter] if vel_primary_meter > 0 else []

    for r in extra_readings or []:
        if r.get("depth_meas_mm", 0) > 0:
            d_meas.append(r["depth_meas_mm"])
        if r.get("depth_meter_mm", 0) > 0:
            d_meter.append(r["depth_meter_mm"])
        if r.get("vel_meas_ms", 0.0) > 0:
            v_meas.append(r["vel_meas_ms"])
        if r.get("vel_meter_ms", 0.0) > 0:
            v_meter.append(r["vel_meter_ms"])

    def _avg(lst):
        return float(sum(lst) / len(lst)) if lst else 0.0

    avg_d_meas = _avg(d_meas)
    avg_d_meter = _avg(d_meter)
    avg_v_meas = _avg(v_meas)
    avg_v_meter = _avg(v_meter)

    area_meas = wetted_area_circular_m2(avg_d_meas, pipe_diameter_mm)
    area_meter = wetted_area_circular_m2(avg_d_meter, pipe_diameter_mm)

    q_meas = area_meas * avg_v_meas * 1000.0
    q_meter = area_meter * avg_v_meter * 1000.0
    q_diff = q_meter - q_meas
    q_diff_pct = (q_diff / q_meas * 100.0) if q_meas else 0.0

    return {
        "avg_depth_meas_mm": avg_d_meas,
        "avg_depth_meter_mm": avg_d_meter,
        "avg_vel_meas_ms": avg_v_meas,
        "avg_vel_meter_ms": avg_v_meter,
        "flow_meas_lps": q_meas,
        "flow_meter_lps": q_meter,
        "flow_diff_lps": q_diff,
        "flow_diff_percent": q_diff_pct,
    }


# ---------- Static site map for PDF ----------
def create_site_map_bytes(lat_str, lon_str, zoom=19, width_px=600, height_px=400):
    """Zoomed-in static map for PDF."""
    if not STATICMAP_AVAILABLE:
        return None
    try:
        lat = float(str(lat_str).strip())
        lon = float(str(lon_str).strip())
    except Exception:
        return None

    try:
        m = StaticMap(
            width_px,
            height_px,
            url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        )
        marker = CircleMarker((lon, lat), "red", 12)
        m.add_marker(marker)
        im = m.render(zoom=zoom)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


# ---------- PDF layout helpers ----------
def draw_header_bar(c, width, project, site_id, site_name):
    margin = 20 * mm
    bar_height = 18 * mm
    c.setFillColor(HexColor("#3d9991"))
    c.rect(0, A4[1] - bar_height, width, bar_height, fill=1, stroke=0)

    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, A4[1] - bar_height + 5 * mm, (project or "")[:80])

    c.setFont("Helvetica", 10)
    right_text = f"{site_id} – {site_name}".strip(" –")
    c.drawRightString(width - margin, A4[1] - bar_height + 5 * mm, right_text)

    c.setFillGray(0.0)


def draw_footer(c, width, client, site_name):
    margin = 20 * mm
    y = 14 * mm
    c.setFont("Helvetica", 8)
    c.setFillGray(0.3)

    left_text = "Environmental Data Services – www.e-d-s.com.au | 1300 721 683"
    client_short = (client or "")[:40]
    site_short = (site_name or "")[:40]
    right_text = f"Client: {client_short} | Site: {site_short}".strip(" |")

    c.drawString(margin, y, left_text)
    c.drawRightString(width - margin, y, right_text)


def draw_section_title(c, text, x, y):
    c.setFont("Helvetica-Bold", 11)
    c.setFillGray(0.1)
    c.drawString(x, y, text)
    c.setLineWidth(0.6)
    c.setStrokeGray(0.6)
    c.line(x, y - 2, x + 170 * mm, y - 2)


def draw_wrapped_kv(
    c,
    label,
    value,
    x,
    y,
    line_height,
    width_label=35 * mm,
    max_width=170 * mm,
    font_size=9,
):
    if value is None:
        value = ""
    value = str(value)

    if label:
        c.setFont("Helvetica-Bold", font_size)
        c.setFillGray(0.1)
        c.drawString(x, y, f"{label}:")
        text_x = x + width_label
    else:
        text_x = x + 5 * mm

    c.setFont("Helvetica", font_size)
    c.setFillGray(0.0)

    max_text_width = max_width - (text_x - x)
    words = value.split()
    if not words:
        return y - line_height

    line = ""
    y_out = y
    for w in words:
        test_line = (line + " " + w).strip()
        w_width = stringWidth(test_line, "Helvetica", font_size)
        if w_width <= max_text_width:
            line = test_line
        else:
            c.drawString(text_x, y_out, line)
            y_out -= line_height
            line = w
    if line:
        c.drawString(text_x, y_out, line)
        y_out -= line_height

    return y_out - 0.3 * line_height


# ---------- Per-site PDF pages ----------
def draw_site_main_page(c, site, width, height):
    margin = 22 * mm
    line_height = 6 * mm

    draw_header_bar(
        c,
        width,
        site.get("project_name", "Project"),
        site.get("site_id", ""),
        site.get("site_name", ""),
    )
    y = height - HEADER_CONTENT_OFFSET

    # 1. Project details
    draw_section_title(c, "1. Project", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(c, "Client", site.get("client", ""), margin, y, line_height)
    y = draw_wrapped_kv(
        c, "Catchment", site.get("catchment", ""), margin, y, line_height
    )
    y = draw_wrapped_kv(
        c,
        "Install date/time",
        f"{site.get('install_date','')} {site.get('install_time','')}",
        margin,
        y,
        line_height,
    )
    asset_line = (
        f"Client asset ID: {site.get('client_asset_id','')}  |  "
        f"GIS ID: {site.get('gis_id','')}"
    )
    y = draw_wrapped_kv(c, "Asset IDs", asset_line, margin, y, line_height)
    gps_line = f"Lat {site.get('gps_lat','')}  |  Lon {site.get('gps_lon','')}"
    y = draw_wrapped_kv(c, "GPS", gps_line, margin, y, line_height)
    if site.get("site_address"):
        y = draw_wrapped_kv(
            c, "Site address", site.get("site_address", ""), margin, y, line_height
        )
    y -= line_height * 0.5

    # 2. Manhole, location & safety
    draw_section_title(c, "2. Manhole, Location & Safety", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(
        c,
        "Location description",
        site.get("manhole_location_desc", ""),
        margin,
        y,
        line_height,
    )
    loc_line = (
        f"{site.get('access_type','')} | "
        f"Confined space: {'Yes' if site.get('confined_space_required') else 'No'}; "
        f"Traffic control: {'Yes' if site.get('traffic_control_required') else 'No'}"
    )
    y = draw_wrapped_kv(c, "Access / permits", loc_line, margin, y, line_height)
    y = draw_wrapped_kv(
        c,
        "Safety constraints",
        site.get("access_safety_constraints", ""),
        margin,
        y,
        line_height,
    )
    if site.get("other_permits_required"):
        y = draw_wrapped_kv(
            c,
            "Other permits",
            site.get("other_permits_required", ""),
            margin,
            y,
            line_height,
        )
    y -= line_height * 0.5

    # 3. Pipe & hydraulics
    draw_section_title(c, "3. Pipe & Hydraulic Assessment", margin, y)
    y -= line_height * 1.5
    pipe_desc = (
        f"{site.get('pipe_diameter_mm','')} mm, "
        f"{site.get('pipe_material','')}, "
        f"{site.get('pipe_shape','')}"
    )
    y = draw_wrapped_kv(c, "Pipe", pipe_desc, margin, y, line_height)

    inv_line = f"Invert depth: {site.get('depth_to_invert_mm','')} mm"
    soffit = site.get("depth_to_soffit_mm", "")
    if soffit not in ("", None):
        inv_line += f"; Soffit: {soffit} mm"
    y = draw_wrapped_kv(c, "Depths", inv_line, margin, y, line_height)

    y = draw_wrapped_kv(
        c,
        "Upstream config",
        site.get("upstream_config", ""),
        margin,
        y,
        line_height,
    )
    y = draw_wrapped_kv(
        c,
        "Downstream config",
        site.get("downstream_config", ""),
        margin,
        y,
        line_height,
    )

    drops = "Yes" if site.get("hydro_drops") else "No"
    bends = "Yes" if site.get("hydro_bends") else "No"
    juncs = "Yes" if site.get("hydro_junctions") else "No"
    surch = "Yes" if site.get("hydro_surcharge_risk") else "No"
    backw = "Yes" if site.get("hydro_backwater_risk") else "No"
    hydro_line1 = (
        f"Turbulence: {site.get('hydro_turbulence_level','')} | "
        f"Drops near meter: {drops}; Bends near meter: {bends}; "
        f"Junctions within 5D: {juncs}"
    )
    hydro_line2 = f"Surcharge risk: {surch}; Backwater risk: {backw}"
    y = draw_wrapped_kv(c, "Hydraulics (1)", hydro_line1, margin, y, line_height)
    y = draw_wrapped_kv(c, "Hydraulics (2)", hydro_line2, margin, y, line_height)
    y = draw_wrapped_kv(
        c,
        "Hydraulic comments",
        site.get("hydraulic_notes", ""),
        margin,
        y,
        line_height,
    )

    draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
    c.showPage()


def draw_site_commissioning_page(c, site, width, height):
    margin = 22 * mm
    line_height = 6 * mm
    min_y_threshold = 40 * mm  # Minimum Y before forcing page break
    
    def check_page_break(y_current, space_needed=10 * mm):
        """Check if we need a page break and create one if necessary."""
        if y_current - space_needed < min_y_threshold:
            draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
            c.showPage()
            draw_header_bar(
                c,
                width,
                site.get("project_name", "Project"),
                site.get("site_id", ""),
                site.get("site_name", ""),
            )
            return height - HEADER_CONTENT_OFFSET
        return y_current

    draw_header_bar(
        c,
        width,
        site.get("project_name", "Project"),
        site.get("site_id", ""),
        site.get("site_name", ""),
    )
    y = height - HEADER_CONTENT_OFFSET

    # 4. Meter, sensor & configuration
    draw_section_title(c, "4. Meter, Sensor & Configuration", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(
        c, "Meter model", site.get("meter_model", ""), margin, y, line_height
    )
    y = draw_wrapped_kv(
        c, "Logger serial", site.get("logger_serial", ""), margin, y, line_height
    )
    y = draw_wrapped_kv(
        c, "Sensor serial", site.get("sensor_serial", ""), margin, y, line_height
    )
    pos_line = (
        f"{site.get('sensor_distance_from_manhole_m','')} m from manhole; "
        f"Orientation: {site.get('sensor_orientation','')}; "
        f"Mount: {site.get('sensor_mount_type','')}"
    )
    y = draw_wrapped_kv(c, "Sensor position", pos_line, margin, y, line_height)
    y = draw_wrapped_kv(
        c,
        "Datum reference",
        site.get("datum_reference_desc", ""),
        margin,
        y,
        line_height,
    )

    cfg_line1 = (
        f"Level range: {site.get('level_range_min_mm','')}–"
        f"{site.get('level_range_max_mm','')} mm; "
        f"Velocity range: {site.get('velocity_range_min_ms','')}–"
        f"{site.get('velocity_range_max_ms','')} m/s"
    )
    y = draw_wrapped_kv(c, "Ranges", cfg_line1, margin, y, line_height)
    y = draw_wrapped_kv(
        c,
        "Output scaling",
        site.get("output_scaling_desc", ""),
        margin,
        y,
        line_height,
    )

    telem_line1 = (
        f"Comms: {site.get('comms_method','')}; "
        f"Logger ID: {site.get('telemetry_logger_id','')}"
    )
    telem_line2 = (
        f"Platform: {site.get('telemetry_server','')}; "
        f"Notes: {site.get('telemetry_notes','')}"
    )
    y = draw_wrapped_kv(c, "Telemetry (1)", telem_line1, margin, y, line_height)
    y = draw_wrapped_kv(c, "Telemetry (2)", telem_line2, margin, y, line_height)

    log_line = (
        f"Logging interval: {site.get('logging_interval_min','')} min; "
        f"Time zone: {site.get('timezone','')}"
    )
    y = draw_wrapped_kv(c, "Logging", log_line, margin, y, line_height)
    y -= line_height * 0.5

    # 5. Commissioning checks
    y = check_page_break(y, space_needed=30 * mm)
    draw_section_title(c, "5. Commissioning Checks", margin, y)
    y -= line_height * 1.5
    depth_line = (
        f"Measured: {site.get('depth_check_meas_mm','')} mm, "
        f"Meter: {site.get('depth_check_meter_mm','')} mm, "
        f"Diff: {site.get('depth_check_diff_mm','')} mm, "
        f"Within tolerance: {site.get('depth_check_within_tol','')}"
    )
    y = draw_wrapped_kv(c, "Depth", depth_line, margin, y, line_height)
    vel_line = (
        f"Measured: {site.get('vel_check_meas_ms','')} m/s, "
        f"Meter: {site.get('vel_check_meter_ms','')} m/s, "
        f"Diff: {site.get('vel_check_diff_ms','')} m/s"
    )
    y = draw_wrapped_kv(c, "Velocity", vel_line, margin, y, line_height)

    comms_line = f"{site.get('comms_verified','')} at {site.get('comms_verified_at','')}"
    y = draw_wrapped_kv(c, "Comms", comms_line, margin, y, line_height)

    zero_line = (
        f"Zero-depth check performed: "
        f"{'Yes' if site.get('zero_depth_check_done') else 'No'}; "
        f"Notes: {site.get('zero_depth_check_notes','')}"
    )
    y = draw_wrapped_kv(c, "Zero-depth check", zero_line, margin, y, line_height)

    ref_line = (
        f"Reference device: {site.get('reference_device_type','')} "
        f"({site.get('reference_device_id','')}); "
        f"Comparison: {site.get('reference_reading_desc','')}"
    )
    y = draw_wrapped_kv(c, "Reference check", ref_line, margin, y, line_height)

    # Additional verification readings
    extra = site.get("verification_readings", []) or []
    if extra:
        y -= line_height * 0.5
        y = check_page_break(y, space_needed=30 * mm)
        draw_section_title(c, "6. Additional Verification Readings", margin, y)
        y -= line_height * 1.5
        for i, r in enumerate(extra):
            # Check if we need a page break before each reading (each takes ~4 lines)
            y = check_page_break(y, space_needed=25 * mm)
            y = draw_wrapped_kv(c, f"Test {i + 1}", "", margin, y, line_height)
            depth_txt = (
                f"Measured {r.get('depth_meas_mm','')} mm / "
                f"Meter {r.get('depth_meter_mm','')} mm"
            )
            y = draw_wrapped_kv(
                c, "Depth", depth_txt, margin + 8 * mm, y, line_height
            )
            vel_txt = (
                f"Measured {r.get('vel_meas_ms','')} m/s / "
                f"Meter {r.get('vel_meter_ms','')} m/s"
            )
            y = draw_wrapped_kv(
                c, "Velocity", vel_txt, margin + 8 * mm, y, line_height
            )
            if r.get("comment"):
                y = draw_wrapped_kv(
                    c,
                    "Notes",
                    r.get("comment", ""),
                    margin + 8 * mm,
                    y,
                    line_height,
                )
            y -= line_height * 0.4

    # Derived flow numbers
    flow_meas = site.get("flow_meas_lps", 0.0)
    flow_meter = site.get("flow_meter_lps", 0.0)
    flow_diff = site.get("flow_diff_lps", 0.0)
    flow_diff_pct = site.get("flow_diff_percent", 0.0)
    avg_d_meas = site.get("avg_depth_meas_mm", 0.0)
    avg_d_meter = site.get("avg_depth_meter_mm", 0.0)
    avg_v_meas = site.get("avg_vel_meas_ms", 0.0)
    avg_v_meter = site.get("avg_vel_meter_ms", 0.0)

    flow_meas_line = (
        f"{flow_meas:.2f} L/s "
        f"(Avg depth {avg_d_meas:.1f} mm, Avg velocity {avg_v_meas:.2f} m/s)"
        if flow_meas
        else "N/A"
    )
    flow_meter_line = (
        f"{flow_meter:.2f} L/s "
        f"(Avg depth {avg_d_meter:.1f} mm, Avg velocity {avg_v_meter:.2f} m/s)"
        if flow_meter
        else "N/A"
    )
    flow_diff_line = (
        f"{flow_diff:.2f} L/s ({flow_diff_pct:.1f} %)"
        if (flow_meas or flow_meter)
        else "N/A"
    )

    y -= line_height * 0.5
    y = check_page_break(y, space_needed=25 * mm)
    draw_section_title(c, "7. Flow (for model calibration)", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(c, "Flow (manual)", flow_meas_line, margin, y, line_height)
    y = draw_wrapped_kv(c, "Flow (meter)", flow_meter_line, margin, y, line_height)
    y = draw_wrapped_kv(c, "Difference", flow_diff_line, margin, y, line_height)
    y -= line_height * 0.5

    # Calibration suitability & notes
    y = check_page_break(y, space_needed=35 * mm)
    draw_section_title(c, "8. Calibration Suitability & Modelling Notes", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(
        c, "Overall rating", site.get("calibration_rating", ""), margin, y, line_height
    )
    y = draw_wrapped_kv(
        c,
        "Suitability comment",
        site.get("calibration_comment", ""),
        margin,
        y,
        line_height,
    )
    y = draw_wrapped_kv(
        c,
        "Modelling notes",
        site.get("modelling_notes", ""),
        margin,
        y,
        line_height,
    )
    y = draw_wrapped_kv(
        c,
        "Data quality risks",
        site.get("data_quality_risks", ""),
        margin,
        y,
        line_height,
    )
    y -= line_height * 0.5

    # Installer checklist
    checklist_flags = []
    if site.get("chk_sensor_in_main_flow"):
        checklist_flags.append("Sensor in main flow path")
    if site.get("chk_no_immediate_drops"):
        checklist_flags.append("No immediate drops / turbulence at sensor")
    if site.get("chk_depth_range_ok"):
        checklist_flags.append("Depth/velocity ranges suitable")
    if site.get("chk_logging_started"):
        checklist_flags.append("Logging started and confirmed")
    if site.get("chk_comms_checked_platform"):
        checklist_flags.append("Comms/data visible on platform")

    chk_text = "; ".join(checklist_flags) if checklist_flags else "Not recorded"
    y = check_page_break(y, space_needed=15 * mm)
    y = draw_wrapped_kv(
        c, "Installer checklist", chk_text, margin, y, line_height, width_label=40 * mm
    )
    y -= line_height * 0.5

    # Diagrams, map and reporting – next page
    draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
    c.showPage()

    margin = 22 * mm
    line_height = 6 * mm
    draw_header_bar(
        c,
        width,
        site.get("project_name", "Project"),
        site.get("site_id", ""),
        site.get("site_name", ""),
    )
    y = height - HEADER_CONTENT_OFFSET
    max_w = width - 2 * margin
    max_diag_h = 70 * mm
    max_map_h = 60 * mm

    section_idx = 9

    # Manhole / site diagram
    diagram = site.get("diagram")
    if diagram:
        draw_section_title(c, f"{section_idx}. Manhole / Site Diagram", margin, y)
        y -= line_height * 1.5

        img_bytes = io.BytesIO(diagram["data"])
        img = ImageReader(img_bytes)
        iw, ih = img.getSize()
        scale = min(max_w / iw, max_diag_h / ih)
        w = iw * scale
        h = ih * scale
        x = margin + (max_w - w) / 2

        c.drawImage(
            img,
            x,
            y - h,
            width=w,
            height=h,
            preserveAspectRatio=True,
            mask="auto",
        )

        c.setFont("Helvetica", 8)
        caption = diagram.get("name", "Manhole / site diagram")
        c.drawCentredString(x + w / 2, y - h - 3 * mm, caption[:120])

        y = y - h - 10 * mm
        section_idx += 1

    # Static site map (zoomed)
    map_buf = create_site_map_bytes(site.get("gps_lat"), site.get("gps_lon"), zoom=19)
    if map_buf:
        if y - max_map_h < 40 * mm:
            draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
            c.showPage()
            draw_header_bar(
                c,
                width,
                site.get("project_name", "Project"),
                site.get("site_id", ""),
                site.get("site_name", ""),
            )
            y = height - HEADER_CONTENT_OFFSET

        draw_section_title(c, f"{section_idx}. Site location map", margin, y)
        y -= line_height * 1.5

        map_img = ImageReader(map_buf)
        iw, ih = map_img.getSize()
        scale = min(max_w / iw, max_map_h / ih)
        w = iw * scale
        h = ih * scale
        x = margin + (max_w - w) / 2

        c.drawImage(
            map_img,
            x,
            y - h,
            width=w,
            height=h,
            preserveAspectRatio=True,
            mask="auto",
        )

        y = y - h - 10 * mm
        section_idx += 1

    # Reporting details
    if y < 60 * mm:
        draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
        c.showPage()
        draw_header_bar(
            c,
            width,
            site.get("project_name", "Project"),
            site.get("site_id", ""),
            site.get("site_name", ""),
        )
        y = height - HEADER_CONTENT_OFFSET

    draw_section_title(c, f"{section_idx}. Reporting", margin, y)
    y -= line_height * 1.5

    prepared_line = (
        f"Prepared by: {site.get('prepared_by','')} "
        f"({site.get('prepared_position','')}) "
        f"on {site.get('prepared_date','')}"
    )
    y = draw_wrapped_kv(c, "", prepared_line, margin, y, line_height, width_label=5 * mm)

    reviewed_line = (
        f"Reviewed by: {site.get('reviewed_by','')} "
        f"({site.get('reviewed_position','')}) "
        f"on {site.get('reviewed_date','')}"
    )
    y = draw_wrapped_kv(c, "", reviewed_line, margin, y, line_height, width_label=5 * mm)

    draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
    c.showPage()


def draw_site_photos(c, site, photos, width, height):
    """Render ALL uploaded site photos with centred captions."""
    if not photos:
        return

    margin = 22 * mm
    line_height = 6 * mm
    max_w = width - 2 * margin
    max_h = 55 * mm

    def start_page(first=False):
        draw_header_bar(
            c,
            width,
            site.get("project_name", "Project"),
            site.get("site_id", ""),
            site.get("site_name", ""),
        )
        y0 = height - HEADER_CONTENT_OFFSET
        c.setFont("Helvetica-Bold", 11)
        c.drawString(
            margin,
            y0,
            "Site Photos" if first else "Site Photos (continued)",
        )
        return y0 - line_height * 2

    y = start_page(first=True)

    for p in photos:
        if y - max_h < 25 * mm:
            draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
            c.showPage()
            y = start_page(first=False)

        img_bytes = io.BytesIO(p["data"])
        img = ImageReader(img_bytes)
        iw, ih = img.getSize()
        scale = min(max_w / iw, max_h / ih)
        w = iw * scale
        h = ih * scale
        x = margin + (max_w - w) / 2

        c.drawImage(
            img,
            x,
            y - h,
            width=w,
            height=h,
            preserveAspectRatio=True,
            mask="auto",
        )

        c.setFont("Helvetica", 8)
        caption = (p.get("name") or "Site photo").strip()
        c.drawCentredString(x + w / 2, y - h - 3 * mm, caption[:160])

        y = y - h - 10 * mm

    draw_footer(c, width, site.get("client", ""), site.get("site_name", ""))
    c.showPage()


def create_pdf_bytes(sites):
    buf = io.BytesIO()
    c = NumberedCanvas(buf, pagesize=A4)
    width, height = A4

    for s in sites:
        draw_site_main_page(c, s, width, height)
        draw_site_commissioning_page(c, s, width, height)
        draw_site_photos(c, s, s.get("photos", []) or [], width, height)

    c.save()
    buf.seek(0)
    pdf_bytes = buf.getvalue()

    # Try to embed a JSON metadata attachment (site data) for reliable round-trip
    try:
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)

        # Prepare compact metadata (exclude large binary fields)
        meta_sites = []
        for s in sites:
            copy = {
                k: v
                for k, v in s.items()
                if k not in ("verification_readings", "photos", "diagram")
            }
            meta_sites.append(copy)

        meta_json = json.dumps(meta_sites, default=str)
        try:
            writer.add_attachment("site_data.json", meta_json.encode("utf-8"))
        except Exception:
            pass

        out = io.BytesIO()
        writer.write(out)
        out.seek(0)
        return out
    except Exception:
        out = io.BytesIO(pdf_bytes)
        out.seek(0)
        return out


# ---------- Photo helpers ----------
def merge_photo_records(existing_photos, new_photos):
    """Merge existing and newly uploaded photo records without duplication.

    Photos are deduplicated by hashing their binary payload so that renaming an
    existing image updates its metadata instead of creating a second copy. All
    outputs have trimmed, non-empty captions and their ``data`` value is
    normalised to ``bytes`` to keep equality checks reliable.
    """

    def _ensure_bytes(payload):
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        if isinstance(payload, memoryview):
            return payload.tobytes()
        return None

    merged_by_hash: dict[str, dict] = {}
    insertion_order: list[str] = []

    def _store(copy: dict, data_bytes: bytes | None, *, fallback_key: str) -> None:
        if data_bytes is None:
            if fallback_key not in merged_by_hash:
                insertion_order.append(fallback_key)
            merged_by_hash[fallback_key] = copy
            return

        digest = hashlib.sha256(data_bytes).hexdigest()
        if digest not in merged_by_hash:
            insertion_order.append(digest)
            merged_by_hash[digest] = copy
        else:
            merged_by_hash[digest].update(copy)

    for idx, photo in enumerate(existing_photos or []):
        if not isinstance(photo, dict):
            continue
        copy = photo.copy()
        copy_name = (copy.get("name") or "").strip()
        copy["name"] = copy_name or "Site photo"
        data_bytes = _ensure_bytes(copy.get("data"))
        if data_bytes is not None:
            copy["data"] = data_bytes
        _store(copy, data_bytes, fallback_key=f"existing-{idx}")

    for idx, photo in enumerate(new_photos or []):
        if not isinstance(photo, dict):
            continue
        data_bytes = _ensure_bytes(photo.get("data"))
        if data_bytes is None:
            continue

        digest = hashlib.sha256(data_bytes).hexdigest()
        cleaned_name = (photo.get("name") or "").strip()

        if digest in merged_by_hash:
            existing = merged_by_hash[digest]
            if cleaned_name:
                existing["name"] = cleaned_name
            if photo.get("mime"):
                existing["mime"] = photo["mime"]
        else:
            copy = photo.copy()
            copy["data"] = data_bytes
            copy["name"] = cleaned_name or "Site photo"
            _store(copy, data_bytes, fallback_key=f"new-{idx}")

    return [merged_by_hash[key] for key in insertion_order]


# ---------- GitHub storage helpers ----------
def slugify_path_component(value: str | None, fallback: str = "item") -> str:
    text = (value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-").lower()
    return text or fallback.lower()


def generate_site_storage_path(site: dict, base_folder: str = "reports") -> str:
    folder = (base_folder or "reports").strip().strip("/")
    if not folder:
        folder = "reports"
    project_slug = slugify_path_component(site.get("project_name"), "project")
    site_slug = slugify_path_component(site.get("site_name"), "site")
    return f"{folder}/{project_slug}/{site_slug}.json"


def _coerce_bytes_or_none(payload):
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, memoryview):
        return payload.tobytes()
    return None


def serialise_site_for_storage(site: dict) -> dict:
    cleaned: dict[str, object] = {}
    for key, value in site.items():
        if key in {"photos", "diagram"}:
            continue
        if isinstance(value, (datetime, date, time)):
            cleaned[key] = str(value)
        else:
            cleaned[key] = value

    photos_meta = []
    for photo in site.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        data_bytes = _coerce_bytes_or_none(photo.get("data"))
        entry = {
            "name": (photo.get("name") or "").strip() or "Site photo",
            "mime": photo.get("mime"),
        }
        if data_bytes:
            entry["sha256"] = hashlib.sha256(data_bytes).hexdigest()
            entry["size_bytes"] = len(data_bytes)
        photos_meta.append(entry)
    if photos_meta:
        cleaned["photos_metadata"] = photos_meta

    diagram = site.get("diagram")
    if isinstance(diagram, dict):
        diag_bytes = _coerce_bytes_or_none(diagram.get("data"))
        diag_entry = {
            "name": diagram.get("name"),
            "mime": diagram.get("mime"),
        }
        if diag_bytes:
            diag_entry["sha256"] = hashlib.sha256(diag_bytes).hexdigest()
            diag_entry["size_bytes"] = len(diag_bytes)
        cleaned["diagram_metadata"] = diag_entry

    cleaned["bundle_generated_at_utc"] = datetime.now(datetime_timezone.utc).isoformat()
    return cleaned


def build_site_report_bundle(site: dict, pdf_bytes: bytes | bytearray | memoryview) -> dict:
    pdf_payload = _coerce_bytes_or_none(pdf_bytes)
    if pdf_payload is None:
        raise TypeError("pdf_bytes must be bytes-like")
    return {
        "bundle_version": 1,
        "site": serialise_site_for_storage(site),
        "pdf_base64": base64.b64encode(pdf_payload).decode("ascii"),
    }


def upload_site_report_to_github(
    site: dict,
    pdf_bytes: bytes | bytearray | memoryview,
    repo_full_name: str,
    *,
    token: str | None = None,
    branch: str = "main",
    base_folder: str = "reports",
    session: requests.Session | None = None,
) -> dict:
    if not repo_full_name or "/" not in repo_full_name:
        raise ValueError("'repo_full_name' must look like 'owner/repo'.")

    resolved_token = (
        token
        or os.getenv("GITHUB_REPORT_TOKEN")
        or os.getenv("GITHUB_TOKEN")
    )
    if not resolved_token:
        raise RuntimeError(
            "GitHub token not configured. Set GITHUB_REPORT_TOKEN or pass 'token'."
        )

    owner, repo = repo_full_name.split("/", 1)
    storage_path = generate_site_storage_path(site, base_folder=base_folder)
    bundle = build_site_report_bundle(site, pdf_bytes)
    bundle_json = json.dumps(bundle, indent=2, sort_keys=True)
    encoded_content = base64.b64encode(bundle_json.encode("utf-8")).decode("ascii")

    headers = {
        "Authorization": f"Bearer {resolved_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    sess = session or requests.Session()
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(storage_path, safe='/')}"
    params = {"ref": branch} if branch else None

    response = sess.get(url, headers=headers, params=params)
    if response.status_code == 200:
        try:
            existing = response.json()
        except Exception as exc:
            raise RuntimeError("Failed to decode GitHub response when checking existing file") from exc
        sha = existing.get("sha") or existing.get("content", {}).get("sha")
        commit_prefix = "Update"
    elif response.status_code == 404:
        sha = None
        commit_prefix = "Add"
    else:
        raise RuntimeError(
            f"GitHub API responded with {response.status_code} while checking existing file: {response.text}"
        )

    site_name = (site.get("site_name") or "installation").strip() or "installation"
    commit_message = f"{commit_prefix} installation report for {site_name}"

    payload = {
        "message": commit_message,
        "content": encoded_content,
    }
    if branch:
        payload["branch"] = branch
    if sha:
        payload["sha"] = sha

    put_response = sess.put(url, headers=headers, json=payload)
    if put_response.status_code not in (200, 201):
        raise RuntimeError(
            f"GitHub API responded with {put_response.status_code} while uploading report: {put_response.text}"
        )

    try:
        put_json = put_response.json()
    except Exception:
        put_json = {}

    return {
        "path": storage_path,
        "commit_sha": put_json.get("commit", {}).get("sha"),
        "html_url": put_json.get("content", {}).get("html_url"),
    }


# ---------- Excel export ----------
def create_excel_bytes(sites):
    flat_sites = []
    for s in sites:
        copy = {
            k: v
            for k, v in s.items()
            if k not in ("verification_readings", "photos", "diagram")
        }
        flat_sites.append(copy)

    df = pd.DataFrame(flat_sites)
    cols = [
        "project_name",
        "client",
        "catchment",
        "site_id",
        "site_name",
        "client_asset_id",
        "gis_id",
        "install_date",
        "install_time",
        "meter_model",
        "pipe_diameter_mm",
        "pipe_material",
        "pipe_shape",
        "depth_to_invert_mm",
        "gps_lat",
        "gps_lon",
        "logging_interval_min",
        "comms_method",
        "comms_verified",
        "calibration_rating",
        "avg_depth_meas_mm",
        "avg_depth_meter_mm",
        "avg_vel_meas_ms",
        "avg_vel_meter_ms",
        "flow_meas_lps",
        "flow_meter_lps",
        "flow_diff_lps",
        "flow_diff_percent",
        "hydro_turbulence_level",
        "hydro_drops",
        "hydro_bends",
        "hydro_junctions",
        "hydro_surcharge_risk",
        "hydro_backwater_risk",
        "modelling_notes",
        "data_quality_risks",
    ]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Sites Summary", index=False)
    buf.seek(0)
    return buf


# ---------- Streamlit helpers ----------
def safe_rerun():
    """Try to rerun the Streamlit app in a safe, backwards-compatible way."""
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
            return
        except Exception:
            pass

    try:
        from streamlit.runtime.scriptrunner.script_runner import RerunException

        raise RerunException()
    except Exception:
        st.session_state["_force_rerun_toggle"] = not st.session_state.get(
            "_force_rerun_toggle", False
        )
        try:
            st.query_params["_rerun"] = str(int(_time.time()))
        except Exception:
            return


def get_address_from_coords(lat: float, lon: float) -> str:
    """Use reverse geocoding (Nominatim) to get street address from lat/lon."""
    try:
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="eds_sewer_reporter")
        location = geolocator.reverse(f"{lat}, {lon}", language="en")
        return location.address if location else ""
    except Exception:
        return ""


def parse_pdf_report(file_bytes: bytes) -> dict:
    """Attempt to parse a PDF report generated by this app and return a
    dictionary of site fields to prepopulate the form.
    """
    try:
        from PyPDF2 import PdfReader
    except Exception:
        return {"_error": "missing_pyPDF2"}

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text_pages = []
        for p in reader.pages:
            try:
                txt = p.extract_text() or ""
            except Exception:
                txt = ""
            text_pages.append(txt)
        full_text = "\n".join(text_pages)
    except Exception:
        return {"_error": "parse_failed"}

    label_map = {
        "project_name": ["Project", "Project name"],
        "client": ["Client"],
        "site_name": ["Site / manhole name", "Site name", "Site"],
        "site_id": ["Site ID", "SiteID", "Manhole", "Manhole number"],
        "client_asset_id": ["Client asset ID"],
        "gis_id": ["GIS ID"],
        "install_date": ["Install date", "Installed on", "Install Date"],
        "install_time": ["Install time", "Install Time"],
        "gps_lat": ["GPS latitude", "GPS Latitude", "Lat"],
        "gps_lon": ["GPS longitude", "GPS Longitude", "Lon"],
        "manhole_location_desc": ["Location description", "Location"],
        "prepared_by": ["Prepared by"],
    }

    parsed = {}
    import re

    for key, variants in label_map.items():
        found = None
        for label in variants:
            pattern = rf"{re.escape(label)}[:\s]+(.+)$"
            m = re.search(pattern, full_text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                val = m.group(1).strip()
                val = val.rstrip(";.,")
                found = val
                break
        if found:
            parsed[key] = found

    if "gps_lat" not in parsed or "gps_lon" not in parsed:
        m = re.search(r"([+-]?\d+\.\d+)\s*[,:\s]\s*([+-]?\d+\.\d+)", full_text)
        if m:
            parsed.setdefault("gps_lat", m.group(1))
            parsed.setdefault("gps_lon", m.group(2))

    return parsed


# ---------- Streamlit UI ----------
st.set_page_config(
    page_title="Sewer Flow Meter Installation Reporter",
    layout="wide",
)

EDS_PRIMARY = "#00507A"
EDS_SECONDARY = "#007A7A"
EDS_LIGHT_BG = "#f5f7fb"
EDS_CARD_BG = "#ffffff"
EDS_BORDER = "#d9e2ef"

# Global styling (simplified, readable)
st.markdown(
    f"""
<style>
html, body, [data-testid="stAppViewContainer"], .stApp {{
    background-color: {EDS_LIGHT_BG} !important;
    color: #111827 !important;
    font-family: Eurostile, "Helvetica Neue", Arial, sans-serif !important;
}}

.block-container {{
    padding-top: 2rem;
    padding-bottom: 2rem;
}}

div[data-testid="stForm"] {{
    background-color: {EDS_CARD_BG};
    padding: 1.5rem 1.75rem;
    border-radius: 8px;
    border: 1px solid {EDS_BORDER};
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}}

h1, h2, h3, h4, h5, h6 {{
    color: {EDS_PRIMARY};
    font-family: Eurostile, "Helvetica Neue", Arial, sans-serif !important;
}}

label, [data-testid="stWidgetLabel"] p {{
    color: #111827 !important;
    font-weight: 500;
    font-size: 0.9rem;
}}

input, textarea, select {{
    background-color: #ffffff !important;
    color: #111827 !important;
    border-radius: 4px !important;
    border: 1px solid #d1d5db !important;
}}

input::placeholder, textarea::placeholder {{
    color: #9ca3af !important;
}}

.stButton>button,
button,
[data-testid="stDownloadButton"]>button {{
    background-color: {EDS_PRIMARY} !important;
    color: #ffffff !important;
    border-radius: 6px !important;
    border: none !important;
    padding: 0.45rem 1.0rem !important;
    font-weight: 600 !important;
}}

.stButton>button:hover,
[data-testid="stDownloadButton"]>button:hover {{
    background-color: {EDS_SECONDARY} !important;
}}

[data-testid="stFormSubmitButton"] button {{
    background-color: {EDS_PRIMARY} !important;
    color: #ffffff !important;
    border-radius: 6px !important;
    font-weight: 700 !important;
}}

/* Selectbox styling - simple & readable */
div[data-testid="stSelectbox"] div[role="combobox"] {{
    background-color: #ffffff !important;
    color: #111827 !important;
    border-radius: 4px !important;
    border: 1px solid #d1d5db !important;
    padding: 0.5rem 0.75rem !important;
    font-weight: 500 !important;
    font-size: 0.95rem !important;
}}

div[data-testid="stSelectbox"] div[role="combobox"] span {{
    color: #111827 !important;
    font-weight: 500 !important;
}}

div[data-testid="stSelectbox"] ul {{
    background-color: #ffffff !important;
    border: 1px solid #d1d5db !important;
    border-radius: 4px !important;
    box-shadow: 0 6px 12px rgba(15, 23, 42, 0.18) !important;
}}

div[data-testid="stSelectbox"] ul li {{
    background-color: #ffffff !important;
    color: #111827 !important;
    padding: 0.5rem 0.75rem !important;
    font-weight: 400 !important;
    font-size: 0.9rem !important;
}}

div[data-testid="stSelectbox"] ul li:hover {{
    background-color: #e5f2fa !important;
    color: {EDS_PRIMARY} !important;
    font-weight: 600 !important;
}}

div[data-testid="stSelectbox"] ul li[data-selected="true"] {{
    background-color: {EDS_PRIMARY} !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}}

/* Focus states for accessibility */
input:focus,
textarea:focus,
select:focus,
button:focus {{
    outline: none !important;
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.35) !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

st.title("EDS Sewer Flow Meter Installation Report")
st.caption(
    "Standardised EDS installation reports for sewer flow modelling and inflow/infiltration studies."
)

# ---------- Session state ----------
if "sites" not in st.session_state:
    st.session_state["sites"] = []
if "draft_site" not in st.session_state:
    st.session_state["draft_site"] = None
if "edit_index" not in st.session_state:
    st.session_state["edit_index"] = None

sites = st.session_state["sites"]
draft = st.session_state["draft_site"] or {}
edit_index = st.session_state["edit_index"]

# GPS / address session state (canonical, NOT widget keys)
if "gps_lat" not in st.session_state:
    st.session_state["gps_lat"] = draft.get("gps_lat", "")
if "gps_lon" not in st.session_state:
    st.session_state["gps_lon"] = draft.get("gps_lon", "")
if "gps_last_clicked" not in st.session_state:
    st.session_state["gps_last_clicked"] = None
if "device_gps_raw" not in st.session_state:
    st.session_state["device_gps_raw"] = None
if "auto_address" not in st.session_state:
    st.session_state["auto_address"] = draft.get("site_address", "") or ""
if "last_geocoded_coords" not in st.session_state:
    st.session_state["last_geocoded_coords"] = None
if "site_address" not in st.session_state:
    st.session_state["site_address"] = (
        draft.get("site_address", "") or st.session_state.get("auto_address", "")
    )

# ---------- Map / GPS helper UI ----------
st.header("Add / Record a Site")

st.markdown(
    "Pan/zoom to your manhole location, then **tap/click the map**. "
    "The GPS fields and site address will update automatically."
)

# Map centre
if st.session_state["gps_lat"] and st.session_state["gps_lon"]:
    try:
        center = [
            float(st.session_state["gps_lat"]),
            float(st.session_state["gps_lon"]),
        ]
    except ValueError:
        center = [-27.4698, 153.0251]
else:
    center = [-27.4698, 153.0251]  # Brisbane default

m = folium.Map(location=center, zoom_start=19, control_scale=True)

if st.session_state["gps_last_clicked"]:
    lat_m, lon_m = st.session_state["gps_last_clicked"]
    folium.Marker([lat_m, lon_m], tooltip="Last clicked location").add_to(m)

map_result = st_folium(
    m,
    height=360,
    width=None,
    key="site_map",
)

# Handle map clicks (desktop & phone taps)
if map_result and map_result.get("last_clicked"):
    lat = map_result["last_clicked"]["lat"]
    lon = map_result["last_clicked"]["lng"]
    st.session_state["gps_last_clicked"] = (lat, lon)
    st.session_state["gps_lat"] = f"{lat:.6f}"
    st.session_state["gps_lon"] = f"{lon:.6f}"

# GPS action buttons
col_map_btn1, col_map_btn2 = st.columns([1, 1])
with col_map_btn1:
    if st.button("📍 Use last map click"):
        if st.session_state["gps_last_clicked"]:
            lat, lon = st.session_state["gps_last_clicked"]
            st.session_state["gps_lat"] = f"{lat:.6f}"
            st.session_state["gps_lon"] = f"{lon:.6f}"
        else:
            st.warning("Tap/click on the map first to set a location.")

with col_map_btn2:
    if GEO_AVAILABLE:
        if st.button("📡 Use device GPS"):
            loc = get_geolocation()
            st.session_state["device_gps_raw"] = loc

            if not loc:
                st.warning(
                    "Device GPS not available or no response yet. "
                    "This is usually due to the browser blocking location access. "
                    "You can still use the map tap/click to set coordinates."
                )
            else:
                err = loc.get("error")
                if err:
                    st.warning(
                        f"Device GPS error from browser: **{err}**. "
                        "Use the map tap/click instead, or ensure location is allowed."
                    )
                else:
                    coords = loc.get("coords", {})
                    lat = coords.get("latitude") or loc.get("lat")
                    lon = coords.get("longitude") or loc.get("lon")
                    if lat is not None and lon is not None:
                        try:
                            st.session_state["gps_lat"] = f"{float(lat):.6f}"
                            st.session_state["gps_lon"] = f"{float(lon):.6f}"
                            st.success("Device GPS position recorded.")
                        except Exception:
                            st.warning(
                                "Received GPS data but couldn't parse it. "
                                "Please use the map tap/click instead."
                            )
                    else:
                        st.warning(
                            "Device GPS did not return coordinates. "
                            "Please use the map tap/click to set a point."
                        )
    else:
        st.caption(
            "Device GPS is not available (install `streamlit-js-eval` to enable it)."
        )

if GEO_AVAILABLE and st.session_state["device_gps_raw"]:
    st.caption(
        f"Last device GPS raw response: {st.session_state['device_gps_raw']}"
    )

# ---------- Reverse geocode GPS -> site address BEFORE the form ----------
lat_str = st.session_state.get("gps_lat", "")
lon_str = st.session_state.get("gps_lon", "")
coords = (lat_str, lon_str) if lat_str and lon_str else None

if coords and coords != st.session_state.get("last_geocoded_coords"):
    try:
        lat_f = float(lat_str)
        lon_f = float(lon_str)
        addr = get_address_from_coords(lat_f, lon_f)
        if addr:
            st.session_state["auto_address"] = addr
            st.session_state["site_address"] = addr
            st.session_state["last_geocoded_coords"] = coords
    except Exception:
        st.session_state["last_geocoded_coords"] = None

# ---------- Optional: PDF pre-fill ----------
with st.expander("Upload completed PDF report to pre-fill form (optional)", expanded=False):
    pdf_file = st.file_uploader(
        "Upload a previously-completed PDF report to pre-populate the form",
        type=["pdf"],
        help="This attempts to parse PDF text and map common fields back into the form.",
    )
    if pdf_file is not None:
        blob = pdf_file.read()
        parsed = parse_pdf_report(blob)
        if not parsed:
            st.error("Couldn't extract any text from the uploaded PDF.")
        elif parsed.get("_error") == "missing_pyPDF2":
            st.warning(
                "PyPDF2 is required to parse PDFs. Install it with `pip install PyPDF2` "
                "and restart the app to enable PDF pre-fill."
            )
        elif parsed.get("_error") == "parse_failed":
            st.error("Failed to parse the uploaded PDF. It may be corrupted or scanned as images.")
        else:
            draft_vals = st.session_state.get("draft_site") or {}
            for k, v in parsed.items():
                if k.startswith("_"):
                    continue
                if v and (not draft_vals.get(k)):
                    draft_vals[k] = v
            st.session_state["draft_site"] = draft_vals
            st.success("PDF parsed — form pre-populated. You can edit and save this draft.")
            safe_rerun()

# Keep draft synced with GPS
if st.session_state["gps_lat"]:
    draft["gps_lat"] = st.session_state["gps_lat"]
if st.session_state["gps_lon"]:
    draft["gps_lon"] = st.session_state["gps_lon"]

# ---------- Site form ----------
with st.form("site_form", clear_on_submit=False):
    if edit_index is not None and 0 <= edit_index < len(sites):
        st.info(
            f"Editing site **{sites[edit_index].get('site_name', '')}** "
            f"in project **{sites[edit_index].get('project_name', '')}**. "
            "Update fields and click **Update site in current project**."
        )

    st.subheader("Project")

    c1, c2, c3 = st.columns([1.2, 1.2, 0.8])
    with c1:
        project_name = st.text_input(
            "Project name",
            value=draft.get("project_name", ""),
        )
        client = st.text_input("Client", value=draft.get("client", ""))
        catchment = st.text_input("Catchment / area", value=draft.get("catchment", ""))
    with c2:
        site_name = st.text_input("Site / manhole name", value=draft.get("site_name", ""))
        site_id = st.text_input("Site ID", value=draft.get("site_id", ""))
        client_asset_id = st.text_input(
            "Client asset ID", value=draft.get("client_asset_id", "")
        )
    with c3:
        gis_id = st.text_input("GIS ID", value=draft.get("gis_id", ""))

        install_date_default = draft.get("install_date")
        if isinstance(install_date_default, str):
            try:
                install_date_default = date.fromisoformat(install_date_default)
            except ValueError:
                install_date_default = date.today()
        elif isinstance(install_date_default, date):
            pass
        else:
            install_date_default = date.today()

        install_date = st.date_input(
            "Install date",
            value=install_date_default,
        )

        install_time_default = draft.get("install_time")
        if isinstance(install_time_default, str):
            try:
                h, m = map(int, install_time_default.split(":"))
                install_time_default = time(h, m)
            except Exception:
                install_time_default = time(9, 0)
        elif isinstance(install_time_default, time):
            pass
        else:
            install_time_default = time(9, 0)

        install_time = st.time_input(
            "Install time",
            value=install_time_default,
        )

    st.markdown("---")

    st.subheader("Location, Access & Safety")

    c_gps1, c_gps2, c_gps3 = st.columns([1, 1, 2])
    with c_gps1:
        gps_lat = st.text_input(
            "GPS latitude",
            value=st.session_state["gps_lat"],
            key="gps_lat_input",
        )
    with c_gps2:
        gps_lon = st.text_input(
            "GPS longitude",
            value=st.session_state["gps_lon"],
            key="gps_lon_input",
        )
    with c_gps3:
        manhole_location_desc = st.text_area(
            "Location description (nearby road, property & landmarks)",
            value=draft.get("manhole_location_desc", ""),
        )

    # keep session state in sync with text inputs
    st.session_state["gps_lat"] = gps_lat
    st.session_state["gps_lon"] = gps_lon

    site_address = st.text_input(
        "Site address",
        value=st.session_state["site_address"],
        key="site_address_input",
        help="This will be included in the PDF report for reference.",
    )
    st.session_state["site_address"] = site_address

    c_acc1, c_acc2, c_acc3 = st.columns([1, 1, 2])
    with c_acc1:
        access_options = ["", "On-road", "Off-road", "Easement", "Private property"]
        access_val = draft.get("access_type", "")
        access_index = access_options.index(access_val) if access_val in access_options else 0
        access_type = st.selectbox(
            "Access type",
            access_options,
            index=access_index,
        )
    with c_acc2:
        confined_space_required = st.checkbox(
            "Confined space entry required",
            value=draft.get("confined_space_required", False),
        )
        traffic_control_required = st.checkbox(
            "Traffic control required",
            value=draft.get("traffic_control_required", False),
        )
    with c_acc3:
        access_safety_constraints = st.text_area(
            "Safety constraints / access notes",
            value=draft.get("access_safety_constraints", ""),
        )

    other_permits_required = st.text_input(
        "Other permits / approvals (if any)",
        value=draft.get("other_permits_required", ""),
    )

    st.markdown("---")

    st.subheader("Pipe & Hydraulics")

    ph1, ph2, ph3, ph4 = st.columns([1, 1, 1, 1])
    with ph1:
        pipe_diameter_mm = st.number_input(
            "Pipe diameter (mm)", min_value=0, value=int(draft.get("pipe_diameter_mm", 0))
        )
        depth_to_invert_mm = st.number_input(
            "Depth to invert (mm)",
            min_value=0,
            value=int(draft.get("depth_to_invert_mm", 0)),
        )
    with ph2:
        pipe_material_opts = ["", "VC", "RC", "PVC", "DICL", "Steel", "HDPE", "Other"]
        pm_val = draft.get("pipe_material", "")
        pm_index = (
            pipe_material_opts.index(pm_val)
            if pm_val in pipe_material_opts
            else (len(pipe_material_opts) - 1 if pm_val else 0)
        )
        pipe_material_choice = st.selectbox(
            "Pipe material",
            pipe_material_opts,
            index=pm_index,
        )
        if pipe_material_choice == "Other":
            pipe_material = st.text_input(
                "Other pipe material",
                value=pm_val if pm_val not in pipe_material_opts else "",
            )
        else:
            pipe_material = pipe_material_choice

        depth_to_soffit_mm = st.number_input(
            "Depth to soffit (mm)",
            min_value=0,
            value=int(draft.get("depth_to_soffit_mm", 0)),
        )
    with ph3:
        pipe_shape_opts = ["", "Circular", "Egg", "Box", "Oval", "Arch", "Other"]
        ps_val = draft.get("pipe_shape", "")
        ps_index = (
            pipe_shape_opts.index(ps_val)
            if ps_val in pipe_shape_opts
            else (len(pipe_shape_opts) - 1 if ps_val else 0)
        )
        pipe_shape_choice = st.selectbox(
            "Pipe shape",
            pipe_shape_opts,
            index=ps_index,
        )
        if pipe_shape_choice == "Other":
            pipe_shape = st.text_input(
                "Other pipe shape",
                value=ps_val if ps_val not in pipe_shape_opts else "",
            )
        else:
            pipe_shape = pipe_shape_choice
    with ph4:
        hydro_turbulence_options = ["", "Low", "Moderate", "High"]
        ht_val = draft.get("hydro_turbulence_level", "")
        ht_index = (
            hydro_turbulence_options.index(ht_val)
            if ht_val in hydro_turbulence_options
            else 0
        )
        hydro_turbulence_level = st.selectbox(
            "Turbulence level at sensor",
            hydro_turbulence_options,
            index=ht_index,
        )

    uh1, uh2 = st.columns(2)
    with uh1:
        upstream_config = st.text_area(
            "Upstream configuration (drops, bends, junctions, distance)",
            value=draft.get("upstream_config", ""),
        )
    with uh2:
        downstream_config = st.text_area(
            "Downstream configuration (drops, bends, junctions, distance)",
            value=draft.get("downstream_config", ""),
        )

    hh1, hh2, hh3 = st.columns(3)
    with hh1:
        hydro_drops = st.checkbox(
            "Drops close to meter (≤2D)",
            value=draft.get("hydro_drops", False),
        )
        hydro_bends = st.checkbox(
            "Bends close to meter (≤5D)",
            value=draft.get("hydro_bends", False),
        )
    with hh2:
        hydro_junctions = st.checkbox(
            "Junctions within 5D",
            value=draft.get("hydro_junctions", False),
        )
        hydro_surcharge_risk = st.checkbox(
            "History of surcharge at site",
            value=draft.get("hydro_surcharge_risk", False),
        )
    with hh3:
        hydro_backwater_risk = st.checkbox(
            "Backwater effects likely",
            value=draft.get("hydro_backwater_risk", False),
        )
        hydraulic_notes = st.text_area(
            "Hydraulic comments (e.g. risk to data quality)",
            value=draft.get("hydraulic_notes", ""),
        )

    st.markdown("---")

    st.subheader("Meter, Sensor & Configuration")

    m1, m2, m3 = st.columns(3)
    with m1:
        meter_model_opts = [
            "",
            "Detectronic MSFM AV",
            "Detectronic MSFM4",
            "LIDoTT AV",
            "Other",
        ]
        mm_val = draft.get("meter_model", "")
        mm_index = (
            meter_model_opts.index(mm_val)
            if mm_val in meter_model_opts
            else (len(meter_model_opts) - 1 if mm_val else 1)
        )
        meter_model_choice = st.selectbox(
            "Meter model",
            meter_model_opts,
            index=mm_index,
        )
        if meter_model_choice == "Other":
            meter_model = st.text_input(
                "Other meter model",
                value=mm_val if mm_val not in meter_model_opts else "",
            )
        else:
            meter_model = meter_model_choice

        logger_serial = st.text_input(
            "Logger serial number", value=draft.get("logger_serial", "")
        )
    with m2:
        sensor_serial = st.text_input(
            "Sensor serial number", value=draft.get("sensor_serial", "")
        )
        sensor_distance_from_manhole_m = st.number_input(
            "Sensor distance from manhole (m)",
            min_value=0.0,
            value=float(draft.get("sensor_distance_from_manhole_m", 0.0)),
        )
    with m3:
        sensor_orientation = st.text_input(
            "Sensor orientation (e.g. upstream, downstream)",
            value=draft.get("sensor_orientation", ""),
        )
        sensor_mount_type = st.text_input(
            "Sensor mount type (e.g. band, bolt-on)",
            value=draft.get("sensor_mount_type", ""),
        )

    datum_reference_desc = st.text_input(
        "Datum reference (e.g. top of lid, local benchmark)",
        value=draft.get("datum_reference_desc", ""),
    )

    r1, r2, r3, r4 = st.columns(4)
    with r1:
        level_range_min_mm = st.number_input(
            "Level range min (mm)",
            min_value=0,
            value=int(draft.get("level_range_min_mm", 0)),
        )
    with r2:
        level_range_max_mm = st.number_input(
            "Level range max (mm)",
            min_value=0,
            value=int(draft.get("level_range_max_mm", 0)),
        )
    with r3:
        velocity_range_min_ms = st.number_input(
            "Velocity range min (m/s)",
            min_value=0.0,
            value=float(draft.get("velocity_range_min_ms", 0.0)),
        )
    with r4:
        velocity_range_max_ms = st.number_input(
            "Velocity range max (m/s)",
            min_value=0.0,
            value=float(draft.get("velocity_range_max_ms", 3.0)),
        )

    output_scaling_desc = st.text_input(
        "Output scaling (e.g. 4–20 mA = 0–50 L/s)",
        value=draft.get("output_scaling_desc", ""),
    )

    cfg1, cfg2, cfg3 = st.columns(3)
    with cfg1:
        logging_interval_min = st.number_input(
            "Logging interval (minutes)",
            min_value=1,
            value=int(draft.get("logging_interval_min", 5)),
        )
    with cfg2:
        tz_options = ["", "AEST", "AEDT", "ACST", "AWST", "UTC"]
        tz_val = draft.get("timezone", "AEST")
        tz_index = tz_options.index(tz_val) if tz_val in tz_options else 1
        timezone = st.selectbox("Time zone", tz_options, index=tz_index)
    with cfg3:
        comms_method_opts = [
            "",
            "SIM – Telstra",
            "SIM – Optus",
            "SIM – Vodafone",
            "Ethernet",
            "LoRaWAN",
            "Modbus",
            "Other",
        ]
        cm_val = draft.get("comms_method", "")
        cm_index = (
            comms_method_opts.index(cm_val)
            if cm_val in comms_method_opts
            else (len(comms_method_opts) - 1 if cm_val else 0)
        )
        comms_method_choice = st.selectbox(
            "Comms method",
            comms_method_opts,
            index=cm_index,
        )
        if comms_method_choice == "Other":
            comms_method = st.text_input(
                "Other comms method",
                value=cm_val if cm_val not in comms_method_opts else "",
            )
        else:
            comms_method = comms_method_choice

    t1, t2 = st.columns(2)
    with t1:
        telemetry_logger_id = st.text_input(
            "Telemetry logger ID / RTU tag",
            value=draft.get("telemetry_logger_id", ""),
        )
    with t2:
        telemetry_server = st.text_input(
            "Telemetry server / platform",
            value=draft.get("telemetry_server", ""),
        )

    telemetry_notes = st.text_area(
        "Telemetry notes (APN, polling, integration, etc.)",
        value=draft.get("telemetry_notes", ""),
    )

    st.markdown("---")

    st.subheader("Commissioning Checks – Primary Reading")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        depth_check_meas_mm = st.number_input(
            "Measured depth (mm)",
            min_value=0,
            value=int(draft.get("depth_check_meas_mm", 0)),
        )
        vel_check_meas_ms = st.number_input(
            "Measured velocity (m/s)",
            min_value=0.0,
            value=float(draft.get("vel_check_meas_ms", 0.0)),
        )
    with cc2:
        depth_check_meter_mm = st.number_input(
            "Meter depth (mm)",
            min_value=0,
            value=int(draft.get("depth_check_meter_mm", 0)),
        )
        vel_check_meter_ms = st.number_input(
            "Meter velocity (m/s)",
            min_value=0.0,
            value=float(draft.get("vel_check_meter_ms", 0.0)),
        )
    with cc3:
        depth_check_tolerance_mm = st.number_input(
            "Depth tolerance (±mm)",
            min_value=0,
            value=int(draft.get("depth_check_tolerance_mm", 5)),
        )
        depth_check_diff_mm = depth_check_meter_mm - depth_check_meas_mm
        depth_check_within_tol = (
            abs(depth_check_diff_mm) <= depth_check_tolerance_mm
        )
        st.markdown(
            f"**Depth diff:** {depth_check_diff_mm} mm – "
            f"{'within tolerance' if depth_check_within_tol else 'outside tolerance'}"
        )

    c_com1, c_com2 = st.columns(2)
    with c_com1:
        cv_options = ["", "Yes", "No"]
        cv_val = draft.get("comms_verified", "")
        cv_index = cv_options.index(cv_val) if cv_val in cv_options else 0
        comms_verified = st.selectbox(
            "Comms verified on platform?",
            cv_options,
            index=cv_index,
        )
    with c_com2:
        comms_verified_at = st.text_input(
            "Comms verified at (timestamp)",
            value=draft.get("comms_verified_at", ""),
        )

    zero_depth_check_done = st.checkbox(
        "Zero-depth check performed",
        value=draft.get("zero_depth_check_done", False),
    )
    zero_depth_check_notes = st.text_input(
        "Zero-depth check notes",
        value=draft.get("zero_depth_check_notes", ""),
    )

    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        reference_device_type = st.text_input(
            "Reference device type (if used)",
            value=draft.get("reference_device_type", ""),
        )
    with rc2:
        reference_device_id = st.text_input(
            "Reference device ID / tag",
            value=draft.get("reference_device_id", ""),
        )
    with rc3:
        reference_reading_desc = st.text_input(
            "Reference comparison (brief)",
            value=draft.get("reference_reading_desc", ""),
        )

    st.markdown("---")

    st.subheader("Additional Verification Readings (optional)")
    extra_readings = draft.get("verification_readings", []) or []
    extra_count = st.number_input(
        "Number of additional readings",
        min_value=0,
        max_value=10,
        value=len(extra_readings),
    )

    updated_extra = []
    for i in range(extra_count):
        prev = extra_readings[i] if i < len(extra_readings) else {}
        st.markdown(f"**Reading {i+1}**")
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            d_meas = st.number_input(
                f"Measured depth (mm) – R{i+1}",
                min_value=0,
                value=int(prev.get("depth_meas_mm", 0)),
                key=f"extra_d_meas_{i}",
            )
        with ec2:
            d_meter = st.number_input(
                f"Meter depth (mm) – R{i+1}",
                min_value=0,
                value=int(prev.get("depth_meter_mm", 0)),
                key=f"extra_d_meter_{i}",
            )
        with ec3:
            v_meas = st.number_input(
                f"Measured velocity (m/s) – R{i+1}",
                min_value=0.0,
                value=float(prev.get("vel_meas_ms", 0.0)),
                key=f"extra_v_meas_{i}",
            )
        with ec4:
            v_meter = st.number_input(
                f"Meter velocity (m/s) – R{i+1}",
                min_value=0.0,
                value=float(prev.get("vel_meter_ms", 0.0)),
                key=f"extra_v_meter_{i}",
            )
        comment = st.text_input(
            f"Notes – R{i+1}",
            value=prev.get("comment", ""),
            key=f"extra_comment_{i}",
        )
        updated_extra.append(
            {
                "depth_meas_mm": d_meas,
                "depth_meter_mm": d_meter,
                "vel_meas_ms": v_meas,
                "vel_meter_ms": v_meter,
                "comment": comment,
            }
        )

    st.markdown("---")

    st.subheader("Calibration Suitability & Modelling Notes")

    cal1, cal2 = st.columns([1, 2])
    with cal1:
        rating_options = ["", "Good", "Fair", "Poor"]
        cr_val = draft.get("calibration_rating", "")
        cr_index = rating_options.index(cr_val) if cr_val in rating_options else 0
        calibration_rating = st.selectbox(
            "Overall rating",
            rating_options,
            index=cr_index,
        )
    with cal2:
        calibration_comment = st.text_input(
            "Calibration suitability comment",
            value=draft.get(
                "calibration_comment",
                "Suitable for 3+ months monitoring for model calibration.",
            ),
        )

    modelling_notes = st.text_area(
        "Modelling notes (how this site should / should not be used)",
        value=draft.get("modelling_notes", ""),
    )
    data_quality_risks = st.text_area(
        "Known data quality risks or limitations",
        value=draft.get("data_quality_risks", ""),
    )

    st.markdown("**Installer checklist**")
    ch1, ch2, ch3, ch4, ch5 = st.columns(5)
    with ch1:
        chk_sensor_in_main_flow = st.checkbox(
            "Sensor in main flow path",
            value=draft.get("chk_sensor_in_main_flow", True),
        )
    with ch2:
        chk_no_immediate_drops = st.checkbox(
            "No immediate drops",
            value=draft.get("chk_no_immediate_drops", True),
        )
    with ch3:
        chk_depth_range_ok = st.checkbox(
            "Depth/velocity ranges OK",
            value=draft.get("chk_depth_range_ok", True),
        )
    with ch4:
        chk_logging_started = st.checkbox(
            "Logging started",
            value=draft.get("chk_logging_started", True),
        )
    with ch5:
        chk_comms_checked_platform = st.checkbox(
            "Comms/data checked",
            value=draft.get("chk_comms_checked_platform", True),
        )

    st.markdown("---")

    st.subheader("Diagram & Photos")

    diag_col1, diag_col2 = st.columns([2, 2])
    with diag_col1:
        diagram_file = st.file_uploader(
            "Upload manhole / site diagram (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
        )
    existing_diagram = draft.get("diagram")
    default_diag_name = (
        existing_diagram.get("name", "Manhole / site diagram")
        if existing_diagram
        else "Manhole / site diagram"
    )
    with diag_col2:
        diagram_name = st.text_input(
            "Diagram name / caption",
            value=default_diag_name,
        )

    photo_files = st.file_uploader(
        "Upload site photos (manhole, sensor, upstream, downstream, access, etc.)",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="photo_files",
    )

    st.caption(
        "You can name each photo below. All uploaded photos will be included in the PDF."
    )

    new_photos = []
    for i, f in enumerate(photo_files or []):
        cap = st.text_input(
            f"Photo {i+1} name / description",
            value=f.name,
            key=f"photo_caption_{f.name}_{i}",
        )
        new_photos.append(
            {
                "name": cap,
                "data": f.getvalue(),
                "mime": f.type,
            }
        )

    existing_photos = draft.get("photos", []) or []
    if existing_photos and not photo_files:
        st.info(
            f"{len(existing_photos)} existing photo(s) already stored for this site. "
            "They will be included in the PDF."
        )
    elif existing_photos and photo_files:
        st.info(
            f"{len(existing_photos)} existing photo(s) plus "
            f"{len(new_photos)} new photo(s) will be stored."
        )

    st.markdown("---")

    st.subheader("Reporting details (Prepared / Reviewed)")

    rep1, rep2, rep3 = st.columns(3)
    with rep1:
        prepared_by = st.text_input(
            "Prepared by",
            value=draft.get("prepared_by", ""),
        )
        prepared_position = st.text_input(
            "Prepared – position",
            value=draft.get("prepared_position", ""),
        )

        prepared_date_default = draft.get("prepared_date")
        if isinstance(prepared_date_default, str):
            try:
                prepared_date_default = date.fromisoformat(prepared_date_default)
            except ValueError:
                prepared_date_default = date.today()
        elif isinstance(prepared_date_default, date):
            pass
        else:
            prepared_date_default = date.today()

        prepared_date = st.date_input(
            "Prepared – date",
            value=prepared_date_default,
        )
    with rep2:
        reviewed_by = st.text_input(
            "Reviewed by",
            value=draft.get("reviewed_by", ""),
        )
        reviewed_position = st.text_input(
            "Reviewed – position",
            value=draft.get("reviewed_position", ""),
        )

        reviewed_date_default = draft.get("reviewed_date")
        if isinstance(reviewed_date_default, str):
            try:
                reviewed_date_default = date.fromisoformat(reviewed_date_default)
            except ValueError:
                reviewed_date_default = date.today()
        elif isinstance(reviewed_date_default, date):
            pass
        else:
            reviewed_date_default = date.today()

        reviewed_date = st.date_input(
            "Reviewed – date",
            value=reviewed_date_default,
        )
    with rep3:
        st.write("")
        st.write("")
        st.write("Use these fields for internal QA / sign-off.")

    st.markdown("---")

    submit_col1, submit_col2 = st.columns([1, 3])
    with submit_col1:
        submit_label = (
            "Update site in current project"
            if edit_index is not None
            else "Add site to current project"
        )
        submitted = st.form_submit_button(
            submit_label,
            use_container_width=True,
        )
    with submit_col2:
        st.caption(
            "Once submitted, the site will appear below and can be exported "
            "to Excel or a single-site PDF report."
        )

    # ---------- Handle form submit ----------
    if submitted:
        derived = calculate_average_depth_velocity_and_flow(
            pipe_diameter_mm,
            depth_check_meas_mm,
            depth_check_meter_mm,
            vel_check_meas_ms,
            vel_check_meter_ms,
            updated_extra,
        )

        if diagram_file is not None:
            diagram_obj = {
                "name": diagram_name or diagram_file.name,
                "data": diagram_file.getvalue(),
                "mime": diagram_file.type,
            }
        else:
            diagram_obj = existing_diagram

        all_photos = merge_photo_records(existing_photos, new_photos)

        site_record = {
            "project_name": project_name,
            "client": client,
            "catchment": catchment,
            "site_name": site_name,
            "site_id": site_id,
            "client_asset_id": client_asset_id,
            "gis_id": gis_id,
            "install_date": str(install_date),
            "install_time": install_time.strftime("%H:%M"),
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "site_address": site_address,
            "manhole_location_desc": manhole_location_desc,
            "access_type": access_type,
            "confined_space_required": confined_space_required,
            "traffic_control_required": traffic_control_required,
            "access_safety_constraints": access_safety_constraints,
            "other_permits_required": other_permits_required,
            "pipe_diameter_mm": pipe_diameter_mm,
            "pipe_material": pipe_material,
            "pipe_shape": pipe_shape,
            "depth_to_invert_mm": depth_to_invert_mm,
            "depth_to_soffit_mm": depth_to_soffit_mm,
            "hydro_turbulence_level": hydro_turbulence_level,
            "upstream_config": upstream_config,
            "downstream_config": downstream_config,
            "hydro_drops": hydro_drops,
            "hydro_bends": hydro_bends,
            "hydro_junctions": hydro_junctions,
            "hydro_surcharge_risk": hydro_surcharge_risk,
            "hydro_backwater_risk": hydro_backwater_risk,
            "hydraulic_notes": hydraulic_notes,
            "meter_model": meter_model,
            "logger_serial": logger_serial,
            "sensor_serial": sensor_serial,
            "sensor_distance_from_manhole_m": sensor_distance_from_manhole_m,
            "sensor_orientation": sensor_orientation,
            "sensor_mount_type": sensor_mount_type,
            "datum_reference_desc": datum_reference_desc,
            "level_range_min_mm": level_range_min_mm,
            "level_range_max_mm": level_range_max_mm,
            "velocity_range_min_ms": velocity_range_min_ms,
            "velocity_range_max_ms": velocity_range_max_ms,
            "output_scaling_desc": output_scaling_desc,
            "logging_interval_min": logging_interval_min,
            "timezone": timezone,
            "comms_method": comms_method,
            "telemetry_logger_id": telemetry_logger_id,
            "telemetry_server": telemetry_server,
            "telemetry_notes": telemetry_notes,
            "depth_check_meas_mm": depth_check_meas_mm,
            "depth_check_meter_mm": depth_check_meter_mm,
            "depth_check_tolerance_mm": depth_check_tolerance_mm,
            "depth_check_diff_mm": depth_check_diff_mm,
            "depth_check_within_tol": depth_check_within_tol,
            "vel_check_meas_ms": vel_check_meas_ms,
            "vel_check_meter_ms": vel_check_meter_ms,
            "vel_check_diff_ms": vel_check_meter_ms - vel_check_meas_ms,
            "comms_verified": comms_verified,
            "comms_verified_at": comms_verified_at,
            "zero_depth_check_done": zero_depth_check_done,
            "zero_depth_check_notes": zero_depth_check_notes,
            "reference_device_type": reference_device_type,
            "reference_device_id": reference_device_id,
            "reference_reading_desc": reference_reading_desc,
            "verification_readings": updated_extra,
            "calibration_rating": calibration_rating,
            "calibration_comment": calibration_comment,
            "modelling_notes": modelling_notes,
            "data_quality_risks": data_quality_risks,
            "chk_sensor_in_main_flow": chk_sensor_in_main_flow,
            "chk_no_immediate_drops": chk_no_immediate_drops,
            "chk_depth_range_ok": chk_depth_range_ok,
            "chk_logging_started": chk_logging_started,
            "chk_comms_checked_platform": chk_comms_checked_platform,
            "diagram": diagram_obj,
            "photos": all_photos,
            "prepared_by": prepared_by,
            "prepared_position": prepared_position,
            "prepared_date": str(prepared_date),
            "reviewed_by": reviewed_by,
            "reviewed_position": reviewed_position,
            "reviewed_date": str(reviewed_date),
        }
        site_record.update(derived)

        # Enforce uniqueness: site name only
        for i, s in enumerate(sites):
            if (
                i != (edit_index if edit_index is not None else -1)
                and s.get("site_name") == site_name
            ):
                st.error(
                    "A site with this **site / manhole name** already exists. "
                    "Please adjust the name or load that site for editing."
                )
                st.stop()

        if edit_index is None:
            st.session_state["sites"].append(site_record)
            st.success("Site added to current project.")
            # Clear GPS and address for next site entry
            st.session_state["gps_lat"] = ""
            st.session_state["gps_lon"] = ""
            st.session_state["gps_last_clicked"] = None
            st.session_state["auto_address"] = ""
            st.session_state["site_address"] = ""
            st.session_state["last_geocoded_coords"] = None
        else:
            st.session_state["sites"][edit_index] = site_record
            st.success("Site updated.")

        st.session_state["draft_site"] = site_record
        st.session_state["edit_index"] = None

# ---------- Current sites / edit / delete ----------
st.subheader("Current Sites in Project")

if not sites:
    st.info("No sites added yet. Use the form above to add your first site.")
else:
    options = [f"{i+1}. {s['project_name']} – {s['site_name']}" for i, s in enumerate(sites)]
    idx = st.selectbox(
        "Select a site to edit / delete",
        options=range(len(sites)),
        format_func=lambda i: options[i],
        key="site_select",
    )

    col_actions1, col_actions2, col_actions3, col_actions4 = st.columns([1, 1, 1, 3])
    with col_actions1:
        if st.button("✏️ Load selected for editing"):
            st.session_state["draft_site"] = sites[idx]
            st.session_state["edit_index"] = idx
            st.session_state["gps_lat"] = sites[idx].get("gps_lat", "")
            st.session_state["gps_lon"] = sites[idx].get("gps_lon", "")
            st.session_state["auto_address"] = sites[idx].get("site_address", "")
            st.session_state["site_address"] = sites[idx].get("site_address", "")
            safe_rerun()
    with col_actions2:
        if st.button("🗑️ Delete selected site"):
            st.session_state["sites"].pop(idx)
            st.session_state["draft_site"] = None
            st.session_state["edit_index"] = None
            st.session_state["gps_lat"] = ""
            st.session_state["gps_lon"] = ""
            st.session_state["gps_last_clicked"] = None
            st.session_state["auto_address"] = ""
            st.session_state["site_address"] = ""
            st.session_state["last_geocoded_coords"] = None
            st.success("Site deleted from project.")
            safe_rerun()
    with col_actions3:
        if st.button("💾 Save to database"):
            try:
                filename = save_report_to_database(sites[idx])
                st.success(f"Report saved to database: {filename}")
            except Exception as e:
                st.error(f"Error saving report: {e}")

# ---------- Export section ----------
st.subheader("Export")

if not sites:
    st.info("Add at least one site to enable exports.")
else:
    col_exp1, col_exp2 = st.columns([1, 1])

    with col_exp1:
        excel_bytes = create_excel_bytes(sites)
        st.download_button(
            "⬇️ Export all sites to Excel",
            data=excel_bytes,
            file_name="sewer_flow_installation_sites.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col_exp2:
        pdf_idx = st.selectbox(
            "Select a site for PDF export",
            options=range(len(sites)),
            format_func=lambda i: f"{i+1}. {sites[i]['project_name']} – {sites[i]['site_name']}",
            key="pdf_site_select",
        )
        pdf_buffer = create_pdf_bytes([sites[pdf_idx]])
        pdf_bytes = pdf_buffer.getvalue()
        proj = sites[pdf_idx].get("project_name", "project").replace(" ", "_")
        sname = sites[pdf_idx].get("site_name", "site").replace(" ", "_")
        st.download_button(
            "📄 Export selected site to PDF",
            data=pdf_bytes,
            file_name=f"{proj}_{sname}_installation_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    selected_site = sites[pdf_idx]

# ---------- Saved Reports Database Section ----------
st.markdown("---")
st.header("📚 Saved Reports Database")

# Load all saved reports
saved_reports = load_all_reports()

if not saved_reports:
    st.info(
        "No reports saved yet. Use the **💾 Save to database** button above "
        "to save completed reports to the GitHub repository."
    )
else:
    st.success(f"Found {len(saved_reports)} saved report(s) in the database.")
    
    # Search and filter
    col_search1, col_search2, col_search3 = st.columns([2, 1, 1])
    with col_search1:
        search_term = st.text_input(
            "🔍 Search reports (project name, site name, client)",
            key="search_reports",
        )
    with col_search2:
        sort_by = st.selectbox(
            "Sort by",
            ["Date (newest)", "Date (oldest)", "Project", "Site"],
            key="sort_reports",
        )
    with col_search3:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh list"):
            safe_rerun()
    
    # Filter reports based on search
    filtered_reports = saved_reports
    if search_term:
        search_lower = search_term.lower()
        filtered_reports = [
            r for r in saved_reports
            if search_lower in r.get("project_name", "").lower()
            or search_lower in r.get("site_name", "").lower()
            or search_lower in r.get("client", "").lower()
            or search_lower in r.get("site_id", "").lower()
        ]
    
    # Sort reports
    if sort_by == "Date (oldest)":
        filtered_reports = list(reversed(filtered_reports))
    elif sort_by == "Project":
        filtered_reports = sorted(
            filtered_reports,
            key=lambda r: r.get("project_name", "").lower()
        )
    elif sort_by == "Site":
        filtered_reports = sorted(
            filtered_reports,
            key=lambda r: r.get("site_name", "").lower()
        )
    
    if not filtered_reports:
        st.warning(f"No reports found matching '{search_term}'")
    else:
        st.caption(f"Showing {len(filtered_reports)} report(s)")
        
        # Display reports in an expandable list
        for i, report in enumerate(filtered_reports):
            summary = get_report_summary(report)
            filename = report.get("_filename", "unknown.json")
            
            with st.expander(f"📄 {summary}"):
                col_info1, col_info2, col_info3 = st.columns([2, 2, 2])
                
                with col_info1:
                    st.markdown("**Project Details**")
                    st.text(f"Project: {report.get('project_name', 'N/A')}")
                    st.text(f"Client: {report.get('client', 'N/A')}")
                    st.text(f"Catchment: {report.get('catchment', 'N/A')}")
                
                with col_info2:
                    st.markdown("**Site Details**")
                    st.text(f"Site: {report.get('site_name', 'N/A')}")
                    st.text(f"Site ID: {report.get('site_id', 'N/A')}")
                    st.text(f"Install Date: {report.get('install_date', 'N/A')}")
                
                with col_info3:
                    st.markdown("**Equipment**")
                    st.text(f"Meter: {report.get('meter_model', 'N/A')}")
                    st.text(f"Logger: {report.get('logger_serial', 'N/A')}")
                    st.text(f"Rating: {report.get('calibration_rating', 'N/A')}")
                
                # Location
                if report.get("gps_lat") and report.get("gps_lon"):
                    st.markdown("**Location**")
                    st.text(f"GPS: {report.get('gps_lat')}, {report.get('gps_lon')}")
                    if report.get("site_address"):
                        st.text(f"Address: {report.get('site_address')}")
                
                # Actions
                st.markdown("---")
                col_act1, col_act2, col_act3, col_act4 = st.columns(4)
                
                with col_act1:
                    if st.button("📥 Load to form", key=f"load_{filename}"):
                        # Load this report into the form for editing
                        st.session_state["draft_site"] = report
                        st.session_state["edit_index"] = None
                        st.session_state["gps_lat"] = report.get("gps_lat", "")
                        st.session_state["gps_lon"] = report.get("gps_lon", "")
                        st.session_state["auto_address"] = report.get("site_address", "")
                        st.session_state["site_address"] = report.get("site_address", "")
                        st.success("Report loaded into form. Scroll up to edit.")
                        safe_rerun()
                
                with col_act2:
                    # Export single report to PDF
                    pdf_single = create_pdf_bytes([report])
                    proj_name = report.get("project_name", "project").replace(" ", "_")
                    site_name = report.get("site_name", "site").replace(" ", "_")
                    st.download_button(
                        "📄 PDF",
                        data=pdf_single,
                        file_name=f"{proj_name}_{site_name}_report.pdf",
                        mime="application/pdf",
                        key=f"pdf_{filename}",
                    )
                
                with col_act3:
                    # Export to Excel
                    excel_single = create_excel_bytes([report])
                    st.download_button(
                        "📊 Excel",
                        data=excel_single,
                        file_name=f"{proj_name}_{site_name}_data.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"excel_{filename}",
                    )
                
                with col_act4:
                    if st.button("🗑️ Delete", key=f"delete_{filename}"):
                        if delete_report_from_database(filename):
                            st.success(f"Report deleted: {filename}")
                            safe_rerun()
                        else:
                            st.error(f"Failed to delete: {filename}")
        
        # Bulk export options
        st.markdown("---")
        st.subheader("Bulk Export")
        col_bulk1, col_bulk2 = st.columns(2)
        
        with col_bulk1:
            # Export all filtered reports to Excel
            if filtered_reports:
                excel_all = create_excel_bytes(filtered_reports)
                st.download_button(
                    "📊 Export all filtered reports to Excel",
                    data=excel_all,
                    file_name="all_saved_reports.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        
        with col_bulk2:
            # Export all filtered reports to a combined PDF
            if filtered_reports:
                pdf_all = create_pdf_bytes(filtered_reports)
                st.download_button(
                    "📄 Export all filtered reports to PDF",
                    data=pdf_all,
                    file_name="all_saved_reports.pdf",
                    mime="application/pdf",
                )

st.markdown("---")
st.caption(
    "💡 **Tip:** All saved reports are stored in the `data/reports/` directory "
    "and are tracked by Git. This means all your installation reports are versioned "
    "and backed up in your GitHub repository."
)

    st.markdown("---")
    st.subheader("GitHub Storage")

    token_env = os.getenv("GITHUB_REPORT_TOKEN") or os.getenv("GITHUB_TOKEN")
    try:
        token_secret = (
            st.secrets.get("github_report_token")
            if hasattr(st, "secrets")
            else None
        )
    except Exception:
        token_secret = None
    github_token = token_secret or token_env

    default_repo = os.getenv("GITHUB_REPORT_REPO", "")
    default_branch = os.getenv("GITHUB_REPORT_BRANCH", "main")
    default_folder = os.getenv("GITHUB_REPORT_FOLDER", "reports")

    repo_value = st.text_input(
        "GitHub repository (owner/name)",
        value=st.session_state.get("github_repo", default_repo),
        key="github_repo_input",
        help="Example: organisation/eds-install-reports",
    )
    branch_value = st.text_input(
        "Branch",
        value=st.session_state.get("github_branch", default_branch),
        key="github_branch_input",
    )
    folder_value = st.text_input(
        "Destination folder in repository",
        value=st.session_state.get("github_folder", default_folder),
        key="github_folder_input",
        help="Reports are stored as JSON bundles inside this folder.",
    )

    st.session_state["github_repo"] = repo_value
    st.session_state["github_branch"] = branch_value
    st.session_state["github_folder"] = folder_value

    if not github_token:
        st.info(
            "Set a `GITHUB_REPORT_TOKEN` environment variable (or `github_report_token` secret) with repo write access to enable uploads."
        )
    elif not repo_value.strip():
        st.info("Enter the target GitHub repository to enable uploads.")
    else:
        if st.button(
            "⬆️ Upload selected site bundle to GitHub",
            use_container_width=True,
            key="github_upload_button",
        ):
            try:
                result = upload_site_report_to_github(
                    selected_site,
                    pdf_bytes,
                    repo_value.strip(),
                    token=github_token,
                    branch=branch_value.strip() or "main",
                    base_folder=folder_value.strip() or "reports",
                )
                destination = result.get("html_url") or result.get("path")
                st.success(f"Report uploaded to GitHub ({destination}).")
            except Exception as exc:
                st.error(f"GitHub upload failed: {exc}")
