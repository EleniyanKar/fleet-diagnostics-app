import os
import json
import re
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai

# 1. Page Configuration & Environment Setup
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ AI Fleet Diagnostics Dashboard")
st.write("Live fleet diagnostics, subscription renewal opportunities, and network analytics.")

# 2. Administrative Email Exclusion List
ADMIN_EMAILS = {
    "hello@cartracker.com.ng", "oluwafemi.a@cartracker.com", "ayo.a@cartracker.com",
    "inyang@cartracker.com", "rukayat@cartracker.com.ng", "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com", "oyindaabegunde@yahoo.com", "abasifrekeekanem1@cartracker.com",
    "andrew@cartracker.com.ng", "ifeoluwa@cartracker.ng", "james@cartracker.com.org",
    "blessing@catracker.com.ng", "damilola@catracker.com.ng", "dammylola@catracker.com.ng",
    "blessing@catracker.ng", "dammylola@catracker.ng",
}

# 1. Enhanced Phone Cleaner
def clean_phone(val):
    """Standardizes Nigerian MSISDNs, removes Excel floats (.0), and fixes prefixes."""
    if pd.isna(val) or str(val).lower() in ["nan", "none", ""]:
        return ""
    s = str(val).split(".")[0].strip()  # Strip trailing Excel float .0
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("234") and len(digits) == 13:
        digits = "0" + digits[3:]
    elif len(digits) == 10 and digits.startswith(("7", "8", "9")):
        digits = "0" + digits
    return digits


# 2. Tail Extractor for Infallible Matching
def extract_tail(val, tail_len=7):
    cleaned = clean_phone(val)
    return cleaned[-tail_len:] if len(cleaned) >= tail_len else ""


# 3. Network Matcher with Tail Lookup
def sim_network(sim, airtel_tails_set):
    sim_clean = clean_phone(sim)
    if not sim_clean:
        return "Missing"
    
    # Check if last 7 digits match the verified Airtel list
    sim_tail = sim_clean[-7:] if len(sim_clean) >= 7 else ""
    if sim_tail and sim_tail in airtel_tails_set:
        return "Airtel (verified)"
    
    # Fallback to Nigerian telecom prefix lookup
    prefix = sim_clean[:4]
    return PREFIX_TO_NETWORK.get(prefix, "Unknown/Other (guessed)")

# 3. Telecom Network Prefixes (Nigeria)
NETWORK_PREFIXES = {
    "MTN": ["0803","0806","0703","0706","0813","0816","0810","0814","0903","0906","0913","0916","0704"],
    "Airtel": ["0802","0808","0708","0812","0701","0902","0901","0904","0907","0912"],
    "Glo": ["0805","0807","0705","0815","0811","0905","0915"],
    "9mobile": ["0809","0817","0818","0908","0909"],
}
PREFIX_TO_NETWORK = {p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes}


# 4. Helper Functions
def clean_phone(val):
    """Standardizes Nigerian MSISDNs to 11-digit strings starting with '0'."""
    if pd.isna(val) or str(val).lower() == "nan":
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("234") and len(digits) == 13:
        digits = "0" + digits[3:]
    elif len(digits) == 10 and digits.startswith(("7", "8", "9")):
        digits = "0" + digits
    return digits


def sim_network(sim, airtel_set):
    """Categorizes SIM by cross-referencing verified Airtel list or prefix dictionary."""
    sim_clean = clean_phone(sim)
    if not sim_clean:
        return "Missing"
    if sim_clean in airtel_set:
        return "Airtel (verified)"
    prefix = sim_clean[:4]
    return PREFIX_TO_NETWORK.get(prefix, "Unknown/Other (guessed)")


def extract_customer_emails(users_str):
    """Regex extracts valid email strings and removes administrative accounts."""
    if pd.isna(users_str) or str(users_str).strip() == "":
        return []
    found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(users_str))
    return [e.strip().lower() for e in found_emails if e.strip().lower() not in ADMIN_EMAILS]


