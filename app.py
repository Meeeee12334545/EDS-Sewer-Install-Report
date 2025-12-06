import io
import math
from datetime import time, date

import pandas as pd
import streamlit as st
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


# ---------- PDF helpers ----------
def draw_header_bar(c, width, project, site_id, site_name):
    margin = 20 * mm
    bar_height = 18 * mm
    c.setFillGray(0.9)
    c.rect(0, A4[1] - bar_height, width, bar_height, fill=1, stroke=0)

    c.setFillGray(0.0)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, A4[1] - bar_height + 5 * mm, (project or "")[:80])

    c.setFont("Helvetica", 10)
    right_text = f"{site_id} – {site_name}".strip(" –")
    c.drawRightString(width - margin, A4[1] - bar_height + 5 * mm, right_text)


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
    y = height - 55 * mm

    # 1. Project & identifiers
    draw_section_title(c, "1. Project & Identifiers", margin, y)
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

    draw_header_bar(
        c,
        width,
        site.get("project_name", "Project"),
        site.get("site_id", ""),
        site.get("site_name", ""),
    )
    y = height - 55 * mm

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
        draw_section_title(c, "6. Additional Verification Readings", margin, y)
        y -= line_height * 1.5
        for i, r in enumerate(extra):
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
    draw_section_title(c, "7. Flow (for model calibration)", margin, y)
    y -= line_height * 1.5
    y = draw_wrapped_kv(c, "Flow (manual)", flow_meas_line, margin, y, line_height)
    y = draw_wrapped_kv(c, "Flow (meter)", flow_meter_line, margin, y, line_height)
    y = draw_wrapped_kv(c, "Difference", flow_diff_line, margin, y, line_height)
    y -= line_height * 0.5

    # Calibration suitability & notes
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
    y = height - 55 * mm
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
            y = height - 55 * mm

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
        y = height - 55 * mm

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
        y0 = height - 55 * mm
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
    return buf


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

