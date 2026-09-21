import json
import os
import re
import pandas as pd
from dotenv import load_dotenv
from google import genai
import streamlit as st

# 1. Page Configuration & Environment Setup
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(
    page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide"
)
st.title("⚡ AI Fleet Diagnostics Dashboard")
st.write(
    "Live fleet diagnostics, subscription renewal opportunities, and network"
    " analytics."
)

# 2. Administrative Email Exclusion List
ADMIN_EMAILS = {
    "hello@cartracker.com.ng",
    "oluwafemi.a@cartracker.com",
    "ayo.a@cartracker.com",
    "inyang@cartracker.com",
    "rukayat@cartracker.com.ng",
    "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com",
    "oyindaabegunde@yahoo.com",
    "abasifrekeekanem1@cartracker.com",
    "andrew@cartracker.com.ng",
    "ifeoluwa@cartracker.ng",
    "james@cartracker.com.org",
    "blessing@catracker.com.ng",
    "damilola@catracker.com.ng",
    "dammylola@catracker.com.ng",
    "blessing@catracker.ng",
    "dammylola@catracker.ng",
}

# 3. Telecom Network Prefixes (Nigeria)
NETWORK_PREFIXES = {
    "MTN": [
        "0803",
        "0806",
        "0703",
        "0706",
        "0813",
        "0816",
        "0810",
        "0814",
        "0903",
        "0906",
        "0913",
        "0916",
        "0704",
    ],
    "Airtel": [
        "0802",
        "0808",
        "0708",
        "0812",
        "0701",
        "0902",
        "0901",
        "0904",
        "0907",
        "0912",
    ],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {
    p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes
}


# 4. Helper Functions
# 1. Improved Normalize Function (Handles floats, scientific notation, and trailing .0)
def normalize_number(n):
    if pd.isna(n) or str(n).strip().lower() in ("", "nan", "null", "none"):
        return ""
    
    # Convert to string and strip floating point suffixes from Pandas
    s = str(n).strip()
    if s.endswith(".0"):
        s = s[:-2]
    elif s.endswith(".00"):
        s = s[:-3]
        
    # Extract only digit characters
    digits = "".join(ch for ch in s if ch.isdigit())
    
    # Trim Nigerian country codes & leading zeros
    if digits.startswith("234"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
        
    # Ensure standard 10-digit bare number format (e.g., 8021234567)
    if len(digits) > 10:
        digits = digits[-10:]
        
    return digits


# 2. Expanded Airtel Prefixes
NETWORK_PREFIXES = {
    "MTN": [
        "0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814",
        "0903", "0906", "0913", "0916", "0704"
    ],
    "Airtel": [
        "0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904",
        "0907", "0912", "0911", "0702"
    ],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {
    p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes
}


def sim_network(sim, airtel_set):
    sim_norm = normalize_number(sim)
    if not sim_norm:
        return "Missing"
    
    # Priority 1: Match against verified uploaded Airtel list
    if sim_norm in airtel_set:
        return "Airtel (verified)"
    
    # Priority 2: Fallback to prefix guessing
    prefix = None
    if len(sim_norm) >= 9:
        prefix = "0" + sim_norm[:3]
        
    if prefix and prefix in PREFIX_TO_NETWORK:
        net = PREFIX_TO_NETWORK[prefix]
        return f"{net} (guessed)" if net != "Airtel" else "Airtel (guessed)"
        
    return "Unknown/Other (guessed)"


# 3. Robust Airtel File Processor (Detects MSISDN, Phone, SIM, or Mobile columns)
airtel_numbers = set()
if airtel_file is not None:
    airtel_df = safe_read_file(airtel_file)
    airtel_df.columns = (
        airtel_df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )
    
    # Flexible column search for MSISDN variants
    msisdn_col = next(
        (col for col in airtel_df.columns if col.lower() in [
            "msisdn", "phone", "phone number", "phonenumber", "sim", "sim number", "sim_number", "mobile"
        ]),
        None
    )
    
    if not msisdn_col:
        st.error(f"Couldn't find an 'MSISDN' or phone column. Found these instead: {list(airtel_df.columns)}")
    else:
        # Convert all entries to normalized strings
        airtel_numbers = set(airtel_df[msisdn_col].apply(normalize_number))
        airtel_numbers.discard("")
        st.success(f"Loaded **{len(airtel_numbers):,} verified Airtel numbers** from column '{msisdn_col}'.")


def valid_imei(v):
  v = str(v).replace(".00", "").strip()
  return v.isdigit() and len(v) == 15


def extract_customer_emails(users_list_value):
  """Regex extracts valid email strings and removes administrative accounts."""
  if pd.isna(users_list_value) or str(users_list_value).strip() == "":
    return []
  found_emails = re.findall(
      r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", str(users_list_value)
  )
  return [
      e.strip().lower()
      for e in found_emails
      if e.strip().lower() not in ADMIN_EMAILS
  ]


def safe_read_file(file_source):
  """Reads CSV or Excel files while handling encoding and empty file edge cases."""
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
      return pd.read_csv(
          file_source, sep=None, engine="python", encoding="utf-8-sig"
      )
    except Exception:
      return pd.read_csv(file_source, encoding="latin1")


# 5. UI File Uploaders & Selection
uploaded_file = st.file_uploader(
    "Choose your fleet CSV file", type=["csv", "xlsx", "xls"]
)
airtel_file = st.file_uploader(
    "Upload Airtel SIM list (optional, for accurate network ID)",
    type=["csv", "xlsx"],
)

# Default dataset fallback search
DEFAULT_FILES = [
    "devices_report.csv.csv",
    "devices_report_1789914045.csv",
    "devices_report.csv",
]
default_path = next(
    (f for f in DEFAULT_FILES if os.path.exists(f) and os.path.getsize(f) > 0),
    None,
)

# Process Airtel Verification File using normalize_number
airtel_numbers = set()
if airtel_file is not None:
  airtel_df = safe_read_file(airtel_file)
  airtel_df.columns = (
      airtel_df.columns.astype(str)
      .str.replace("\ufeff", "", regex=False)
      .str.strip()
  )

  if "MSISDN" not in airtel_df.columns:
    st.error(
        "Couldn't find an 'MSISDN' column. Found these instead: "
        + str(list(airtel_df.columns))
    )
  else:
    airtel_numbers = set(airtel_df["MSISDN"].apply(normalize_number))
    airtel_numbers.discard("")
    st.write(
        "Loaded "
        + str(len(airtel_numbers))
        + " Airtel numbers for cross-reference."
    )


# 6. Fleet Dataset Loading & Execution
if uploaded_file is not None:
  df = safe_read_file(uploaded_file)
  st.info(f"Loaded uploaded file: **{uploaded_file.name}**")
elif default_path:
  df = safe_read_file(default_path)
  st.info(f"Displaying default dataset (**{default_path}**)")
else:
  st.warning(
      "No fleet dataset found in repository. Please upload a CSV or Excel"
      " report."
  )
  st.stop()

df.columns = (
    df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
)
st.write(f"Analyzing **{len(df):,} total fleet records**")

# Data Processing
df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
df["last_connect_time"] = pd.to_datetime(df["last_connect_time"], errors="coerce")
df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce")

df["expiration_year"] = df["expiration_date"].dt.year
df["expiration_month_name"] = df["expiration_date"].dt.strftime("%B")

now = pd.Timestamp.now()
df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400

if "users_list" in df.columns:
  df["user_emails"] = df["users_list"].apply(extract_customer_emails)
  df["primary_email"] = df["user_emails"].apply(
      lambda emails: emails[0] if emails else ""
  )
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

active_vehicles = (
    df[df["active"] == 1] if "active" in df.columns else df.head(0)
)
active_but_offline = active_vehicles[active_vehicles["hours_offline"] > 24]

# Network Categorization
df["sim_number_norm"] = (
    df["sim_number"].apply(normalize_number)
    if "sim_number" in df.columns
    else ""
)
df["sim_network"] = (
    df["sim_number"].apply(lambda x: sim_network(x, airtel_numbers))
    if "sim_number" in df.columns
    else "Missing"
)
network_breakdown = df["sim_network"].value_counts()
offline_by_network = df[df["hours_offline"] > 24]["sim_network"].value_counts()

missing_sim = (
    df[
        df["sim_number"].isna()
        | (df["sim_number"].astype(str).str.strip() == "")
    ]
    if "sim_number" in df.columns
    else df
)
sim_counts = (
    df["sim_number"].astype(str).value_counts()
    if "sim_number" in df.columns
    else pd.Series()
)
duplicate_sims = sim_counts[sim_counts > 1].index.tolist()
duplicate_sim_rows = (
    df[
        df["sim_number"].astype(str).isin(duplicate_sims)
        & (df["sim_number"].astype(str) != "nan")
    ]
    if "sim_number" in df.columns
    else df.head(0)
)

if "imei" in df.columns:
  df["imei_clean"] = (
      df["imei"].astype(str).str.replace(".00", "", regex=False).str.strip()
  )
  invalid_imei = df[~df["imei"].apply(valid_imei)]
  imei_counts = df["imei_clean"].value_counts()
  duplicate_imeis = imei_counts[imei_counts > 1].index.tolist()
  duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imeis)]
else:
  invalid_imei = df.head(0)
  duplicate_imei_rows = df.head(0)

install_trend = df.groupby(
    df["created_at"].dt.to_period("M").astype(str)
).size()

renewal_opportunity = df[
    (df["days_to_expiry"] >= 0)
    & (df["days_to_expiry"] <= 30)
    & (df["hours_offline"] <= 24)
].sort_values("days_to_expiry")

stats = {
    "total_vehicles": len(df),
    "reporting_24h": len(reporting_24h),
    "not_reporting": len(not_reporting),
    "expired_last_24h": len(expired_24h),
    "expired_last_30d": len(expired_30d),
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

st.session_state["last_stats"] = stats

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
    "All Months",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

col_years, col_month = st.columns([2, 1])
with col_years:
  selected_years = st.multiselect(
      "Select Expiration Year Batches:",
      options=TARGET_YEARS,
      default=TARGET_YEARS,
  )
with col_month:
  selected_month = st.selectbox(
      "Filter by Expiration Month:", options=MONTH_OPTIONS
  )

filtered_batch_df = df[df["expiration_year"].isin(selected_years)].copy()
if selected_month != "All Months":
  filtered_batch_df = filtered_batch_df[
      filtered_batch_df["expiration_month_name"] == selected_month
  ]

st.write(
    f"Found **{len(filtered_batch_df):,} vehicles** matching the selected year"
    " and month criteria."
)

if selected_years:
  year_tabs = st.tabs([f"📆 {yr}" for yr in sorted(selected_years)])
  for idx, yr in enumerate(sorted(selected_years)):
    with year_tabs[idx]:
      yr_df = filtered_batch_df[
          filtered_batch_df["expiration_year"] == yr
      ].sort_values("expiration_date")
      st.metric(f"Vehicles Expiring/Expired in {yr}", f"{len(yr_df):,} units")

      if not yr_df.empty:
        display_cols = [
            "id",
            "name",
            "plate_number",
            "sim_number",
            "primary_email",
            "expiration_date",
            "days_to_expiry",
        ]
        available_cols = [c for c in display_cols if c in yr_df.columns]
        st.dataframe(yr_df[available_cols], use_container_width=True)
        st.download_button(
            f"⬇️ Download {yr} Expiration List (CSV)",
            yr_df[available_cols].to_csv(index=False),
            f"fleet_expirations_{yr}_{selected_month.lower().replace(' ', '_')}.csv",
            "text/csv",
            key=f"dl_btn_{yr}",
        )
      else:
        st.info(
            f"No vehicles found expiring in {yr} for the selected month"
            f" ({selected_month})."
        )
st.write("---")

st.subheader("📡 Network Breakdown (SIM)")
st.bar_chart(network_breakdown)

st.subheader("📵 Offline Devices by Network")
st.bar_chart(offline_by_network)

st.subheader("📵 Airtel SIM Network Analysis")
all_airtel_df = df[
    df["sim_network"].str.contains("Airtel", case=False, na=False)
]
total_airtel_count = len(all_airtel_df)

airtel_offline_48h = all_airtel_df[all_airtel_df["hours_offline"] >= 48][
    ["id", "name", "plate_number", "sim_number", "last_connect_time", "hours_offline"]
].sort_values("hours_offline", ascending=False)

m1, m2 = st.columns(2)
m1.metric("Total Airtel SIMs in Fleet", f"{total_airtel_count:,}")
m2.metric("Airtel SIMs Offline 48h+", f"{len(airtel_offline_48h):,}")

st.write(
    f"Showing **{len(airtel_offline_48h):,} Airtel SIMs** that have not"
    " reported in 48+ hours:"
)
st.dataframe(airtel_offline_48h, use_container_width=True)
st.download_button(
    "⬇️ Download Airtel Offline 48h+ List (CSV)",
    airtel_offline_48h.to_csv(index=False),
    "airtel_offline_48h.csv",
    "text/csv",
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
st.write(
    f"**{stats['renewal_opportunity_count']:,} vehicles** — easiest to renew"
    " since they're currently reporting."
)
renewal_cols = [
    "id",
    "name",
    "plate_number",
    "sim_number",
    "expiration_date",
    "days_to_expiry",
]
available_renewal = [c for c in renewal_cols if c in renewal_opportunity.columns]
st.dataframe(renewal_opportunity[available_renewal], use_container_width=True)
st.download_button(
    "⬇️ Download Renewal Opportunity List (CSV)",
    renewal_opportunity.to_csv(index=False),
    "renewal_opportunity.csv",
    "text/csv",
)

st.subheader("📧 Renewal Opportunity - By Customer Email")
renewal_with_email = renewal_opportunity.copy()
has_email = renewal_with_email["primary_email"] != ""
email_groups = renewal_with_email[has_email].groupby("primary_email")

for email, group in email_groups:
  label = f"{email} - {len(group)} vehicle(s) expiring soon"
  with st.expander(label):
    group_cols = [
        c
        for c in [
            "id",
            "name",
            "plate_number",
            "expiration_date",
            "days_to_expiry",
        ]
        if c in group.columns
    ]
    st.dataframe(group[group_cols])
    vehicle_list = ", ".join(group["name"].astype(str))
    body_text = (
        "Dear Customer,%0A%0AThe following vehicles on your account are"
        " expiring soon: "
        + vehicle_list.replace(" ", "%20")
        + ".%0A%0APlease renew to avoid service interruption."
    )
    mailto_link = (
        f"mailto:{email}?subject=Vehicle%20Subscription%20Renewal%20Reminder&body={body_text}"
    )
    st.markdown(f"[Send renewal email]({mailto_link})")

st.subheader("📥 Download Customer Contact List")
contact_cols = [
    "id",
    "name",
    "plate_number",
    "sim_number",
    "primary_email",
    "expiration_date",
    "days_to_expiry",
]
contact_export = df[df["primary_email"] != ""][
    [c for c in contact_cols if c in df.columns]
].copy()
st.download_button(
    "⬇️ Download Full Customer Email List (CSV)",
    contact_export.to_csv(index=False),
    "customer_email_list.csv",
    "text/csv",
)

# 9. AI Executive Assessment & Interactive Q&A via Gemini API
st.write("---")
if GEMINI_API_KEY:
  try:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "You are analyzing a fleet tracking dataset. Use ONLY these verified"
        " numbers, do not recalculate:\n"
        + json.dumps(stats, indent=2, default=str)
        + "\n\nReturn ONLY valid JSON with keys: summary (one paragraph),"
        " insights (4-6 bullet strings), actions (list of objects with task and"
        " detail)."
    )
    response = client.models.generate_content(
        model="gemini-3.6-flash", contents=prompt
    )
    raw = response.text.strip().strip("`").replace("json", "", 1).strip()
    result = json.loads(raw)

    st.subheader("📋 AI Executive Summary")
    st.write(result.get("summary", ""))

    st.subheader("💡 Insights")
    for i in result.get("insights", []):
      st.markdown(f"- {i}")

    st.subheader("🛠️ Recommended Actions")
    for a in result.get("actions", []):
      task = a.get("task", "")
      detail = a.get("detail", "")
      st.markdown(f"- **{task}**: {detail}")
  except Exception as e:
    st.info(f"AI summary engine standby or API rate limit reached ({e}).")

# Interactive Q&A section
st.subheader("❓ Ask a Question About This Fleet Data")
question = st.text_input(
    "e.g., Which network has the most offline devices? or How many vehicles"
    " expire in 2026?"
)
if st.button("Ask AI Agent"):
  if question.strip() != "":
    with st.spinner("Analyzing fleet statistics..."):
      try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        qa_prompt = (
            "You are answering a question about a fleet tracking dataset.\nUse"
            " ONLY the numbers below - do not invent figures.\n\nFleet"
            " stats:\n"
            + json.dumps(stats, indent=2, default=str)
            + f"\n\nQuestion: {question}\n\nAnswer concisely and directly."
        )
        answer = client.models.generate_content(
            model="gemini-3.6-flash", contents=qa_prompt
        )
        st.write(answer.text)
      except Exception as e:
        st.warning(f"Couldn't get an answer right now. Error: {e}")