def safe_read_file(file_source):
    """Reads CSV or Excel files while handling empty files gracefully."""
    filename = getattr(file_source, "name", str(file_source))
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_source)
    try:
        return pd.read_csv(file_source, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        st.error(f"The file **{filename}** is empty. Please upload a valid report.")
        st.stop()
    except Exception:
        try:
            return pd.read_csv(file_source, sep=None, engine="python", encoding="utf-8-sig")
        except Exception:
            return pd.read_csv(file_source, encoding="latin1")


# 5. UI File Uploaders & Selection
uploaded_file = st.file_uploader("Upload new fleet report (Optional - overrides default dataset)", type=["csv", "xlsx", "xls"])
airtel_file = st.file_uploader("Upload Airtel SIM list (Optional - for verified network identification)", type=["csv", "xlsx"])

# Search for valid non-empty default datasets
DEFAULT_FILES = ["devices_report.csv.csv", "devices_report_1789914045.csv", "devices_report.csv"]
default_path = next((f for f in DEFAULT_FILES if os.path.exists(f) and os.path.getsize(f) > 0), None)

# Process Airtel Verification File
airtel_numbers = set()
if airtel_file is not None:
    airtel_df = safe_read_file(airtel_file)
    airtel_df.columns = airtel_df.columns.str.replace("\ufeff", "", regex=False).str.strip()
    if "MSISDN" in airtel_df.columns:
        airtel_numbers = set(airtel_df["MSISDN"].apply(clean_phone))
        airtel_numbers.discard("")
        st.write(f"Loaded **{len(airtel_numbers):,} Airtel numbers** for cross-reference.")
    else:
        st.error(f"Couldn't find an 'MSISDN' column in Airtel file. Found columns: {list(airtel_df.columns)}")


# 6. Fleet Dataset Loading & Execution
if uploaded_file is not None:
    df = safe_read_file(uploaded_file)
    st.info(f"Loaded uploaded file: **{uploaded_file.name}**")
elif default_path:
    df = safe_read_file(default_path)
    st.info(f"Displaying default dataset (**{default_path}**)")
else:
    st.warning("No fleet dataset found in repository. Please upload a CSV or Excel report.")
    st.stop()

df.columns = df.columns.str.replace("\ufeff", "", regex=False).str.strip()
st.write(f"Analyzing **{len(df):,} total fleet records**")

# Data Processing
df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
df["last_connect_time"] = pd.to_datetime(df["last_connect_time"], errors="coerce")
df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce")

# Extract Expiration Year and Month attributes
df["expiration_year"] = df["expiration_date"].dt.year
df["expiration_month_num"] = df["expiration_date"].dt.month
df["expiration_month_name"] = df["expiration_date"].dt.strftime("%B")

now = pd.Timestamp.now()
df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400

if "users_list" in df.columns:
    df["user_emails"] = df["users_list"].apply(extract_customer_emails)
    df["primary_email"] = df["user_emails"].apply(lambda emails: emails[0] if emails else "")
else:
    df["primary_email"] = ""

# 7. Diagnostic Analytics Computation
reporting_24h = df[df["hours_offline"] <= 24]
not_reporting = df[df["hours_offline"] > 24]

expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
expired_total = df[df["days_to_expiry"] < 0]

expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]

active_vehicles = df[df["active"] == 1] if "active" in df.columns else df.head(0)
active_but_offline = active_vehicles[active_vehicles["hours_offline"] > 24]

df["sim_network"] = df["sim_number"].apply(lambda x: sim_network(x, airtel_numbers)) if "sim_number" in df.columns else "Missing"
network_breakdown = df["sim_network"].value_counts()
offline_by_network = df[df["hours_offline"] > 24]["sim_network"].value_counts()

missing_sim = df[df["sim_number"].isna() | (df["sim_number"].astype(str).str.strip() == "")] if "sim_number" in df.columns else df
sim_counts = df["sim_number"].astype(str).value_counts() if "sim_number" in df.columns else pd.Series()
duplicate_sims = sim_counts[sim_counts > 1].index.tolist()
duplicate_sim_rows = df[
    df["sim_number"].astype(str).isin(duplicate_sims) & (df["sim_number"].astype(str) != "nan")
] if "sim_number" in df.columns else df.head(0)

def valid_imei(v):
    v = str(v).replace(".00", "").strip()
    return v.isdigit() and len(v) == 15

