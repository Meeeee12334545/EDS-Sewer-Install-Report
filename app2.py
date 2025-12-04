import io
import math
from datetime import date, time
from typing import List, Dict, Any

import pandas as pd

# --- Optional UI dependency ---
STREAMLIT_AVAILABLE = True
try:
    import streamlit as st
except ModuleNotFoundError:
    STREAMLIT_AVAILABLE = False
    print("Warning: Streamlit is not available. Running in CLI mode.")

# --- PDF (ReportLab) ---
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# ==========================
# Hydraulics / Calculations
# ==========================

def wetted_area_circular_m2(depth_mm: float, diameter_mm: float) -> float:
    """Wetted area for a circular pipe flowing partially full.
    depth_mm, diameter_mm in mm -> area in m^2
    """
    if diameter_mm <= 0 or depth_mm <= 0:
        return 0.0
    D_m = diameter_mm / 1000.0
    r = D_m / 2.0
    h = max(0.0, min(depth_mm / 1000.0, D_m))
    if h >= D_m:  # full
        return math.pi * r * r
    # circular segment area: r^2*acos((r-h)/r) - (r-h)*sqrt(2rh - h^2)
    return r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(max(0.0, 2 * r * h - h * h))


def calc_summary(
    pipe_diameter_mm: float,
    depth_meas_mm: float,
    depth_meter_mm: float,
    vel_meas_ms: float,
    vel_meter_ms: float,
    extra: List[Dict[str, Any]] | None = None,
) -> Dict[str, float]:
    extra = extra or []
    d_meas = [v for v in [depth_meas_mm] + [r.get("depth_meas_mm", 0) for r in extra] if v and v > 0]
    d_meter = [v for v in [depth_meter_mm] + [r.get("depth_meter_mm", 0) for r in extra] if v and v > 0]
    v_meas = [v for v in [vel_meas_ms] + [r.get("vel_meas_ms", 0.0) for r in extra] if v and v > 0]
    v_meter = [v for v in [vel_meter_ms] + [r.get("vel_meter_ms", 0.0) for r in extra] if v and v > 0]

    avg_d_meas = sum(d_meas) / len(d_meas) if d_meas else 0.0
    avg_d_meter = sum(d_meter) / len(d_meter) if d_meter else 0.0
    avg_v_meas = sum(v_meas) / len(v_meas) if v_meas else 0.0
    avg_v_meter = sum(v_meter) / len(v_meter) if v_meter else 0.0

    area_meas = wetted_area_circular_m2(avg_d_meas, pipe_diameter_mm)
    area_meter = wetted_area_circular_m2(avg_d_meter, pipe_diameter_mm)

    q_meas = area_meas * avg_v_meas * 1000.0
    q_meter = area_meter * avg_v_meter * 1000.0
    q_diff = q_meter - q_meas
    q_diff_pct = (q_diff / q_meas * 100.0) if q_meas else 0.0

    return {
        "avg_depth_meas_mm": round(avg_d_meas, 2),
        "avg_depth_meter_mm": round(avg_d_meter, 2),
        "avg_vel_meas_ms": round(avg_v_meas, 3),
        "avg_vel_meter_ms": round(avg_v_meter, 3),
        "flow_meas_lps": round(q_meas, 3),
        "flow_meter_lps": round(q_meter, 3),
        "flow_diff_lps": round(q_diff, 3),
        "flow_diff_percent": round(q_diff_pct, 3),
    }

# ==================
# Export Utilities
# ==================

def export_csv_bytes(sites: List[Dict[str, Any]]) -> io.BytesIO:
    df = pd.DataFrame(sites)
    buf = io.BytesIO()
    buf.write(df.to_csv(index=False).encode("utf-8"))
    buf.seek(0)
    return buf


