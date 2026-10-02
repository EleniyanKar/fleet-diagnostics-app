import json
import os
import re
import pandas as pd
import requests

from dotenv import load_dotenv
from google import genai
import streamlit as st

# ==========================================
# 1. Page Configuration & Modern Styling
# ==========================================
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(
    page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide"
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
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(-45deg, #2563eb, #3b82f6, #06b6d4, #10b981);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradientText 6s ease infinite;
        margin-bottom: 0px;
    }
    .modern-subtitle {
        font-size: 1rem;
        color: #64748b;
        margin-bottom: 25px;
    }
    .icon-header {
        font-size: 1.25rem;
        font-weight: 700;
        color: #1e293b;
        margin-top: 20px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<p class="modern-title">⚡ AI Fleet Diagnostics Dashboard</p>', unsafe_allow_html=True)
st.markdown('<p class="modern-subtitle">Live fleet diagnostics, subscription renewal opportunities, and network analytics.</p>', unsafe_allow_html=True)

# ==========================================
# 2. Administrative & Blacklisted Emails
# ==========================================
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

EXCLUDED_KEYWORDS = [
    "cartracker", "catracker", "clicktgi", "gbovo", "hopmobiletransport.com",
]

# ==========================================
# 3. Telecom Network Prefixes (Nigeria)
# ==========================================
NETWORK_PREFIXES = {
    "MTN": ["0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814", "0903", "0906", "0913", "0916", "0704"],
    "Airtel": ["0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904", "0907", "0912", "0911", "0702"],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes}

# ==========================================
# 4. Helper & Data Parsing Functions
# ==========================================
def normalize_number(n):
    if pd.isna(n) or str(n).strip().lower() in ("", "nan", "null", "none"):
        return ""
    s = str(n).strip()
    if s.endswith(".0"):
        s = s[:-2]
    elif s.endswith(".00"):
        s = s[:-3]
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits.startswith("234"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits

def sim_network(sim, airtel_set):
    sim_norm = normalize_number(sim)
    if not sim_norm or str(sim).strip().lower() in ("", "nan", "none"):
        return "Missing"
    if sim_norm in airtel_set:
        return "Airtel (verified)"
    prefix = None
    if len(sim_norm) >= 9:
        prefix = "0" + sim_norm[:3]
    if prefix and prefix in PREFIX_TO_NETWORK:
        return PREFIX_TO_NETWORK[prefix]
    return "Unknown/Other (guessed)"

def valid_imei(v):
    v = str(v).replace(".00", "").strip()
    return v.isdigit() and len(v) == 15

def is_excluded_email(email_str):
    e = str(email_str).strip().lower()
    if e in EXCLUDED_EMAILS:
        return True
    for kw in EXCLUDED_KEYWORDS:
        if kw in e:
            return True
    return False

def extract_customer_emails(users_list_value):
    if pd.isna(users_list_value) or str(users_list_value).strip() == "":
        return []
    found_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", str(users_list_value))
    return [e.strip().lower() for e in found_emails if not is_excluded_email(e.strip().lower())]

def extract_clean_unique_emails(dataframe):
    all_extracted_emails = set()
    target_columns = [col for col in ["users_list", "user_emails", "primary_email"] if col in dataframe.columns]
    for col in target_columns:
        for val in dataframe[col].dropna():
            found = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", str(val))
            for email in found:
                e = email.strip().lower()
                if not is_excluded_email(e):
                    all_extracted_emails.add(e)
    return pd.DataFrame(sorted(list(all_extracted_emails)), columns=["Customer Email"])

def safe_read_file(file_source):
    filename = getattr(file_source, "name", str(file_source))
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_source, dtype=str)
    try:
        return pd.read_csv(file_source, encoding="utf-8-sig", dtype=str)
    except pd.errors.EmptyDataError:
        st.error(f"The file **{filename}** is empty. Please upload a valid report.")
        st.stop()
    except Exception:
        try:
            return pd.read_csv(file_source, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
        except Exception:
            return pd.read_csv(file_source, encoding="latin1", dtype=str)

# Zoho CRM API Helpers
def get_zoho_access_token():
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        return None
    url = f"https://accounts.zoho.com/oauth/v2/token?refresh_token={refresh_token}&client_id={client_id}&client_secret={client_secret}&grant_type=refresh_token"
    res = requests.post(url)
    return res.json().get("access_token") if res.status_code == 200 else None

def fetch_zoho_module(module_name, access_token):
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    url = f"https://www.zohoapis.com/crm/v3/{module_name}?fields=id,Email,Contact_Name,Phone,Full_Name,Account_Name"
    res = requests.get(url, headers=headers)
    return pd.DataFrame(res.json().get("data", [])) if res.status_code == 200 else pd.DataFrame()

# ==========================================
# 5. File Selection & Execution
# ==========================================
uploaded_file = st.file_uploader("Upload new fleet report (Optional)", type=["csv", "xlsx", "xls"])
airtel_file = st.file_uploader("Upload Airtel SIM list (Optional)", type=["csv", "xlsx"])

DEFAULT_FILES = ["devices_report.csv.csv", "devices_report_1789914045.csv", "devices_report.csv"]
default_path = next((f for f in DEFAULT_FILES if os.path.exists(f) and os.path.getsize(f) > 0), None)

airtel_numbers = set()
if airtel_file is not None:
    airtel_df = safe_read_file(airtel_file)
    airtel_df.columns = airtel_df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
    msisdn_col = next((col for col in airtel_df.columns if col.lower() in ["msisdn", "phone", "sim", "sim_number", "mobile"]), None)
    if msisdn_col:
        airtel_numbers = set(airtel_df[msisdn_col].apply(normalize_number))
        airtel_numbers.discard("")

if uploaded_file is not None:
    df = safe_read_file(uploaded_file)
elif default_path:
    df = safe_read_file(default_path)
else:
    st.warning("No fleet dataset found. Please upload a CSV or Excel report.")
    st.stop()

df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()

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
    df["primary_email"] = df["user_emails"].apply(lambda emails: emails[0] if emails else "")
else:
    df["user_emails"] = [[] for _ in range(len(df))]
    df["primary_email"] = ""

reporting_24h = df[df["hours_offline"] <= 24]
not_reporting = df[df["hours_offline"] > 24]
expired_total = df[df["days_to_expiry"] < 0]
expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]

active_vehicles = df[df["active"].astype(str).str.strip() == "1"] if "active" in df.columns else df.head(0)
active_but_offline = active_vehicles[active_vehicles["hours_offline"] > 24]

if "sim_number" in df.columns:
    df["sim_number_norm"] = df["sim_number"].apply(normalize_number)
    df["sim_network"] = df["sim_number"].apply(lambda x: sim_network(x, airtel_numbers))
else:
    df["sim_network"] = "Missing"

network_breakdown = df["sim_network"].value_counts()
offline_by_network = df[df["hours_offline"] > 24]["sim_network"].value_counts()

renewal_opportunity = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) & (df["hours_offline"] <= 24)].sort_values("days_to_expiry")

