import os
import pandas as pd
from google import genai
import streamlit as st
from dotenv import load_dotenv

# 1. Load environment variables securely from the .env file
load_dotenv()

# 2. Safety Check: Stop execution if GEMINI_API_KEY is not loaded
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("API Key not found! Please check your .env file.")
    st.stop()

# 3. Configure Dashboard Header
st.title("⚡ AI Fleet Diagnostics Dashboard")
st.write("Upload a device CSV report to generate an automated AI summary.")

# 4. CSV File Upload Widget
uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

if uploaded_file is not None:
    # Read and display data preview
    df = pd.read_csv(uploaded_file)
    st.subheader("Raw Data Preview")
    st.dataframe(df.head(10))

    # Trigger AI Diagnostic Analysis
    if st.button("Run AI Diagnostic Assessment"):
        with st.spinner("Analyzing dataset with Gemini..."):
            # Initialize the Gemini client using the environment key
            client = genai.Client(api_key=api_key)
            
            # Extract a sample of raw rows for evaluation
            csv_sample = df.head(20).to_csv(index=False)

            prompt = (
                "You are a fleet diagnostic specialist. Analyze this device sample "
                f"and list key operational risks, faulty units, and maintenance steps:\n{csv_sample}"
            )

            # Request content generation using Gemini 2.5 Flash
            response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )

            # Display Results
            st.success("Analysis Complete!")
            st.subheader("AI Operational Summary")
            st.write(response.text)