def export_pdf_bytes(sites: List[Dict[str, Any]]) -> io.BytesIO:
    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    W, H = A4
    for s in sites:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, H - 20 * mm, f"Site: {s.get('site_name','')}")
        c.setFont("Helvetica", 10)
        y = H - 30 * mm
        for k, v in s.items():
            if k == "verification_readings":
                continue
            c.drawString(20 * mm, y, f"{k}: {v}")
            y -= 6 * mm
            if y < 20 * mm:
                c.showPage(); y = H - 20 * mm
        # Verification table
        ver = s.get("verification_readings") or []
        if ver:
            if y < 50 * mm:
                c.showPage(); y = H - 20 * mm
            c.setFont("Helvetica-Bold", 11)
            c.drawString(20 * mm, y, "Verification Readings")
            y -= 7 * mm
            c.setFont("Helvetica", 10)
            headers = ["depth_meas_mm", "depth_meter_mm", "vel_meas_ms", "vel_meter_ms", "comment"]
            c.drawString(20 * mm, y, " | ".join(headers))
            y -= 6 * mm
            for row in ver:
                line = " | ".join(str(row.get(h, "")) for h in headers)
                c.drawString(20 * mm, y, line)
                y -= 6 * mm
                if y < 20 * mm:
                    c.showPage(); y = H - 20 * mm
        c.showPage()
    c.save()
    pdf_buf.seek(0)
    return pdf_buf