# ==========================================
# 6. Dashboard UI Rendering
# ==========================================
st.success("Analysis Complete!")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reporting (24h)", f"{len(reporting_24h):,}")
c2.metric("Not Reporting", f"{len(not_reporting):,}")
c3.metric("Expired (total)", f"{len(expired_total):,}")
c4.metric("Active but Offline", f"{len(active_but_offline):,}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Expired (last 24h)", len(expired_24h))
c6.metric("Expired (last 30d)", len(expired_30d))
c7.metric("Expiring (next 24h)", len(expiring_24h))
c8.metric("Expiring (next 30d)", len(expiring_30d))

# ==========================================
# 7. ZOHO CRM & EXPIRED FLEET RECOVERY LINKER
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">📞 Zoho CRM & Expired Fleet Recovery Linker</div>', unsafe_allow_html=True)

sync_mode = st.radio("Select Integration Mode:", ["🔄 Live Zoho CRM API Sync", "📁 Manual Zoho File Upload"], horizontal=True)

if sync_mode == "🔄 Live Zoho CRM API Sync":
    if st.button("⚡ Fetch & Merge Live Data from Zoho CRM"):
        with st.spinner("Connecting to Zoho CRM API and generating recovery lists..."):
            token = get_zoho_access_token()
            if not token:
                st.error("Could not generate Zoho Access Token. Please verify ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN in your .env file.")
            else:
                deals_df = fetch_zoho_module("Deals", token)
                contacts_df = fetch_zoho_module("Contacts", token)

                if not deals_df.empty and not contacts_df.empty:
                    expired_df = df[df["days_to_expiry"] < 0].copy()
                    merged_deals = pd.merge(expired_df, deals_df, left_on="primary_email", right_on="Email", how="inner")
                    final_merged = pd.merge(merged_deals, contacts_df, left_on="Contact_Name", right_on="Full_Name", how="inner")

                    st.success(f"Matched **{len(final_merged):,} expired vehicle records** directly from Zoho CRM!")

                    rc1, rc2 = st.columns(2)
                    rc1.metric("Calling Contacts Found", f"{len(final_merged):,}")
                    rc1.download_button("⬇️ Download Calling List (CSV)", final_merged[["Full_Name", "Phone", "plate_number", "expiration_date"]].to_csv(index=False), "Zoho_Calling_List.csv", "text/csv")

                    rc2.metric("Email Contacts Found", f"{len(final_merged):,}")
                    rc2.download_button("⬇️ Download Email List (CSV)", final_merged[["Full_Name", "Email", "plate_number", "expiration_date"]].to_csv(index=False), "Zoho_Email_List.csv", "text/csv")
                else:
                    st.warning("Could not retrieve Deals or Contacts records from Zoho CRM.")

