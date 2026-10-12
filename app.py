import os
import re
import glob
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None

# ============================================================
# 1. App setup
# ============================================================
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

st.set_page_config(
    page_title="AI Fleet Diagnostics Dashboard",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
    @keyframes gradientText {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .modern-title {
        font-size: 2.3rem; font-weight: 800;
        background: linear-gradient(-45deg, #2563eb, #3b82f6, #06b6d4, #10b981);
        background-size: 300% 300%; -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradientText 6s ease infinite; margin-bottom: 0;
    }
    .modern-subtitle { font-size: 1rem; color: #64748b; margin-bottom: 25px; }
    .icon-header { font-size: 1.2rem; font-weight: 700; margin-top: 20px; margin-bottom: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown('<p class="modern-title">⚡ AI Fleet Diagnostics Dashboard</p>', unsafe_allow_html=True)
st.markdown('<p class="modern-subtitle">Fleet diagnostics, subscription renewal opportunities, and network analytics.</p>', unsafe_allow_html=True)

# ============================================================
# 2. Email exclusions and Nigerian network prefixes
# ============================================================
EXCLUDED_EMAILS = {
    "hello@cartracker.com.ng", "oluwafemi.a@cartracker.com", "ayo.a@cartracker.com",
    "inyang@cartracker.com", "rukayat@cartracker.com.ng", "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com", "oyindaabegunde@yahoo.com", "abasifrekeekanem1@cartracker.com",
    "andrew@cartracker.com.ng", "ifeoluwa@cartracker.ng", "james@cartracker.com.org",
    "blessing@catracker.com.ng", "damilola@catracker.com.ng", "dammylola@catracker.com.ng",
    "blessing@catracker.ng", "dammylola@catracker.ng", "10device@cartracker.com.ng",
    "ag@cartracker.com.ng", "joyvivian111@gmail.com", "ehonreoluwaseun@icloud.com",
    "obinnaezenwa@gmail.com", "frankcay12345@yahoo.com", "access@hopmobiletransport.com",
    "adadioma@gmail.com", "balogunisiaka38@gmail.com", "gbaguje@yahoo.com",
    "akeemakinwale26@gmail.com", "rhemzy82@gmail.com", "muibihammedaliu@gmail.com",
    "faruqafolabi05@gmail.com", "chuklexy@gmail.com", "uokigbo@gmail.com",
    "ballingtonlogistics@gmail.com",
}
EXCLUDED_KEYWORDS = ["cartracker", "catracker", "clicktgi", "gbovo", "hopmobiletransport.com"]
NETWORK_PREFIXES = {
    "MTN": ["0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814", "0903", "0906", "0913", "0916", "0704"],
    "Airtel": ["0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904", "0907", "0912", "0911", "0702"],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {prefix: network for network, prefixes in NETWORK_PREFIXES.items() for prefix in prefixes}

# ============================================================
# 3. Helpers
# ============================================================
def normalize_number(value):
    if pd.isna(value):
        return ""
    raw = str(value).strip()
    if raw.lower() in {"", "nan", "none", "null", "nat"}:
        return ""
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("234"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits[-10:] if len(digits) > 10 else digits


def sim_network(value, verified_airtel_numbers):
    number = normalize_number(value)
    if not number:
        return "Missing"
    if number in verified_airtel_numbers:
        return "Airtel (verified)"
    if len(number) >= 10:
        prefix = "0" + number[:3]
        if prefix in PREFIX_TO_NETWORK:
            return PREFIX_TO_NETWORK[prefix] + " (prefix estimate)"
    return "Unknown/Other"


def is_excluded_email(email):
    email = str(email).strip().lower()
    return email in EXCLUDED_EMAILS or any(keyword in email for keyword in EXCLUDED_KEYWORDS)


def extract_emails(value):
    """Extract emails safely from strings, lists, and missing values."""
    if value is None:
        return []

    # Some columns (especially user_emails) may contain lists rather than strings.
    if isinstance(value, (list, tuple, set)):
        found = []
        for item in value:
            found.extend(extract_emails(item))
        return list(dict.fromkeys(found))

    # pd.isna() can return an array for list-like values, so only call it
    # after handling those values above.
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass

    text_value = str(value).strip()
    if text_value.lower() in ("", "nan", "none", "null"):
        return []

    found = re.findall(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        text_value,
    )
    return list(dict.fromkeys(
        email.lower() for email in found if not is_excluded_email(email)
    ))


def valid_imei(value):
    if pd.isna(value):
        return False
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    return len(digits) == 15


def read_file(file_source):
    name = str(getattr(file_source, "name", file_source)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_source, dtype=str)
    try:
        return pd.read_csv(file_source, encoding="utf-8-sig", dtype=str, low_memory=False)
    except pd.errors.EmptyDataError:
        raise ValueError(f"The file {name} is empty.")
    except Exception:
        try:
            file_source.seek(0)
        except Exception:
            pass
        try:
            return pd.read_csv(file_source, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
        except Exception:
            try:
                file_source.seek(0)
            except Exception:
                pass
            return pd.read_csv(file_source, encoding="latin1", dtype=str, low_memory=False)


def clean_columns(dataframe):
    dataframe = dataframe.copy()
    dataframe.columns = [str(col).replace("\ufeff", "").strip() for col in dataframe.columns]
    # Map common export variations to one consistent column name.
    aliases = {
        "sim_num": "sim_number", "sim_numbe": "sim_number", "sim": "sim_number",
        "phone": "sim_number", "msisdn": "sim_number",
        "plate": "plate_number", "registration_number": "plate_number",
        "imei_number": "imei", "last_report_time": "last_connect_time",
        "last_connection": "last_connect_time", "expiry_date": "expiration_date",
        "expires_at": "expiration_date", "created date": "created_at",
        "user list": "users_list", "user_emails": "users_list",
    }
    lower_lookup = {str(col).strip().lower(): col for col in dataframe.columns}
    rename = {}
    for alias, standard in aliases.items():
        if standard not in dataframe.columns and alias in lower_lookup:
            rename[lower_lookup[alias]] = standard
    if rename:
        dataframe = dataframe.rename(columns=rename)
    return dataframe


def first_existing_column(dataframe, candidates):
    for candidate in candidates:
        if candidate in dataframe.columns:
            return dataframe[candidate]
    return pd.Series([""] * len(dataframe), index=dataframe.index, dtype="object")


def parse_date_column(dataframe, column):
    if column not in dataframe.columns:
        dataframe[column] = pd.NaT
    dataframe[column] = pd.to_datetime(dataframe[column], errors="coerce", utc=True).dt.tz_localize(None)


def ensure_columns(dataframe, columns):
    for column in columns:
        if column not in dataframe.columns:
            dataframe[column] = ""
    return dataframe

# ============================================================
# 4. Load files already committed to the GitHub repository
# ============================================================
# No upload widgets: the app reads the committed report files automatically.
FLEET_REPORT_CANDIDATES = [
    "devices_report.csv",
    "devices_report.csv.csv",
    "devices_report_1789914045.csv",
]

fleet_path = next(
    (path for path in FLEET_REPORT_CANDIDATES
     if os.path.isfile(path) and os.path.getsize(path) > 0),
    None,
)

if fleet_path is None:
    # Fall back to the most recently modified device-report CSV in the repo.
    other_reports = sorted(
        [path for path in glob.glob("*.csv")
         if "device" in Path(path).name.lower() and os.path.getsize(path) > 0],
        key=os.path.getmtime,
        reverse=True,
    )
    fleet_path = other_reports[0] if other_reports else None

if fleet_path is None:
    st.error(
        "Fleet report not found. Commit `devices_report.csv` (or one of the supported "
        "device-report filenames) to the same GitHub repository folder as `app.py`."
    )
    st.stop()

try:
    df = clean_columns(read_file(fleet_path))
    st.caption(f"Fleet data source: `{fleet_path}` (loaded from the GitHub repository)")
except Exception as exc:
    st.error(f"Could not read fleet report `{fleet_path}`: {exc}")
    st.stop()

# Automatically locate the verified Airtel SIM inventory committed to the repo.
AIRTEL_FILE_PATTERNS = [
    "*airtel*.csv", "*airtel*.xlsx", "*airtel*.xls",
    "*sim*list*.csv", "*sim*list*.xlsx", "*sim*list*.xls",
]
airtel_candidates = []
for pattern in AIRTEL_FILE_PATTERNS:
    airtel_candidates.extend(glob.glob(pattern))
airtel_candidates = sorted(
    {path for path in airtel_candidates
     if os.path.isfile(path) and os.path.getsize(path) > 0
     and Path(path).name != Path(fleet_path).name},
    key=os.path.getmtime,
    reverse=True,
)
verified_airtel_numbers = set()
airtel_source_path = None
if airtel_candidates:
    airtel_source_path = airtel_candidates[0]
    try:
        airtel_df = clean_columns(read_file(airtel_source_path))
        airtel_col = next((col for col in airtel_df.columns if str(col).strip().lower() in {
            "msisdn", "phone", "sim", "sim_number", "mobile", "line", "number", "mobile number"
        }), None)
        if airtel_col is None and len(airtel_df.columns):
            airtel_col = airtel_df.columns[0]
        if airtel_col is not None:
            verified_airtel_numbers = {
                normalize_number(value) for value in airtel_df[airtel_col].dropna()
            }
            verified_airtel_numbers.discard("")
            st.caption(
                f"Verified Airtel SIM source: `{airtel_source_path}` — "
                f"{len(verified_airtel_numbers):,} unique numbers loaded."
            )
        else:
            st.warning(f"Airtel file `{airtel_source_path}` has no usable columns.")
    except Exception as exc:
        st.warning(f"Could not read Airtel SIM file `{airtel_source_path}`: {exc}")
else:
    st.warning(
        "No Airtel SIM inventory was found automatically. Commit a file whose name includes "
        "`airtel` (for example `airtel_sim_list.csv`) beside `app.py` to enable verified Airtel matching. "
        "Network prefixes will still be shown as estimates, not verified lines."
    )

if df.empty:
    st.error("The fleet report contains no rows.")
    st.stop()

# Keep the app alive even when a report has slightly different column names.
df = ensure_columns(df, [
    "id", "name", "imei", "sim_number", "plate_number", "active", "users_list",
    "created_at", "last_connect_time", "expiration_date", "latitude", "longitude",
])
for date_column in ["created_at", "last_connect_time", "expiration_date"]:
    parse_date_column(df, date_column)

now = pd.Timestamp.now()
df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400

df["user_emails"] = df["users_list"].apply(extract_emails)
df["primary_email"] = df["user_emails"].apply(lambda values: values[0] if values else "")
df["sim_number_norm"] = df["sim_number"].apply(normalize_number)
df["sim_network"] = df["sim_number"].apply(lambda value: sim_network(value, verified_airtel_numbers))
df["imei_clean"] = df["imei"].fillna("").astype(str).str.replace(r"\.0+$", "", regex=True).str.strip()

# ============================================================
# 5. Fleet metrics
# ============================================================
reporting_30h = df[df["hours_offline"].notna() & (df["hours_offline"] >= 0) & (df["hours_offline"] <= 30)]
not_reporting = df[df["hours_offline"].isna() | (df["hours_offline"] < 0) | (df["hours_offline"] > 30)]
expired_total = df[df["days_to_expiry"] < 0]
expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]
active_mask = df["active"].astype(str).str.strip().str.lower().isin(["1", "true", "yes", "active"])
active_vehicles = df[active_mask]
active_but_offline = active_vehicles[active_vehicles["hours_offline"].isna() | (active_vehicles["hours_offline"] < 0) | (active_vehicles["hours_offline"] > 30)]
missing_sim = df[df["sim_number_norm"] == ""]
valid_sim = df[df["sim_number_norm"] != ""]
sim_counts = valid_sim["sim_number_norm"].value_counts()
duplicate_sim_numbers = set(sim_counts[sim_counts > 1].index)
duplicate_sim_rows = valid_sim[valid_sim["sim_number_norm"].isin(duplicate_sim_numbers)]
invalid_imei = df[~df["imei"].apply(valid_imei)]
valid_imei_values = df.loc[df["imei"].apply(valid_imei), "imei_clean"]
duplicate_imei_values = set(valid_imei_values[valid_imei_values.duplicated(keep=False)])
duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imei_values)]
renewal_opportunity = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) & (df["hours_offline"].notna()) & (df["hours_offline"] <= 30)].sort_values("days_to_expiry")
network_breakdown = df["sim_network"].value_counts()

# ============================================================
# 6. Dashboard metrics
# ============================================================
st.success("Analysis complete")
st.caption(f"Report contains {len(df):,} records. Dates are interpreted using the app server's current time.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reporting (last 30h)", f"{len(reporting_30h):,}")
c2.metric("Not Reporting / Unknown", f"{len(not_reporting):,}")
c3.metric("Expired (total)", f"{len(expired_total):,}")
c4.metric("Active but Offline", f"{len(active_but_offline):,}")
c5, c6, c7, c8 = st.columns(4)
c5.metric("Expired (last 24h)", f"{len(expired_24h):,}")
c6.metric("Expired (last 30d)", f"{len(expired_30d):,}")
c7.metric("Expiring (next 24h)", f"{len(expiring_24h):,}")
c8.metric("Expiring (next 30d)", f"{len(expiring_30d):,}")

# ============================================================
# 7. Zoho CRM expired-fleet linker (optional files)
# ============================================================
st.subheader("📞 Zoho CRM & Expired Fleet Recovery Linker")
deals_candidates = sorted(glob.glob("Deals_*.csv"), reverse=True)
customer_candidates = sorted(glob.glob("Customer_*.csv"), reverse=True)

if deals_candidates and customer_candidates:
    deals_path, customer_path = deals_candidates[0], customer_candidates[0]
    st.caption(f"Using repository files: `{deals_path}` and `{customer_path}`")
    try:
        deals_df = clean_columns(read_file(deals_path))
        customer_df = clean_columns(read_file(customer_path))
        deal_link_col = next((c for c in ["Customer Name.id", "Accounts Name.id", "Account Name.id"] if c in deals_df.columns), None)
        customer_link_col = next((c for c in ["Record Id", "Record ID", "id"] if c in customer_df.columns), customer_df.columns[0] if len(customer_df.columns) else None)
        deal_plate_col = next((c for c in ["Plate Number", "Deal Name", "Vehicle Name", "plate_number"] if c in deals_df.columns), None)
        if not deal_link_col or not customer_link_col:
            st.warning("Could not find the expected Zoho customer-link columns. Check the Deals and Customer export headers.")
        elif not deal_plate_col:
            st.warning("Could not find a vehicle plate column in the Deals export. Looked for Plate Number, Deal Name, and Vehicle Name.")
        else:
            deals_df["link_id_clean"] = deals_df[deal_link_col].fillna("").astype(str).str.strip()
            customer_df["link_id_clean"] = customer_df[customer_link_col].fillna("").astype(str).str.strip()
            zoho_merged = pd.merge(deals_df, customer_df, on="link_id_clean", how="left", suffixes=("_deal", "_cust"))
            expired_units = expired_total.copy()
            expired_units["match_plate"] = expired_units["plate_number"].fillna("").astype(str).str.replace(r"[-\s]", "", regex=True).str.upper()
            zoho_merged["match_plate"] = zoho_merged[deal_plate_col].fillna("").astype(str).str.replace(r"[-\s]", "", regex=True).str.upper()
            expired_units = expired_units[expired_units["match_plate"] != ""]
            zoho_merged = zoho_merged[zoho_merged["match_plate"] != ""]
            final_recovery = pd.merge(expired_units, zoho_merged, on="match_plate", how="inner", suffixes=("_fleet", "_zoho"))
            phone_raw = first_existing_column(final_recovery, ["Phone_cust", "Phone", "Phone_deal", "Phone Number_cust", "Phone Number", "Phone Number_deal"])
            email_raw = first_existing_column(final_recovery, ["Email_cust", "Email", "Email_deal", "Customer Email_cust", "Customer Email", "Customer Email_deal"])
            final_recovery["phone_clean"] = phone_raw.apply(normalize_number)
            final_recovery["email_clean"] = email_raw.fillna("").astype(str).str.strip().str.lower()
            final_recovery = final_recovery.drop_duplicates(subset=["match_plate"])
            valid_calls = final_recovery[final_recovery["phone_clean"] != ""]
            valid_emails = final_recovery[
                (final_recovery["email_clean"] != "") &
                (final_recovery["email_clean"] != "nan") &
                (~final_recovery["email_clean"].apply(is_excluded_email))
            ]
            st.success(f"Matched {len(final_recovery):,} expired vehicles to Zoho CRM records by plate number.")
            m1, m2, m3 = st.columns(3)
            m1.metric("Matched Expired Vehicles", f"{len(final_recovery):,}")
            m2.metric("With Phone Numbers", f"{len(valid_calls):,}")
            m3.metric("With Customer Emails", f"{len(valid_emails):,}")
            customer_name_col = next((c for c in ["Customer Name_cust", "Account Name_cust", "Customer Name", "Account Name"] if c in final_recovery.columns), None)
            preview_cols = [c for c in ["plate_number", "name", "expiration_date", customer_name_col, "phone_clean", "email_clean"] if c and c in final_recovery.columns]
            st.dataframe(final_recovery[preview_cols], use_container_width=True)
            download_cols = preview_cols or ["match_plate", "phone_clean", "email_clean"]
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Download expired-fleet calling list", valid_calls[download_cols].to_csv(index=False).encode("utf-8"), "zoho_expired_fleet_calling_list.csv", "text/csv", key="dl_calling")
            d2.download_button("⬇️ Download expired-fleet email list", valid_emails[download_cols].to_csv(index=False).encode("utf-8"), "zoho_expired_fleet_email_list.csv", "text/csv", key="dl_emails")
    except Exception as exc:
        st.warning(f"Zoho matching could not run, but the main fleet dashboard is still available. Details: {exc}")
else:
    st.info("Optional Zoho exports not found. Add files named like `Deals_YYYY_MM_DD.csv` and `Customer_YYYY_MM_DD.csv` to enable CRM matching.")

# ============================================================
# 8. Clean customer email export
# ============================================================
st.markdown("---")
st.markdown('<div class="icon-header">✉️ Deduplicated Clean Customer Emails</div>', unsafe_allow_html=True)
all_customer_emails = set()
for column in ["users_list", "primary_email", "user_emails"]:
    if column in df.columns:
        for value in df[column].dropna():
            all_customer_emails.update(extract_emails(value))
clean_emails_df = pd.DataFrame(sorted(all_customer_emails), columns=["Customer Email"])
st.write(f"Total clean unique customer emails: **{len(clean_emails_df):,}**")
st.dataframe(clean_emails_df, use_container_width=True, hide_index=True)
st.download_button("⬇️ Download clean unique emails (CSV)", clean_emails_df.to_csv(index=False).encode("utf-8"), "deduplicated_customer_emails.csv", "text/csv")

# ============================================================
# 9. Network analytics, Airtel offline and data quality
# ============================================================
st.markdown("---")
st.markdown('<div class="icon-header">📡 Network Breakdown</div>', unsafe_allow_html=True)
st.bar_chart(network_breakdown)
network_df = pd.DataFrame({
    "Network Operator": network_breakdown.index,
    "Device Count": network_breakdown.values,
    "Percentage (%)": (network_breakdown.values / max(len(df), 1) * 100).round(2),
})
st.dataframe(network_df, use_container_width=True, hide_index=True)

st.markdown('<div class="icon-header">📡 Verified Airtel SIMs Offline for 30+ Hours</div>', unsafe_allow_html=True)
airtel_30h_offline = df[(df["sim_network"] == "Airtel (verified)") & (df["hours_offline"] >= 30)].sort_values("hours_offline", ascending=False)
st.write(f"Found **{len(airtel_30h_offline):,} verified Airtel units** offline for 30 hours or more.")
if not airtel_30h_offline.empty:
    airtel_cols = [c for c in ["id", "name", "plate_number", "sim_number", "hours_offline", "expiration_date"] if c in airtel_30h_offline.columns]
    st.dataframe(airtel_30h_offline[airtel_cols], use_container_width=True)
    st.download_button("⬇️ Download Airtel 30h+ offline list", airtel_30h_offline[airtel_cols].to_csv(index=False).encode("utf-8"), "airtel_30h_offline_fleet.csv", "text/csv")

st.markdown('<div class="icon-header">🔍 SIM & IMEI Data Quality</div>', unsafe_allow_html=True)
d1, d2, d3, d4 = st.columns(4)
d1.metric("Missing SIM", f"{len(missing_sim):,}")
d2.metric("Rows with Duplicate SIMs", f"{len(duplicate_sim_rows):,}")
d3.metric("Invalid IMEI", f"{len(invalid_imei):,}")
d4.metric("Rows with Duplicate IMEIs", f"{len(duplicate_imei_rows):,}")


# ============================================================
# 10. SIM & Device Troubleshooting Workbench
# ============================================================
st.markdown("---")
st.subheader("🛠️ SIM & Device Troubleshooting Workbench")
st.caption(
    "This section flags likely troubleshooting priorities from the uploaded report. "
    "It cannot remotely test a SIM, confirm network coverage, or prove a device is faulty."
)

trouble = df.copy()

def troubleshooting_reason(row):
    reasons = []
    sim = str(row.get("sim_number_norm", "")).strip()
    imei = str(row.get("imei_clean", "")).strip()
    hours = row.get("hours_offline")
    network = str(row.get("sim_network", "Unknown/Other"))
    active = str(row.get("active", "")).strip().lower() in {"1", "true", "yes", "active"}

    if not sim:
        reasons.append("SIM number missing — verify SIM is installed and recorded")
    if not imei or not valid_imei(imei):
        reasons.append("IMEI missing/invalid — verify device label and platform record")
    if pd.isna(hours):
        reasons.append("No valid last-report time — check device record and server reporting")
    elif hours >= 30:
        if network == "Airtel (verified)":
            reasons.append("Verified Airtel SIM offline 30h+ — check SIM status/data, signal, power and server settings")
        else:
            reasons.append("Offline 30h+ — check vehicle power, SIM/data, signal, wiring and server settings")
    elif hours > 30:
        reasons.append("Offline 30h+ — check ignition/power, signal and recent tracker reports")
    if not active:
        reasons.append("Device marked inactive — confirm subscription/account status")
    if row.get("days_to_expiry") is not None and not pd.isna(row.get("days_to_expiry")) and row.get("days_to_expiry") < 0:
        reasons.append("Subscription expired — verify renewal status")
    return reasons

trouble["troubleshooting_flags"] = trouble.apply(troubleshooting_reason, axis=1)
trouble["troubleshooting_priority"] = trouble.apply(
    lambda row: "High" if (
        (pd.isna(row.get("hours_offline")) or row.get("hours_offline", 0) >= 30)
        and (not str(row.get("sim_number_norm", "")).strip() or not valid_imei(row.get("imei_clean", "")))
    ) or row.get("sim_network") == "Airtel (verified)" and (
        pd.isna(row.get("hours_offline")) or row.get("hours_offline", 0) >= 30
    ) else (
        "Medium" if pd.isna(row.get("hours_offline")) or row.get("hours_offline", 0) > 30 else "Low"
    ),
    axis=1,
)
trouble["troubleshooting_flags"] = trouble["troubleshooting_flags"].apply(
    lambda flags: "; ".join(flags) if flags else "No immediate issue detected from available report fields"
)

priority_filter = st.multiselect(
    "Filter troubleshooting priority",
    options=["High", "Medium", "Low"],
    default=["High", "Medium"],
    key="trouble_priority_filter",
)
issue_filter = st.selectbox(
    "Show devices with",
    options=[
        "Any flagged issue",
        "Any flagged issue",
        "Offline 30h+",
        "Missing SIM",
        "Invalid IMEI",
        "Verified Airtel offline 30h+",
        "Expired subscription",
    ],
    key="trouble_issue_filter",
)
trouble_view = trouble[trouble["troubleshooting_priority"].isin(priority_filter)].copy()
if issue_filter == "Offline 30h+":
    trouble_view = trouble_view[trouble_view["hours_offline"] >= 30]
elif issue_filter == "Missing SIM":
    trouble_view = trouble_view[trouble_view["sim_number_norm"] == ""]
elif issue_filter == "Invalid IMEI":
    trouble_view = trouble_view[~trouble_view["imei"].apply(valid_imei)]
elif issue_filter == "Verified Airtel offline 30h+":
    trouble_view = trouble_view[
        (trouble_view["sim_network"] == "Airtel (verified)") &
        (trouble_view["hours_offline"] >= 30)
    ]
elif issue_filter == "Expired subscription":
    trouble_view = trouble_view[trouble_view["days_to_expiry"] < 0]
elif issue_filter == "Any flagged issue":
    trouble_view = trouble_view[
        trouble_view["troubleshooting_flags"] !=
        "No immediate issue detected from available report fields"
    ]

t1, t2, t3 = st.columns(3)
t1.metric("Devices in troubleshooting view", f"{len(trouble_view):,}")
t2.metric("High priority", f"{(trouble_view['troubleshooting_priority'] == 'High').sum():,}")
t3.metric("Offline 30h+", f"{(trouble_view['hours_offline'] >= 30).sum():,}")

trouble_cols = [
    col for col in [
        "id", "name", "plate_number", "imei", "sim_number", "sim_network",
        "active", "last_connect_time", "hours_offline", "expiration_date",
        "troubleshooting_priority", "troubleshooting_flags",
    ] if col in trouble_view.columns
]
if trouble_view.empty:
    st.info("No devices match the selected troubleshooting filters.")
else:
    st.dataframe(trouble_view[trouble_cols], use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download troubleshooting list (CSV)",
        trouble_view[trouble_cols].to_csv(index=False).encode("utf-8"),
        "sim_device_troubleshooting.csv",
        "text/csv",
        key="download_sim_troubleshooting",
    )

with st.expander("Suggested field troubleshooting checklist"):
    st.markdown(
        """
        1. **Confirm the record:** compare vehicle plate, IMEI and SIM/MSISDN with the physical device and SIM inventory.
        2. **Check SIM status:** confirm the line is active, has the correct data plan/bundle, and is not barred or suspended with the telecom provider.
        3. **Check coverage:** verify signal/network availability at the vehicle's current location.
        4. **Check power:** inspect tracker power, ground, fuse and wiring; check whether the unit restarts when vehicle power changes.
        5. **Check server settings:** verify the device's correct protocol, server domain/IP and port against the approved device configuration.
        6. **Check reporting:** compare the last report time with the platform/server logs and confirm the device is assigned to the correct account.
        7. **Retest before closing:** record the test time, person handling it, outcome and next action.

        **Safety:** do not send configuration SMS commands or change server settings unless the exact device model and its command manual are confirmed.
        """
    )

# ============================================================
# 11. Renewals and expired fleet
# ============================================================
st.markdown("---")
st.markdown('<div class="icon-header">💰 Renewal Opportunities</div>', unsafe_allow_html=True)
st.write(f"Found **{len(renewal_opportunity):,} vehicles** that reported within the last 30 hours and expire within 30 days.")
renewal_cols = [c for c in ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date"] if c in renewal_opportunity.columns]
st.dataframe(renewal_opportunity[renewal_cols], use_container_width=True)
st.download_button("⬇️ Download renewal opportunities (CSV)", renewal_opportunity.to_csv(index=False).encode("utf-8"), "renewal_opportunities.csv", "text/csv")

st.markdown('<div class="icon-header">⚠️ Expired Vehicles List</div>', unsafe_allow_html=True)
st.write(f"Found **{len(expired_total):,} expired vehicles**.")
st.download_button("⬇️ Download expired vehicles (CSV)", expired_total.to_csv(index=False).encode("utf-8"), "expired_vehicles_list.csv", "text/csv")

# ============================================================
# 12. Data sources, definitions and technical references
# ============================================================
st.markdown("---")
with st.expander("📚 Data sources, definitions & references"):
    st.markdown(
        f"""
        **Data files used**
        - Fleet report: `{fleet_path}` from this GitHub repository.
        - Verified Airtel SIM inventory: `{airtel_source_path}` if found; otherwise Airtel matches are not verified.
        - Zoho CRM exports: the newest `Deals_*.csv` and `Customer_*.csv` files found beside `app.py`.

        **How the dashboard interprets the data**
        - **Reporting (last 30h):** `last_connect_time` is between now and 30 hours ago.
        - **Not reporting / unknown:** no valid last-report timestamp, a future timestamp, or a report older than 30 hours.
        - **Network labels:** Airtel is marked verified only when its normalized number matches the repository SIM inventory. Other Nigerian network labels are prefix estimates and can be wrong after mobile-number portability.
        - **Offline does not prove SIM failure:** the cause can also be power, wiring, coverage, device configuration, server settings or stale platform data.
        - **Renewal and expiry counts:** calculated from `expiration_date` using the app server's current time.

        **Technical references**
        - Streamlit documentation: https://docs.streamlit.io/
        - pandas documentation (data cleaning and timestamps): https://pandas.pydata.org/docs/
        - Google Gen AI Python SDK (optional AI summary): https://googleapis.github.io/python-genai/
        - Nigerian Communications Commission (telecom regulation and numbering information): https://www.ncc.gov.ng/

        These references describe the libraries and telecom context; the vehicle counts and account matches come from the repository exports, not from these websites.
        """
    )

# ============================================================
# 13. Optional Gemini AI summary
# ============================================================
st.markdown("---")
st.markdown('<div class="icon-header">🤖 AI Fleet Intelligence</div>', unsafe_allow_html=True)
if not GEMINI_API_KEY:
    st.info("AI summary is disabled because GEMINI_API_KEY is not configured in Streamlit Secrets. The rest of the dashboard works without it.")
elif genai is None:
    st.info("The Google GenAI package is not installed. Add `google-genai` to requirements.txt to enable AI summaries.")
else:
    if st.button("Generate AI fleet summary"):
        stats = {
            "total_vehicles": int(len(df)),
            "reporting_30h": int(len(reporting_30h)),
            "not_reporting_or_unknown": int(len(not_reporting)),
            "expired_total": int(len(expired_total)),
            "expiring_next_30d": int(len(expiring_30d)),
            "active_vehicles": int(len(active_vehicles)),
            "active_but_offline": int(len(active_but_offline)),
            "missing_sim": int(len(missing_sim)),
            "duplicate_sim_rows": int(len(duplicate_sim_rows)),
            "invalid_imei": int(len(invalid_imei)),
            "duplicate_imei_rows": int(len(duplicate_imei_rows)),
            "renewal_opportunities": int(len(renewal_opportunity)),
            "network_breakdown": {str(k): int(v) for k, v in network_breakdown.items()},
        }
        prompt = (
            "You are an operations analyst for a vehicle tracking company. Analyze only the verified figures below. "
            "Give a concise executive summary, 3-5 insights, and prioritized actions. Do not invent causes or figures.\n\n"
            + json.dumps(stats, indent=2)
        )
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            st.subheader("📋 AI Executive Summary")
            st.write(response.text or "The AI service returned an empty response.")
        except Exception as exc:
            st.warning(f"The AI summary could not be generated. The rest of the dashboard is still working. Details: {exc}")
