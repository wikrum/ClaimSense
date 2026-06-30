import os

import requests
import streamlit as st

st.set_page_config(page_title="ClaimSense", page_icon="🧾", layout="centered")
st.title("ClaimSense")
st.caption("Multi-agent insurance claims assistant")

api_base = os.getenv("CLAIMSENSE_API_URL", "http://localhost:8000")

claim_id = st.text_input("Claim ID", placeholder="CLM-1001")
message = st.text_area("Ask ClaimSense", placeholder="What policy coverage applies to this claim?")

if st.button("Send", type="primary"):
    if not message.strip():
        st.warning("Please enter a message.")
    else:
        with st.spinner("Thinking..."):
            res = requests.post(
                f"{api_base}/chat",
                json={"message": message, "claim_id": claim_id or None},
                timeout=30,
            )
            res.raise_for_status()
            data = res.json()
        st.subheader("Response")
        st.write(data.get("reply", ""))
        st.caption(f"Route: {data.get('route', 'unknown')}")