st.markdown(
    f"""
<style>
:root {{
  --eds-primary: {EDS_PRIMARY};
  --eds-secondary: {EDS_SECONDARY};
  --eds-light-bg: {EDS_LIGHT_BG};
  --eds-card-bg: {EDS_CARD_BG};
  --eds-border: {EDS_BORDER};
  --eds-text: #111827;
  --eds-btn-padding: 0.5rem 1.2rem;
}}

/* Apply Helvetica Neue everywhere possible and enforce readable text colour */
html, body, [data-testid="stAppViewContainer"], .stApp {{
    background-color: var(--eds-light-bg) !important;
    color: var(--eds-text) !important;
    font-family: "Helvetica Neue", "Helvetica", Arial, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

/* Container spacing */
.block-container {{
    padding-top: 2rem;
    padding-bottom: 2rem;
    font-family: inherit !important;
    color: inherit !important;
}}

/* Form card */
div[data-testid="stForm"] {{
    background-color: var(--eds-card-bg) !important;
    padding: 1.5rem 1.75rem;
    border-radius: 8px;
    border: 1px solid var(--eds-border);
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}

/* Headings */
h1, h2, h3 {{
    color: var(--eds-primary) !important;
    font-family: "Helvetica Neue", "Helvetica", Arial, sans-serif !important;
}}

/* Labels and widget labels */
label, [data-testid="stWidgetLabel"] p {{
    color: var(--eds-text) !important;
    font-weight: 500;
    font-size: 0.95rem;
    font-family: inherit !important;
}}

/* Inputs, textareas and selects: ensure white background and dark text */
input, textarea, select, .stText, .stMarkdown, .stCheckbox {{
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    border-radius: 4px !important;
    font-family: inherit !important;
}}

/* Baseweb input/textarea/select */
[data-baseweb="input"], [data-baseweb="input"] * {{
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}
[data-baseweb="textarea"], [data-baseweb="textarea"] * {{
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}
[data-baseweb="select"], [data-baseweb="select"] * {{
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}

/* Streamlit selectbox container */
[data-testid="stSelectbox"] div[role="combobox"] {{
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    border-radius: 4px !important;
    border: 1px solid #d1d5db !important;
    font-family: inherit !important;
}}

/* Expander */
[data-testid="stExpander"] > div {{
    border-radius: 4px !important;
    border: 1px solid #e5e7eb !important;
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] p,
[data-testid="stExpander"] svg {{
    color: var(--eds-text) !important;
    fill: var(--eds-text) !important;
    font-weight: 600 !important;
}}

/* Buttons: normal and download. Force EDS colours and readable foregrounds */
button,
.stButton>button,
[data-testid="stDownloadButton"]>button,
.stDownloadButton>button,
input[type="submit"],
input[type="button"] {{
    font-family: inherit !important;
    background-color: var(--eds-primary) !important;
    color: #ffffff !important;
    border-radius: 6px !important;
    border: none !important;
    padding: var(--eds-btn-padding) !important;
    font-weight: 600 !important;
    box-shadow: none !important;
    cursor: pointer;
}}

/* Download buttons use secondary by default */
[data-testid="stDownloadButton"]>button,
.stDownloadButton>button {{
    background-color: var(--eds-secondary) !important;
}}

/* Hover states: slightly lighter secondary */
button:hover,
.stButton>button:hover,
[data-testid="stDownloadButton"]>button:hover,
.stDownloadButton>button:hover {{
    background-color: var(--eds-secondary) !important;
    color: #ffffff !important;
}}

/* Ensure any icon/text inside buttons is white */
.stButton>button * , .stDownloadButton>button * {{
    color: #ffffff !important;
    fill: #ffffff !important;
}}

/* Alerts – keep background white and readable text */
[data-testid="stAlert"] {{
    border-radius: 4px !important;
    background-color: #ffffff !important;
    border: 1px solid var(--eds-border) !important;
    color: var(--eds-text) !important;
}}
[data-testid="stAlert"] p {{
    color: var(--eds-text) !important;
}}

/* Strong focus highlight for keyboard navigation */
input:focus,
textarea:focus,
select:focus,
button:focus,
[data-baseweb="input"] input:focus,
[data-baseweb="textarea"] textarea:focus,
[data-baseweb="select"] [role="combobox"]:focus {{
    outline: none !important;
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12) !important;
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
}}

/* Streamlit selectbox focus */
[data-testid="stSelectbox"] div[role="combobox"]:focus-within {{
    outline: none !important;
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12) !important;
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
}}

/* Date/time/number inputs focus */
input[type="date"]:focus,
input[type="time"]:focus,
input[type="number"]:focus {{
    outline: none !important;
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12) !important;
}}

/* File uploader focus */
[data-testid="stFileUploader"] section:focus-within {{
    outline: none !important;
    border: 1px solid #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12) !important;
    background-color: #ffffff !important;
    color: var(--eds-text) !important;
}}

/* Defensive fixes: override suspicious inline dark backgrounds */
button[style*="background"] {{
    background-color: var(--eds-primary) !important;
    color: #ffffff !important;
}}
[style*="background-color: black"],
[style*="background-color:#000"],
[style*="background-color: rgb(0, 0, 0)"] {{
    background-color: var(--eds-card-bg) !important;
    color: var(--eds-text) !important;
}}

/* Ensure text nodes inside common containers are readable */
.stApp, .main, .block-container, .css-1bd6qhb, .css-1v3fvcr {{
    color: var(--eds-text) !important;
    font-family: inherit !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

st.title("💧 Sewer Flow Meter Installation Reporter")
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
if "gps_lat" not in st.session_state:
    st.session_state["gps_lat"] = ""
if "gps_lon" not in st.session_state:
    st.session_state["gps_lon"] = ""
if "gps_last_clicked" not in st.session_state:
    st.session_state["gps_last_clicked"] = None
if "device_gps_raw" not in st.session_state:
    st.session_state["device_gps_raw"] = None

sites = st.session_state["sites"]
draft = st.session_state["draft_site"] or {}
edit_index = st.session_state["edit_index"]

# ---------- Map / GPS helper UI ----------
st.header("Add / Record a Site")

with st.expander("Optional: map to set GPS coordinates", expanded=True):
    st.markdown(
        "Pan/zoom to your manhole location, click the map, then use "
        "**Use last map click** to push it into the GPS fields. "
        "If available, **Use device GPS** will read your browser location."
    )

    if st.session_state["gps_lat"] and st.session_state["gps_lon"]:
        center = [float(st.session_state["gps_lat"]), float(st.session_state["gps_lon"])]
    else:
        center = [-27.4698, 153.0251]  # Brisbane default

    # Zoom in more on the interactive map
    m = folium.Map(location=center, zoom_start=19, control_scale=True)

    if st.session_state["gps_last_clicked"]:
        lat, lon = st.session_state["gps_last_clicked"]
        folium.Marker([lat, lon], tooltip="Last clicked location").add_to(m)

    map_result = st_folium(m, height=360, width=None, key="site_map")

    if map_result and map_result.get("last_clicked"):
        lat = map_result["last_clicked"]["lat"]
        lon = map_result["last_clicked"]["lng"]
        st.session_state["gps_last_clicked"] = (lat, lon)

    col_map_btn1, col_map_btn2 = st.columns([1, 1])
    with col_map_btn1:
        if st.button("📍 Use last map click"):
            if st.session_state["gps_last_clicked"]:
                lat, lon = st.session_state["gps_last_clicked"]
                st.session_state["gps_lat"] = f"{lat:.6f}"
                st.session_state["gps_lon"] = f"{lon:.6f}"
            else:
                st.warning("Click on the map first to set a location.")
    with col_map_btn2:
        if GEO_AVAILABLE:
            if st.button("📡 Use device GPS"):
                loc = get_geolocation()
                st.session_state["device_gps_raw"] = loc

                if not loc:
                    st.warning(
                        "Device GPS not available or no response yet. "
                        "This is usually due to the browser blocking location access. "
                        "You can still use the map click to set coordinates."
                    )
                else:
                    err = loc.get("error")
                    if err:
                        st.warning(
                            f"Device GPS error from browser: **{err}**. "
                            "This is controlled by your browser/OS (e.g. blocked on "
                            "non-secure origins or site-level permissions). "
                            "Use the map click instead, or open the app via "
                            "`http://localhost:8501` with Location allowed."
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
                                    "Please use the map click instead."
                                )
                        else:
                            st.warning(
                                "Device GPS did not return coordinates. "
                                "This can happen if the browser only allows "
                                "approximate or blocked location. "
                                "Please use the map click to set an accurate point."
                            )
        else:
            st.caption(
                "Device GPS is not available (install `streamlit-js-eval` to enable it)."
            )

    if GEO_AVAILABLE and st.session_state["device_gps_raw"]:
        st.caption(
            f"Last device GPS raw response: {st.session_state['device_gps_raw']}"
        )

# Pull any stored GPS into the draft
if not draft.get("gps_lat") and st.session_state["gps_lat"]:
    draft["gps_lat"] = st.session_state["gps_lat"]
if not draft.get("gps_lon") and st.session_state["gps_lon"]:
    draft["gps_lon"] = st.session_state["gps_lon"]

# ---------- Site form ----------
with st.form("site_form", clear_on_submit=False):
    # Editing banner
    if edit_index is not None and 0 <= edit_index < len(sites):
        st.info(
            f"Editing site **{sites[edit_index].get('site_name', '')}** "
            f"in project **{sites[edit_index].get('project_name', '')}**. "
            "Update fields and click **Update site in current project**."
        )

    st.subheader("Project & Site")

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
        gps_lat = st.text_input("GPS latitude", value=draft.get("gps_lat", ""))
    with c_gps2:
        gps_lon = st.text_input("GPS longitude", value=draft.get("gps_lon", ""))
    with c_gps3:
        manhole_location_desc = st.text_area(
            "Location description (nearby road, property & landmarks)",
            value=draft.get("manhole_location_desc", ""),
        )

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