if "imei" in df.columns:
    df["imei_clean"] = df["imei"].astype(str).str.replace(".00", "", regex=False).str.strip()
    invalid_imei = df[~df["imei"].apply(valid_imei)]
    imei_counts = df["imei_clean"].value_counts()
    duplicate_imeis = imei_counts[imei_counts > 1].index.tolist()
    duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imeis)]
else:
    invalid_imei = df.head(0)
    duplicate_imei_rows = df.head(0)

install_trend = df.groupby(df["created_at"].dt.to_period("M").astype(str)).size()

renewal_opportunity = df[
    (df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) &
    (df["hours_offline"] <= 24)
].sort_values("days_to_expiry")

stats = {
    "total_vehicles": len(df),
    "reporting_24h": len(reporting_24h),
    "not_reporting": len(not_reporting),
    "expired_last_24h": len(expired_24h),
    "expired_last_30d": len(expired_30d),  # Corrected variable name reference
    "expired_total": len(expired_total),
    "expiring_next_24h": len(expiring_24h),
    "expiring_next_30d": len(expiring_30d),
    "active_vehicles": len(active_vehicles),
    "active_but_offline": len(active_but_offline),
    "missing_sim": len(missing_sim),
    "duplicate_sim_count": len(duplicate_sim_rows),
    "invalid_imei": len(invalid_imei),
    "duplicate_imei_count": len(duplicate_imei_rows),
    "renewal_opportunity_count": len(renewal_opportunity),
    "network_breakdown": network_breakdown.to_dict(),
}

# 8. Render Operational Dashboard UI
st.success("Analysis Complete!")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reporting (24h)", f"{stats['reporting_24h']:,}")
c2.metric("Not Reporting", f"{stats['not_reporting']:,}")
c3.metric("Expired (total)", f"{stats['expired_total']:,}")
c4.metric("Active but Offline", f"{stats['active_but_offline']:,}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Expired (last 24h)", stats["expired_last_24h"])
c6.metric("Expired (last 30d)", stats["expired_last_30d"])
c7.metric("Expiring (next 24h)", stats["expiring_next_24h"])
c8.metric("Expiring (next 30d)", stats["expiring_next_30d"])

# --- EXPIRATION BY YEAR BATCHES & MONTH FILTER ---
st.write("---")
st.subheader("📅 Expiration Batches (2023 - 2027) & Monthly Filter")