else:
    col_deal, col_cust = st.columns(2)
    with col_deal:
        deals_file = st.file_uploader("Upload Zoho Deals File (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="zoho_deals")
    with col_cust:
        customers_file = st.file_uploader("Upload Zoho Customers File (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="zoho_cust")

    if deals_file and customers_file:
        if st.button("⚡ Merge Data & Generate Recovery Lists"):
            try:
                deal_df = safe_read_file(deals_file)
                customer_df = safe_read_file(customers_file)

                deal_df.columns = deal_df.columns.astype(str).str.strip()
                customer_df.columns = customer_df.columns.astype(str).str.strip()

                expired_df = df[df["days_to_expiry"] < 0].copy()

                deal_email_col = next((c for c in deal_df.columns if "email" in c.lower()), deal_df.columns[0])
                deal_contact_col = next((c for c in deal_df.columns if "contact" in c.lower() or "name" in c.lower()), deal_df.columns[0])
                cust_name_col = next((c for c in customer_df.columns if "name" in c.lower() or "contact" in c.lower()), customer_df.columns[0])
                cust_phone_col = next((c for c in customer_df.columns if "phone" in c.lower() or "mobile" in c.lower()), customer_df.columns[0])

                merged_deals = pd.merge(expired_df, deal_df, left_on="primary_email", right_on=deal_email_col, how="inner")
                final_merged = pd.merge(merged_deals, customer_df, left_on=deal_contact_col, right_on=cust_name_col, how="inner")

                st.success(f"Successfully matched **{len(final_merged):,} records**!")

                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    st.metric("Phone Numbers Found for Calling", f"{len(final_merged):,}")
                    st.download_button("⬇️ Download Calling List (CSV)", final_merged[[cust_name_col, cust_phone_col, "plate_number", "expiration_date"]].to_csv(index=False), "Expired_Vehicles_Calling_List.csv", "text/csv")
                with res_col2:
                    st.metric("Verified Email Contacts Found", f"{len(final_merged):,}")
                    st.download_button("⬇️ Download Email List (CSV)", final_merged[[cust_name_col, "primary_email", "plate_number", "expiration_date"]].to_csv(index=False), "Expired_Vehicles_Email_List.csv", "text/csv")

            except Exception as e:
                st.error(f"Error linking datasets: {e}")

st.write("---")
st.markdown('<div class="icon-header">✉️ Deduplicated Clean Customer Emails</div>', unsafe_allow_html=True)
clean_emails_df = extract_clean_unique_emails(df)

st.write(f"Total Clean Customer Emails: **{len(clean_emails_df):,}**")
st.download_button(
    label="⬇️ Download Clean Unique Emails (CSV)",
    data=clean_emails_df.to_csv(index=False).encode("utf-8"),
    file_name="deduplicated_customer_emails.csv",
    mime="text/csv",
)

st.write("---")
st.markdown('<div class="icon-header">📡 Network Breakdown</div>', unsafe_allow_html=True)
st.bar_chart(network_breakdown)

st.markdown('<div class="icon-header">💰 Renewal Opportunities</div>', unsafe_allow_html=True)
st.write(f"Found **{len(renewal_opportunity):,} vehicles** ready for renewal.")
st.dataframe(renewal_opportunity[["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date"]], use_container_width=True)