# ==================
# Streamlit UI
# ==================
if STREAMLIT_AVAILABLE:
    st.set_page_config(
        page_title="Sewer Flow Meter Installation Reporter",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # --- Light theme CSS (high-contrast, readable) ---
    st.markdown(
        """
        <style>
        :root {
            --bg: #f7f9fc;           /* light background */
            --card: #ffffff;         /* white cards */
            --text: #0f172a;         /* slate-900 */
            --muted: #334155;        /* slate-700 */
            --accent: #0ea5e9;       /* sky-500 */
            --border: #e2e8f0;       /* gray-200 */
        }
        html { color-scheme: light; }
        .stApp { background: var(--bg) !important; color: var(--text) !important; }
        .block-container { padding-top: 1.2rem; }
        h1, h2, h3, h4, h5, h6, p, label { color: var(--text) !important; }
        .eds-card { background: var(--card); padding: 16px; border: 1px solid var(--border); border-radius: 12px; }
        .eds-pill { background: #eaf6ff; color: var(--muted); padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); }
        hr { border-color: var(--border); }

        /* --- Inputs: force light controls even in dark OS/Streamlit theme --- */
        input, textarea, select {
            background: #ffffff !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
            border-radius: 10px !important;
        }
        .stTextInput > div > div > input,
        .stTextArea textarea,
        .stNumberInput input,
        .stDateInput input,
        .stTimeInput input {
            background: #ffffff !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
            border-radius: 10px !important;
        }
        /* Selectbox (BaseWeb) */
        [data-baseweb="select"] > div,
        [data-baseweb="select"] input {
            background: #ffffff !important;
            color: var(--text) !important;
        }
        /* Tabs */
        .stTabs [data-baseweb="tab"] {
            color: #1f2937 !important;  /* slate-800 */
        }
        .stTabs [data-baseweb="tab"]:hover { color: #0f172a !important; }
        .stTabs [aria-selected="true"] { border-color: var(--accent) !important; color: #0f172a !important; }
    </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("💧 Sewer Flow Meter Installation Reporter")
    st.caption("Standardised EDS installation reports for sewer flow modelling and inflow/infiltration studies.")

    # --- Session init ---
    if "sites" not in st.session_state:
        st.session_state.sites: List[Dict[str, Any]] = []
    if "verify_df" not in st.session_state:
        st.session_state.verify_df = pd.DataFrame(
            columns=["depth_meas_mm", "depth_meter_mm", "vel_meas_ms", "vel_meter_ms", "comment"]
        )

    # --- Tabs ---
    t1, t2, t3, t4, t5 = st.tabs([
        "Project & Site",
        "Pipe & Hydraulics",
        "Verification",
        "Results",
        "Export",
    ])

    with t1:
        st.subheader("Project & Site", divider="gray")
        col1, col2, col3 = st.columns([1.2, 1, 1])
        with col1:
            project_name = st.text_input("Project name", value="Example Project")
            client = st.text_input("Client", value="Example Client")
            catchment = st.text_input("Catchment / area", value="")
            site_name = st.text_input("Site / manhole name", value="Manhole 1")
            site_id = st.text_input("Site ID", value="")
        with col2:
            client_asset_id = st.text_input("Client asset ID", value="")
            gis_id = st.text_input("GIS ID", value="")
            install_date = st.date_input("Install date", value=date.today())
            install_time = st.time_input("Install time", value=time(9, 0))
        with col3:
            gps_lat = st.text_input("GPS latitude", value="")
            gps_lon = st.text_input("GPS longitude", value="")
            access_desc = st.text_area("Location / access notes", value="", height=100)

    with t2:
        st.subheader("Pipe & Hydraulics", divider="gray")
        c1, c2, c3 = st.columns(3)
        with c1:
            pipe_d = st.number_input("Pipe diameter (mm)", min_value=0, max_value=4000, value=300, step=25)
            depth_meas = st.number_input("Measured depth (mm)", min_value=0, max_value=4000, value=250, step=5)
        with c2:
            depth_meter = st.number_input("Meter depth (mm)", min_value=0, max_value=4000, value=245, step=5)
            vel_meas = st.number_input("Measured velocity (m/s)", min_value=0.0, max_value=10.0, value=1.2, step=0.05)
        with c3:
            vel_meter = st.number_input("Meter velocity (m/s)", min_value=0.0, max_value=10.0, value=1.15, step=0.05)
            st.markdown("<span class='eds-pill'>Tip:</span> Enter primary checks here; add extra checks in the Verification tab.", unsafe_allow_html=True)

    with t3:
        st.subheader("Additional Verification Readings", divider="gray")
        st.caption("Use the table to add any additional depth/velocity checks taken on-site.")
        st.session_state.verify_df = st.data_editor(
            st.session_state.verify_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "depth_meas_mm": st.column_config.NumberColumn("Depth (meas, mm)", step=1),
                "depth_meter_mm": st.column_config.NumberColumn("Depth (meter, mm)", step=1),
                "vel_meas_ms": st.column_config.NumberColumn("Velocity (meas, m/s)", step=0.01),
                "vel_meter_ms": st.column_config.NumberColumn("Velocity (meter, m/s)", step=0.01),
                "comment": st.column_config.TextColumn("Comment"),
            },
        )

    with t4:
        st.subheader("Results", divider="gray")
        results = calc_summary(
            pipe_diameter_mm=pipe_d,
            depth_meas_mm=depth_meas,
            depth_meter_mm=depth_meter,
            vel_meas_ms=vel_meas,
            vel_meter_ms=vel_meter,
            extra=st.session_state.verify_df.to_dict("records"),
        )
        cA, cB = st.columns([1, 1])
        with cA:
            st.metric("Average depth (meas, mm)", results["avg_depth_meas_mm"])
            st.metric("Average velocity (meas, m/s)", results["avg_vel_meas_ms"])
            st.metric("Flow (meas, L/s)", results["flow_meas_lps"])
        with cB:
            st.metric("Average depth (meter, mm)", results["avg_depth_meter_mm"])
            st.metric("Average velocity (meter, m/s)", results["avg_vel_meter_ms"])
            st.metric("Flow (meter, L/s)", results["flow_meter_lps"])
        st.divider()
        st.metric("Difference (L/s)", results["flow_diff_lps"])
        st.metric("Difference (%)", results["flow_diff_percent"]) 

        if st.button("Add site to project", type="primary"):
            site_record = {
                "project_name": project_name,
                "client": client,
                "catchment": catchment,
                "site_name": site_name,
                "site_id": site_id,
                "client_asset_id": client_asset_id,
                "gis_id": gis_id,
                "install_date": str(install_date),
                "install_time": str(install_time),
                "gps_lat": gps_lat,
                "gps_lon": gps_lon,
                "access_desc": access_desc,
                "pipe_diameter_mm": pipe_d,
                "depth_check_meas_mm": depth_meas,
                "depth_check_meter_mm": depth_meter,
                "vel_check_meas_ms": vel_meas,
                "vel_check_meter_ms": vel_meter,
                "verification_readings": st.session_state.verify_df.to_dict("records"),
            }
            site_record.update(results)
            st.session_state.sites.append(site_record)
            st.success(f"Added site: {site_name}")

        # Show current list
        if st.session_state.sites:
            st.write("### Current project sites")
            st.dataframe(pd.DataFrame(st.session_state.sites)[[
                "site_name", "flow_meas_lps", "flow_meter_lps", "flow_diff_lps", "flow_diff_percent"
            ]], use_container_width=True)

    with t5:
        st.subheader("Export", divider="gray")
        if not st.session_state.sites:
            st.info("Add at least one site in the Results tab before exporting.")
        else:
            csv_buf = export_csv_bytes(st.session_state.sites)
            st.download_button("Download CSV", data=csv_buf, file_name="sites_summary.csv", mime="text/csv")
            pdf_buf = export_pdf_bytes(st.session_state.sites)
            st.download_button("Download PDF", data=pdf_buf, file_name="sites_summary.pdf", mime="application/pdf")
            st.success("Exports are ready. CSV includes all fields; PDF includes a readable summary and verification table.")

# ==================
# CLI fallback
# ==================
if not STREAMLIT_AVAILABLE:
    print("Running in CLI mode with sample data.")
    sample_sites = [
        {
            "project_name": "Example Project",
            "client": "Example Client",
            "catchment": "",
            "site_name": "Manhole 1",
            "site_id": "",
            "client_asset_id": "",
            "gis_id": "",
            "install_date": str(date.today()),
            "install_time": str(time(9, 0)),
            "gps_lat": "",
            "gps_lon": "",
            "access_desc": "",
            "pipe_diameter_mm": 300.0,
            "depth_check_meas_mm": 250.0,
            "depth_check_meter_mm": 245.0,
            "vel_check_meas_ms": 1.2,
            "vel_check_meter_ms": 1.15,
            "verification_readings": [
                {"depth_meas_mm": 255, "depth_meter_mm": 248, "vel_meas_ms": 1.23, "vel_meter_ms": 1.16, "comment": "check #2"}
            ],
        }
    ]
    # compute
    for s in sample_sites:
        res = calc_summary(
            s["pipe_diameter_mm"], s["depth_check_meas_mm"], s["depth_check_meter_mm"], s["vel_check_meas_ms"], s["vel_check_meter_ms"], s["verification_readings"],
        )
        s.update(res)

    # console table
    print("\nSummary of All Sites:")
    print(f"{'Site Name':<15} {'Flow Meas (L/s)':<17} {'Flow Meter (L/s)':<18} {'Diff (L/s)':<12} {'Diff (%)':<10}")
    for s in sample_sites:
        print(f"{s['site_name']:<15} {s['flow_meas_lps']:<17.2f} {s['flow_meter_lps']:<18.2f} {s['flow_diff_lps']:<12.2f} {s['flow_diff_percent']:<10.2f}")

    # exports
    with open("sites_summary.csv", "wb") as f:
        f.write(export_csv_bytes(sample_sites).getbuffer())
    with open("sites_summary.pdf", "wb") as f:
        f.write(export_pdf_bytes(sample_sites).getbuffer())
    print("\nCreated: sites_summary.csv, sites_summary.pdf")