TARGET_YEARS = [2023, 2024, 2025, 2026, 2027]
MONTH_OPTIONS = [
    "All Months", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

col_years, col_month = st.columns([2, 1])

with col_years:
    selected_years = st.multiselect(
        "Select Expiration Year Batches:",
        options=TARGET_YEARS,
        default=TARGET_YEARS
    )

with col_month:
    selected_month = st.selectbox(
        "Filter by Expiration Month:",
        options=MONTH_OPTIONS
    )

filtered_batch_df = df[df["expiration_year"].isin(selected_years)].copy()
if selected_month != "All Months":
    filtered_batch_df = filtered_batch_df[filtered_batch_df["expiration_month_name"] == selected_month]

st.write(
    f"Found **{len(filtered_batch_df):,} vehicles** matching the selected year and month criteria."
)

if selected_years:
    year_tabs = st.tabs([f"📆 {yr}" for yr in sorted(selected_years)])
    for idx, yr in enumerate(sorted(selected_years)):
        with year_tabs[idx]:
            yr_df = filtered_batch_df[filtered_batch_df["expiration_year"] == yr].sort_values("expiration_date")
            st.metric(f"Vehicles Expiring/Expired in {yr}", f"{len(yr_df):,} units")
            
            if not yr_df.empty:
                display_cols = ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date", "days_to_expiry"]
                available_cols = [c for c in display_cols if c in yr_df.columns]
                st.dataframe(yr_df[available_cols], use_container_width=True)
                
                st.download_button(
                    f"⬇️ Download {yr} Expiration List (CSV)",
                    yr_df[available_cols].to_csv(index=False),
                    f"fleet_expirations_{yr}_{selected_month.lower().replace(' ', '_')}.csv",
                    "text/csv",
                    key=f"dl_btn_{yr}"
                )
            else:
                st.info(f"No vehicles found expiring in {yr} for the selected month ({selected_month}).")
st.write("---")

st.subheader("📡 Network Breakdown (SIM)")
st.bar_chart(network_breakdown)

st.subheader("📵 Offline Devices by Network")
st.bar_chart(offline_by_network)

st.subheader("📵 Airtel SIMs Offline 48+ Hours")
airtel_offline_48h = df[
    (df["sim_network"] == "Airtel (verified)") & (df["hours_offline"] >= 48)
][["id", "name", "plate_number", "sim_number", "last_connect_time", "hours_offline"]].sort_values(
    "hours_offline", ascending=False
)
st.write(f"**{len(airtel_offline_48h):,} Airtel SIMs** have not reported in 48+ hours.")
st.dataframe(airtel_offline_48h, use_container_width=True)
st.download_button(
    "⬇️ Download Airtel Offline 48h+ List (CSV)",
    airtel_offline_48h.to_csv(index=False),
    "airtel_offline_48h.csv",
    "text/csv"
)

st.subheader("🔍 SIM & IMEI Data Quality")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Missing SIM", stats["missing_sim"])
d2.metric("Duplicate SIMs", stats["duplicate_sim_count"])
d3.metric("Invalid IMEI", stats["invalid_imei"])
d4.metric("Duplicate IMEIs", stats["duplicate_imei_count"])

st.subheader("📈 Installation Trend")
st.bar_chart(install_trend)

st.subheader("💰 Renewal Opportunity (active, reporting, expiring ≤30 days)")
st.write(f"**{stats['renewal_opportunity_count']:,} vehicles** — easiest to renew since they're currently reporting.")
st.dataframe(
    renewal_opportunity[["id", "name", "plate_number", "sim_number", "expiration_date", "days_to_expiry"]],
    use_container_width=True
)
st.download_button(
    "⬇️ Download Renewal Opportunity List (CSV)",
    renewal_opportunity.to_csv(index=False),
    "renewal_opportunity.csv",
    "text/csv"
)

st.subheader("📥 Download Customer Contact List")
contact_export = df[df["primary_email"] != ""][
    ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date", "days_to_expiry"]
].copy()
st.download_button(
    "⬇️ Download Full Customer Email List (CSV)",
    contact_export.to_csv(index=False),
    "customer_email_list.csv",
    "text/csv"
)

st.subheader("⚠️ Expired Vehicles List (All Units)")
expired_df = df[df["days_to_expiry"] < 0][
    [
        "id",
        "name",
        "plate_number",
        "sim_number",
        "users_list",
        "primary_email",
        "expiration_date",
        "days_to_expiry",
    ]
].sort_values("days_to_expiry")

with_email_count = len(expired_df[expired_df["primary_email"] != ""])
st.write(
    f"Found **{len(expired_df):,} total expired vehicles** "
    f"({with_email_count:,} have verified customer emails attached)."
)
st.dataframe(expired_df, use_container_width=True)
st.download_button(
    "⬇️ Download Expired Vehicles List (CSV)",
    expired_df.to_csv(index=False),
    "expired_vehicles_list.csv",
    "text/csv"
)

# 9. AI Executive Assessment via Gemini API
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""You are analyzing a fleet tracking dataset. Use ONLY these verified numbers, do not recalculate:
{json.dumps(stats, indent=2, default=str)}

Return ONLY valid JSON with keys: summary (one paragraph), insights (4-6 bullet strings), actions (list of {{"task":..., "detail":...}}).
"""
    try:
        response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        raw = response.text.strip().strip("`").replace("json", "", 1).strip()
        result = json.loads(raw)
        st.subheader("📋 AI Summary")
        st.write(result.get("summary", ""))
        st.subheader("💡 Insights")
        for i in result.get("insights", []):
            st.markdown(f"- {i}")
        st.subheader("🛠️ Recommended Actions")
        for a in result.get("actions", []):
            st.markdown(f"- **{a.get('task','')}**: {a.get('detail','')}")
    except Exception as e:
        st.info("AI summary engine standby or API rate limit reached.")
